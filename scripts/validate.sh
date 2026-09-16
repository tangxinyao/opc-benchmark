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
  mapfile -t TASKS < <(find "$ROOT/tasks" -maxdepth 1 -mindepth 1 -type d | sort)
fi

for task in "${TASKS[@]}"; do
  echo "=== $(basename "$task") ==="
  uv run harbor run -p "$task" --agent oracle
  uv run harbor run -p "$task" --agent nop
done
