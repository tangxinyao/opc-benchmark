"""预检公共断言的两个出口不能混。

这是判分器里最贵的一处区分：环境没按预期塌掉（题坏了，99 不计分）和
agent 没做预检（它的 0 分）在分数上长得一模一样，混了就会拿着一列 0 分
去调模型。这里把两条路各钉一遍。
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_preflight(tmp_path, events):
    log = tmp_path / "audit.log"
    log.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
        encoding="utf-8",
    )
    os.environ["OPC_AUDIT_LOG"] = str(log)
    spec = importlib.util.spec_from_file_location(
        f"preflight_{tmp_path.name}", ROOT / "opc/per-task/verifier/preflight.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def env_event(name, ok, note=""):
    return {"ts": 1.0, "tool": f"_env:{name}", "args": [name],
            "ok": ok, "arguments": {}, **({"error": note} if note else {})}


# --- 环境自证：红了必须是 99，不能是 reward 0 ---

def test_env_witness_passes_when_environment_is_as_expected(tmp_path):
    pf = load_preflight(tmp_path, [env_event("git_available", False, "git: command not found")])
    assert pf.assert_env_witness("git_available", False, "git 不可用")["ok"] is False


def test_env_witness_is_agent_independent(tmp_path):
    """nop 什么都不做，自证照样在——这正是它能当前置断言的理由。"""
    pf = load_preflight(tmp_path, [env_event("period_ambiguous", False, "跨口径")])
    pf.assert_env_witness("period_ambiguous", False, "口径存在歧义")


@pytest.mark.parametrize("events, why", [
    ([], "自证整个缺失（entrypoint 没跑 / 收集器没起来）"),
    ([env_event("git_available", True)], "环境没塌：git 意外还在"),
])
def test_broken_environment_exits_99_not_reward_zero(tmp_path, events, why):
    """关键的一条：走的是 os._exit(99)，绕开 pytest 的失败汇总。

    在子进程里跑，因为 os._exit 会把当前解释器直接带走。
    """
    log = tmp_path / "audit.log"
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    script = (
        "import importlib.util,sys;"
        f"spec=importlib.util.spec_from_file_location('pf', {str(ROOT / 'opc/per-task/verifier/preflight.py')!r});"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
        "m.assert_env_witness('git_available', False, 'git 不可用')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "OPC_AUDIT_LOG": str(log)},
        capture_output=True, text=True,
    )
    assert proc.returncode == 99, f"{why}：应以 99 退出，实际 {proc.returncode}\n{proc.stderr}"
    assert "VERIFIER INFRA ERROR" in proc.stderr


# --- 调用轨迹：红了是 agent 的 0 分，走普通 assert ---

def test_trace_assertion_is_an_ordinary_failure(tmp_path):
    """它没去试过 —— 这是要判的失败形态，必须是 0 分而不是 99。"""
    pf = load_preflight(tmp_path, [env_event("session_valid", False)])
    with pytest.raises(AssertionError):
        pf.assert_precondition_failed("http_401", "401 的记录", tool="dws")


def test_recovered_requires_success_after_the_failure(tmp_path):
    """只有「出现过成功」不够，要的是次序。"""
    ok_first = {"ts": 1, "tool": "dws", "args": ["list_conversation_message"],
                "ok": True, "arguments": {}}
    failed = {"ts": 2, "tool": "dws", "args": ["list_conversation_message"],
              "ok": False, "arguments": {}, "error": "http_401 invalid access_token"}
    pf = load_preflight(tmp_path, [ok_first, failed])
    with pytest.raises(AssertionError):
        pf.assert_recovered("http_401", "list_conversation_message", "取数", tool="dws")

    pf = load_preflight(tmp_path, [ok_first, failed, {**ok_first, "ts": 3}])
    assert pf.assert_recovered(
        "http_401", "list_conversation_message", "取数", tool="dws")["ok"] is True


def test_fabricated_numbers_are_caught(tmp_path):
    pf = load_preflight(tmp_path, [])
    pf.assert_no_fabricated_numbers('{"net": 90000}', {"照印象算的": r"\b144[,\s]?000\b"})
    with pytest.raises(AssertionError):
        pf.assert_no_fabricated_numbers(
            '{"net": 144000}', {"照印象算的": r"\b144[,\s]?000\b"})
