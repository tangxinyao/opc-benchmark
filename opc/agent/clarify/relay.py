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

被 hermes 的工具层调用时，这里**不写任何日志**。clarify 是 hermes 的原生工具，
每次提问本来就是 trajectory 里的一个 tool_call（tool="clarify"，问题在 args[0]），
判分器直接从那儿读「它问没问、问了什么」——见 opc/verifier/preflight.py 的
clarify_calls()。再记一份只会多出一个能对不上的事实来源。

命令行入口（`python3 clarify_relay.py "问题"`）是唯一的例外，它只给 oracle 用。
oracle 是一段 shell，跑不进 hermes 的工具层，也就没有 trajectory——于是「必须问」
那几道题在 oracle 上永远是红的，尺子自己先站不住。所以走命令行时，这里把这次提问
按 hermes 导出的会话格式**追加进同一个 trajectory 文件**：不是第三处证据，是把
oracle 的提问补进本来就该记着它的那一处。agent 侧一个字节都不受影响。
"""

from __future__ import annotations

import json
import os
import re
import sys

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


# trajectory 的落点。必须与 opc/agent/hermes.py 的 SESSION_LOG、以及各题
# task.toml 的 artifacts 里那一行逐字一致——判分容器按绝对路径原样取。
TRAJECTORY_PATH = os.environ.get(
    "OPC_TRAJECTORY_SINK", "/logs/agent/hermes-session.jsonl"
)


def _record_in_trajectory(question: str, choices, reply: str) -> None:
    """把一次提问按 hermes 导出的会话格式追加进 trajectory。

    形状要能被 preflight._messages() / _trajectory_events() 原样吃下：
    一条带 tool_calls 的 assistant 消息，加一条配对的 tool 消息。
    tool_call 的 id 用问题文本的哈希，同一次跑里不会和别的调用撞上。

    写不进去是**硬错误**：oracle 这一侧的「它问没问」只有这一处证据，写不下
    就等于这次提问没发生过，判分器会把它读成「该问不问」——一个环境故障于是
    长成了模型的 0 分。宁可让解法脚本当场挂掉，那至少看得出是环境的事。
    """
    import hashlib

    call_id = "clarify-" + hashlib.sha1(question.encode("utf-8")).hexdigest()[:12]
    arguments = {"question": question}
    if choices:
        arguments["choices"] = choices
    payload = {
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "clarify",
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }],
            },
            {"role": "tool", "tool_call_id": call_id, "content": reply},
        ]
    }
    try:
        path = os.path.abspath(TRAJECTORY_PATH)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise SystemExit(
            "clarify: 提问写不进 trajectory（%s: %s）。判分器只从这一处读"
            "「它问没问」，写不下就会被读成没问过——这是环境故障，不是解法的错，"
            "先修落点权限再跑。" % (path, exc)
        )


if __name__ == "__main__":
    # 命令行入口。给 oracle 解法用——它是一段 shell，进不了 hermes 的工具层，
    # 但它必须能走出和 agent 一模一样的提问动作，否则这道题的判分器
    # 在 oracle 上就是红的，尺子自己先不成立。
    question_text = " ".join(sys.argv[1:]).strip()
    result = clarify(question_text)
    parsed = json.loads(result)
    if "error" not in parsed:
        _record_in_trajectory(
            parsed["question"], parsed.get("choices_offered"), parsed["user_response"]
        )
    print(result)
