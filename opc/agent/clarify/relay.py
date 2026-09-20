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

这里**不写任何日志**。clarify 是 hermes 的原生工具，每次提问本来就是 trajectory
里的一个 tool_call（tool="clarify"，问题在 args[0]），判分器直接从那儿读
「它问没问、问了什么」——见 opc/verifier/preflight.py 的 clarify_calls()。
再记一份只会多出一个能对不上的事实来源。
"""

from __future__ import annotations

import json
import os
import re

SCRIPT_PATH = os.environ.get("OPC_CLARIFY_SCRIPT", "/opt/opc/clarify.json")

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


def clarify(question, choices=None, callback=None) -> str:
    """tools.clarify_tool.clarify_tool 的替身，签名和返回值保持一致。

    callback 收下但不用——谁来答由应答表决定，不由前端决定。
    """
    question = (question or "").strip()
    if not question:
        return json.dumps({"error": "Question text is required."}, ensure_ascii=False)

    choices = _normalize_choices(choices)
    reply, _rule = _resolve(question, choices, _load_script())
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
