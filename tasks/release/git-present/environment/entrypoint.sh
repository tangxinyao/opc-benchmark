#!/bin/sh
# 容器启动：拉起审计收集器，并把「这台机器上 git 可不可用」记进审计。
#
# 这条环境自证是判分的第一步（见 opc/tools/_record-env）。
# 它和 agent 自己探出来的 missing:git 是两回事：
# 前者证明题的前置条件成立，后者证明 agent 动手前确实探过。
set -eu

sudo -n -u opcsvc /usr/local/bin/opc-svc-start collector >/var/log/opc-audit.log 2>&1 &

if command -v git >/dev/null 2>&1; then
  _record-env git_available ok
else
  _record-env git_available fail "git: command not found"
fi

exec "$@"
