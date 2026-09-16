#!/bin/bash
# 本地自检：每道题都必须 oracle 满分、nop 零分。加 -p 只跑一道题。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASKS=("${@:-}")
if [ -z "${TASKS[0]:-}" ]; then
  mapfile -t TASKS < <(find "$ROOT/tasks" -maxdepth 1 -mindepth 1 -type d | sort)
fi

for task in "${TASKS[@]}"; do
  echo "=== $(basename "$task") ==="
  harbor check "$task" -r rubrics/task-implementation.toml || true
  harbor run -p "$task" --agent oracle
  harbor run -p "$task" --agent nop
done
