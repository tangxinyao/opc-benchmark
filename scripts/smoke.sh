#!/bin/bash
# 不依赖 Docker 的快速自检：把 /app 重写到临时目录，跑 oracle 解法再跑判分器。
# 只验证解法与判分器的逻辑，不验证 Dockerfile 与 harbor 集成——那要跑 scripts/validate.sh。
set -uo pipefail
# 判分跑在项目环境里（make smoke 会传 PYTHON）。裸跑时回落到 python3，
# 但宿主机的 python3 可能很老——容器里是 3.12，别让两边的行为分叉。
PYTHON="${PYTHON:-python3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAILED=0

for task in "$ROOT"/tasks/*/*/*/; do
  name="${task#"$ROOT/tasks/"}"; name="${name%/}"
  # 带 entrypoint 的题，环境要在 agent 进来之前先立起来（拉服务、摆权限、
  # 换登录态、删二进制）。那是 Dockerfile + entrypoint 的活，宿主机上复刻不了，
  # 硬跑只会得到一堆假红。这些题的门槛在 scripts/validate.sh。
  # 要真发信的题同样立不起来：判据是 mailpit 落的那份库，而那是容器里的服务写的。
  if [ -f "$task"environment/entrypoint.sh ] \
     || grep -q 'opc-init-outbound-mail' "$task"environment/Dockerfile; then
    echo "SKIP  $name (要在容器里立环境，跑 make validate)"
    continue
  fi

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
  : > "$work/audit.log"

  # 判分器自带的固定语料（比如原始流水）跟着测试走，也要一起搬过来，
  # 并且 /tests 这个前缀同样要重写——只重写 /app 的话，判分器会去宿主机的
  # 根目录下找 /tests/data，找不到。
  [ -d "$task"tests/data ] && cp -r "$task"tests/data "$work/tests/data"

  sed -e "s#/app#$app#g" -e "s#/tests#$work/tests#g" \
      "$task"solution/solve.sh > "$work/solve.sh"
  sed -e "s#/app#$app#g" -e "s#/tests#$work/tests#g" \
      "$task"tests/test_state.py > "$work/tests/test_state.py"

  # 差分判分的题：判分器要 import oracle。没有凭证也要能跑基线，
  # 所以用题目自带的 tests/oracle_fake.json 走 fake 模式——
  # 这里验证的是判分逻辑，真 API 的连通性由 scripts/validate.sh 在容器里验。
  [ -f "$task"tests/oracle.py ] && cp "$task"tests/oracle.py "$work/tests/oracle.py"
  fake=""
  if [ -f "$task"tests/oracle_fake.json ]; then
    fake="$task/tests/oracle_fake.json"
  fi

  # 基线：什么都不做（nop）必须拿 0 分，否则这道题量不出东西
  if OPC_AUDIT_LOG="$work/audit.log" OPC_ORACLE_FAKE="$fake" OPC_VERIFIER_LOG_DIR="$work/logs" \
       "$PYTHON" -m pytest -q "$work/tests/test_state.py" > "$work/nop.log" 2>&1; then
    echo "FAIL  $name (nop 就能通过，题目量不出东西)"; FAILED=1
  fi

  if OPC_AUDIT_LOG="$work/audit.log" OPC_RULES="$app/rules/platform_rules.json" PATH="$work/tools:$PATH" bash "$work/solve.sh" \
       > "$work/solve.log" 2>&1; then
    if OPC_AUDIT_LOG="$work/audit.log" OPC_ORACLE_FAKE="$fake" OPC_VERIFIER_LOG_DIR="$work/logs" \
         "$PYTHON" -m pytest -q "$work/tests/test_state.py" > "$work/test.log" 2>&1; then
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
