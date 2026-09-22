#!/bin/bash
# 验证 inbox-triage 四道题从 gam 迁到 google-workspace skill。
#
#   scripts/probe-inbox-triage.sh                  # 四道都跑
#   scripts/probe-inbox-triage.sh batch-partial    # 只跑一道
#
# 这是那次迁移的临时验证工具，不是长期设施——四道题都验稳之后连同
# 这个文件一起删掉。放进仓库只是因为验证要在另一台机器上做，
# 脚本得能跟着 git pull 走。
#
# 风险最高的是 batch-partial：它的考点是「列了 3 条、只读到 1 条、如实报缺口」。
# google_api.py 的 gmail search 会对列出来的每条再发一次 get(format=metadata)
# 且没有 try/except，所以 fixture 改成 fetch_error 只在取正文（full/raw）时生效，
# 列清单那一次照常成功——失败点摆回它本来的位置。这一版就是在验这件事。
#
# 不用 set -e：每条探针都要跑，挂了也要看到报错和退出码。
set -u

BASE=opc-benchmark/hermes-base:local
GAPI=/usr/local/lib/hermes-agent/skills/productivity/google-workspace/scripts/google_api.py
TASKS=("${@:-}")
if [ -z "${TASKS[0]:-}" ]; then
  TASKS=(single-source ambiguous-source batch-complete batch-partial)
fi

NAME=opc-probe
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "=============== 0. 基底：fixture server 是不是当前代码 ==============="
# fixture 这次改了两处（fetch_error 只在取正文时生效、日志记真实邮箱），
# 它住在基底里——不 make image 的话症状和没改一模一样。
repo_sum="$(md5sum opc/agent/datasources/gws_fixture_server.py | cut -d' ' -f1)"
img_sum="$(docker run --rm --entrypoint sh "$BASE" \
             -c 'md5sum /opt/opc/lib/gws_fixture_server.py' 2>/dev/null | cut -d' ' -f1)"
echo "仓库里: $repo_sum"
echo "基底里: ${img_sum:-（读不到，基底可能还没构建）}"
if [ "$repo_sum" != "$img_sum" ]; then
  echo "基底旧了，正在 make image（要几分钟）..."
  if ! make image >/tmp/opc-base-build.log 2>&1; then
    echo "基底构建失败，尾部日志："; tail -40 /tmp/opc-base-build.log; exit 1
  fi
  echo "基底已重建"
else
  echo "基底是当前代码，跳过重建"
fi

fail=0

for t in "${TASKS[@]}"; do
  TASK="tasks/support/inbox-triage/$t"
  IMG="opc-probe-$t"

  echo
  echo "################################################################"
  echo "###  $t"
  echo "################################################################"

  echo "--- 构建镜像"
  if ! docker build -q -t "$IMG" "$TASK/environment" >/tmp/opc-task-build.log 2>&1; then
    echo "构建失败，尾部日志："; tail -30 /tmp/opc-task-build.log; fail=1; continue
  fi
  echo "ok"

  echo "--- 起容器"
  # 必须带常驻命令：entrypoint 最后一行是 `exec "$@"`，镜像没有 CMD，
  # 平时由 harbor 带命令进来。不带的话 exec 拿到空参数，容器立刻退出。
  cleanup
  docker run -d --name "$NAME" "$IMG" sleep infinity >/dev/null 2>&1
  for _ in $(seq 1 60); do
    docker exec "$NAME" test -f /tmp/opc-ready >/dev/null 2>&1 && break
    sleep 1
  done
  if ! docker exec "$NAME" test -f /tmp/opc-ready >/dev/null 2>&1; then
    echo "等不到 /tmp/opc-ready。现场："
    docker inspect -f 'Running={{.State.Running}} ExitCode={{.State.ExitCode}}' "$NAME" 2>&1
    docker logs "$NAME" 2>&1 | tail -20
    fail=1; continue
  fi
  echo "ok"

  echo "--- httplib2 认的 CA【预期 /etc/ssl/certs/ca-certificates.crt】"
  docker exec -u opc "$NAME" sh -c 'python3 -m httplib2.certs 2>/dev/null' 2>&1

  echo "--- gmail search【预期退出码 0；batch 两道这一步也必须全列出来】"
  docker exec -u opc "$NAME" sh -c \
    "python3 $GAPI gmail search 'after:2026/07/31 before:2026/09/01' --max 100 > /tmp/s.json; \
     echo '退出码:' \$?; \
     python3 -c \"import json;d=json.load(open('/tmp/s.json'));print('列出',len(d),'条');[print(' ',x['id'],x['from'][:36],x['subject'][:24]) for x in d]\"" 2>&1 | tail -15

  echo "--- 跑 oracle"
  docker cp "$TASK/solution/solve.sh" "$NAME:/tmp/solve.sh" >/dev/null 2>&1
  docker exec -u root "$NAME" sh -c 'chmod 0755 /tmp/solve.sh' >/dev/null 2>&1
  docker exec -u opc "$NAME" sh -c 'bash /tmp/solve.sh; echo "退出码:" $?' 2>&1 | tail -15

  echo "--- 产物"
  docker exec "$NAME" sh -c 'cat /app/triage.json 2>/dev/null || cat /app/issues.json 2>/dev/null || echo "(没有产物)"' 2>&1

  echo "--- 失败的 messages.get 条数【batch-partial 预期 >0，其余预期 0】"
  docker exec -u root "$NAME" sh -c \
    'grep -a messages.get /var/lib/opc/server-log.jsonl 2>/dev/null | grep -c "\"ok\": false"' 2>&1

  echo "--- 日志里的 user【预期 hello@yisi.example.com，不是 me】"
  docker exec -u root "$NAME" sh -c \
    'grep -a -o "\"user\": \"[^\"]*\"" /var/lib/opc/server-log.jsonl 2>/dev/null | sort -u' 2>&1
done

echo
echo "################################################################"
if [ "$fail" -eq 0 ]; then
  echo "四道题都跑完了。重点看："
else
  echo "有题目没跑起来（见上面的失败）。其余的重点看："
fi
echo "  1. batch-partial 的 gmail search 是否仍列全（fetch_error 没有前移到列清单）"
echo "  2. batch-partial 产物里 listed_count 与 items+unreadable 是否对得上"
echo "  3. 每道题日志里的 user 是否都是 hello@yisi.example.com"
