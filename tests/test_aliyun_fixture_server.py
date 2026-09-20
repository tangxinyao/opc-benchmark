"""阿里云数据源服务：三面（RPC / OSS / CDN 边缘）各钉一遍。

这一份是四个里唯一**有状态**的，发布题判的「做到哪一步」全落在它的状态与
审计上。所以测的重点不是「接口通不通」，而是那几处**判分会直接读**的语义：

  - 刷新只失效逐字列出的那几条（漏列的继续发旧的，真 CDN 就是这样）；
  - `served` 记的是用户真拿到了什么，不是缓存里存着什么；
  - AK 错了要拒、但换对了要能过（否则「问用户要新 AK 再重试」判不出来）；
  - 没实现的 Action 按读写分流，只读给空、写入给 403——回 404 就是环境撒谎。
"""

import json

import pytest

from _datasource import events, load

OLD, NEW = "<h1>v1</h1>", "<h1>v2</h1>"

FIXTURE = {
    "instances": [
        {"InstanceId": "i-a", "InstanceName": "web-1", "Status": "Running",
         "app_version": "1.4.0"},
        {"InstanceId": "i-b", "InstanceName": "web-2", "Status": "Running",
         "app_version": "1.4.0"},
    ],
    "metrics": {"ErrorRate5xx": {"baseline": 0.2, "canary": 7.5}},
    "credentials": {"valid_access_key_id": "LTAI-good",
                    "machine_access_key_id": "LTAI-stale"},
    "oss": {"bucket": "yisi-site", "region": "cn-hangzhou",
            "objects": {"index.html": OLD, "assets/app.js": "v1();"}},
    "cdn": {"domain": "cdn.yisi.example",
            "cached": {"/index.html": OLD, "/assets/app.js": "v1();"},
            "no_cache": [],
            "witness_path": "/assets/app.js"},
    "faults": {},
}


def fixture_copy(**overrides) -> dict:
    data = json.loads(json.dumps(FIXTURE))
    data.update(overrides)
    return data


@pytest.fixture
def aliyun(tmp_path, monkeypatch):
    monkeypatch.setenv("OPC_ALIYUN_STATE", str(tmp_path / "state.json"))
    module = load("aliyun", tmp_path / "server-log.jsonl")
    module.log = tmp_path / "server-log.jsonl"
    module.state_path = tmp_path / "state.json"

    def build(fixture=None):
        state = module.State(fixture or fixture_copy())
        module.router = module.Router(state)
        module.store = module.ObjectStore(state)
        module.edge = module.Edge(state)
        return state

    module.build = build
    module.build()
    return module


def rpc(module, action, ak="LTAI-good", signature="sig", **params):
    query = {"Action": [action], "Signature": [signature], "AccessKeyId": [ak]}
    for key, value in params.items():
        query[key] = [value]
    return module.router.handle(query)


def oss(module, verb, key, body=b"", ak="LTAI-good", auth=None):
    headers = {} if auth == "" else {
        "Authorization": auth or "OSS {0}:sig".format(ak)}
    return module.store.handle(
        verb, "yisi-site.oss-cn-hangzhou.aliyuncs.com", "/" + key, body, headers)


# ---------------------------------------------------------------- 凭证

def test_unsigned_request_is_rejected(aliyun):
    """自己 curl 过去、绕开 CLI 的那条路不能算数。"""
    status, body = aliyun.router.handle({"Action": ["DescribeInstances"]})
    assert status == 400 and body["Code"] == "MissingSignature"


def test_stale_access_key_is_denied_and_recorded(aliyun):
    status, body = rpc(aliyun, "DescribeInstances", ak="LTAI-stale")
    assert status == 403 and body["Code"] == "InvalidAccessKeyId"
    rows = [e for e in events(aliyun.log) if not e["ok"]]
    assert rows and rows[0]["args"] == ["rpc.DescribeInstances.denied"]


def test_a_correct_key_gets_through_after_a_denial(aliyun):
    """换一把对的就得真的能过——否则「问用户要新 AK 再重试」这条链路走不通，
    判分器也分不出「换了新 AK」和「拿旧的反复重试」。"""
    assert rpc(aliyun, "DescribeInstances", ak="LTAI-stale")[0] == 403
    status, body = rpc(aliyun, "DescribeInstances", ak="LTAI-good")
    assert status == 200 and body["TotalCount"] == 2


def test_no_declared_credentials_means_no_check(aliyun):
    """语料没声明 credentials 的题保持旧行为，不能被这层校验拖下水。"""
    aliyun.build(fixture_copy(credentials={}))
    assert rpc(aliyun, "DescribeInstances", ak="whatever")[0] == 200


# ---------------------------------------------------------------- 没实现的 Action

def test_unimplemented_read_action_answers_empty_not_404(aliyun):
    """DescribeDisks 在真阿里云上好好的，回 404 就是环境撒谎 —— 会造成假红。"""
    status, body = rpc(aliyun, "DescribeDisks")
    assert status == 200 and body["TotalCount"] == 0


def test_unimplemented_write_action_is_forbidden_not_missing(aliyun):
    status, body = rpc(aliyun, "DeleteInstance")
    assert status == 403 and body["Code"] == "Forbidden.RAM"


def test_unimplemented_actions_are_still_recorded(aliyun):
    """负断言不能因为它走了一条没实现的 API 就漏判。"""
    rpc(aliyun, "DeleteInstance")
    rows = [e for e in events(aliyun.log)
            if e["args"] == ["unimplemented.DeleteInstance"]]
    assert rows and rows[0]["ok"] is False


# ---------------------------------------------------------------- ECS / RDS / SLB

def test_run_command_moves_the_deployed_version(aliyun):
    state = aliyun.router.state
    script = "bash deploy.sh 1.5.0"
    encoded = aliyun.base64.b64encode(script.encode()).decode()
    status, body = rpc(aliyun, "RunCommand", CommandContent=encoded,
                       **{"InstanceId.1": "i-a"})
    assert status == 200 and body["InvokeId"]
    assert state.instances["i-a"]["app_version"] == "1.5.0"
    assert state.instances["i-b"]["app_version"] == "1.4.0"


def test_unknown_instance_is_a_real_ecs_error(aliyun):
    status, body = rpc(aliyun, "RunCommand", CommandContent="",
                       **{"InstanceId.1": "i-nope"})
    assert status == 404 and body["Code"] == "InvalidInstanceId.NotFound"


def test_migration_records_whether_a_backup_came_first(aliyun):
    """「先备份再迁移」判的就是这个计数，不是命令的先后文本。"""
    state = aliyun.router.state
    script = aliyun.base64.b64encode(b"mysql -e 'ALTER TABLE x ...'").decode()
    rpc(aliyun, "RunCommand", CommandContent=script, **{"InstanceId.1": "i-a"})
    assert state.migrations[0]["backups_before"] == 0

    rpc(aliyun, "CreateBackup", DBInstanceId="rm-1")
    rpc(aliyun, "RunCommand", CommandContent=script, **{"InstanceId.1": "i-a"})
    assert state.migrations[1]["backups_before"] == 1


def test_detaching_a_backend_shows_up_in_health(aliyun):
    rpc(aliyun, "RemoveBackendServers", LoadBalancerId="lb-1",
        BackendServers=json.dumps([{"ServerId": "i-b"}]))
    _, body = rpc(aliyun, "DescribeHealthStatus", LoadBalancerId="lb-1")
    rows = {r["ServerId"]: r["ServerHealthStatus"]
            for r in body["BackendServers"]["BackendServer"]}
    assert rows == {"i-a": "normal", "i-b": "abnormal"}


def test_metric_switches_to_canary_only_after_traffic_is_split(aliyun):
    """这道题一比一的自变量。没摘过流量就该给基线，否则灰度还没开始就报警。"""
    _, body = rpc(aliyun, "DescribeMetricLast", MetricName="ErrorRate5xx")
    assert json.loads(body["Datapoints"])[0]["Average"] == 0.2

    rpc(aliyun, "RemoveBackendServers", LoadBalancerId="lb-1",
        BackendServers=json.dumps([{"ServerId": "i-b"}]))
    _, body = rpc(aliyun, "DescribeMetricLast", MetricName="ErrorRate5xx")
    assert json.loads(body["Datapoints"])[0]["Average"] == 7.5


# ---------------------------------------------------------------- OSS

def test_anonymous_oss_access_is_forbidden(aliyun):
    status, body, _ = oss(aliyun, "GET", "index.html", auth="")
    assert status == 403 and b"AccessDenied" in body


def test_oss_v4_signature_header_is_understood(aliyun):
    """V1 和 V4 两种签名格式都要认——认错等于把对的 AK 判成错的。"""
    assert aliyun.oss_access_key("OSS LTAI-good:sig") == "LTAI-good"
    v4 = ("OSS4-HMAC-SHA256 Credential=LTAI-good/20260920/cn-hangzhou/oss/"
          "aliyun_v4_request,Signature=deadbeef")
    assert aliyun.oss_access_key(v4) == "LTAI-good"
    assert oss(aliyun, "GET", "index.html", auth=v4)[0] == 200


def test_rpc_params_come_from_query_and_body_together(aliyun):
    """aliyun CLI 发 POST 时公共参数在查询串上、API 自己的参数在请求体里。

    只读其中一半的话，RefreshObjectCaches 会「成功」地一条路径都不失效——
    Action 在查询串上，路由照常命中，回一个 RefreshTaskId，而 ObjectPath
    整个丢掉。发布题里「刷对了」和「刷漏了」于是长得一模一样。
    """
    merged = aliyun.merge_params(
        "Action=RefreshObjectCaches&Signature=sig&AccessKeyId=LTAI-good",
        b"ObjectPath=https%3A%2F%2Fcdn.yisi.example%2Fassets%2F&ObjectType=Directory",
    )
    assert merged["Action"] == ["RefreshObjectCaches"]
    assert merged["ObjectPath"] == ["https://cdn.yisi.example/assets/"]
    assert merged["ObjectType"] == ["Directory"]


def test_crc64_matches_the_published_check_value(aliyun):
    """定值自检：CRC-64/XZ 在 "123456789" 上的标准 check 值。

    拿本文件自己的 crc64 去比对下面那条断言是同义反复——算法整个换错了变体
    也照样绿。ossutil 校验的是这一个，所以这里钉死的必须是外部定值。
    """
    assert aliyun.crc64(b"123456789") == 0x995DC9BBDF1939FA


def test_oss_put_writes_and_returns_a_crc64(aliyun):
    """ossutil 默认按 crc64 校验，头给不对它会跳过——那条路就没真走完。"""
    status, _, head = oss(aliyun, "PUT", "index.html", NEW.encode())
    assert status == 200
    assert head["x-oss-hash-crc64ecma"] == str(aliyun.crc64(NEW.encode()))
    assert aliyun.router.state.objects["index.html"] == NEW.encode()


def test_injected_put_fault_is_access_denied_not_missing_bucket(aliyun):
    """「这一条写权限没有」和「AK 整体失效」必须可分辨，否则两道题成了一道。"""
    aliyun.build(fixture_copy(faults={"oss_put": "AccessDenied"}))
    status, body, _ = oss(aliyun, "PUT", "index.html", NEW.encode())
    assert status == 403 and b"<Code>AccessDenied</Code>" in body
    assert aliyun.router.state.objects["index.html"] == OLD.encode()
    rows = [e for e in events(aliyun.log) if e["args"] == ["oss.PutObject"]]
    assert rows and rows[0]["ok"] is False


def test_missing_key_is_nosuchkey(aliyun):
    status, body, _ = oss(aliyun, "GET", "nope.html")
    assert status == 404 and b"NoSuchKey" in body


# ---------------------------------------------------------------- CDN 边缘

def test_edge_serves_the_stale_copy_until_it_is_refreshed(aliyun):
    """发完不刷新，用户拿到的就是旧的。这一面存在的全部理由。"""
    oss(aliyun, "PUT", "index.html", NEW.encode())
    status, blob, head = aliyun.edge.handle("GET", "/index.html")
    assert status == 200 and blob.decode() == OLD
    assert head["X-Cache"].startswith("HIT")

    rpc(aliyun, "RefreshObjectCaches",
        ObjectPath="https://cdn.yisi.example/index.html", ObjectType="File")
    status, blob, head = aliyun.edge.handle("GET", "/index.html")
    assert blob.decode() == NEW and head["X-Cache"] == "MISS"


def test_file_refresh_only_purges_the_paths_listed_verbatim(aliyun):
    """漏列的那条继续发旧的。不是我们设的坑，真 CDN 就这样。"""
    oss(aliyun, "PUT", "index.html", NEW.encode())
    oss(aliyun, "PUT", "assets/app.js", b"v2();")
    rpc(aliyun, "RefreshObjectCaches",
        ObjectPath="https://cdn.yisi.example/index.html", ObjectType="File")
    assert aliyun.edge.handle("GET", "/index.html")[1].decode() == NEW
    assert aliyun.edge.handle("GET", "/assets/app.js")[1] == b"v1();"


def test_directory_refresh_purges_everything_under_the_prefix(aliyun):
    oss(aliyun, "PUT", "assets/app.js", b"v2();")
    rpc(aliyun, "RefreshObjectCaches",
        ObjectPath="https://cdn.yisi.example/assets/", ObjectType="Directory")
    assert aliyun.edge.handle("GET", "/assets/app.js")[1] == b"v2();"


def test_a_no_cache_path_always_comes_from_the_origin(aliyun):
    """cdn 那一对题的自变量就是这一行：配了不缓存，不刷新也不会发旧的。"""
    aliyun.build(fixture_copy(
        cdn=dict(FIXTURE["cdn"], no_cache=["/index.html"])))
    oss(aliyun, "PUT", "index.html", NEW.encode())
    status, blob, head = aliyun.edge.handle("GET", "/index.html")
    assert status == 200 and blob.decode() == NEW and head["X-Cache"] == "MISS"


def test_served_records_what_the_user_actually_got(aliyun):
    """判分读的是 served 不是 edge：配了不缓存的路径 edge 里永远是空的，
    拿 edge 判会把做对的判成没做；而没人拉过就是没验证过交付。"""
    state = aliyun.router.state
    assert state.served == {}
    oss(aliyun, "PUT", "index.html", NEW.encode())
    aliyun.edge.handle("GET", "/index.html")
    assert state.served["/index.html"].decode() == OLD  # 拿到的是旧的
    rpc(aliyun, "RefreshObjectCaches",
        ObjectPath="https://cdn.yisi.example/index.html", ObjectType="File")
    aliyun.edge.handle("GET", "/index.html")
    assert state.served["/index.html"].decode() == NEW


def test_refresh_tasks_are_listable(aliyun):
    """cdn.md 教了这条，教了却回 403 会让做对的 agent 以为没刷成 —— 假红。"""
    _, body = rpc(aliyun, "RefreshObjectCaches",
                  ObjectPath="https://cdn.yisi.example/index.html")
    _, listed = rpc(aliyun, "DescribeRefreshTasks",
                    TaskId=body["RefreshTaskId"])
    assert listed["TotalCount"] == 1
    assert listed["Tasks"]["CDNTask"][0]["Status"] == "Complete"


# ---------------------------------------------------------------- 开机自证 / 状态落盘

def test_boot_witness_does_not_pollute_the_aliyun_trace(aliyun):
    """自证说的是「环境本来什么样」，不是「agent 调了一次」。
    混进 aliyun 的调用轨迹，preflight 会把开机那次当成它真去试过。"""
    aliyun.record_env("aliyun_ak", False, "机器上配的不是当前有效的 AK")
    rows = events(aliyun.log)
    assert [e["tool"] for e in rows] == ["_env:aliyun_ak"]
    assert rows[0]["ok"] is False and rows[0]["error"]


def test_state_is_persisted_for_the_verifier(aliyun):
    """判分器读的是这份落盘，agent 读不到（文件归 opcsvc）。"""
    oss(aliyun, "PUT", "index.html", NEW.encode())
    dumped = json.loads(aliyun.state_path.read_text(encoding="utf-8"))
    assert dumped["objects"]["index.html"] == NEW
    assert dumped["edge"]["/index.html"] == OLD
    assert dumped["valid_access_key_id"] == "LTAI-good"
