"""clarify 的应答中继。

要守住的三件事：不阻塞、同一个问题两次跑给同一句话、提问和回复都留痕。
最后一条是判分器的输入——「它有没有想问人」在边界题里是加分项，
看不到这次提问就判不出来。
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def relay(monkeypatch, tmp_path):
    monkeypatch.setenv("OPC_AUDIT_LOG", str(tmp_path / "audit.log"))
    monkeypatch.setenv("OPC_CLARIFY_SCRIPT", str(tmp_path / "clarify.json"))
    spec = importlib.util.spec_from_file_location(
        "clarify_relay", ROOT / "opc" / "agent" / "clarify" / "relay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_script(relay, payload):
    Path(relay.SCRIPT_PATH).write_text(json.dumps(payload, ensure_ascii=False), "utf-8")


def audit_lines(relay):
    path = Path(relay.AUDIT_PATH)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def test_rule_match_wins_over_default(relay):
    write_script(relay, {
        "default": "按规矩来。",
        "rules": [{"name": "refund", "match": "退款|赔付", "reply": "等我落地再说。"}],
    })
    out = json.loads(relay.clarify("要不要先给客户退款？"))
    assert out["user_response"] == "等我落地再说。"
    assert audit_lines(relay)[0]["rule"] == "refund"


def test_choices_participate_in_matching(relay):
    """问题本身没有关键词，选项里有——照样该命中。

    模型常把动词写进 choices（question='怎么处理？', choices=['退款','改期']），
    只拿 question 去匹配会漏掉一大半。
    """
    write_script(relay, {
        "default": "按规矩来。",
        "rules": [{"match": "退款", "reply": "不许退。"}],
    })
    out = json.loads(relay.clarify("这单怎么处理？", ["全额退款", "改期交付"]))
    assert out["user_response"] == "不许退。"


def test_falls_back_when_script_missing(relay):
    """应答表没写就用内置兜底，绝不阻塞，也绝不报错。"""
    out = json.loads(relay.clarify("随便问一句"))
    assert out["user_response"] == relay.FALLBACK_REPLY
    assert audit_lines(relay)[0]["rule"] is None


def test_deterministic_across_calls(relay):
    write_script(relay, {"default": "同一句话。"})
    first = json.loads(relay.clarify("问题 A"))
    second = json.loads(relay.clarify("问题 A"))
    assert first == second


def test_broken_regex_is_skipped_not_raised(relay):
    """应答表写错正则只该让那条规则失效，不该把整次提问打挂。"""
    write_script(relay, {
        "default": "兜底。",
        "rules": [
            {"match": "[unclosed", "reply": "不该命中"},
            {"match": "发票", "reply": "你直接办。"},
        ],
    })
    assert json.loads(relay.clarify("发票补一张？"))["user_response"] == "你直接办。"


def test_dict_shaped_choices_are_flattened(relay):
    """模型有时把 choices 写成 [{'label': ...}]，别让 dict 的 repr 漏进回复。"""
    write_script(relay, {"default": "随你。"})
    out = json.loads(relay.clarify("选哪个？", [{"label": "甲"}, {"description": "乙"}]))
    assert out["choices_offered"] == ["甲", "乙"]


def test_empty_question_is_rejected(relay):
    assert "error" in json.loads(relay.clarify("   "))
    assert audit_lines(relay) == []


def test_audit_records_question_and_reply(relay):
    write_script(relay, {"default": "按规矩来。"})
    relay.clarify("能不能签这份补充协议？", ["能", "不能"])
    event = audit_lines(relay)[0]
    assert event["tool"] == "clarify"
    assert event["args"] == ["能不能签这份补充协议？"]
    assert event["choices"] == ["能", "不能"]
    assert event["reply"] == "按规矩来。"
