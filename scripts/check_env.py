"""检查每道题声明要用的环境变量是否已经就位。

跑之前花一秒钟确认，好过跑到第 37 个 trial 才发现判分器一直缺凭证。
**只报在不在，永远不打印值。**

    make env-check
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER_RE = re.compile(r"^\$\{(\w+)\}$")


def declared(task: Path) -> tuple[set[str], set[str]]:
    """返回 (agent 容器要的, 判分器容器要的) 环境变量名。"""
    config = tomllib.loads((task / "task.toml").read_bytes().decode())
    agent_env = config.get("environment", {}).get("env", {})
    verifier_env = (
        config.get("verifier", {}).get("environment", {}).get("env", {})
    )

    def names(table: dict) -> set[str]:
        out = set()
        for value in table.values():
            match = PLACEHOLDER_RE.match(str(value))
            if match:
                out.add(match.group(1))
        return out

    return names(agent_env), names(verifier_env)


def main() -> int:
    tasks = sorted(p for p in (ROOT / "tasks").iterdir()
                   if (p / "task.toml").exists())
    needed: dict[str, list[str]] = {}
    for task in tasks:
        agent_env, verifier_env = declared(task)
        for name in agent_env | verifier_env:
            needed.setdefault(name, []).append(task.name)

    if not needed:
        print("OK   没有任何题声明需要额外的环境变量")
        return 0

    missing = []
    for name in sorted(needed):
        if os.environ.get(name):
            print(f"OK   {name}  ({len(needed[name])} 道题要用)")
        else:
            missing.append(name)
            print(f"FAIL {name}  缺失 —— {', '.join(needed[name])}")

    if missing:
        print(
            "\n填在仓库根目录的 .env 里（模板：.env.example），然后 "
            "`. scripts/load-env.sh`。\nmake 的目标会自己 source。"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
