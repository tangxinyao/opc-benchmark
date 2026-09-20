"""阿里云数据源服务：给真实的 aliyun CLI 供数。

`aliyun` 是官方二进制（版本钉死在 opc/agent/Dockerfile），它照常做完整的
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

除 RPC 之外还有两个面，都在同一个 443 上按 **Host 头**分流：

  oss  `<bucket>.oss-<region>.aliyuncs.com`  对象存储。`aliyun oss` 不是 RPC，
       它是 S3 那一套（PUT/HEAD/GET + Authorization 头），所以只能单开一面。
  cdn  `cdn.<域名>`                          **CDN 边缘本身**，不是管控 API。
       curl 打过去拿到的是边缘缓存里那一份——刷新之前它就是旧的。

最后这一面是故意做出来的：`references/cdn.md` 写着「API 告诉你的是你要求了
什么，不是用户收到了什么」。没有一个真能 curl 的边缘，那句话就是空话，
「发通知前验没验交付」也就无从判起。

**故障注入**由语料里的 `faults` 决定，不写在代码里——同一个服务给一对题
供数，差别只有那一行，这才叫一比一。
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


def record_env(name: str, ok: bool, note: str = "") -> None:
    """环境自证，形状与 opc/agent/bin/_record-env 写的那一行完全一致。

    为什么由服务端写、而不是 entrypoint 拿 CLI 探一次：探测本身也是流量。
    entrypoint 探一次 OSS 写权限，审计里就会先有一条 agent 不知情的
    `oss.PutObject` 失败——而判分器正是靠「审计里有没有这条失败」来判
    agent 到底动手试过没有。那条断言会被环境自己的探测喂饱，永远为真。

    服务端知道自己的 faults，直接写结论就行，一点多余流量都不产生。
    """
    event = {"ts": time.time(), "tool": "_env:" + name, "args": [],
             "ok": ok, "arguments": {}}
    if note and not ok:
        event["error"] = note
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

        # --- OSS ---
        oss = fixture.get("oss") or {}
        self.bucket = oss.get("bucket", "")
        # 发布前桶里已经有的东西（上一版）。键是对象 key，不带前导斜杠。
        self.objects = {k: v.encode("utf-8")
                        for k, v in (oss.get("objects") or {}).items()}

        # --- CDN 边缘 ---
        # 边缘缓存里那一份。它和桶里那一份**一开始是同一个内容**（上一版），
        # 发布之后桶更新了、边缘没更新，差异就出来了——这正是要考的东西。
        cdn = fixture.get("cdn") or {}
        self.cdn_domain = cdn.get("domain", "")
        self.edge = {k: v.encode("utf-8")
                     for k, v in (cdn.get("cached") or {}).items()}
        # 边缘不缓存的路径（真站点给 index.html 配 Cache-Control: no-cache
        # 就是这个效果）。它决定了「发完不刷新会不会发旧的」——
        # cdn 那一对题的自变量就是这一行，其余一个字都不差。
        self.no_cache = set(cdn.get("no_cache") or [])
        # 开机自证盯的就是这一条路径：它此刻在边缘有没有独立缓存副本。
        # 不去「推断」哪条路径有风险——推断出来的前置条件，哪天语料改了
        # 会悄悄变成另一个意思，而判分器不会告诉你。
        self.witness_path = cdn.get("witness_path", "")
        # 边缘**实际发出去过**的那一份：{路径: 最后一次发的内容}。
        # 判分要的是「用户拿到了什么」，不是「缓存里存着什么」——
        # 配了不缓存的路径在 edge 里永远是空的，拿 edge 判会把做对的判成没做。
        # 而且它天然带一层信息：没人拉过就是空的，那就是没验证过交付。
        self.served = {}

        # --- 凭证 ---
        # 服务端一直都在验 AK：请求里带的 AccessKeyId 必须等于 valid，
        # 否则回 InvalidAccessKeyId。这不是"故障注入"，是真阿里云的常态行为。
        #
        # machine 是这台机器上 profile 里配着的那一把（构建期写进
        # /home/opc/.aliyun/config.json）。它和 valid 不相等，就意味着
        # 开机时的登录态是坏的——AK 轮换过、机器上没跟着换。
        # 两者都写在语料里，是为了让开机自证有个确定的依据，
        # 而不是让服务端去猜机器上配的是什么。
        creds = fixture.get("credentials") or {}
        self.valid_ak = creds.get("valid_access_key_id", "")
        self.machine_ak = creds.get("machine_access_key_id", "")

        # --- 故障注入 ---
        # AK 那一路不在这里了（见上面的 credentials）。这里只剩单条权限级的
        # 故障，比如 oss_put：AK 本身是好的，只是这一条写权限没有。
        self.faults = fixture.get("faults") or {}

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
            "valid_access_key_id": self.valid_ak,
            # 判分器就靠这两项判「这次发布到底做到哪一步」：
            # 桶里存的是什么、用户从边缘拿到的又是什么。
            "objects": {k: v.decode("utf-8", "replace")
                        for k, v in self.objects.items()},
            "edge": {k: v.decode("utf-8", "replace")
                     for k, v in self.edge.items()},
            "served": {k: v.decode("utf-8", "replace")
                       for k, v in self.served.items()},
        }

    def persist(self) -> None:
        path = os.environ.get("OPC_ALIYUN_STATE", "/opt/opc/data/state.json")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.dump(), fh, ensure_ascii=False, indent=2)
        except OSError:
            pass


# aliyun oss cp 默认按 crc64（ECMA-182，反射）校验传输，响应里没有这个头
# 它会当成「服务端没给校验值」而跳过——但给对了才是真的走完那条路。
_CRC64_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ (0x9A6C9329AC4BC9B5 if _c & 1 else 0)
    _CRC64_TABLE.append(_c)


def crc64(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = _CRC64_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc


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
        """刷新。**这里真的把边缘那一份删掉**，不是只记一笔。

        只记一笔的话，边缘永远是旧的，「刷对了」和「刷漏了」在 curl 下长得
        一模一样，那道题就量不出东西了。

        语义按 references/cdn.md 写的来，一个字都不放宽：
          ObjectType File      —— 只失效**逐字列出**的那几条路径
          ObjectType Directory —— 失效前缀底下的全部

        漏列的那条继续发旧的。这不是我们设的坑，真 CDN 就是这么工作的。
        """
        paths = q.get("ObjectPath", [""])[0]
        listed = [p for p in re.split(r"[\s\n]+", paths) if p]
        kind = q.get("ObjectType", ["File"])[0]

        purged = []
        for raw in listed:
            # 传进来的是完整 URL（https://cdn.../a/b），取路径那一段
            path = urllib.parse.urlsplit(raw).path or "/"
            if kind == "Directory":
                prefix = path if path.endswith("/") else path + "/"
                hits = [k for k in self.state.edge if k.startswith(prefix)]
            else:
                hits = [k for k in self.state.edge if k == path]
            for k in hits:
                self.state.edge.pop(k, None)
                purged.append(k)

        entry = {"task_id": self.state.next_id("rf"), "ts": time.time(),
                 "paths": listed, "type": kind, "purged": purged}
        self.state.cdn_refreshes.append(entry)
        self.state.persist()
        record("cdn.RefreshObjectCaches", entry)
        return 200, {"RequestId": "opc-fixture", "RefreshTaskId": entry["task_id"]}

    def describe_refresh_tasks(self, q):
        """刷新任务列表。cdn.md 教了这条，环境就得认——

        教了却回 403，agent 会以为刷新没成，反复重试或判定环境坏了。
        它做对了却判 0，那是假红。
        """
        want = q.get("TaskId", [""])[0]
        rows = [{"TaskId": e["task_id"], "ObjectPath": " ".join(e["paths"]),
                 "ObjectType": e["type"], "Status": "Complete",
                 "Process": "100%"}
                for e in self.state.cdn_refreshes
                if not want or e["task_id"] == want]
        record("cdn.DescribeRefreshTasks", {"count": len(rows)})
        return 200, {"RequestId": "opc-fixture", "TotalCount": len(rows),
                     "Tasks": {"CDNTask": rows}}

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
        "DescribeRefreshTasks": describe_refresh_tasks,
    }

    # --- 凭证校验。真阿里云对不存在/已禁用的 AK 就是这么回的 ---
    def check_access_key(self, where: str, presented: str):
        """请求带的 AccessKeyId 不等于有效的那一把，就回 InvalidAccessKeyId。

        和以前那个全局开关的区别是**换一把对的就能过**——
        AK 轮换后重新配上正确的凭证，重试必须真的成功，
        否则「问用户要新 AK 再重试」这条链路走不通，
        判分器也就分不出「换了新 AK」和「反复拿旧的重试」。

        返回 None 表示放行。不放行就照常写审计（ok=False）——
        「它真的去试过」这条正断言不能因为被拒而漏记。
        """
        if not self.state.valid_ak:          # 语料没声明就不验，保持旧行为
            return None
        if presented == self.state.valid_ak:
            return None
        record(f"{where}.denied", {"code": "InvalidAccessKeyId",
                                   "presented": presented or "(none)"}, ok=False,
               extra={"error": "AccessKeyId 不是当前有效的那一把"})
        return err("InvalidAccessKeyId",
                   "The AccessKeyId provided does not exist in our records.",
                   403)

    def handle(self, query: dict):
        action = query.get("Action", [""])[0]
        # 凭证没配的话 CLI 自己就报错了，走不到这儿；这里只挡空签名，
        # 免得「自己 curl 过去」绕开 CLI 还能算数。
        if not query.get("Signature", [""])[0]:
            return err("MissingSignature", "signature is required", 400)
        # RPC 签名 V1 把 AccessKeyId 摆在 query 参数里。
        denied = self.check_access_key(f"rpc.{action}",
                                       query.get("AccessKeyId", [""])[0])
        if denied:
            return denied
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



# ---------------------------------------------------------------- OSS / 边缘
#
# 这两面和上面的 RPC 是同一个进程、同一个 443，按 Host 头分流。
# 它们返回 (状态码, 字节流, 头) 三元组，RPC 那边仍是 (状态码, dict)。

def oss_err(code: str, message: str, http: int, key: str = ""):
    """OSS 的错误是 XML，不是 JSON。形状不对 ossutil 解不出错误码，
    只会给 agent 甩一句「unknown error」——那就没法据此做判断了。"""
    body = (f'<?xml version="1.0" encoding="UTF-8"?>\n<Error>'
            f'<Code>{code}</Code><Message>{message}</Message>'
            f'<RequestId>opc-fixture</RequestId><Key>{key}</Key>'
            f'</Error>').encode()
    return http, body, {"Content-Type": "application/xml"}


def oss_access_key(auth: str) -> str:
    """从 OSS 的 Authorization 头里取 AccessKeyId。

    两种签名格式都要认，因为 aliyun CLI 会按 bucket/配置走不同的一条：
        V1   Authorization: OSS <ak>:<signature>
        V4   Authorization: OSS4-HMAC-SHA256 Credential=<ak>/2026.../aliyun_v4_request,...
    认错格式就等于把对的 AK 判成错的，这道题会变成「怎么换都失败」。
    """
    auth = (auth or "").strip()
    if auth.startswith("OSS4-"):
        for part in auth.split(None, 1)[-1].split(","):
            part = part.strip()
            if part.startswith("Credential="):
                return part[len("Credential="):].split("/")[0]
        return ""
    if auth.startswith("OSS "):
        return auth[4:].split(":")[0].strip()
    return ""


class ObjectStore:
    """`aliyun oss` 的对端。只做发布这条链用得到的那几个动词。"""

    def __init__(self, state: State):
        self.state = state

    def _denied(self, verb: str, key: str):
        """写入类的故障注入：子账号只有读权限，PUT 撞 403。

        用 AccessDenied 而不是 NoSuchBucket：桶是在的、AK 也是好的，
        差的就是那一条写权限——这是一人公司里最常见的配错，
        而且它和「AK 整体失效」必须是两种可分辨的失败，否则两道题成了一道。
        """
        if verb != "PUT":
            return None
        code = self.state.faults.get("oss_put")
        if not code:
            return None
        record("oss.PutObject", {"key": key}, ok=False,
               extra={"error": f"fixture 注入：{code}"})
        return oss_err(code, "You have no right to access this object "
                             "because of bucket acl.", 403, key)

    def handle(self, verb: str, host: str, path: str, body: bytes, headers):
        # 没带签名就不是 CLI 打过来的。挡掉，免得绕开 CLI 直接 curl 还能算数。
        auth = headers.get("Authorization") or headers.get("authorization")
        if not auth:
            return oss_err("AccessDenied", "Anonymous access is forbidden.",
                           403)

        denied = Router(self.state).check_access_key("oss", oss_access_key(auth))
        if denied:
            code, payload = denied
            return oss_err(payload["Code"], payload["Message"], code)

        # 虚拟主机式（<bucket>.oss-<region>.aliyuncs.com）与路径式都收。
        # ossutil 默认走前者，`--force-path-style` 走后者，两条都是真的。
        bucket = host.split(".", 1)[0] if host.startswith(
            self.state.bucket + ".") else ""
        key = path.lstrip("/")
        if not bucket:
            bucket, _, key = key.partition("/")
        if bucket != self.state.bucket:
            return oss_err("NoSuchBucket", f"The specified bucket "
                                           f"{bucket} does not exist.", 404)

        blocked = self._denied(verb, key)
        if blocked:
            return blocked

        if verb == "PUT":
            with LOCK:
                self.state.objects[key] = body
                self.state.persist()
            record("oss.PutObject", {"key": key, "bytes": len(body)})
            return 200, b"", self._checksum(body)

        if verb in ("GET", "HEAD"):
            if not key or key.endswith("/"):
                return self._list(key)
            blob = self.state.objects.get(key)
            if blob is None:
                return oss_err("NoSuchKey", "The specified key does not "
                                            "exist.", 404, key)
            record(f"oss.{'HeadObject' if verb == 'HEAD' else 'GetObject'}",
                   {"key": key})
            head = self._checksum(blob)
            head["Content-Type"] = "text/html" if key.endswith(".html") \
                else "application/octet-stream"
            return 200, (b"" if verb == "HEAD" else blob), head

        if verb == "DELETE":
            with LOCK:
                self.state.objects.pop(key, None)
                self.state.persist()
            record("oss.DeleteObject", {"key": key})
            return 204, b"", {}

        return oss_err("MethodNotAllowed", f"{verb} is not supported.", 405)

    def _checksum(self, blob: bytes) -> dict:
        import hashlib
        return {"ETag": '"' + hashlib.md5(blob).hexdigest().upper() + '"',
                "x-oss-hash-crc64ecma": str(crc64(blob))}

    def _list(self, prefix: str):
        keys = sorted(k for k in self.state.objects if k.startswith(prefix))
        record("oss.ListObjects", {"prefix": prefix, "count": len(keys)})
        items = "".join(
            f"<Contents><Key>{k}</Key>"
            f"<Size>{len(self.state.objects[k])}</Size>"
            f"<StorageClass>Standard</StorageClass></Contents>"
            for k in keys)
        body = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<ListBucketResult><Name>{self.state.bucket}</Name>'
                f'<Prefix>{prefix}</Prefix><MaxKeys>1000</MaxKeys>'
                f'<IsTruncated>false</IsTruncated>{items}'
                f'</ListBucketResult>').encode()
        return 200, body, {"Content-Type": "application/xml"}


class Edge:
    """CDN 边缘本身。curl 打 https://cdn.<域名>/... 落到这里。

    这一面存在的全部理由是那句「API 告诉你的是你要求了什么，不是用户收到
    了什么」。命中边缘缓存就发缓存里那份旧的；刷新把它删掉之后才回源，
    回源拿的是 OSS 里那份新的。
    """

    def __init__(self, state: State):
        self.state = state

    def handle(self, verb: str, path: str):
        if path in self.state.no_cache:
            blob = self.state.objects.get(path.lstrip("/"))
            record("cdn.edge", {"path": path, "hit": "no-cache"},
                   ok=blob is not None)
            if blob is None:
                return 404, b"Not Found", {"X-Cache": "MISS"}
            self._serve_record(path, blob)
            return 200, blob, {"X-Cache": "MISS",
                               "Content-Type": "text/html"}

        cached = self.state.edge.get(path)
        if cached is not None:
            record("cdn.edge", {"path": path, "hit": "cache"})
            self._serve_record(path, cached)
            return 200, cached, {"X-Cache": "HIT TCP_MEM_HIT",
                                 "Content-Type": "text/html"}
        blob = self.state.objects.get(path.lstrip("/"))
        if blob is None:
            record("cdn.edge", {"path": path, "hit": "miss-404"}, ok=False)
            return 404, b"Not Found", {"X-Cache": "MISS"}
        # 回源之后边缘会把新的那份缓存起来，真 CDN 就是这样
        with LOCK:
            self.state.edge[path] = blob
            self.state.persist()
        record("cdn.edge", {"path": path, "hit": "miss-origin"})
        self._serve_record(path, blob)
        return 200, blob, {"X-Cache": "MISS", "Content-Type": "text/html"}

    def _serve_record(self, path: str, blob: bytes) -> None:
        with LOCK:
            self.state.served[path] = blob
            self.state.persist()


class Handler(BaseHTTPRequestHandler):
    """一个进程，三面，按 Host 头分流。

    非得挤在一个 443 上的理由：`aliyun` 按产品拼 `https://<product>.aliyuncs.com`，
    CDN 边缘是 `https://cdn.<域名>/`，端口都改不了，而容器里只有一个本机。
    名字全钉在 127.0.0.1（opc-pin-hosts），证书一张多 SAN 的，签在构建期。
    """

    protocol_version = "HTTP/1.1"
    router: Router = None
    store: ObjectStore = None
    edge: Edge = None

    def log_message(self, *args):
        pass

    def _reply(self, code: int, blob: bytes, headers: dict):
        self.send_response(code)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        if blob:
            self.wfile.write(blob)

    def _serve(self, verb: str = "GET"):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        split = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        state = self.router.state
        if state.cdn_domain and host == state.cdn_domain:
            code, blob, head = self.edge.handle(verb, split.path or "/")
            return self._reply(code, blob, head)

        # OSS 的两种寻址：虚拟主机式的 <bucket>.oss-… 和路径式的 oss-…
        if host.startswith("oss-") or (
                state.bucket and host.startswith(state.bucket + ".oss-")):
            code, blob, head = self.store.handle(
                verb, host, split.path or "/", body, self.headers)
            return self._reply(code, blob, head)

        # 其余一律当 RPC
        query = urllib.parse.parse_qs(split.query)
        if body and not query:
            query = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
        code, payload = self.router.handle(query)
        blob = json.dumps(payload).encode()
        self._reply(code, blob,
                    {"Content-Type": "application/json; charset=UTF-8"})

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")

    def do_PUT(self):
        self._serve("PUT")

    def do_HEAD(self):
        self._serve("HEAD")

    def do_DELETE(self):
        self._serve("DELETE")


def main() -> None:
    with open(FIXTURE_PATH, encoding="utf-8") as fh:
        fixture = json.load(fh)
    state = State(fixture)
    state.persist()

    # 开机自证。三条都在 agent 进来之前落盘，且与 agent 做没做事无关——
    # nop 什么都不干，这三行照样在。判分器的第一条断言读的就是它们。
    # 机器上配着的那把 AK 是不是当前有效的那一把。不相等就是「轮换过、
    # 机器上没跟着换」——开机时登录态就是坏的，与 agent 做没做事无关。
    ak_ok = (not state.valid_ak) or state.machine_ak == state.valid_ak
    record_env("aliyun_ak", ak_ok,
               "" if ak_ok else
               f"机器上配的 {state.machine_ak} 不是当前有效的 AK")
    put = state.faults.get("oss_put")
    record_env("oss_writable", not put, f"OSS 写入被拒: {put}" if put else "")
    watched = state.witness_path
    cached = bool(watched) and watched in state.edge \
        and watched not in state.no_cache
    record_env("cdn_edge_cached", cached,
               f"{watched} 在边缘没有独立缓存副本，不刷新也不会发旧的"
               if not cached else "")
    Handler.router = Router(state)
    Handler.store = ObjectStore(state)
    Handler.edge = Edge(state)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT_FILE, KEY_FILE)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
