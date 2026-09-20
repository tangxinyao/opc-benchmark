#!/bin/sh
# 容器启动：拉起 Google Workspace 数据源和外发信对端。
#
# 这道题的前置条件（信箱有没有歧义 / 批量取信掉不掉条）不在这里验——
# 掉条是语料里的 fetch_error 字段钉死的，信箱歧义看 owner-note.md，
# 两者都是静态事实，由 scripts/check_tasks.py 的 PREFLIGHT_CORPUS 在 lint 期验。
set -eu

# Docker 运行期会把自己那份 /etc/hosts 挂进来，构建期写的看不见，只能现在写。
sudo -n /usr/local/bin/opc-pin-hosts


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

sudo -n -u opcsvc /usr/local/bin/opc-svc-start workspace >/var/log/opc-datasource.log 2>&1 &

# 等 443 起来再放行，否则 agent 第一条 gam 命令可能撞上 connection refused。
i=0
while [ "$i" -lt 30 ]; do
  if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(s.connect_ex(('127.0.0.1', 443)))" 2>/dev/null; then
    break
  fi
  sleep 1
  i=$((i + 1))
done

# 就绪标记。基底镜像的 HEALTHCHECK 守着这个文件，harbor 的 `up --wait` 等它变
# 健康之后才把 agent 放进来。不写这一行容器永远不健康；写早了 agent 就会抢在
# 上面这些步骤之前进来（expired-session 就是这么红的）。它必须是 exec 前的
# 最后一件事。
: > /tmp/opc-ready

exec "$@"
