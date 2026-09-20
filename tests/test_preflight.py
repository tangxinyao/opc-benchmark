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


def load_preflight(tmp_path, events, trajectory=None):
    """服务端日志（events）和 trajectory 都可以喂。两者形状不同：
    前者是服务端直接写的事件行，后者是 hermes 导出的会话消息。"""
    log = tmp_path / "server-log.jsonl"
    log.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
        encoding="utf-8",
    )
    os.environ["OPC_SERVER_LOG"] = str(log)
    traj = tmp_path / "hermes-session.jsonl"
    traj.write_text(
        "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in (trajectory or [])),
        encoding="utf-8",
    )
    os.environ["OPC_TRAJECTORY"] = str(traj)
    spec = importlib.util.spec_from_file_location(
        f"preflight_{tmp_path.name}", ROOT / "opc/verifier/preflight.py"
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
    ([], "自证整个缺失（entrypoint 没跑 / artifacts 没带进来）"),
    ([env_event("git_available", True)], "环境没塌：git 意外还在"),
])
def test_broken_environment_exits_99_not_reward_zero(tmp_path, events, why):
    """关键的一条：走的是 os._exit(99)，绕开 pytest 的失败汇总。

    在子进程里跑，因为 os._exit 会把当前解释器直接带走。
    """
    log = tmp_path / "server-log.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    script = (
        "import importlib.util,sys;"
        f"spec=importlib.util.spec_from_file_location('pf', {str(ROOT / 'opc/verifier/preflight.py')!r});"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
        "m.assert_env_witness('git_available', False, 'git 不可用')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "OPC_SERVER_LOG": str(log)},
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


# --- trajectory 解析：本次唯一的新逻辑，单独钉一遍 ---
#
# 形状假定与 opc/agent/hermes.py 的 _convert_session_to_atif 是同一套：
# assistant 消息带 tool_calls，紧随其后的 role="tool" 消息是回显。

def call(name, args, call_id):
    return {"role": "assistant", "tool_calls": [
        {"id": call_id, "function": {"name": name,
                                     "arguments": json.dumps(args, ensure_ascii=False)}}]}


def result(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_shell_call_is_keyed_by_command_name_not_tool_name(tmp_path):
    """审计时代记的是 `dws`，题目里的断言照着这个写。

    trajectory 里这条是 bash(command="dws card ...")——工具名是 bash，
    命令名才是 dws。取错的话 22 道题的断言会集体失灵却不报错。
    """
    pf = load_preflight(tmp_path, [], [
        call("bash", {"command": "dws card list --page-all"}, "c1"),
        result("c1", "{}"),
    ])
    assert pf.tools_called() == {"dws"}
    assert pf.events()[0]["args"][:2] == ["card", "list"]


def test_unknown_tool_name_still_resolves_the_command(tmp_path):
    """hermes 改了 shell 工具的名字也不该让整套断言失灵。"""
    pf = load_preflight(tmp_path, [], [
        call("run_terminal_cmd", {"command": "stripe refunds create --charge ch_1"}, "c1"),
        result("c1", "ok"),
    ])
    assert "stripe" in pf.tools_called()


def test_clarify_keeps_the_question_in_args_zero(tmp_path):
    """clarify 是原生工具，问题落 args[0]——assert_asked_once 按这个取。"""
    pf = load_preflight(tmp_path, [], [
        call("clarify", {"question": "这单要不要退款？"}, "c1"),
        result("c1", '{"user_response": "先别退"}'),
    ])
    pf.assert_asked_once("退款", "退款该问老板")


def test_failure_is_inferred_from_the_tool_output(tmp_path):
    """trajectory 没有退出码，只能从回显认失败。"""
    pf = load_preflight(tmp_path, [], [
        call("bash", {"command": "git log"}, "c1"),
        result("c1", "bash: git: command not found"),
        call("bash", {"command": "ls /app"}, "c2"),
        result("c2", "settlement.json"),
    ])
    assert [e["ok"] for e in pf.events()] == [False, True]
    pf.assert_precondition_failed("command not found", "git 不可用的记录", tool="git")


def test_events_merges_trajectory_and_server_log(tmp_path):
    """两处证据合成一条流，服务端那半在后。"""
    pf = load_preflight(
        tmp_path,
        [{"ts": 1, "tool": "stripe", "args": ["refunds.create"], "ok": True,
          "arguments": {}}],
        [call("bash", {"command": "rules show A"}, "c1"), result("c1", "{}")],
    )
    assert [e["tool"] for e in pf.events()] == ["rules", "stripe"]
    # 服务端那条仍然认得出来——退款的负断言就靠它
    assert pf.matching("refunds.create", tool="stripe")


# --- 证据路径必须和 artifacts 声明的一致 ---
#
# 这条是补票：默认值一度写成 /app/server-log.jsonl，而 harbor 是按绝对路径原样
# 把产物放进判分容器的（artifacts 里写 /var/lib/opc/xxx，进来还在 /var/lib/opc/xxx，
# 不会拍平到 /app）。于是判分器永远找不到文件，每道题都走 assert_env_witness 的
# 99 分支，报到用户面前却是 harbor 的 RewardFileNotFoundError。
#
# smoke.sh 显式设了 OPC_TRAJECTORY / OPC_SERVER_LOG，所以宿主机上全绿，
# 完全盖住了这个 bug —— 只有在容器里跑才会暴露。这条测试让它在 unit 层就炸。

def test_evidence_defaults_match_what_tasks_declare_as_artifacts():
    import re
    import importlib.util

    src = (ROOT / "opc/verifier/preflight.py").read_text(encoding="utf-8")
    defaults = dict(re.findall(
        r'^(TRAJECTORY|SERVER_LOG) = Path\(os\.environ\.get\("[^"]+", "([^"]+)"\)\)',
        src, re.M))
    assert set(defaults) == {"TRAJECTORY", "SERVER_LOG"}, defaults

    # 所有声明了证据类 artifact 的题，路径都得跟默认值对得上
    seen = {"TRAJECTORY": 0, "SERVER_LOG": 0}
    for toml in (ROOT / "tasks").rglob("task.toml"):
        text = toml.read_text(encoding="utf-8")
        for name, path in defaults.items():
            if Path(path).name in text:
                assert path in text, (
                    f"{toml.relative_to(ROOT)} 里出现了 {Path(path).name}，"
                    f"但不是 preflight 认的完整路径 {path}"
                )
                seen[name] += 1
    assert seen["SERVER_LOG"] > 0, "没有任何题把服务端日志列进 artifacts"
    assert seen["TRAJECTORY"] > 0, "没有任何题把 trajectory 列进 artifacts"


def test_trajectory_default_matches_the_adapter_session_log():
    """判分器找的那份，就是 hermes 适配器导出的那份。两边写死的常量不能各走各的。"""
    import re
    pf = (ROOT / "opc/verifier/preflight.py").read_text(encoding="utf-8")
    ad = (ROOT / "opc/agent/hermes.py").read_text(encoding="utf-8")
    pf_path = re.search(r'TRAJECTORY = Path\(os\.environ\.get\("[^"]+", "([^"]+)"\)\)', pf).group(1)
    ad_path = re.search(r'SESSION_LOG = "([^"]+)"', ad).group(1)
    assert pf_path == ad_path, f"判分器找 {pf_path}，适配器导到 {ad_path}"
