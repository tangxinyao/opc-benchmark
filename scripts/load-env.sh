#!/bin/bash
# 把仓库根目录的 .env 读进当前 shell 的环境变量。**source 它，别执行它。**
#
#     set -a; . scripts/load-env.sh; set +a     # 或者直接 . scripts/load-env.sh
#
# 为什么在 shell 层读而不是在适配器里读：凭证有三个去处——harbor 本体、
# agent 容器、判分器容器。只有 shell 层能一次覆盖三个。
#
# .env 永远不要提交（.gitignore 已经挡了）。模板见 .env.example。

_opc_env_file="${OPC_ENV_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env}"

if [ -f "$_opc_env_file" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$_opc_env_file"
  set +a
else
  echo "提示：没找到 $_opc_env_file，凭证只能靠已有的 export。" \
       "可以 cp .env.example .env 再填。" >&2
fi

unset _opc_env_file
