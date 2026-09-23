"""把每道题的 [metadata.opc] 展开成 harbor 的 job config。

为什么需要这一步：harbor 的「跑几遍」（n_attempts）和「用哪些模型」（agents）
是 **job 级**的，task.toml 里没有这两个字段——一道题不该自己决定谁来考它，
否则各题的分数不可比。所以 task.toml 里的 [metadata.opc] 是**声明**，
由这个脚本按 (models, attempts) 把题分组，
每组在 configs/policy.toml 的默认值之上生成一个 job config。

    make configs        # 读 configs/policy.toml，生成到 configs/jobs/
    harbor run -c configs/jobs/job-<组名>.yaml
"""

from __future__ import annotations

import sys
import tomllib
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"
# configs/ 分两层：policy.toml 是手改的输入，jobs/ 整个目录是产物。
POLICY = ROOT / "configs" / "policy.toml"
OUT_DIR = ROOT / "configs" / "jobs"
AGENT_IMPORT_PATH = "opc.agent.hermes:Hermes"


def load_policy() -> dict:
    return tomllib.loads(POLICY.read_bytes().decode())


def load_defaults() -> dict:
    return load_policy()["defaults"]


def load_extra_jobs() -> list[dict]:
    """policy.toml 的 [[extra_jobs]]：不按题目声明分组的旁路 job。

    正式跑分的分组来自每道题 [metadata.opc] 里的 (models, attempts)——
    那是「谁来考它」，属于题目。而「拿一个还没上线的模型、或者本地推理服务
    把全部题跑一遍」不属于任何一道题，为它去改 22 份 task.toml 会把正式跑分
    的分组也一起搅了。所以这类 job 单独声明，独立成文件，互不影响。
    """
    return load_policy().get("extra_jobs", [])


def task_policy(task: Path, defaults: dict) -> dict:
    config = tomllib.loads((task / "task.toml").read_bytes().decode())
    metadata = config.get("metadata", {})
    opc = metadata.get("opc", {})
    return {
        "attempts": opc.get("attempts", defaults["attempts"]),
        "models": tuple(opc.get("models", defaults["models"])),
        "tags": [str(t) for t in metadata.get("tags", [])],
    }


def pair_of(policy: dict) -> str | None:
    return next(
        (t[len("pair:"):] for t in policy["tags"] if t.startswith("pair:")), None
    )


def group_key(policy: dict) -> tuple:
    return (policy["attempts"], policy["models"])


def group_name(key: tuple) -> str:
    attempts, models = key
    slug = "-".join(m.split("/", 1)[0] for m in models)
    return f"{slug}-x{attempts}"


def check_pairs_share_a_group(policies: dict[str, dict]) -> list[str]:
    """配对的两道题必须用同一套模型、同样的遍数跑。

    否则那一对就失去意义了：拒答题跑 5 遍、对照题跑 1 遍，
    两个数不在同一个尺度上，凑在一起说明不了「它敢说不知道」。
    """
    problems = []
    for name, policy in policies.items():
        pair = pair_of(policy)
        if pair is None:
            continue
        if pair not in policies:
            problems.append(f"{name}: pair 指向不存在的题 {pair}")
        elif group_key(policy) != group_key(policies[pair]):
            problems.append(
                f"{name} 与配对的 {pair} 跑法不一致"
                f"（{group_key(policy)} vs {group_key(policies[pair])}）——"
                "配对的两道题必须同模型、同遍数，否则那一对不成立"
            )
    return problems


def write_job(name: str, config: dict, n_tasks: int, n_models: int, attempts: int) -> None:
    path = OUT_DIR / f"job-{name}.yaml"
    path.write_text(
        "# 由 scripts/gen_job_configs.py 生成，不要手改。\n"
        "# 改题的跑法请改 task.toml 的 [metadata.opc] 或 configs/policy.toml，\n"
        "# 然后 make configs。\n"
        + yaml.dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(
        f"OK   {path.relative_to(ROOT)}: {n_tasks} 道题 × "
        f"{n_models} 个模型 × {attempts} 遍 = "
        f"{n_tasks * n_models * attempts} 次 trial"
    )


def main() -> int:
    defaults = load_defaults()
    # 题目目录是三层：tasks/<职能>/<活>/<案例>/，题的标识就是这三段
    tasks = sorted(p.parent for p in TASKS_DIR.glob("*/*/*/task.toml"))
    ids = {t: t.relative_to(TASKS_DIR).as_posix() for t in tasks}
    policies = {ids[t]: task_policy(t, defaults) for t in tasks}

    if problems := check_pairs_share_a_group(policies):
        for problem in problems:
            print(f"FAIL {problem}")
        return 1

    groups: dict[tuple, list[str]] = defaultdict(list)
    for task in tasks:
        groups[group_key(policies[ids[task]])].append(ids[task])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("job-*.yaml"):
        stale.unlink()

    for key, names in sorted(groups.items(), key=lambda kv: group_name(kv[0])):
        attempts, models = key
        name = group_name(key)
        config = {
            "job_name": f"opc-{name}",
            "n_attempts": attempts,
            "n_concurrent_trials": defaults["n_concurrent_trials"],
            "agents": [
                {"import_path": AGENT_IMPORT_PATH, "model_name": model}
                for model in models
            ],
            "tasks": [{"path": f"tasks/{n}"} for n in names],
        }
        write_job(name, config, len(names), len(models), attempts)

    # 旁路 job：全部题 × 指定的模型，和上面的分组结果互不影响。
    all_names = [ids[t] for t in tasks]
    for extra in load_extra_jobs():
        name = extra["name"]
        models = list(extra["models"])
        attempts = extra.get("attempts", defaults["attempts"])
        agent_kwargs = extra.get("agent_kwargs", {})
        agent = {"import_path": AGENT_IMPORT_PATH}
        config = {
            "job_name": f"opc-{name}",
            "n_attempts": attempts,
            "n_concurrent_trials": extra.get(
                "n_concurrent_trials", defaults["n_concurrent_trials"]
            ),
            "agents": [
                {**agent, "model_name": model,
                 **({"kwargs": dict(agent_kwargs)} if agent_kwargs else {})}
                for model in models
            ],
            "tasks": [{"path": f"tasks/{n}"} for n in all_names],
        }
        write_job(name, config, len(all_names), len(models), attempts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
