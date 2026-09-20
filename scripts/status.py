"""把 jobs/ 下最近一次跑分拍成一张按题一行的表。

为什么要这个：`harbor job summarize` 已经被上游删成一个空壳（Removed command
shim），`harbor view` 是个要开浏览器的 web 服务，想在终端里扫一眼「哪道题红了」
没有现成的命令。而 harbor 顶层的 result.json 只有汇总计数，**不带题名**——
题名在每个 trial 自己那份 result.json 里。

三态要分开显示，理由同 tests/test.sh：
  pass        判分器通过
  fail        agent 没做到
  infra/err   判分器或环境自己坏了（build 失败、网络、凭证）
把后两者混成一个「没过」，你就分不清是模型变了还是尺子坏了。

用法：
    make status              # 最近一次 job
    make status JOB=jobs/2026-09-20__20-10-09
    uv run python scripts/status.py --all   # 所有 job 各一行汇总
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def reward_of(trial: dict):
    """harbor 版本之间 verifier_result 的形状变过，所以按几个常见键找。"""
    vr = trial.get("verifier_result") or {}
    for key in ("reward", "score", "value"):
        if isinstance(vr.get(key), (int, float)):
            return vr[key]
    metrics = vr.get("metrics")
    if isinstance(metrics, dict):
        for key in ("reward", "score"):
            if isinstance(metrics.get(key), (int, float)):
                return metrics[key]
    return None


def classify(trial: dict) -> tuple[str, str]:
    """返回 (状态, 备注)。"""
    exc = trial.get("exception_info")
    if exc:
        kind = exc.get("exception_type", "Error")
        msg = (exc.get("exception_message") or "").strip().splitlines()
        head = msg[0][:60] if msg else ""
        return "ERR ", f"{kind}: {head}"

    reward = reward_of(trial)
    if reward is None:
        return "?   ", "没有 verifier_result（可能被中断）"
    if reward >= 1:
        return "PASS", ""
    return "FAIL", f"reward={reward}"


def agent_of(trial: dict) -> str:
    return ((trial.get("agent_info") or {}).get("name")
            or (((trial.get("config") or {}).get("agent") or {}).get("name"))
            or "?")


def report(job_dir: Path) -> int:
    trials = sorted(job_dir.glob("*/result.json"))
    if not trials:
        print(f"{job_dir}: 没有 trial")
        return 1

    rows = []
    for path in trials:
        t = load(path)
        status, note = classify(t)
        rows.append((status, t.get("task_name", path.parent.name),
                     agent_of(t), note))

    width = max(len(r[1]) for r in rows)
    print(f"\n{job_dir}  （{len(rows)} 个 trial）\n")
    for status, task, agent, note in sorted(rows, key=lambda r: (r[0], r[1])):
        print(f"  {status}  {task:<{width}}  {agent:<8} {note}")

    tally = {}
    for r in rows:
        tally[r[0].strip()] = tally.get(r[0].strip(), 0) + 1
    print("\n  " + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    # 这是个看板，不是门槛：有红也返回 0，否则 make 会在后面糊一行
    # 「make: *** Error 1」，看着像是这个命令自己坏了。
    # 真正的门槛是 scripts/validate.sh 与 make smoke。
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("job", nargs="?", help="job 目录，默认取最近一个")
    ap.add_argument("--all", action="store_true", help="所有 job 各一行")
    args = ap.parse_args()

    jobs_root = ROOT / "jobs"
    if not jobs_root.is_dir():
        print("还没有 jobs/ 目录——先跑一次 scripts/validate.sh 或 make run")
        return 1

    jobs = sorted(d for d in jobs_root.iterdir() if d.is_dir())
    if not jobs:
        print("jobs/ 是空的")
        return 1

    if args.all:
        for d in jobs:
            trials = list(d.glob("*/result.json"))
            states = [classify(load(p))[0].strip() for p in trials]
            tally = {s: states.count(s) for s in sorted(set(states))}
            summary = " ".join(f"{k}={v}" for k, v in tally.items()) or "空"
            print(f"{d.name}  {len(trials):>3} trial  {summary}")
        return 0

    return report(Path(args.job) if args.job else jobs[-1])


if __name__ == "__main__":
    raise SystemExit(main())
