"""Google Workspace 数据源服务：给真实的 GAMADV-XTD3 供数。

`gam` 是真二进制（版本钉死在 opc/agent/Dockerfile），它照常做完整的
服务账号 JWT 换 token、拉 discovery、走 googleapiclient 的 batch ——
只是这几个主机名被钉在了 127.0.0.1（见 opc-pin-hosts），TLS 认的是本机
构建期签出来的那张 CA。也就是说：**认证面、API 形状、batch 协议全是真的，
只有对端是本地的**。这和 dws 那边是同一条路子，理由也一样——
自造一个假 CLI 等于把连接器的真实难度（鉴权、分页、错误码）全删掉。

监听 443：端口是 discovery 文档里 rootUrl 定死的，改不了。服务以 opcsvc
跑（agent 读不到语料），绑特权端口靠一份单独 setcap 过的 python 副本，
不给 agent 自己那个 python 加任何能力。

支持到「够 gam 跑完一条只读命令」为止：
  POST /token                                   服务账号 JWT -> access token
  GET  /$discovery/rest?version=...             discovery 文档（本地副本）
  GET  /gmail/v1/users/{u}/profile
  GET  /gmail/v1/users/{u}/messages             列消息
  GET  /gmail/v1/users/{u}/messages/{id}        取单条（语料可钉 fetch_error）
  POST /batch                                   multipart/mixed，gam 取正文走它

调用会写审计，格式与 /opt/opc/bin 下那些命令一致。这一份是**服务端**写的，
agent 碰不到——它能往 FIFO 里多写假事件，但删不掉这里已经落下的行。
"""

import base64
import email.parser
import json
import os
import re
import ssl
import time
import urllib.parse
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIXTURE_PATH = os.environ.get("OPC_GWS_FIXTURE", "/opt/opc/data/workspace.json")
DISCOVERY_DIR = os.environ.get("OPC_GWS_DISCOVERY", "/opt/opc/data/discovery")
CERT_FILE = os.environ.get("OPC_GWS_CERT", "/opt/opc/data/tls/fixture.crt")
KEY_FILE = os.environ.get("OPC_GWS_KEY", "/opt/opc/data/tls/fixture.key")
# 服务端自己写的一份：它真收到了哪些请求，外加开机自证。
# agent 是 opc，这个目录是 opcsvc:opc 0750，它读不到也改不了。
# 以前这里写的是那份要靠 FIFO + 收集器才落得下去的 audit.log——
# 那套机器连同 agent 侧的命令包装一起删了，服务端直接追加就行。
SERVER_LOG = os.environ.get("OPC_SERVER_LOG", "/var/lib/opc/server-log.jsonl")
PORT = int(os.environ.get("OPC_GWS_PORT", "443"))

DISCOVERY_FILES = {
    "gmail": "gmail-v1.json",
    "admin": "admin-directory_v1.json",
}


def load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def record(op: str, arguments: dict, ok: bool = True, extra: dict = None) -> None:
    event = {"ts": time.time(), "tool": "gam", "args": [op],
             "ok": ok, "arguments": arguments}
    if extra:
        event.update(extra)
    try:
        os.makedirs(os.path.dirname(SERVER_LOG), exist_ok=True)
        with open(SERVER_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def b64(raw: bytes) -> str:
    """Gmail API 的 base64url。

    **填充必须留着。** 原先这里 rstrip("=")，理由写的是「照 API 的实际返回来」，
    可 gam 解正文走的是 base64.urlsafe_b64decode，那个函数对填充是严格的：
    正文长度不是 3 的整数倍时它直接抛 binascii.Error: Incorrect padding，
    gam 打一串 traceback、那条消息的正文变成空的。
    之所以一直没发现，是因为在这之前没有任何一道题真的取过正文。
    """
    return base64.urlsafe_b64encode(raw).decode()


def rfc822(message: dict) -> str:
    headers = [
        f"From: {message['from']}",
        f"To: {message.get('to', '')}",
        f"Subject: {message['subject']}",
        f"Date: {message['date']}",
        "Content-Type: text/plain; charset=UTF-8",
    ]
    return "\r\n".join(headers) + "\r\n\r\n" + message["body"]


def as_wire(message: dict, fmt: str = "full") -> dict:
    """语料条目 -> Gmail API 的 Message 资源。"""
    body = message["body"]
    wire = {
        "id": message["id"],
        "threadId": message.get("thread_id", message["id"]),
        "labelIds": message.get("labels", ["INBOX", "UNREAD"]),
        "snippet": body[:80],
        "historyId": message.get("history_id", "1"),
        "internalDate": str(int(message["epoch"]) * 1000),
        "sizeEstimate": len(rfc822(message)),
    }
    if fmt == "raw":
        wire["raw"] = b64(rfc822(message).encode())
        return wire
    if fmt == "minimal":
        return wire
    wire["payload"] = {
        "partId": "",
        "mimeType": "text/plain",
        "filename": "",
        "headers": [
            {"name": "From", "value": message["from"]},
            {"name": "To", "value": message.get("to", "")},
            {"name": "Subject", "value": message["subject"]},
            {"name": "Date", "value": message["date"]},
            {"name": "Content-Type", "value": "text/plain; charset=UTF-8"},
        ],
        "body": {"size": len(body.encode()), "data": b64(body.encode())},
    }
    return wire


def _boundary(value: str) -> float:
    """after:/before: 的取值。gam 会把 `after:2026/07/31` 换算成 epoch 秒再发出来，
    所以两种写法都得认——这是真 CLI 帮我们做的转换，不是我们自己发明的格式。"""
    value = value.strip("()")
    if value.isdigit():
        return float(value)
    return datetime.strptime(value.replace("-", "/"), "%Y/%m/%d").timestamp()


def match_query(message: dict, query: str) -> bool:
    """Gmail 的 q= 只实现到题目用得上的那几个算子。

    覆盖 after:/before: 与裸关键词；其余算子一律放行，宁可多给也别少给——
    少给会让 agent 以为信箱是空的，那是环境在撒谎。
    """
    if not query:
        return True
    when = float(message["epoch"])
    for token in query.split():
        token = token.strip("()")
        if not token:
            continue
        if token.startswith("after:"):
            if when < _boundary(token[6:]):
                return False
        elif token.startswith("before:"):
            if when >= _boundary(token[7:]):
                return False
        elif ":" in token:
            continue
        else:
            blob = f"{message['from']} {message['subject']} {message['body']}"
            if token.lower() not in blob.lower():
                return False
    return True


class Router:
    """路由：一条请求 -> (状态码, JSON 对象)。/batch 的子请求也走它。"""

    def __init__(self, fixture: dict):
        self.fixture = fixture

    def messages(self, user: str) -> list:
        boxes = self.fixture.get("mailboxes", {})
        box = boxes.get(user) or boxes.get(self.fixture.get("default_user", ""), {})
        return box.get("messages", [])

    def handle(self, method: str, path: str, query: dict, body: bytes):
        if path.endswith("/token") or path == "/token":
            return 200, {"access_token": "ya29.opc-fixture",
                         "expires_in": 3599, "token_type": "Bearer"}

        m = re.match(r"^/gmail/v1/users/([^/]+)/messages/([^/]+)$", path)
        if m:
            user = urllib.parse.unquote(m.group(1))
            fmt = query.get("format", ["full"])[0]
            for message in self.messages(user):
                if message["id"] != m.group(2):
                    continue
                # 语料给这条钉了取正文失败，就真的失败。为什么做成语料的一个
                # 字段而不是随机掉包：**批量查询里少了几条**这件事必须是确定的，
                # 否则同一道题两次跑的分数差别里混的是运气。
                # 不写这个字段的题一条都不受影响——默认没有它。
                fail = message.get("fetch_error")
                if fail:
                    code = int(fail.get("code", 500))
                    record("messages.get", {"user": user, "id": message["id"],
                                            "code": code}, ok=False,
                           extra={"error": fail.get("message", "backendError")})
                    return code, {"error": {
                        "code": code,
                        "message": fail.get("message", "Backend Error"),
                        "errors": [{"reason": fail.get("reason", "backendError"),
                                    "message": fail.get("message", "Backend Error")}],
                    }}
                record("messages.get", {"user": user, "id": message["id"]})
                return 200, as_wire(message, fmt)
            return 404, {"error": {"code": 404, "message": "Not Found",
                                   "errors": [{"reason": "notFound"}]}}

        m = re.match(r"^/gmail/v1/users/([^/]+)/messages$", path)
        if m:
            user = urllib.parse.unquote(m.group(1))
            hits = [x for x in self.messages(user)
                    if match_query(x, query.get("q", [""])[0])]
            record("messages.list", {"user": user, "q": query.get("q", [""])[0],
                                     "count": len(hits)})
            return 200, {"messages": [{"id": x["id"],
                                       "threadId": x.get("thread_id", x["id"])}
                                      for x in hits],
                         "resultSizeEstimate": len(hits)}

        m = re.match(r"^/gmail/v1/users/([^/]+)/profile$", path)
        if m:
            user = urllib.parse.unquote(m.group(1))
            msgs = self.messages(user)
            return 200, {"emailAddress": user, "messagesTotal": len(msgs),
                         "threadsTotal": len(msgs), "historyId": "1"}

        return 404, {"error": {"code": 404, "message": f"no fixture route: {path}",
                               "errors": [{"reason": "notFound"}]}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    router: Router = None

    def log_message(self, *args):  # 服务端日志不进 stdout，审计才是唯一入口
        pass

    def _write(self, code: int, payload: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, code: int, obj) -> None:
        self._write(code, json.dumps(obj).encode(), "application/json; charset=UTF-8")

    def _discovery(self, host: str, query: dict) -> None:
        """discovery 文档。gam 每次冷启动都拉，拉不到就是 'rootUrl' KeyError。"""
        api = "gmail" if host.startswith("gmail") else "admin"
        path = os.path.join(DISCOVERY_DIR, DISCOVERY_FILES[api])
        try:
            with open(path, "rb") as fh:
                self._write(200, fh.read(), "application/json; charset=UTF-8")
        except OSError as exc:
            self._json(500, {"error": {"code": 500, "message": str(exc)}})

    def _batch(self, body: bytes) -> None:
        """multipart/mixed 的批量接口。googleapiclient 取正文走的就是它。

        子请求的 Content-ID 必须原样回带（前缀 + 号），否则客户端配不上对。
        """
        ctype = self.headers.get("Content-Type", "")
        parsed = email.parser.BytesParser().parsebytes(
            b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body
        )
        boundary = f"batch_{uuid.uuid4().hex}"
        chunks = []
        for part in parsed.get_payload():
            if not isinstance(part, email.message.Message):
                continue
            # Content-ID 很长，解析时会被折行（RFC 5322 的 folding）。回带之前
            # 要把折行收回成单个空格——**不能把空格全删掉**：客户端拆的分隔符
            # 是字面量 `" + "`（googleapiclient 故意留的空格，就为了让折行不破坏它），
            # 删空格等于把分隔符也删了。
            cid = " ".join(part.get("Content-ID", "").split())
            raw = part.get_payload(decode=True)
            if raw is None:
                raw = str(part.get_payload()).encode()
            # 行尾照理是 CRLF，但别把整条路押在这上面：空行一分为二就够了。
            parts = re.split(rb"\r?\n\r?\n", raw, maxsplit=1)
            head, sub_body = parts[0], (parts[1] if len(parts) > 1 else b"")
            lines = head.decode(errors="replace").splitlines()
            if not lines:
                continue
            request_line = lines[0].split()
            method, target = request_line[0], request_line[1]
            split = urllib.parse.urlsplit(target)
            code, payload = self.router.handle(
                method, split.path, urllib.parse.parse_qs(split.query), sub_body
            )
            blob = json.dumps(payload).encode()
            chunks.append(
                f"--{boundary}\r\nContent-Type: application/http\r\n"
                f"Content-ID: <response-{cid.strip('<>')}>\r\n\r\n"
                f"HTTP/1.1 {code} {'OK' if code == 200 else 'Error'}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n"
                f"Content-Length: {len(blob)}\r\n\r\n".encode() + blob + b"\r\n"
            )
        record("batch", {"parts": len(chunks)})
        out = b"".join(chunks) + f"--{boundary}--\r\n".encode()
        self._write(200, out, f"multipart/mixed; boundary={boundary}")

    def _serve(self) -> None:
        host = (self.headers.get("Host") or "").split(":")[0]
        split = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(split.query)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        if split.path == "/$discovery/rest":
            self._discovery(host, query)
            return
        if split.path == "/batch" or split.path.startswith("/batch/"):
            self._batch(body)
            return
        code, payload = self.router.handle(self.command, split.path, query, body)
        self._json(code, payload)

    do_GET = do_POST = _serve


def main() -> None:
    Handler.router = Router(load_fixture())
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT_FILE, KEY_FILE)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
