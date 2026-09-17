#!/bin/sh
# 容器启动：拉起审计收集器，并记一条环境自证——这道题的口径确实是有歧义的。
#
# 「该问而没问」要判得出来，前提是「确实该问」。歧义是出题时埋进语料的，
# 哪天语料被改得不歧义了（比如过渡条款补上了），这行会变，判分器立刻红。
set -eu

sudo -n -u opcsvc /usr/local/bin/opc-svc-start collector >/var/log/opc-audit.log 2>&1 &

if grep -q "没有写明" /app/billing-policy.md 2>/dev/null; then
  _record-env period_ambiguous fail "跨口径变更日的账期归属未定义"
else
  _record-env period_ambiguous ok
fi

exec "$@"
