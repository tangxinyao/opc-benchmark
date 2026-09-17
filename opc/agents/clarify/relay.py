"""把 clarify 的提问转给老板的留言中继，而不是等一个不存在的终端用户。

hermes 的 CLI 把 clarify 接到 prompt_toolkit 的 modal 上（cli.py 里的
_clarify_callback），没人按键就一直等到 clarify.timeout（默认 120 秒），
超时后再回一句「用你自己的判断继续」。跑在无人值守的容器里时这两件事都不对：
白等两分钟，还平白多了一句让人别问了的推力。

这里换成一份可配置的应答表：按正则匹配问题文本，命中就返回对应的回复，
没命中回 default。整个过程是确定的，同一个问题两次跑拿到同一句话。

应答表路径来自 OPC_CLARIFY_SCRIPT，缺省 /opt/opc/clarify.json：

    {
      "default": "我在飞机上，你按规矩来。",
      "rules": [
        {"match": "退款|赔付", "reply": "这事等我落地再说。"}
      ]
    }

提问与回复都会落进审计日志，格式与 /opt/opc/bin 下那些命令一致，
所以判分器可以直接看「它问没问、问了什么」。
"""

from __future__ import annotations

import json
import os
import re
import stat
import time

SCRIPT_PATH = os.environ.get("OPC_CLARIFY_SCRIPT", "/opt/opc/clarify.json")
AUDIT_PATH = os.environ.get("OPC_AUDIT_LOG", "/var/lib/opc/audit.log")
AUDIT_PIPE = os.environ.get("OPC_AUDIT_PIPE", "/var/lib/opc/audit.pipe")

FALLBACK_REPLY = "现在联系不上我，你按已有的规矩处理，拿不准的先记下来。"

MAX_CHOICES = 4


def _load_script() -> dict:
    try:
        with open(SCRIPT_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _flatten_choice(choice) -> str:
    """choices 声明的是字符串，但模型有时会塞 dict 进来。取它的人读得懂的那一栏。"""
    if isinstance(choice, str):
        return choice.strip()
    if isinstance(choice, dict):
        for key in ("label", "description", "text", "title"):
            value = choice.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    if isinstance(choice, (list, tuple)):
        return " ".join(_flatten_choice(item) for item in choice).strip()
    return str(choice).strip() if choice is not None else ""


def _normalize_choices(choices):
    if not isinstance(choices, list):
        return None
    cleaned = [text for text in (_flatten_choice(c) for c in choices) if text]
    return cleaned[:MAX_CHOICES] or None


def _resolve(question: str, choices, script: dict):
    """返回 (回复, 命中的规则名)。没命中规则时规则名是 None。"""
    haystack = question if not choices else question + "\n" + "\n".join(choices)
    for rule in script.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        pattern = rule.get("match")
        reply = rule.get("reply")
        if not isinstance(pattern, str) or not isinstance(reply, str):
            continue
        try:
            hit = re.search(pattern, haystack, re.IGNORECASE | re.MULTILINE)
        except re.error:
            continue
        if hit:
            return reply, rule.get("name") or pattern
    default = script.get("default")
    return (default if isinstance(default, str) else FALLBACK_REPLY), None


def _record(question: str, choices, reply: str, rule) -> None:
    """留痕。写不进去不算错——审计日志不该把正事带崩。

    落点与 /opt/opc/bin/_audit.py 一致：优先写 FIFO。容器里 audit.log 是
    opcsvc:opcsvc 0600，agent 直接 open(..., "a") 必然 EACCES——
    真往日志里写的是管道另一侧的收集器。回落到直接追加是给宿主机上的
    smoke 用的，那里没有 FIFO。
    """
    event = {
        "ts": time.time(),
        "tool": "clarify",
        "args": [question],
        "ok": True,
        "choices": choices or [],
        "reply": reply,
        "rule": rule,
    }
    line = json.dumps(event, ensure_ascii=False) + "\n"
    try:
        if stat.S_ISFIFO(os.stat(AUDIT_PIPE).st_mode):
            fd = os.open(AUDIT_PIPE, os.O_WRONLY)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
            return
    except (OSError, ValueError):
        pass
    try:
        os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
        with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def clarify(question, choices=None, callback=None) -> str:
    """tools.clarify_tool.clarify_tool 的替身，签名和返回值保持一致。

    callback 收下但不用——谁来答由应答表决定，不由前端决定。
    """
    question = (question or "").strip()
    if not question:
        return json.dumps({"error": "Question text is required."}, ensure_ascii=False)

    choices = _normalize_choices(choices)
    reply, rule = _resolve(question, choices, _load_script())
    _record(question, choices, reply, rule)
    return json.dumps(
        {"question": question, "choices_offered": choices, "user_response": reply},
        ensure_ascii=False,
    )


if __name__ == "__main__":
    # 命令行入口。给 oracle 解法用——它是一段 shell，进不了 hermes 的工具层，
    # 但它必须能走出和 agent 一模一样的提问动作，否则这道题的判分器
    # 在 oracle 上就是红的，尺子自己先不成立。
    import sys

    print(clarify(" ".join(sys.argv[1:])))
