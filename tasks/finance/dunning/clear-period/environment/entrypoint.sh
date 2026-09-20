#!/bin/sh
# 容器启动：拉起计费数据源。
#
# 这道题的前置条件（口径确实有歧义）不在这里验——它是语料里的静态事实，
# 由 scripts/check_tasks.py 的 PREFLIGHT_CORPUS 在 lint 期钉死。
# 运行期再 grep 一遍不产生新信息，只会把「lint 就该炸」推迟到跑分时才炸。
set -eu


# 计费数据源：真 stripe CLI 的对端，api.stripe.com 由 opc-pin-hosts 钉到本机。
# 这道题固定要 billing 这一个数据源，直接起。
# （以前这里守「实现文件在不在」，那是数据源按题扇出时代的判据；
#   现在四份实现都烘在基底里，每题都在，守它没有意义。）
sudo -n -u opcsvc /usr/local/bin/opc-svc-start billing >/var/log/opc-billing.log 2>&1 &

i=0
while [ "$i" -lt 30 ]; do
  if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(s.connect_ex(('127.0.0.1', 443)))" 2>/dev/null; then
    break
  fi
  sleep 1
  i=$((i + 1))
done

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

# 就绪标记。基底镜像的 HEALTHCHECK 守着这个文件，harbor 的 `up --wait` 等它变
# 健康之后才把 agent 放进来。不写这一行容器永远不健康；写早了 agent 就会抢在
# 上面这些步骤之前进来（expired-session 就是这么红的）。它必须是 exec 前的
# 最后一件事。
: > /tmp/opc-ready

exec "$@"
