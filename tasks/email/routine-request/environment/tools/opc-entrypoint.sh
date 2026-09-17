#!/bin/sh
# 容器启动：拉起审计收集器和企业数据源服务，并准备好 dws 的登录态。
# harbor 用 ["sh","-c","sleep infinity"] 覆盖 CMD，但不覆盖 ENTRYPOINT，
# 所以这里是唯一能在 agent 进来之前跑一次的地方。
#
# 这里已经是 agent 的身份（opc）。要 opcsvc 才能做的两件事——读语料、写审计——
# 都经 sudo 走 opc-svc-start，sudoers 里只放行了这一个脚本。
set -eu

sudo -n -u opcsvc /usr/local/bin/opc-svc-start collector >/var/log/opc-audit.log 2>&1 &

if [ -f /opt/opc/lib/datasource_server.py ]; then
  sudo -n -u opcsvc /usr/local/bin/opc-svc-start datasource >/var/log/opc-datasource.log 2>&1 &

  # 等端口起来再放行，否则 agent 第一条命令可能撞上 connection refused
  port="${OPC_DWS_FIXTURE_PORT:-18080}"
  i=0
  while [ "$i" -lt 30 ]; do
    if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(s.connect_ex(('127.0.0.1', $port)))" 2>/dev/null; then
      break
    fi
    # 服务起不来时别空转——原来这里没有间隔，一旦失败就是 100 次忙等
    sleep 1
    i=$((i + 1))
  done
fi

# 企业应用的长期凭证已配置，换成本地登录态。
if [ -n "${DINGTALK_ACCESS_TOKEN:-}" ]; then
  dws auth login --token "$DINGTALK_ACCESS_TOKEN" >/dev/null 2>&1 || true
fi

exec "$@"
