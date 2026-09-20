"""Google Workspace 数据源服务：gam 真正会踩到的那几处。

这一份的坑都不在「路由通不通」上，而在**客户端严格、服务端松**的地方：
base64 的填充、batch 回带的 Content-ID、q= 的两种时间写法。
每一条都曾经（或差点）让 gam 拿到空正文却不报错——环境在撒谎，而判分照跑。
"""

import base64
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from _datasource import events, load

FIXTURE = {
    "default_user": "amy@yisi.example",
    "mailboxes": {
        "amy@yisi.example": {
            "messages": [
                {"id": "m1", "from": "a@x.example", "to": "amy@yisi.example",
                 "subject": "发票抬头", "body": "请开票，抬头是壹思。" * 3,
                 "date": "Tue, 04 Aug 2026 09:00:00 +0800", "epoch": "1785805200"},
                {"id": "m2", "from": "b@x.example", "to": "amy@yisi.example",
                 "subject": "续费", "body": "明年还续",
                 "date": "Fri, 04 Jul 2026 09:00:00 +0800", "epoch": "1783213200"},
                {"id": "m3", "from": "c@x.example", "to": "amy@yisi.example",
                 "subject": "坏的那条", "body": "取不到",
                 "date": "Tue, 04 Aug 2026 10:00:00 +0800", "epoch": "1785808800",
                 "fetch_error": {"code": 503, "reason": "backendError",
                                 "message": "Backend Error"}},
            ]
        }
    },
}


@pytest.fixture
def gws(tmp_path):
    module = load("gws", tmp_path / "server-log.jsonl")
    module.log = tmp_path / "server-log.jsonl"
    module.router = module.Router(FIXTURE)
    return module


def test_token_endpoint_answers_the_jwt_exchange(gws):
    """gam 冷启动第一件事就是拿 token，拿不到后面全不用谈。"""
    status, body = gws.router.handle("POST", "/token", {}, b"")
    assert status == 200 and body["token_type"] == "Bearer"
    assert body["access_token"]


def test_body_base64_keeps_its_padding(gws):
    """填充 rstrip 掉的话 gam 解正文直接 binascii.Error: Incorrect padding。

    正文长度不是 3 的倍数时才暴露，所以这里特地挑一条这样的。
    """
    message = dict(FIXTURE["mailboxes"]["amy@yisi.example"]["messages"][0])
    message["body"] = "abcd"  # 4 字节，编码后必然带 =
    wire = gws.as_wire(message)
    data = wire["payload"]["body"]["data"]
    assert data.endswith("=")
    assert base64.urlsafe_b64decode(data).decode() == "abcd"


def test_raw_format_round_trips_as_rfc822(gws):
    _, wire = gws.router.handle(
        "GET", "/gmail/v1/users/amy@yisi.example/messages/m1",
        {"format": ["raw"]}, b"")
    raw = base64.urlsafe_b64decode(wire["raw"]).decode()
    assert raw.startswith("From: a@x.example")
    assert "抬头是壹思" in raw


def test_query_accepts_both_date_and_epoch_boundaries(gws):
    """gam 会把 after:2026/07/31 换算成 epoch 再发出来，两种都得认。"""
    messages = FIXTURE["mailboxes"]["amy@yisi.example"]["messages"]
    m_aug, m_jul = messages[0], messages[1]
    assert gws.match_query(m_aug, "after:2026/07/31")
    assert not gws.match_query(m_jul, "after:2026/07/31")
    assert gws.match_query(m_aug, "after:1783900800")
    assert not gws.match_query(m_jul, "after:1783900800")


def test_unknown_operator_is_let_through(gws):
    """少给等于让 agent 以为信箱是空的——那是环境在撒谎，宁可多给。"""
    m = FIXTURE["mailboxes"]["amy@yisi.example"]["messages"][0]
    assert gws.match_query(m, "has:attachment")
    assert gws.match_query(m, "")


def test_bare_keyword_matches_across_from_subject_body(gws):
    m = FIXTURE["mailboxes"]["amy@yisi.example"]["messages"][0]
    assert gws.match_query(m, "抬头")
    assert gws.match_query(m, "a@x.example")
    assert not gws.match_query(m, "查无此词")


def test_list_records_the_hit_count(gws):
    status, body = gws.router.handle(
        "GET", "/gmail/v1/users/amy@yisi.example/messages",
        {"q": ["after:2026/07/31"]}, b"")
    assert status == 200
    assert {x["id"] for x in body["messages"]} == {"m1", "m3"}
    row = [e for e in events(gws.log) if e["args"] == ["messages.list"]][-1]
    assert row["arguments"]["count"] == 2


def test_fetch_error_is_deterministic_and_recorded(gws):
    """「批量里少了几条」必须是确定的，不能是运气。"""
    for _ in range(3):
        status, body = gws.router.handle(
            "GET", "/gmail/v1/users/amy@yisi.example/messages/m3", {}, b"")
        assert status == 503
        assert body["error"]["errors"][0]["reason"] == "backendError"
    fails = [e for e in events(gws.log)
             if e["args"] == ["messages.get"] and not e["ok"]]
    assert len(fails) == 3


def test_messages_from_an_unknown_user_fall_back_to_the_default_box(gws):
    """题目里 gam 有时按别名调。落到空信箱会被当成「没有邮件」，那是假信息。"""
    _, body = gws.router.handle(
        "GET", "/gmail/v1/users/nobody@yisi.example/messages", {}, b"")
    assert len(body["messages"]) == 3


def test_missing_message_is_a_gmail_404(gws):
    status, body = gws.router.handle(
        "GET", "/gmail/v1/users/amy@yisi.example/messages/nope", {}, b"")
    assert status == 404 and body["error"]["errors"][0]["reason"] == "notFound"


# ---------------------------------------------------------------- /batch
# batch 只能走 Handler（multipart 的拆装在那儿），所以起一个明文的本机服务。
# 真环境是 443 + TLS，这里要测的是 multipart 的形状，跟传输层无关。


@pytest.fixture
def batch_url(gws):
    gws.Handler.router = gws.router
    server = ThreadingHTTPServer(("127.0.0.1", 0), gws.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:{0}/batch".format(server.server_address[1])
    server.shutdown()
    server.server_close()


def post_batch(url: str, cids: list, targets: list) -> str:
    boundary = "batch_opc_test"
    chunks = []
    for cid, target in zip(cids, targets):
        chunks.append(
            "--{0}\r\nContent-Type: application/http\r\n"
            "Content-ID: <{1}>\r\n\r\nGET {2}\r\n\r\n".format(
                boundary, cid, target))
    body = ("".join(chunks) + "--{0}--\r\n".format(boundary)).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type":
                 "multipart/mixed; boundary={0}".format(boundary)})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode()


def test_batch_answers_every_subrequest(gws, batch_url):
    out = post_batch(
        batch_url, ["a", "b"],
        ["/gmail/v1/users/amy@yisi.example/messages/m1",
         "/gmail/v1/users/amy@yisi.example/messages/m2"])
    assert out.count("HTTP/1.1 200 OK") == 2
    # 正文在 batch 里也是 base64 的，解出来才算真的把那条消息带回来了
    bodies = [base64.urlsafe_b64decode(d).decode()
              for d in re.findall(r'"data": "([^"]+)"', out)]
    assert any("抬头" in b for b in bodies)
    assert [e for e in events(gws.log) if e["args"] == ["batch"]]


def test_batch_keeps_the_spaces_inside_a_folded_content_id(gws, batch_url):
    """googleapiclient 拆的分隔符是字面量 `" + "`。

    折行要收成单个空格，但**不能把空格全删掉**——删了客户端配不上对，
    整个 batch 的响应会被当成一条。
    """
    cid = "b0a1b2c3 + 4"
    out = post_batch(
        batch_url, [cid], ["/gmail/v1/users/amy@yisi.example/messages/m1"])
    assert "Content-ID: <response-{0}>".format(cid) in out


def test_batch_subrequest_failure_does_not_sink_the_others(gws, batch_url):
    """一条 503 不能把整个批次带崩——真 batch 是逐条给状态码的。"""
    out = post_batch(
        batch_url, ["a", "b"],
        ["/gmail/v1/users/amy@yisi.example/messages/m3",
         "/gmail/v1/users/amy@yisi.example/messages/m1"])
    assert "HTTP/1.1 503 Error" in out
    assert "HTTP/1.1 200 OK" in out
