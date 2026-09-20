#!/bin/bash
# 本地自检：每道题都必须 oracle 满分、nop 零分。加 -p 只跑一道题。
#
# 这一步是真门槛：make check 只在宿主机上验证了解法与判分器的逻辑，
# 没验证 Dockerfile 和 harbor 集成。
#
# 不跑 `harbor check`——那是让一个评审模型按 rubric 给题目质量打分，
# 判的是题写得好不好，不是判分器准不准，而且要烧 API。
# 这个仓库的尺子是 oracle/nop 这条基线，不是模型的意见。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASKS=("${@:-}")
if [ -z "${TASKS[0]:-}" ]; then
  # 不用 mapfile：那是 bash 4.0+ 的 builtin，而 macOS 自带的 /bin/bash 停在
  # 3.2.57（GPLv3 之后 Apple 就不再跟了），在那儿会报 command not found。
  # while read + 进程替换从 bash 2 起就有，两边都跑得动。
  TASKS=()
  while IFS= read -r _task_dir; do
    TASKS+=("$_task_dir")
  done < <(find "$ROOT/tasks" -maxdepth 3 -mindepth 3 -type d | sort)
fi

# ${TASKS[@]+...}：bash 4.4 之前，set -u 下展开空数组会报 unbound variable。
# 这里 find 正常时不会为空，但空了该是「没题可跑」而不是一条看不懂的报错。
for task in ${TASKS[@]+"${TASKS[@]}"}; do
  echo "=== ${task#"$ROOT/tasks/"} ==="
  uv run harbor run -p "$task" --agent oracle
  uv run harbor run -p "$task" --agent nop
done
