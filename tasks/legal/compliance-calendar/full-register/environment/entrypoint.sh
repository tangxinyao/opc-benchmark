#!/bin/sh
# 容器启动。
#
# 这道题的前置条件（台账里那条义务有没有起算日）不在这里验——它是语料里的
# 静态事实，由 scripts/check_tasks.py 的 PREFLIGHT_CORPUS 在 lint 期钉死。
set -eu


exec "$@"
