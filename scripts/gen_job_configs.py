"""把每道题的 [metadata.opc] 展开成 harbor 的 job config。

为什么需要这一步：harbor 的「跑几遍」（n_attempts）和「用哪些模型」（agents）
是 **job 级**的，task.toml 里没有这两个字段——一道题不该自己决定谁来考它，
否则各题的分数不可比。所以 task.toml 里的 [metadata.opc] 是**声明**，
由这个脚本按 models 把题分组，每组在 configs/policy.toml 的默认值之上生成
一个**跑全部题**的 job config。

「跑几遍」不再是分组轴：所有 job 一律跑 configs/policy.toml 的
`defaults.attempts` 遍（现在是 3）。从前按 attempts 分出 x3/x5 两份，
看着像两档跑法，实际只是把同一个模型的题拆成了两堆——分组轴该是
**跑哪些题**，不是跑几遍。挑题跑请写 [[extra_jobs]] 的 tasks。

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

    正式跑分的分组来自每道题 [metadata.opc] 里的 models——那是「谁来考它」，
    属于题目。而「拿一个还没上线的模型、或者本地推理服务
    把全部题跑一遍」不属于任何一道题，为它去改 22 份 task.toml 会把正式跑分
    的分组也一起搅了。所以这类 job 单独声明，独立成文件，互不影响。
    """
    return load_policy().get("extra_jobs", [])


def task_policy(task: Path, defaults: dict) -> dict:
    config = tomllib.loads((task / "task.toml").read_bytes().decode())
    metadata = config.get("metadata", {})
    opc = metadata.get("opc", {})
    return {
        "models": tuple(opc.get("models", defaults["models"])),
        "tags": [str(t) for t in metadata.get("tags", [])],
    }


def check_no_attempts_override(task: Path, rel: str) -> list[str]:
    """遍数只有一个来源：configs/policy.toml 的 defaults.attempts。

    从前每道题可以自己写 attempts，于是 22 道题按 3/5 分成两个 job，
    看着像两档跑法，其实只是把同一个模型的题拆成两堆，还让两堆的分不可比。
    现在一律 3 遍，题里再写 attempts 只会造成「我改了却没生效」。
    """
    config = tomllib.loads((task / "task.toml").read_bytes().decode())
    if "attempts" in config.get("metadata", {}).get("opc", {}):
        return [
            f"{rel}: [metadata.opc] 不再支持 attempts——遍数由 "
            "configs/policy.toml 的 defaults.attempts 统一决定，"
            "想只跑一部分题请写 [[extra_jobs]] 的 tasks"
        ]
    return []


def pair_of(policy: dict) -> str | None:
    return next(
        (t[len("pair:"):] for t in policy["tags"] if t.startswith("pair:")), None
    )


def group_key(policy: dict) -> tuple:
    return policy["models"]


def group_name(key: tuple) -> str:
    """跑全部题的那一份，名字里带 -all，与挑题的旁路 job 区分开。"""
    slug = "-".join(m.split("/", 1)[0] for m in key)
    return f"{slug}-all"


def check_pairs_share_a_group(policies: dict[str, dict]) -> list[str]:
    """配对的两道题必须用同一套模型跑。

    否则那一对就失去意义了：两道题的分不在同一个尺度上，
    凑在一起说明不了「它敢说不知道」。遍数已经全局统一，不用再查。
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
                "配对的两道题必须用同一套模型，否则那一对不成立"
            )
    return problems


def check_extra_job_tasks(
    name: str, picked: list[str], policies: dict[str, dict]
) -> list[str]:
    """旁路 job 挑题时，配对的两道必须一起挑。

    少列一边，那一对就不成立了——拒答题单独跑出来的分说明不了
    「它敢说不知道」，因为一律拒答的模型也能拿满分。这和
    check_pairs_share_a_group() 是同一条规矩，只是那条管「同一套模型」，
    这条管「别把一对拆开」。
    """
    problems = []
    seen = set(picked)
    for item in picked:
        if item not in policies:
            problems.append(f"{name}: tasks 里的 {item} 不是一道题")
            continue
        pair = pair_of(policies[item])
        if pair is not None and pair not in seen:
            problems.append(
                f"{name}: 挑了 {item} 却没挑它的对照题 {pair}——"
                "配对的两道必须一起跑，否则那一对不成立"
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

    problems = [p for t in tasks
                for p in check_no_attempts_override(t, ids[t])]
    problems += check_pairs_share_a_group(policies)
    if problems:
        for problem in problems:
            print(f"FAIL {problem}")
        return 1

    groups: dict[tuple, list[str]] = defaultdict(list)
    for task in tasks:
        groups[group_key(policies[ids[task]])].append(ids[task])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("job-*.yaml"):
        stale.unlink()

    attempts = defaults["attempts"]
    for models, names in sorted(groups.items(), key=lambda kv: group_name(kv[0])):
        name = group_name(models)
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

    # 旁路 job：指定的模型 × 指定的题（省略就是全部），与上面的分组互不影响。
    all_names = [ids[t] for t in tasks]
    for extra in load_extra_jobs():
        name = extra["name"]
        models = list(extra["models"])
        if "attempts" in extra:
            print(f"FAIL {name}: [[extra_jobs]] 不再支持 attempts——"
                  "所有 job 一律跑 defaults.attempts 遍，区分点是跑哪些题")
            return 1
        agent_kwargs = extra.get("agent_kwargs", {})
        picked = list(extra.get("tasks", all_names))

        if problems := check_extra_job_tasks(name, picked, policies):
            for problem in problems:
                print(f"FAIL {problem}")
            return 1

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
            "tasks": [{"path": f"tasks/{n}"} for n in picked],
        }
        write_job(name, config, len(picked), len(models), attempts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
