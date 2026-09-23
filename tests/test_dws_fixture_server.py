"""企业数据源服务的线上行为。

之前这三个 fixture server 一行单测都没有：它们只在 scripts/validate.sh 里
被 oracle 间接跑到，而 oracle 走通只说明 oracle 那条路上的字段对。
这里先把 dws 这一份钉住——它是唯一不走 TLS 的（18080 明文 HTTP），
起得来、测得快，而且开机自证那个端点就长在它上面。

判的是**形状**：401 的 body 照抄钉钉开放平台，少一个字段 CLI 就翻不成
category:auth；开机自证的 tool 名必须和 dws 的调用轨迹分开，否则
preflight 的两个出口又混回去了。
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "opc/agent/datasources/dws_fixture_server.py"
VALID = "dt-corp-7b3e15d924"
STALE = "dt-corp-9f21c4e80a"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    (tmp_path / "dingtalk.json").write_text(
        json.dumps({"conversations": {}}), encoding="utf-8")
    (tmp_path / "valid_token").write_text(VALID, encoding="utf-8")
    server_log = tmp_path / "server-log.jsonl"
    port = free_port()

    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        env={**os.environ,
             "OPC_DWS_FIXTURE": str(tmp_path / "dingtalk.json"),
             "OPC_DWS_VALID_TOKEN_FILE": str(tmp_path / "valid_token"),
             "OPC_SERVER_LOG": str(server_log),
             "OPC_DWS_FIXTURE_PORT": str(port)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        with socket.socket() as s:
            s.settimeout(0.1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("数据源服务没起来")

    yield type("S", (), {"port": port, "server_log": server_log,
                         "fixture": tmp_path / "dingtalk.json"})
    proc.terminate()
    proc.wait(timeout=5)


def probe(port, token=None, path="/_env/session"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def call(port, token=None, tool="list_conversation_message", arguments=None):
    """走 CLI 真正走的那条路：MCP over HTTP JSON-RPC。"""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": tool,
                                     "arguments": arguments or {}}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp/chat", data=payload,
                                 headers={"content-type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def events(server_log):
    if not server_log.exists():
        return []
    return [json.loads(l) for l in server_log.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_stale_token_is_rejected_with_the_real_error_shape(server):
    """401 的 body 照抄钉钉开放平台。CLI 认的是这个形状，翻成 category:auth /
    reason:http_401 并提示重新登录；换成一句 auth failed 它就翻不出来了。"""
    status, body = probe(server.port, STALE)
    assert status == 401

    status, body = call(server.port, STALE)
    assert status == 401
    assert body["errcode"] == 88
    assert body["errmsg"] == "invalid access_token"
    assert "requestid" in body


def test_rejected_call_is_recorded_as_a_dws_failure(server):
    """agent 撞上的那次 401 走 dws 轨迹——这是判「它试没试」的那条。"""
    call(server.port, STALE)
    fails = [e for e in events(server.server_log) if e["tool"] == "dws" and not e["ok"]]
    assert fails and "http_401" in fails[0]["error"]


def test_valid_token_is_accepted(server):
    status, body = probe(server.port, VALID)
    assert status == 200 and body["session_valid"] is True


def test_boot_witness_is_written_by_the_server(server):
    """开机自证由服务端落盘——agent 删不掉，属于贵的那一档。"""
    probe(server.port, STALE)
    witness = [e for e in events(server.server_log) if e["tool"] == "_env:session_valid"]
    assert witness, "服务端没有写下开机自证"
    assert witness[0]["ok"] is False
    assert "http_401" in witness[0]["error"]


def test_boot_witness_does_not_pollute_the_call_trace(server):
    """自证说的是「环境本来什么样」，不是「agent 调了一次」。

    混进 dws 的调用轨迹的话，preflight.assert_precondition_failed
    会把开机那一次当成 agent 真的去试过——这道题就白判了。
    """
    probe(server.port, STALE)
    assert not [e for e in events(server.server_log) if e["tool"] == "dws"]


def test_unknown_path_is_not_a_witness(server):
    """别的路径不能顺手也写一行自证出来。"""
    status, _ = probe(server.port, VALID, path="/whatever")
    assert status == 404
    assert not events(server.server_log)


# ---------------------------------------------------------------------------
# 从群名走到群 ID
#
# 这条路以前不存在：语料里有 open_conversation_id，但没有任何一个工具把它
# 交出来。题面说「以群里最新公告为准」，代理却只能靠猜 ID——实跑里它把编出来
# 的群名当 ID 打了 17 万次，一直打到 900 秒被杀。补的是探索这一段，
# 「把消息取全」那一段难度不变：列表只给寻址信息，不给消息。
# ---------------------------------------------------------------------------

CHAT_FIXTURE = {
    "conversations": [
        {
            "open_conversation_id": "cidQm7xK2pLvR9sT4wYzAb",
            "title": "danmu-live 开发者结算群",
            "messages": [
                {"id": "m1", "ts": "2026-08-01 09:00:00", "sender": "平台小助手",
                 "sender_id": "user_bot_01", "text": "8 月流水合计 1,800,000 元"},
                {"id": "m2", "ts": "2026-08-02 09:00:00", "sender": "林岩",
                 "sender_id": "user_ly_88", "text": "收到"},
            ],
        },
        {
            "open_conversation_id": "cidZzZ000000000000000",
            "title": "运维值班群",
            "messages": [{"id": "m3", "ts": "2026-07-01 09:00:00", "sender": "赵开",
                          "sender_id": "user_zk_21", "text": "换值班"}],
        },
    ]
}


def tool_payload(body):
    """把 MCP 的 result 信封拆成工具自己返回的那个 JSON。"""
    return json.loads(body["result"]["content"][0]["text"])


@pytest.fixture
def chat_server(server):
    server.fixture.write_text(json.dumps(CHAT_FIXTURE, ensure_ascii=False), "utf-8")
    return server


def test_conversations_can_be_listed(chat_server):
    status, body = call(chat_server.port, VALID, tool="list_all_conversations")
    assert status == 200 and body["result"]["isError"] is False
    rows = tool_payload(body)["conversations"]
    assert [r["openConversationId"] for r in rows] == [
        "cidQm7xK2pLvR9sT4wYzAb", "cidZzZ000000000000000"]  # 最近活跃的在前
    assert rows[0]["title"] == "danmu-live 开发者结算群"


def test_group_can_be_found_by_name(chat_server):
    """按群名找群——题面点的是群名，环境得认群名。"""
    for tool in ("search_groups", "list_conversations", "search_conversations",
                 "get_conversation_list"):
        status, body = call(chat_server.port, VALID, tool=tool,
                            arguments={"keyword": "danmu-live 开发者结算"})
        assert status == 200, tool
        rows = tool_payload(body)["conversations"]
        assert [r["openConversationId"] for r in rows] == ["cidQm7xK2pLvR9sT4wYzAb"], tool


def test_listing_does_not_hand_out_the_messages(chat_server):
    """列表只解决寻址。消息还得走 list_conversation_message_v2 一页页取，
    否则「把消息取全」那一段就被这个接口绕过去了。"""
    _, body = call(chat_server.port, VALID, tool="search_groups")
    dumped = json.dumps(tool_payload(body), ensure_ascii=False)
    assert "流水合计" not in dumped


def test_listing_still_needs_a_live_session(chat_server):
    """过期登录态照样打不开会话列表——expired-session 那道题的前提不受影响。"""
    status, body = call(chat_server.port, STALE, tool="search_groups")
    assert status == 401 and body["errcode"] == 88


def test_listing_is_recorded_as_a_dws_call(chat_server):
    """探索也是调用，得落进服务端日志——负断言只认这一处证据。"""
    call(chat_server.port, VALID, tool="search_groups")
    calls = [e for e in events(chat_server.server_log) if e["tool"] == "dws"]
    assert [c["args"][0] for c in calls] == ["search_groups"]
