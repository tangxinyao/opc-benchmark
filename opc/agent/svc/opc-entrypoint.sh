#!/bin/sh
# 容器启动：钉 DNS、按 OPC_SERVICES 拉起数据源，并准备好 dws 的登录态。
# harbor 用 ["sh","-c","sleep infinity"] 覆盖 CMD，但不覆盖 ENTRYPOINT，
# 所以这里是唯一能在 agent 进来之前跑一次的地方。
#
# 这里已经是 agent 的身份（opc）。要 opcsvc 才能做的两件事——读语料、写审计——
# 都经 sudo 走 opc-svc-start，sudoers 里只放行了这一个脚本。
set -eu

# 要钉的主机名由 /opt/opc/hosts.pin 决定，构建期写、运行期生效（Docker 把 /etc/hosts 挂进来）。
if [ -s /opt/opc/hosts.pin ]; then
  sudo -n /usr/local/bin/opc-pin-hosts
fi

# 外发信的对端。按「库在不在」opt-in——建了库的题才起，和下面数据源同一个路数。
# 没有它，himalaya 发信会撞上 connection refused；而收走的信就是判分的产物。
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

# 数据源：起哪些由题目在 environment/Dockerfile 里用 OPC_SERVICES 声明，
# 空格分隔，比如 ENV OPC_SERVICES="billing"。
#
# 以前的判据是「/opt/opc/lib/xxx_server.py 在不在」——那时四份实现按题扇出，
# 文件在就等于这道题要用它。现在四份全烘进基底、每题都在，那个判据会让每道题
# 都去起四个服务，所以换成显式声明。
#
# 端口是为了「等它起来再放行 agent」——不等的话 agent 第一条命令可能撞上
# connection refused，那会被判成它自己没做对。
for svc in ${OPC_SERVICES:-}; do
  case "$svc" in
    billing)    port=443 ;;
    cloud)      port=443 ;;
    workspace)  port=443 ;;
    datasource) port="${OPC_DWS_FIXTURE_PORT:-18080}" ;;
    *) echo "opc-entrypoint: 未知的 OPC_SERVICES 项: $svc" >&2; exit 2 ;;
  esac

  sudo -n -u opcsvc /usr/local/bin/opc-svc-start "$svc" \
    >"/var/log/opc-datasource.log" 2>&1 &

  i=0
  while [ "$i" -lt 30 ]; do
    if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(s.connect_ex(('127.0.0.1', $port)))" 2>/dev/null; then
      break
    fi
    # 服务起不来时别空转——原来这里没有间隔，一旦失败就是 100 次忙等
    sleep 1
    i=$((i + 1))
  done
done

# 企业应用的长期凭证已配置，换成本地登录态。
if [ -n "${DINGTALK_ACCESS_TOKEN:-}" ]; then
  dws auth login --token "$DINGTALK_ACCESS_TOKEN" >/dev/null 2>&1 || true
fi

exec "$@"
