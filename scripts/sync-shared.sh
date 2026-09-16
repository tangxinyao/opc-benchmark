#!/bin/bash
# 把 shared/ 里的模拟工具与判分脚手架同步到每个任务目录。
# shared/ 是唯一事实来源；改完 shared/ 后跑这个脚本，然后提交两边。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for task in "$ROOT"/tasks/*/; do
  [ -f "$task/task.toml" ] || continue
  mkdir -p "$task/environment/tools" "$task/tests"
  cp "$ROOT"/shared/tools/* "$task/environment/tools/"
  cp "$ROOT"/shared/test.sh "$task/tests/test.sh"
  chmod +x "$task/tests/test.sh"
  echo "synced $(basename "$task")"
done
