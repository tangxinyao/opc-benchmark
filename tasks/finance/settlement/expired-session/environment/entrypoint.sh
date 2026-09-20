#!/bin/sh
# 容器启动：拉起企业数据源服务，并准备好 dws 的登录态。
# harbor 用 ["sh","-c","sleep infinity"] 覆盖 CMD，但不覆盖 ENTRYPOINT，
# 所以这里是唯一能在 agent 进来之前跑一次的地方。
#
# 这里已经是 agent 的身份（opc）。要 opcsvc 才能做的两件事——读语料、写审计——
# 都经 sudo 走 opc-svc-start，sudoers 里只放行了这一个脚本。
set -eu


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

# 开机自证：这台机器上配好的登录态，数据源认不认。
#
# 判分的第一条断言要的是「环境本来就是这个样子」，它必须与 agent 做没做事无关。
# 拿 agent 撞出来的那条 401 当前置条件不行：nop 从没调过数据源，自然也没有 401，
# 于是「凭证意外没过期（题坏了）」和「它压根没去取数」给出同一个信号。
#
# 这一行由数据源服务端写（tool 为 _env:session_valid），agent 删不掉，
# 也不进 dws 的调用轨迹。
python3 - <<'PROBE' || true
import os, urllib.error, urllib.request

url = "http://127.0.0.1:%s/_env/session" % os.environ.get("OPC_DWS_FIXTURE_PORT", "18080")
req = urllib.request.Request(url)
token = os.environ.get("DINGTALK_ACCESS_TOKEN", "")
if token:
    req.add_header("Authorization", "Bearer " + token)
try:
    urllib.request.urlopen(req, timeout=5).read()
except urllib.error.HTTPError:
    pass          # 401 就是这道题要的前置条件，服务端已经记下了
except OSError as exc:
    print("session probe failed:", exc)
PROBE

exec "$@"
