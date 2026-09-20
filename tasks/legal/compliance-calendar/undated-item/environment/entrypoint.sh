#!/bin/sh
# 容器启动。
#
# 这道题的前置条件（台账里那条义务有没有起算日）不在这里验——它是语料里的
# 静态事实，由 scripts/check_tasks.py 的 PREFLIGHT_CORPUS 在 lint 期钉死。
set -eu


# 就绪标记。基底镜像的 HEALTHCHECK 守着这个文件，harbor 的 `up --wait` 等它变
# 健康之后才把 agent 放进来。不写这一行容器永远不健康；写早了 agent 就会抢在
# 上面这些步骤之前进来（expired-session 就是这么红的）。它必须是 exec 前的
# 最后一件事。
: > /tmp/opc-ready

exec "$@"
