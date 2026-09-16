#!/bin/bash
# 不依赖 Docker 的快速自检：把 /app 重写到临时目录，跑 oracle 解法再跑判分器。
# 只验证解法与判分器的逻辑，不验证 Dockerfile 与 harbor 集成——那要跑 scripts/validate.sh。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAILED=0

for task in "$ROOT"/tasks/*/; do
  name="$(basename "$task")"
  work="$(mktemp -d)"
  app="$work/app"
  mkdir -p "$app" "$work/tests"

  # environment/ 里除 tools 外的内容就是容器 /app 的初始状态
  for item in "$task"environment/*; do
    case "$(basename "$item")" in
      Dockerfile|tools) continue ;;
    esac
    cp -r "$item" "$app/"
  done
  cp -r "$task"environment/tools "$work/tools"
  : > "$app/trace.jsonl"

  sed "s#/app#$app#g" "$task"solution/solve.sh > "$work/solve.sh"
  sed "s#/app#$app#g" "$task"tests/test_state.py > "$work/tests/test_state.py"

  # 基线：什么都不做（nop）必须拿 0 分，否则这道题量不出东西
  if python3 -m pytest -q "$work/tests/test_state.py" > "$work/nop.log" 2>&1; then
    echo "FAIL  $name (nop 就能通过，题目量不出东西)"; FAILED=1
  fi

  if OPC_TRACE="$app/trace.jsonl" OPC_KB="$app/kb/records.json" OPC_RULES="$app/rules/platform_rules.json" PATH="$work/tools:$PATH" bash "$work/solve.sh" \
       > "$work/solve.log" 2>&1; then
    if python3 -m pytest -q "$work/tests/test_state.py" > "$work/test.log" 2>&1; then
      echo "PASS  $name"
    else
      echo "FAIL  $name (判分器不通过)"; tail -20 "$work/test.log"; FAILED=1
    fi
  else
    echo "FAIL  $name (oracle 解法执行失败)"; tail -20 "$work/solve.log"; FAILED=1
  fi
  rm -rf "$work"
done
exit $FAILED
