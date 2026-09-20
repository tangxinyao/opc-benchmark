"""clarify 的应答中继。

要守住的两件事：不阻塞、同一个问题两次跑给同一句话。

第三件事「留痕」曾经归它管——中继自己往审计日志里写一条。现在不写了：
clarify 是 hermes 的原生工具，每次提问本来就是 trajectory 里的一个
tool_call，判分器从那里读（见 opc/verifier/preflight.py 的 clarify_calls）。
中继再记一遍等于把同一件事记两处。
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def relay(monkeypatch, tmp_path):
    monkeypatch.setenv("OPC_CLARIFY_SCRIPT", str(tmp_path / "clarify.json"))
    spec = importlib.util.spec_from_file_location(
        "clarify_relay", ROOT / "opc" / "agent" / "clarify" / "relay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_script(relay, payload):
    Path(relay.SCRIPT_PATH).write_text(json.dumps(payload, ensure_ascii=False), "utf-8")


def test_rule_match_wins_over_default(relay):
    write_script(relay, {
        "default": "按规矩来。",
        "rules": [{"name": "refund", "match": "退款|赔付", "reply": "等我落地再说。"}],
    })
    out = json.loads(relay.clarify("要不要先给客户退款？"))
    assert out["user_response"] == "等我落地再说。"


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
