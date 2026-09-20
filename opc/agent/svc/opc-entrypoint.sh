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
# 这一步以前是 `|| true`：登录办不成也一声不吭。代价是判分器那头看到的是
# 「一条 dws 事件都没有」，和「agent 压根没去取数」长得一模一样——在另一台
# 机器上就是这么丢了半天：真实原因是 CLI 解不出 token（open .../.data: no such
# file），报出来却是几条断言无缘无故全红。
#
# 登录态是**环境的前置条件**，不是 agent 的活。它没办成就是题坏了，
# 那就当场停在这儿：容器起不来比起来了但少半个前提要便宜得多。
#
# 注意门禁看的是 `authenticated` 字段，不是退出码——`dws auth status`
# 未登录时同样退 0，拿 rc 当判据等于没判。
if [ -n "${DINGTALK_ACCESS_TOKEN:-}" ]; then
  # 落点在基底里已经 touch 好（opcsvc:opc 0660）。万一是旧基底就退到 /tmp——
  # 这一步是为了让失败看得见，它自己不该成为新的失败点。
  dws_log=/var/log/opc-dws-login.log
  : >"$dws_log" 2>/dev/null || dws_log=/tmp/opc-dws-login.log
  if ! dws auth login --token "$DINGTALK_ACCESS_TOKEN" >"$dws_log" 2>&1; then
    echo "opc-entrypoint: dws auth login 失败，登录态没办成：" >&2
    cat "$dws_log" >&2
    exit 3
  fi
  if ! dws auth status --format json 2>>"$dws_log" \
       | grep -q '"authenticated": *true'; then
    echo "opc-entrypoint: dws auth login 退了 0，但登录态没落地（DWS_CONFIG_DIR=${DWS_CONFIG_DIR:-未设置}）：" >&2
    dws auth status --format json >&2 2>&1 || true
    cat "$dws_log" >&2
    exit 3
  fi
fi

exec "$@"
