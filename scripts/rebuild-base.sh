#!/bin/bash
# 重建 agent 基础镜像，并当场验证几条**不重建就看不出来**的性质。
#
# 为什么单独写一个脚本而不是只 `make image`：基底改了但镜像没重建时，
# 症状和没改一样——题目照常构建、照常跑分，只是可供性悄悄是旧的。
# 所以构建完必须立刻验，而且验的是镜像里的事实，不是 Dockerfile 的文本。
#
# 用法（在能跑 docker build 的机器上，仓库根目录）：
#   scripts/rebuild-base.sh
#
# 可覆盖的环境变量：
#   IMAGE             镜像 tag，默认 opc-benchmark/hermes-base:local
#   HERMES_VERSION    钉死 hermes 分支/版本，默认空（跟随安装脚本默认）
#   GH_MIRROR         github release 的加速前缀。内网直连 github 时传空：
#                       GH_MIRROR= scripts/rebuild-base.sh
#   SKIP_BUILD=1      跳过构建，只对现有镜像跑验证
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${IMAGE:-opc-benchmark/hermes-base:local}"
HERMES_VERSION="${HERMES_VERSION:-}"

cd "$ROOT"

ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILED=1; }
FAILED=0

# ---------------------------------------------------------------- 构建

if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "==> 构建 $IMAGE"
  # 改完 opc/agent/ 一定要重建：基底不重建的症状和没改一样。
  # 构建前先把源文件的 md5 打出来，跟构建后镜像里的那份比——
  # 「我以为我重建过了」是这里唯一真正要防的东西。
  build_args=(--build-arg "HERMES_VERSION=${HERMES_VERSION}")
  if [ "${GH_MIRROR+set}" = set ]; then
    build_args+=(--build-arg "GH_MIRROR=${GH_MIRROR}")
  fi
  docker build "${build_args[@]}" -f opc/agent/Dockerfile -t "$IMAGE" opc/agent
else
  echo "==> SKIP_BUILD=1，只验现有的 $IMAGE"
fi

# ---------------------------------------------------------------- 验证

echo
echo "==> 验证 $IMAGE"

run() { docker run --rm --entrypoint sh "$IMAGE" -c "$1"; }

# 1) 镜像里的 svc 脚本确实是仓库里这一份。
#    比 md5 而不是比 mtime 或凭印象：构建缓存命中时文件日期照样是新的。
echo "-- svc 脚本与仓库一致"
for f in opc-install-skills opc-prune-tools opc-entrypoint.sh opc-pin-hosts; do
  host_md5="$(md5sum "opc/agent/svc/$f" | cut -d' ' -f1)"
  img_md5="$(run "md5sum /usr/local/bin/$f 2>/dev/null | cut -d' ' -f1" || true)"
  if [ "$host_md5" = "$img_md5" ]; then
    ok "$f"
  else
    fail "$f 对不上（仓库 ${host_md5:0:8}… / 镜像 ${img_md5:-缺失})"
  fi
done

# 2) HERMES_HOME/skills 必须是空的。
#    基底只烘工具，不发 skill——发哪些是每道题自己的事（skills.manifest /
#    skills_dir）。dws 的 install.sh 会往这里塞 14 条指向 /root(0700) 的软链，
#    agent 一条都读不开，而且它们从没被任何一道题点名。留着就是污染可供性：
#    12 道本该零 skill 的题会凭空多出 14 个，从分数上还看不出来。
echo "-- HERMES_HOME/skills 干净"
leftovers="$(run 'ls -A ${HERMES_HOME:-/opt/hermes}/skills 2>/dev/null | tr "\n" " "' || true)"
if [ -z "${leftovers// }" ]; then
  ok "空目录（没有任何默认下发的 skill）"
else
  fail "有残留：$leftovers"
fi
links="$(run 'find ${HERMES_HOME:-/opt/hermes}/skills -maxdepth 1 -type l | wc -l' || echo 99)"
if [ "$links" = "0" ]; then ok "没有软链"; else fail "还有 $links 条软链（dws 那 14 条没删干净）"; fi

# 3) hermes 自带 skill 还在老地方，且 opc-install-skills 装得进去、agent 读得开。
#    这条是 skills.manifest 的 `hermes:` 前缀的全部前提：hermes 换版本改了
#    路径的话，要在这里红，而不是等某道题少发一个 skill 才发现。
echo "-- hermes: 前缀可用"
probe='
set -e
for s in email/himalaya email/email-inbox-triage productivity/google-workspace productivity/xlsx; do
  test -f /usr/local/lib/hermes-agent/skills/$s/SKILL.md || { echo "缺 $s"; exit 1; }
done
printf "hermes:email/himalaya\n" > /tmp/p
opc-install-skills /tmp/p >/dev/null
su -s /bin/sh opc -c "head -1 ${HERMES_HOME:-/opt/hermes}/skills/himalaya/SKILL.md" >/dev/null
echo ALLGOOD
'
if [ "$(docker run --rm --user root --entrypoint sh "$IMAGE" -c "$probe" 2>&1 | tail -1)" = "ALLGOOD" ]; then
  ok "自带 skill 路径在，装得进去，agent 身份读得开"
else
  fail "自带 skill 装不进去（跑 docker run --rm --user root --entrypoint sh $IMAGE 看详情）"
fi

# 4) 工具面：每个 CLI 都得真能起来。
#    版本号顺带打出来——跑分结论绑在这些版本上，换了要知道。
echo "-- CLI 可用"
for probe in "hermes --version" "dws --version" "himalaya --version" \
             "mailpit version" "stripe version" "aliyun version"; do
  name="${probe%% *}"
  if out="$(run "$probe 2>&1 | head -1")"; then ok "$name — $out"; else fail "$name 起不来"; fi
done

# 5) google-workspace skill 的执行后端（gws 缺席时的回落路径）。
echo "-- google api 客户端"
if run 'python3 -c "from googleapiclient.discovery import build; import google.auth"' >/dev/null 2>&1; then
  ok "googleapiclient 可导入"
else
  fail "googleapiclient 导不进来"
fi

echo
if [ "$FAILED" = 0 ]; then
  echo "全部通过。接着在这台机器上跑： make validate"
else
  echo "有失败项，别拿这个镜像去跑分。" >&2
fi
exit "$FAILED"
