#!/bin/sh
# 容器启动：拉起审计收集器和计费数据源。
#
# 这道题的前置条件（口径确实有歧义）不在这里验——它是语料里的静态事实，
# 由 scripts/check_tasks.py 的 PREFLIGHT_CORPUS 在 lint 期钉死。
# 运行期再 grep 一遍不产生新信息，只会把「lint 就该炸」推迟到跑分时才炸。
set -eu

sudo -n -u opcsvc /usr/local/bin/opc-svc-start collector >/var/log/opc-audit.log 2>&1 &

# 计费数据源：真 stripe CLI 的对端，api.stripe.com 由 opc-pin-hosts 钉到本机。
if [ -f /opt/opc/lib/billing_server.py ]; then
  sudo -n -u opcsvc /usr/local/bin/opc-svc-start billing >/var/log/opc-billing.log 2>&1 &

  i=0
  while [ "$i" -lt 30 ]; do
    if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(s.connect_ex(('127.0.0.1', 443)))" 2>/dev/null; then
      break
    fi
    sleep 1
    i=$((i + 1))
  done
fi

# 外发信的对端。库在就起——判分要的那份产物由它写。
if [ -f /var/lib/opc/mailpit.db ]; then
  sudo -n -u opcsvc /usr/local/bin/opc-svc-start mailpit >/var/log/opc-mailpit.log 2>&1 &

  i=0
  while [ "$i" -lt 30 ]; do
    if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(s.connect_ex(('127.0.0.1', 1025)))" 2>/dev/null; then
      break
    fi
    sleep 1
    i=$((i + 1))
  done
fi

exec "$@"
