#!/bin/bash
# 把 opc/ 里的工具与判分脚手架同步到每个任务目录。
#
#   opc/tools/     -> tasks/*/environment/tools/   （进 agent 容器）
#   opc/verifier/  -> tasks/*/tests/               （进判分容器）
#
# opc/ 是唯一事实来源；改完跑这个脚本，然后两边一起提交。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for task in "$ROOT"/tasks/*/; do
  [ -f "$task/task.toml" ] || continue
  mkdir -p "$task/environment/tools" "$task/tests"
  rm -f "$task"/environment/tools/*   # 先清，避免 opc/tools/ 改名后留下孤儿脚本
  find "$ROOT/opc/tools" -maxdepth 1 -type f -exec cp {} "$task/environment/tools/" \;
  cp "$ROOT"/opc/verifier/test.sh "$task/tests/test.sh"
  cp "$ROOT"/opc/verifier/oracle.py "$task/tests/oracle.py"   # 差分判分骨架
  cp "$ROOT"/opc/verifier/task-tests.Dockerfile "$task/tests/Dockerfile"
  chmod +x "$task/tests/test.sh"
  echo "synced $(basename "$task")"
done
