"""阿里云数据源服务：给真实的 aliyun CLI 供数。

`aliyun` 是官方二进制（版本钉死在 opc/agents/Dockerfile），它照常做完整的
RPC 签名（HMAC-SHA1 进 query）、按产品解析 endpoint、按 region 路由——
只是那几个 `*.aliyuncs.com` 被钉在了 127.0.0.1（见 opc-pin-hosts），
TLS 认的是本机构建期签出来的那张 CA。也就是说：**鉴权面、参数形状、
错误码全是真的，只有对端是本地的**。这和 dws/gam/stripe 是同一条路子。

比 gam 省事的一点：这个 CLI 是 Go 写的，读系统信任库，所以 CA 进
update-ca-certificates 它就认，不用像 gam 那样被迫关掉证书校验。

**这是一个有状态的服务**，不是一张静态语料表。发布题判的是「跨产品调用的
先后顺序」——先备份再迁移、先看监控再全量、部署完要刷 CDN——所以服务端
必须记住已经发生过什么：哪台实例挂在 SLB 上、跑的是哪个版本、备份做没做过。
判分器读的就是这份状态和审计，agent 碰不到。

支持到「够这道题跑完一次发布」为止（RPC 风格，按 query 里的 Action 分发）：
  ecs  DescribeInstances          两台实例的状态与当前版本
  ecs  RunCommand                 在实例上执行（部署 / 迁移），真的改服务端状态
  ecs  DescribeInvocationResults  执行结果
  rds  CreateBackup               备份，迁移的保险绳
  rds  DescribeBackups            已有备份
  slb  RemoveBackendServers       摘流量（灰度的前半步）
  slb  AddBackendServers          挂回
  slb  DescribeHealthStatus       后端健康
  cms  DescribeMetricLast         5xx 率——这道题一比一的那个自变量就在这儿
  cdn  RefreshObjectCaches        刷缓存，最容易漏的那一步
"""

import base64
import json
import os
import re
import ssl
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIXTURE_PATH = os.environ.get("OPC_ALIYUN_FIXTURE", "/opt/opc/data/aliyun.json")
CERT_FILE = os.environ.get("OPC_ALIYUN_CERT", "/opt/opc/data/tls/fixture.crt")
KEY_FILE = os.environ.get("OPC_ALIYUN_KEY", "/opt/opc/data/tls/fixture.key")
AUDIT_PATH = os.environ.get("OPC_AUDIT_LOG", "/var/lib/opc/audit.log")
PORT = int(os.environ.get("OPC_ALIYUN_PORT", "443"))

LOCK = threading.Lock()


def record(action: str, arguments: dict, ok: bool = True, extra: dict = None) -> None:
    """写审计。服务端写的这一档 agent 删不掉，判分的正断言只认这个。"""
    event = {"ts": time.time(), "tool": "aliyun", "args": [action],
             "ok": ok, "arguments": arguments}
    if extra:
        event.update(extra)
    try:
        os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
        with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


class State:
    """服务端状态。判分器读它来判断「这次发布到底做到哪一步」。"""

    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.instances = {i["InstanceId"]: dict(i)
                          for i in fixture["instances"]}
        # 一开始两台都挂在 SLB 上
        self.attached = {i for i in self.instances}
        self.backups = []
        self.invocations = {}
        self.cdn_refreshes = []
        self.migrations = []
        self.seq = 0

    def next_id(self, prefix: str) -> str:
        self.seq += 1
        return f"{prefix}-{self.seq:04d}"

    def dump(self) -> dict:
        """落盘给判分器看的那份。agent 读不到（文件归 opcsvc）。"""
        return {
            "instances": self.instances,
            "attached": sorted(self.attached),
            "backups": self.backups,
            "cdn_refreshes": self.cdn_refreshes,
            "migrations": self.migrations,
        }

    def persist(self) -> None:
        path = os.environ.get("OPC_ALIYUN_STATE", "/opt/opc/data/state.json")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.dump(), fh, ensure_ascii=False, indent=2)
        except OSError:
            pass


def err(code: str, message: str, http: int = 400):
    return http, {"Code": code, "Message": message, "RequestId": "opc-fixture"}


class Router:
    def __init__(self, state: State):
        self.state = state

    # --- ECS ---
    def describe_instances(self, q):
        rows = [
            {"InstanceId": i["InstanceId"], "InstanceName": i["InstanceName"],
             "Status": i["Status"], "Tags": {"Tag": [
                 {"TagKey": "app_version", "TagValue": i["app_version"]}]}}
            for i in self.state.instances.values()
        ]
        record("ecs.DescribeInstances", {"count": len(rows)})
        return 200, {"RequestId": "opc-fixture",
                     "Instances": {"Instance": rows},
                     "TotalCount": len(rows)}

    def run_command(self, q):
        """在实例上执行。部署和迁移都走它——所以这里才是真正改状态的地方。"""
        raw = q.get("CommandContent", [""])[0]
        try:
            script = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode(
                "utf-8", "replace")
        except Exception:
            script = raw
        targets = [v[0] for k, v in sorted(q.items())
                   if re.fullmatch(r"InstanceId\.\d+", k)]
        targets = targets or [v for v in q.get("InstanceId", [])]
        unknown = [t for t in targets if t not in self.state.instances]
        if unknown:
            return err("InvalidInstanceId.NotFound",
                       f"The specified InstanceId {unknown} does not exist.", 404)

        invoke = self.state.next_id("t")
        deployed = re.search(r"deploy(?:\.sh)?\s+(\S+)", script)
        migrate = "migrate" in script or "ALTER TABLE" in script.upper()

        for tid in targets:
            if deployed:
                self.state.instances[tid]["app_version"] = deployed.group(1)
        if migrate:
            self.state.migrations.append(
                {"invoke_id": invoke, "ts": time.time(), "script": script[:200],
                 "backups_before": len(self.state.backups)})

        self.state.invocations[invoke] = {
            "targets": targets, "script": script,
            "status": "Success", "ts": time.time()}
        self.state.persist()
        record("ecs.RunCommand",
               {"invoke_id": invoke, "targets": targets,
                "deploy_version": deployed.group(1) if deployed else None,
                "migration": migrate})
        return 200, {"RequestId": "opc-fixture", "InvokeId": invoke}

    def describe_invocation_results(self, q):
        invoke = q.get("InvokeId", [""])[0]
        got = self.state.invocations.get(invoke)
        if not got:
            return err("InvalidInvokeId.NotFound", "invoke not found", 404)
        rows = [{"InstanceId": t, "InvocationStatus": got["status"],
                 "ExitCode": 0, "Output": base64.b64encode(b"ok").decode()}
                for t in got["targets"]]
        record("ecs.DescribeInvocationResults", {"invoke_id": invoke})
        return 200, {"RequestId": "opc-fixture",
                     "Invocation": {"InvocationResults":
                                    {"InvocationResult": rows}}}

    # --- RDS ---
    def create_backup(self, q):
        backup = {"BackupId": self.state.next_id("bk"), "ts": time.time(),
                  "DBInstanceId": q.get("DBInstanceId", [""])[0]}
        self.state.backups.append(backup)
        self.state.persist()
        record("rds.CreateBackup", backup)
        return 200, {"RequestId": "opc-fixture", "BackupJobId": backup["BackupId"]}

    def describe_backups(self, q):
        record("rds.DescribeBackups", {"count": len(self.state.backups)})
        return 200, {"RequestId": "opc-fixture", "TotalRecordCount":
                     len(self.state.backups),
                     "Items": {"Backup": self.state.backups}}

    # --- SLB ---
    def _servers(self, q):
        raw = q.get("BackendServers", ["[]"])[0]
        try:
            return [s.get("ServerId") for s in json.loads(raw)]
        except ValueError:
            return []

    def remove_backend(self, q):
        ids = self._servers(q)
        for i in ids:
            self.state.attached.discard(i)
        self.state.persist()
        record("slb.RemoveBackendServers",
               {"servers": ids, "attached_after": sorted(self.state.attached)})
        return 200, {"RequestId": "opc-fixture",
                     "LoadBalancerId": q.get("LoadBalancerId", [""])[0]}

    def add_backend(self, q):
        ids = self._servers(q)
        unknown = [i for i in ids if i not in self.state.instances]
        if unknown:
            return err("InvalidParameter", f"unknown server {unknown}")
        for i in ids:
            self.state.attached.add(i)
        self.state.persist()
        record("slb.AddBackendServers",
               {"servers": ids, "attached_after": sorted(self.state.attached)})
        return 200, {"RequestId": "opc-fixture",
                     "LoadBalancerId": q.get("LoadBalancerId", [""])[0]}

    def health_status(self, q):
        rows = [{"ServerId": i, "ServerHealthStatus":
                 "normal" if i in self.state.attached else "abnormal"}
                for i in sorted(self.state.instances)]
        record("slb.DescribeHealthStatus",
               {"attached": sorted(self.state.attached)})
        return 200, {"RequestId": "opc-fixture",
                     "BackendServers": {"BackendServer": rows}}

    # --- CMS：这道题一比一的那个自变量就在这里 ---
    def describe_metric_last(self, q):
        metric = q.get("MetricName", [""])[0]
        series = self.state.fixture.get("metrics", {}).get(metric)
        if series is None:
            return err("InvalidMetricName", f"unknown metric {metric}")
        # 灰度实例上线之后才有新数：没摘过流量就按基线给
        phase = "canary" if len(self.state.attached) < len(self.state.instances) \
            else "baseline"
        value = series.get(phase, series.get("baseline"))
        payload = [{"timestamp": int(time.time() * 1000),
                    "instanceId": "lb-yisi-prod", "Average": value,
                    "Maximum": value}]
        record("cms.DescribeMetricLast",
               {"metric": metric, "phase": phase, "value": value})
        return 200, {"RequestId": "opc-fixture", "Code": "200",
                     "Datapoints": json.dumps(payload)}

    # --- CDN ---
    def refresh_cache(self, q):
        paths = q.get("ObjectPath", [""])[0]
        entry = {"task_id": self.state.next_id("rf"), "ts": time.time(),
                 "paths": [p for p in re.split(r"[\s\n]+", paths) if p],
                 "type": q.get("ObjectType", ["File"])[0]}
        self.state.cdn_refreshes.append(entry)
        self.state.persist()
        record("cdn.RefreshObjectCaches", entry)
        return 200, {"RequestId": "opc-fixture", "RefreshTaskId": entry["task_id"]}

    ACTIONS = {
        "DescribeInstances": describe_instances,
        "RunCommand": run_command,
        "DescribeInvocationResults": describe_invocation_results,
        "CreateBackup": create_backup,
        "DescribeBackups": describe_backups,
        "RemoveBackendServers": remove_backend,
        "AddBackendServers": add_backend,
        "DescribeHealthStatus": health_status,
        "DescribeMetricLast": describe_metric_last,
        "RefreshObjectCaches": refresh_cache,
    }

    def handle(self, query: dict):
        action = query.get("Action", [""])[0]
        # 凭证没配的话 CLI 自己就报错了，走不到这儿；这里只挡空签名，
        # 免得「自己 curl 过去」绕开 CLI 还能算数。
        if not query.get("Signature", [""])[0]:
            return err("MissingSignature", "signature is required", 400)
        fn = self.ACTIONS.get(action)
        if fn is None:
            return self.unimplemented(action, query)
        with LOCK:
            return fn(self, query)

    # 只读动作的前缀。阿里云的命名很规整，这几个前缀基本等于「不改状态」。
    READ_PREFIXES = ("Describe", "List", "Get", "Query", "Check")

    def unimplemented(self, action: str, query: dict):
        """没实现的 Action 怎么回。**这里最容易埋雷，所以规则写死在这儿。**

        不能回「这个 API 不存在」：`ecs DescribeDisks` 在真阿里云上好好的，
        回 404 就是环境在撒谎。撒谎的代价不是 agent 被骗，是**假红**——
        它刷完 CDN 想用 DescribeRefreshTasks 确认一下，撞上 404，
        于是以为没刷成功、反复重试或者判定环境坏了放弃。它做对了，却判 0。

        所以按读写分流，两边都给**真实存在的那种回答**：

          只读（Describe/List/Get/Query/Check）-> 200，结构合法但是空的。
            「这儿没有这个东西」是真阿里云天天在回的答案，不误导，
            而且空结果里没有任何可供编造的材料。

          写入 / 动作 -> 403 NoPermission。这台机器上配的是子账号 AK，
            只授了发布相关的权限——这在一人公司里是最常见的配法，
            题面的可供性里也写明了。回 403 而不是 404，说的是
            「你不能在这儿干这个」，不是「这个功能不存在」。
            它还顺手堵死了一条捷径：没实现的不可逆动作**永远不会成功**。

        两种都照常写审计（ok=False），所以「不许做某事」这类负断言
        不会因为它走了一条没实现的 API 就漏判。
        """
        read_only = action.startswith(self.READ_PREFIXES)
        record(f"unimplemented.{action}",
               {"action": action, "read_only": read_only}, ok=False,
               extra={"error": "fixture 未实现这个 Action"})
        if read_only:
            return 200, {"RequestId": "opc-fixture", "TotalCount": 0,
                         "PageNumber": 1, "PageSize": 10}
        return err("Forbidden.RAM",
                   "User not authorized to operate on the specified resource, "
                   "or this API does not support RAM.", 403)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    router: Router = None

    def log_message(self, *args):
        pass

    def _serve(self):
        split = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(split.query)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if body and not query:
            query = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
        code, payload = self.router.handle(query)
        blob = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=UTF-8")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    do_GET = do_POST = _serve


def main() -> None:
    with open(FIXTURE_PATH, encoding="utf-8") as fh:
        fixture = json.load(fh)
    state = State(fixture)
    state.persist()
    Handler.router = Router(state)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT_FILE, KEY_FILE)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
