"""企业数据源服务：为 dws CLI 提供 MCP over HTTP JSON-RPC 接口。

CLI 的数据端点由 DINGTALK_<服务>_MCP_URL 指定，本进程监听本机端口并按
钉钉开放平台的返回形状供数，数据来自 OPC_DWS_FIXTURE 指向的归档。

分页按 CLI 的契约实现：hasMore 必须给，nextCursor 必须是正整数毫秒时间戳，
下一页以它换算出的 time 为边界。少给字段会让调用方判定「无法证明结果完整」。

调用会写入审计日志，与其他内部命令同一格式。
"""

import json
import os
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIXTURE_PATH = os.environ.get("OPC_DWS_FIXTURE", "/opt/opc/data/dingtalk.json")
# 服务端自己写的一份：它真收到了哪些请求，外加开机自证。
# agent 是 opc，这个目录是 opcsvc:opc 0750，它读不到也改不了。
# 以前这里写的是那份要靠 FIFO + 收集器才落得下去的 audit.log——
# 那套机器连同 agent 侧的命令包装一起删了，服务端直接追加就行。
SERVER_LOG = os.environ.get("OPC_SERVER_LOG", "/var/lib/opc/server-log.jsonl")
PORT = int(os.environ.get("OPC_DWS_FIXTURE_PORT", "18080"))
# 有它就校验登录态：CLI 把 token 透成 Authorization: Bearer <token>。
# 没有（老题）就不校验，行为与以前完全一致。
#
# 为什么走文件而不是环境变量：本进程是 entrypoint 经 sudo 以 opcsvc 拉起的，
# 而 sudoers 是 env_reset，环境变量根本透不过来。落在 /opt/opc/data 下还有
# 另一层好处——那个目录是 opcsvc:opcsvc 0700，agent 读不到有效凭证，
# 只能从它该看的地方（运维笔记、老板的交代）拿。
VALID_TOKEN_FILE = os.environ.get(
    "OPC_DWS_VALID_TOKEN_FILE", "/opt/opc/data/valid_token"
)


def _valid_token():
    token = os.environ.get("OPC_DWS_VALID_TOKEN")
    if token:
        return token.strip()
    try:
        with open(VALID_TOKEN_FILE, encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


VALID_TOKEN = _valid_token()

TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")
DEFAULT_LIMIT = 20


def parse_ts(value: str) -> float:
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).timestamp()
        except ValueError:
            continue
    raise ValueError(f"unparsable timestamp: {value!r}")


def load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def record(tool: str, arguments: dict, ok: bool = True, extra: dict = None,
           as_tool: str = "dws") -> None:
    """留痕。和 /opt/opc/bin 下那些命令同一个格式，判分器一把读。

    这一份是**服务端**写的，agent 碰不到：它能往 FIFO 里多写假事件，
    但删不掉这里已经落下的行。

    as_tool 给 `_env:<名字>` 时写的是**开机自证**而不是一次调用——见 do_GET
    里的 /_env/session。两者要分开：调用轨迹说的是「agent 做了什么」，
    自证说的是「环境本来是什么样」，判分时的出口也不一样（见 preflight.py）。
    """
    event = {"ts": time.time(), "tool": as_tool, "args": [tool],
             "ok": ok, "arguments": arguments}
    if extra:
        event.update(extra)
    try:
        os.makedirs(os.path.dirname(SERVER_LOG), exist_ok=True)
        with open(SERVER_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def as_wire(message: dict) -> dict:
    """语料条目 -> 钉钉开放平台风格的消息对象。"""
    wire = {
        "openMessageId": message["id"],
        "messageId": message["id"],
        "createAt": message["ts"],
        "senderNick": message.get("sender", ""),
        "senderId": message.get("sender_id", ""),
        "msgtype": message.get("msgtype", "text"),
    }
    if message.get("recalled"):
        wire["recalled"] = True
        wire["text"] = {"content": "[该消息已撤回]"}
        wire["content"] = "[该消息已撤回]"
        return wire
    text = message.get("text", "")
    wire["text"] = {"content": text}
    wire["content"] = text
    return wire


def list_conversation_message(fixture: dict, arguments: dict) -> dict:
    cid = arguments.get("openconversation_id") or arguments.get("openConversationId")
    for conversation in fixture.get("conversations", []):
        if conversation["open_conversation_id"] == cid:
            break
    else:
        return {"error": f"conversation not found: {cid}"}

    limit = int(arguments.get("limit") or DEFAULT_LIMIT)
    forward = bool(arguments.get("forward", False))
    boundary = arguments.get("time")

    ordered = sorted(conversation["messages"], key=lambda m: parse_ts(m["ts"]),
                     reverse=not forward)
    if boundary:
        edge = parse_ts(boundary)
        if forward:
            ordered = [m for m in ordered if parse_ts(m["ts"]) > edge]
        else:
            ordered = [m for m in ordered if parse_ts(m["ts"]) < edge]

    page, rest = ordered[:limit], ordered[limit:]
    payload = {
        "messages": [as_wire(m) for m in page],
        "hasMore": bool(rest),
    }
    if rest and page:
        # nextCursor 必须是正整数毫秒时间戳：CLI 拿它换算下一页的 time 边界。
        payload["nextCursor"] = int(parse_ts(page[-1]["ts"]) * 1000)
    return payload


TOOLS = {
    "list_conversation_message_v2": list_conversation_message,
    "list_individual_chat_message": list_conversation_message,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 别把请求日志喷到 stderr
        pass

    def _bearer(self) -> str:
        raw = self.headers.get("Authorization") or ""
        if raw.lower().startswith("bearer "):
            return raw[7:].strip()
        return (self.headers.get("X-User-Access-Token") or "").strip()

    def _send(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """开机自证端点：这台机器上配好的登录态，数据源认不认。

        为什么要有它：判分的第一条断言是「前置条件真的塌了」，而这条断言
        必须**与 agent 做没做事无关**——否则 nop（什么都不做）也会让它红，
        「题坏了」和「agent 没动」就混成了同一个信号。

        entrypoint 在 agent 进来之前拿配好的那个 token 请求一次，
        结果以 `_env:session_valid` 落进审计。写的人是服务端，agent 删不掉；
        用的是独立的 tool 名，不污染 dws 的调用轨迹。
        """
        if self.path.split("?")[0] != "/_env/session":
            self._send({"errcode": 404, "errmsg": "not found"}, status=404)
            return
        valid = VALID_TOKEN is None or self._bearer() == VALID_TOKEN
        record("session_valid", {}, ok=valid, as_tool="_env:session_valid",
               extra=None if valid else {"error": "http_401 invalid access_token"})
        self._send({"session_valid": valid}, status=200 if valid else 401)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            request = json.loads(raw)
        except ValueError:
            self._send({"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "parse error"}})
            return

        method = request.get("method")
        request_id = request.get("id", 1)

        if method == "initialize":
            self._send({"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "dingtalk-mcp", "version": "1.0"},
            }})
            return
        if method == "notifications/initialized":
            self._send({"jsonrpc": "2.0", "id": request_id, "result": {}})
            return
        if method == "tools/list":
            self._send({"jsonrpc": "2.0", "id": request_id,
                        "result": {"tools": [{"name": name, "inputSchema":
                                              {"type": "object"}} for name in TOOLS]}})
            return
        if method != "tools/call":
            self._send({"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32601, "message": f"unknown method {method}"}})
            return

        params = request.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}

        # 登录态校验。错误形状照抄钉钉开放平台：HTTP 401 + errcode/errmsg，
        # 不是一句 "auth failed"——CLI 认这个形状，会翻成 category:auth /
        # reason:http_401，并提示「必要时重新登录」。
        if VALID_TOKEN is not None and self._bearer() != VALID_TOKEN:
            record(name, arguments, ok=False,
                   extra={"error": "http_401 invalid access_token",
                          "errcode": 88})
            self._send({"errcode": 88, "errmsg": "invalid access_token",
                        "requestid": "f3c1a7e2-9d40-4a11-8e7c-0b52d9a6c318"},
                       status=401)
            return

        record(name, arguments)

        handler = TOOLS.get(name)
        if handler is None:
            self._send({"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": json.dumps(
                    {"error": f"tool not supported: {name}"}, ensure_ascii=False)}],
                "isError": True,
            }})
            return

        payload = handler(load_fixture(), arguments)
        self._send({"jsonrpc": "2.0", "id": request_id, "result": {
            "content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": False,
        }})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
