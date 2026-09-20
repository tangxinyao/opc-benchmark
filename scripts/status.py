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


def _primary_reward(rewards) -> float | None:
    """照抄 harbor 自己的取法，别另发明一套。

    见 harbor/cli/jobs.py:_primary_reward —— VerifierResult 只有 `rewards`
    一个字段，是个 {名字: 数} 的**字典**，不是标量：优先取 "reward" 这个键，
    只有一项时就取那一项，其余情况说不清是哪个,返回 None。
    """
    if not isinstance(rewards, dict) or not rewards:
        return None
    if isinstance(rewards.get("reward"), (int, float)):
        return float(rewards["reward"])
    if len(rewards) == 1:
        only = next(iter(rewards.values()))
        if isinstance(only, (int, float)):
            return float(only)
    return None


def reward_of(trial: dict):
    """返回 (reward, 说明)。reward 为 None 时说明里写清是哪一步断的。"""
    vr = trial.get("verifier_result")
    if isinstance(vr, dict):
        reward = _primary_reward(vr.get("rewards"))
        if reward is not None:
            return reward, ""

    # 多步题不在 trial 顶层记 verifier_result，而是每步各记一份。
    for step in trial.get("step_results") or []:
        if not isinstance(step, dict):
            continue
        svr = step.get("verifier_result")
        if isinstance(svr, dict):
            reward = _primary_reward(svr.get("rewards"))
            if reward is not None:
                return reward, f"（取自步骤 {step.get('step_name', '?')}）"

    if vr is None:
        return None, "没有 verifier_result（判分没跑到，多半是被中断）"
    return None, f"verifier_result.rewards 取不到数：{vr.get('rewards')!r}"


def classify(trial: dict, agent: str = "") -> tuple[str, str]:
    """返回 (状态, 备注)。

    oracle / nop 这两个基线 agent 要按**这道题的尺子成不成立**来读，
    不是按分数高低：oracle 必须满分、nop 必须零分（见 scripts/validate.sh）。
    nop 拿 0 分是**对的**，照着分数报一个 FAIL 会让人以为题坏了。
    """
    exc = trial.get("exception_info")
    if exc:
        kind = exc.get("exception_type", "Error")
        msg = (exc.get("exception_message") or "").strip().splitlines()
        head = msg[0][:60] if msg else ""
        return "ERR ", f"{kind}: {head}"

    reward, note = reward_of(trial)
    if reward is None:
        return "?   ", note

    if agent == "oracle":
        return ("PASS", note) if reward >= 1 else (
            "BAD ", f"oracle 只拿到 {reward:g}，解法或判分器对不上 {note}".strip())
    if agent == "nop":
        return ("PASS", f"nop=0，符合预期 {note}".strip()) if reward <= 0 else (
            "BAD ", f"nop 拿到 {reward:g}，这道题量不出东西 {note}".strip())

    if reward >= 1:
        return "PASS", note
    return "FAIL", f"reward={reward:g} {note}".strip()


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
        agent = agent_of(t)
        status, note = classify(t, agent)
        rows.append((status, t.get("task_name", path.parent.name),
                     agent, note))

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
            states = []
            for p in trials:
                t = load(p)
                states.append(classify(t, agent_of(t))[0].strip())
            tally = {s: states.count(s) for s in sorted(set(states))}
            summary = " ".join(f"{k}={v}" for k, v in tally.items()) or "空"
            print(f"{d.name}  {len(trials):>3} trial  {summary}")
        return 0

    return report(Path(args.job) if args.job else jobs[-1])


if __name__ == "__main__":
    raise SystemExit(main())
