# opc-benchmark 的 agent 基础镜像：hermes 及其依赖全部预先烘进来。
#
# 这样 Harbor 适配器的 install() 就不用再 exec 装任何东西——
# 每道题、每次 trial 都省掉一次装包，也不用在评测中途联网。
#
# 构建：make image        （make images 连判分镜像一起构建）
# 任务镜像用它作基底：FROM opc-benchmark/hermes-base:local

FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm

# --- 国内镜像源：apt 与 pip 都走阿里云 ---
# 基底是 Debian 12（bookworm），不是 Ubuntu，而且 slim 镜像用的是 deb822 格式的
# /etc/apt/sources.list.d/debian.sources，没有传统的 /etc/apt/sources.list——
# 照搬 Ubuntu 那套 sed 会改到一个不存在的文件，还悄无声息地成功。
# deb.debian.org/debian 与 .../debian-security 在阿里云下的路径同名，一条规则就够。
RUN sed -i 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' \
      /etc/apt/sources.list.d/debian.sources \
 && grep -q mirrors.aliyun.com /etc/apt/sources.list.d/debian.sources

# pip / uv 的索引。写 ENV 是给构建期之后（题目容器里现装东西）也留着，
# 写 /etc/pip.conf 是因为 ENV 不跨 sudo -u opcsvc 这类切身份的调用。
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com
RUN printf '[global]\nindex-url = https://mirrors.aliyun.com/pypi/simple/\ntrusted-host = mirrors.aliyun.com\n' \
      > /etc/pip.conf

# --- 系统依赖：hermes 的安装脚本和运行都要用 ---
# stdbuf 来自 coreutils，适配器用它做行缓冲；ripgrep 是 hermes 的检索后端。
# unzip 是 dws install.sh 解 skills zip 的硬依赖——缺了它脚本会中途报
# 「Install unzip」然后失败，而不是回退到别的解法。
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      ripgrep \
      unzip \
      xz-utils \
      coreutils \
      procps \
      openssl \
      libcap2-bin \
 && rm -rf /var/lib/apt/lists/*

# --- hermes 本体 ---
# 官方安装脚本。--skip-setup 跳过交互式初始化（镜像里没有 tty，配置由适配器写）。
# HERMES_VERSION 非空时传给安装脚本的 --branch，把版本钉死——
# 评测里浮动的 hermes 版本等于浮动的结论，两次跑分不可比。
# 默认 shell 是 dash，没有 pipefail，而下面那行是 curl | bash——
# 没有 pipefail 的话 curl 失败（404、DNS、被墙）也会被 bash 的 0 退出码盖掉，
# 构建照样成功，装出一个没有 hermes 的镜像。
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG HERMES_VERSION=
RUN set -euo pipefail; \
    branch_flag=""; \
    if [ -n "${HERMES_VERSION}" ]; then branch_flag=" --branch ${HERMES_VERSION}"; fi; \
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh \
      | bash -s -- --skip-setup${branch_flag}

# 构建期是 root，安装脚本走 FHS 布局：代码在 /usr/local/lib/hermes-agent，
# 入口已经是 /usr/local/bin/hermes——本来就在所有用户的 PATH 上，不用再 symlink。
# （早先这里 ln -sf /root/.local/bin/hermes 过去，反而把真入口覆盖成了死链。）
# 任务容器里 agent 可能不是 root，所以放开读与进目录的权限。
RUN test -x /usr/local/bin/hermes \
 && chmod -R a+rX /usr/local/lib/hermes-agent

# --- HERMES_HOME：配置、会话、skills 的落点 ---
# 必须与 opc/agent/hermes.py 里的 HERMES_HOME 常量一致（make lint 会check）。
# 放 /opt 而不是上游默认的 /tmp：/tmp 在某些环境里会被清理或挂成 tmpfs。
ENV HERMES_HOME=/opt/hermes \
    TERMINAL_ENV=local \
    PYTHONUNBUFFERED=1
RUN mkdir -p "${HERMES_HOME}/sessions" "${HERMES_HOME}/skills" "${HERMES_HOME}/memories" \
 && chmod -R 777 "${HERMES_HOME}"

# 构建期自检：镜像里没有可用的 hermes 就不该构建成功，
# 否则错误会推迟到评测中途才暴露。
RUN hermes --version

WORKDIR /app

# --- clarify 的去向 ---
# hermes 的 CLI 把 clarify 接在 prompt_toolkit 的 modal 上，容器里没人按键，
# 于是每问一次白等 clarify.timeout（默认 120 秒），超时后还会回一句
# 「用你自己的判断继续」——既烧任务预算，又往「别问了自己拍板」的方向推。
# 这里把它改接到一份可配置的应答表上：确定、即时、提问和回复都留痕。
# 应答表由每道题用 OPC_CLARIFY_SCRIPT 指定，缺省是下面这份。
COPY clarify/relay.py /opt/opc/lib/clarify_relay.py
COPY clarify/default.json /opt/opc/clarify.json
COPY clarify/override.py /tmp/clarify_override.py
RUN cat /tmp/clarify_override.py >> /usr/local/lib/hermes-agent/tools/clarify_tool.py \
 && rm /tmp/clarify_override.py \
 && chmod a+r /opt/opc/lib/clarify_relay.py /opt/opc/clarify.json \
 && OPC_AUDIT_LOG=/tmp/clarify-selfcheck.log \
    /usr/local/lib/hermes-agent/venv/bin/python -c "\
import sys, json; sys.path.insert(0, '/usr/local/lib/hermes-agent'); \
from tools.clarify_tool import clarify_tool; \
out = json.loads(clarify_tool('走一下通路')); \
assert out['user_response'], out; \
print('clarify relay ok:', out['user_response'])" \
 && rm -rf /tmp/clarify-selfcheck.log /var/lib/opc

# --- 钉钉官方 CLI（dws）及其 skills ---
# 题目的材料从真实连接器里来，而不是预先摆好的文件。这里烘的是官方发布的
# 二进制和官方写的 skills，我们不自己造一个假 CLI——假 CLI 等于把
# 连接器的真实难度（鉴权、分页、契约字段）全删掉。
# 版本钉死：浮动的 CLI 版本等于浮动的结论。
# 下载走 gitee：github 的 release 端点在国内网络下不稳，构建会随机挂。
# 版本从 v1.0.62 降到 v1.0.60——gitee 镜像最新只到这一档。降版本会动基线，
# 是明确拍板过的取舍：可复现地建得起来，优先于多那两个小版本。
# 装法用官方 install.sh 而不是自己拼 URL：gitee 的 attachment URL 带不稳定的
# 数字 id，只能由脚本走 API 解析，拼 releases/download/... 必然 404。
# 脚本把 skills 装到 $HOME，我们再搬到 /opt/dws/skills——
# tasks/settlement/*/environment/Dockerfile 认的是这个路径。
ARG DWS_VERSION=v1.0.60
ARG DWS_GITEE_REPO=DingTalk-Real-AI/dingtalk-workspace-cli
RUN set -euo pipefail; \
    DWS_GITEE_REPO="${DWS_GITEE_REPO}" \
    DWS_VERSION="${DWS_VERSION}" \
    DWS_INSTALL_DIR=/usr/local/bin \
      sh -c 'curl -fsSL "https://gitee.com/${DWS_GITEE_REPO}/raw/main/scripts/install.sh" | sh'; \
    mkdir -p /opt/dws/skills; \
    cp -r "$HOME/.dws/skills/." /opt/dws/skills/; \
    test -d /opt/dws/skills/multi/dingtalk-chat; \
    chmod -R a+rX /opt/dws/skills; \
    dws --version

# --- 开源工具预烘（真二进制、零账号、版本钉死） ---
# 选型见 docs/todo-no-preflight.md 5.2：接法 A 只收开源可自托管、注册成本为零的。
# 版本一律钉死——浮动的 CLI 版本等于浮动的结论，这条和上面 dws/hermes 一致。
#   himalaya  真实 IMAP/SMTP 客户端，配置文件与认证面都是真的
#   mailpit   本地 SMTP/IMAP 服务端，给 himalaya 当对端，全程不出容器
# 其余几个还是 github 的 release，没有 gitee 镜像；统一套一层可覆盖的加速前缀，
# 内网构建时传 --build-arg GH_MIRROR= 即可回到直连 github。
ARG GH_MIRROR=https://gh-proxy.com/
# 架构跟随 buildkit 的 TARGETARCH（amd64 / arm64），不再写死 x86_64：
# 在 arm 机器上建时，写死的 amd64 二进制装得进去、跑不起来。
# 四家的资产命名各不相同，所以逐个映射，不能共用一个变量：
#   himalaya  x86_64 / aarch64      mailpit  amd64 / arm64（就是 TARGETARCH）
#   gam       x86_64 / arm64        stripe   x86_64 / arm64
# case 里显式 *) 报错：出现没映射过的架构要当场停，而不是拼出一个 404。
ARG TARGETARCH
ARG HIMALAYA_VERSION=v2.1.0
ARG MAILPIT_VERSION=v1.31.1
RUN set -euo pipefail; \
    case "${TARGETARCH}" in \
      amd64) hima_arch=x86_64 ;; \
      arm64) hima_arch=aarch64 ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "${GH_MIRROR}https://github.com/pimalaya/himalaya/releases/download/${HIMALAYA_VERSION}/himalaya.${hima_arch}-linux.tgz" \
      -o /tmp/himalaya.tgz; \
    mkdir -p /tmp/himalaya && tar xzf /tmp/himalaya.tgz -C /tmp/himalaya; \
    install -m 0755 "$(find /tmp/himalaya -type f -name himalaya | head -1)" /usr/local/bin/himalaya; \
    curl -fsSL "${GH_MIRROR}https://github.com/axllent/mailpit/releases/download/${MAILPIT_VERSION}/mailpit-linux-${TARGETARCH}.tar.gz" \
      -o /tmp/mailpit.tgz; \
    mkdir -p /tmp/mailpit && tar xzf /tmp/mailpit.tgz -C /tmp/mailpit; \
    install -m 0755 "$(find /tmp/mailpit -type f -name mailpit | head -1)" /usr/local/bin/mailpit; \
    rm -rf /tmp/himalaya /tmp/himalaya.tgz /tmp/mailpit /tmp/mailpit.tgz; \
    himalaya --version; \
    mailpit version

# --- GAMADV-XTD3（Google Workspace 的事实标准 CLI）---
# 官方发布的 PyInstaller 冻结二进制，不是我们自己写的壳：服务账号 JWT、
# discovery、googleapiclient 的 batch 协议全按真的走，只是几个 googleapis.com
# 主机名在题目容器里被钉到本机（opc-pin-hosts + 本地 CA）。
# glibc 变体跟着基底走：python:3.12-slim-bookworm 是 Debian 12 / glibc 2.36。
ARG GAM_VERSION=7.05.08
RUN set -euo pipefail; \
    case "${TARGETARCH}" in \
      amd64) gam_arch=x86_64 ;; \
      arm64) gam_arch=arm64 ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "${GH_MIRROR}https://github.com/taers232c/GAMADV-XTD3/releases/download/v${GAM_VERSION}/gamadv-xtd3-${GAM_VERSION}-linux-${gam_arch}-glibc2.35.tar.xz" \
      -o /tmp/gam.tar.xz; \
    mkdir -p /opt/gam && tar xf /tmp/gam.tar.xz -C /opt/gam --strip-components=1; \
    rm -f /tmp/gam.tar.xz; \
    ln -sf /opt/gam/gam /usr/local/bin/gam; \
    chmod -R a+rX /opt/gam; \
    GAMCFGDIR=/tmp/gam-selfcheck gam version; \
    rm -rf /tmp/gam-selfcheck /root/Downloads

# --- Stripe 官方 CLI ---
# 退款这个不可逆动作，现实里长的就是 `stripe refunds create --charge ... --amount ...`，
# 不是我们自己造的 `issue_refund`。用真 CLI 的理由和 gam/dws 一样：
# 自造一个假命令等于把真实难度（要先查到 charge id、要带币种、要确认）全删掉，
# 而且 agent 认不出那是真工具时，「忍住没退款」量到的就不是克制。
# 对端是 stripe_fixture_server.py，api.stripe.com 由 opc-pin-hosts 钉到本机。
ARG STRIPE_VERSION=1.21.8
RUN set -euo pipefail; \
    case "${TARGETARCH}" in \
      amd64) stripe_arch=x86_64 ;; \
      arm64) stripe_arch=arm64 ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "${GH_MIRROR}https://github.com/stripe/stripe-cli/releases/download/v${STRIPE_VERSION}/stripe_${STRIPE_VERSION}_linux_${stripe_arch}.tar.gz" \
      -o /tmp/stripe.tgz; \
    mkdir -p /tmp/stripe && tar xzf /tmp/stripe.tgz -C /tmp/stripe; \
    install -m 0755 /tmp/stripe/stripe /usr/local/bin/stripe; \
    rm -rf /tmp/stripe /tmp/stripe.tgz; \
    stripe version

# --- 阿里云官方 CLI ---
# 发布类题目的载体：一人公司的后端就跑在 ECS + SLB + RDS + CDN 上，
# 发版是一串跨产品、有严格先后的调用（备份 -> 迁移 -> 摘流量 -> 部署 -> 挂回
# -> 看监控 -> 全量 -> 刷 CDN），比「写份更新日志」真实得多。
#
# 和 gam/stripe/dws 一样用官方二进制、钉死版本、对端指向本机 fixture。
# 比 gam 干净的一点：这个 CLI 是 Go 写的，**读系统信任库**，
# 所以本地 CA 进 update-ca-certificates 它就认——不用像 gam 那样被迫开
# no_verify_ssl。完整 TLS 校验保留，agent 也不需要带任何特殊参数。
ARG ALIYUN_CLI_VERSION=3.0.226
RUN set -euo pipefail; \
    case "${TARGETARCH}" in \
      amd64) aliyun_arch=amd64 ;; \
      arm64) aliyun_arch=arm64 ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "${GH_MIRROR}https://github.com/aliyun/aliyun-cli/releases/download/v${ALIYUN_CLI_VERSION}/aliyun-cli-linux-${ALIYUN_CLI_VERSION}-${aliyun_arch}.tgz" \
      -o /tmp/aliyun.tgz; \
    mkdir -p /tmp/aliyun && tar xzf /tmp/aliyun.tgz -C /tmp/aliyun; \
    install -m 0755 "$(find /tmp/aliyun -type f -name aliyun | head -1)" /usr/local/bin/aliyun; \
    rm -rf /tmp/aliyun /tmp/aliyun.tgz; \
    aliyun version

# --- 身份与权限 ---
# agent 以前是 root，于是语料文件、审计日志它都能直接动：
# 答案就躺在 fixture JSON 里，`cat` 一下就绕过了连接器；审计日志也能改写，
# 把「不得调用某工具」这类负断言一笔勾销。
#
#   opc     uid 1000  agent 的身份，docker exec 进来就是它
#   opcsvc  uid 1001  服务身份：持有语料与审计日志，agent 读不到
#
# sudo 只放行一个固定脚本、且只能切到 opcsvc，除此之外提不了权。
RUN apt-get update && apt-get install -y --no-install-recommends sudo \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 1000 opc \
 && useradd -u 1000 -g 1000 -m -s /bin/bash opc \
 && groupadd -g 1001 opcsvc \
 && useradd -u 1001 -g 1001 -M -s /usr/sbin/nologin opcsvc \
 && usermod -a -G opc opcsvc
# opc-entrypoint.sh 与 opc-prune-tools 也在这里：它们是流程脚本（容器启动、
# 题目构建期裁剪），agent 永远不该调，所以跟其余 svc 脚本一样落 /usr/local/bin，
# 不进 /opt/opc/bin —— 那个目录在 agent 的 PATH 上、`ls` 就看得见。
COPY svc/opc-init-audit svc/opc-audit-collector svc/opc-svc-start \
     svc/opc-pin-hosts svc/opc-init-outbound-mail svc/opc-init-billing \
     svc/opc-entrypoint.sh svc/opc-prune-tools \
     /usr/local/bin/
# Google 那几个 API 的端口写死在 discovery 文档的 rootUrl 里（443），改不了。
# 服务身份 opcsvc 绑不了特权端口，于是单独复制一份 python 给它加 cap——
# agent 自己那个 /usr/local/bin/python3 一点能力都不加。
RUN mkdir -p /usr/local/lib/opc \
 && cp /usr/local/bin/python3.12 /usr/local/lib/opc/python3-net \
 && setcap cap_net_bind_service=+ep /usr/local/lib/opc/python3-net \
 && chmod 0755 /usr/local/lib/opc/python3-net
RUN chmod 0755 /usr/local/bin/opc-init-audit /usr/local/bin/opc-audit-collector \
      /usr/local/bin/opc-svc-start /usr/local/bin/opc-pin-hosts \
      /usr/local/bin/opc-init-outbound-mail /usr/local/bin/opc-init-billing \
      /usr/local/bin/opc-entrypoint.sh /usr/local/bin/opc-prune-tools \
 && printf '%s\n' 'opc ALL=(opcsvc) NOPASSWD: /usr/local/bin/opc-svc-start' \
      'opc ALL=(root) NOPASSWD: /usr/local/bin/opc-pin-hosts' \
      > /etc/sudoers.d/opc-svc \
 && chmod 0440 /etc/sudoers.d/opc-svc \
 && visudo -c -f /etc/sudoers.d/opc-svc \
 && touch /var/log/opc-audit.log /var/log/opc-datasource.log \
      /var/log/opc-mailpit.log /var/log/opc-billing.log \
 && chown opcsvc:opc /var/log/opc-audit.log /var/log/opc-datasource.log \
      /var/log/opc-mailpit.log /var/log/opc-billing.log \
 && chmod 0660 /var/log/opc-audit.log /var/log/opc-datasource.log \
      /var/log/opc-mailpit.log /var/log/opc-billing.log \
 && chown -R opc:opc /app "${HERMES_HOME}"

# --- 环境里的内部命令 ---
# 以前这些是由 scripts/sync-tasks.sh 扇出到每道题的 environment/tools/、
# 再由题目 Dockerfile `COPY tools/ /opt/opc/bin/` 进去的：22 道题 22 份逐字节
# 相同的拷贝，且拷贝在题目录里和手写文件长得一模一样，改错了没人拦。
# 烘进基底之后题目录里不再有这个目录，来源只剩这一处。
#
# 源目录分三个，一一对应镜像里三个不同的落点——放进哪个目录就决定了落到哪，
# 没有隐式规则。依据是「它是不是一条命令」，不是它用什么语言写的
# （rules 是 Python 写的命令，所以它没有 .py 后缀）：
#   bin/     有 shebang、可执行、被当命令调  -> /opt/opc/bin（在 PATH 上）
#   pylib/   被 import 的包                 -> /opt/opc/pylib（PYTHONPATH）
#   etc/     被 source 的                   -> /opt/opc/bashenv.sh（BASH_ENV）
#
# 实现收在 pylib/opc_internal/ 里而不是摊在 bin/：/opt/opc/bin 在 agent 的
# PATH 上、`ls` 就看得见，一个带 .py 后缀的模块摆在一堆公司内部命令中间，
# 不像内部工具，像评测脚手架（设计立场 3）。
# 做成包而不是裸模块，是因为 PYTHONPATH 对容器里每个 python 进程都生效。
#
# 流程脚本（opc-entrypoint.sh / opc-prune-tools）不在这三个里，它们跟其余
# svc 脚本一起落 /usr/local/bin——agent 永远不该调，也就不该在它的 PATH 上。
# 按题裁剪仍然发生在题目构建期：opc-prune-tools 在语料 COPY 之后跑，
# 把后端语料不存在的只读工具从 PATH 上摘掉。烘进基底不影响这一层。
COPY bin/ /opt/opc/bin/
COPY pylib/ /opt/opc/pylib/
COPY etc/bashenv.sh /opt/opc/bashenv.sh
RUN chmod 0755 /opt/opc/bin/* \
 && chmod -R a+rX /opt/opc/pylib /opt/opc/bashenv.sh \
 && test -x /opt/opc/bin/rules \
 && test -f /opt/opc/pylib/opc_internal/audit.py

# PATH 与 PYTHONPATH 在这里就位，题目 Dockerfile 不必再各自声明。
# BASH_ENV：hermes 每条命令都是一个新的 `bash -c`，于是每条命令都会读这份。
ENV PATH="/opt/opc/bin:${PATH}" \
    PYTHONPATH="/opt/opc/pylib" \
    BASH_ENV=/opt/opc/bashenv.sh

# 构建期自检：rules 要能在 PATH 上被找到，并且 import 得到 opc_internal。
# 只改了目录布局没改 PYTHONPATH 的话，这里当场炸，而不是等到评测中途。
RUN python3 -c "from opc_internal import audit" \
 && command -v rules >/dev/null

# agent 从这里起不再是 root。题目镜像里凡是 agent 要写的目录，
# 都要在 environment/Dockerfile 里 chown 给 opc（`opc-init-audit` 之后那行）。
USER opc
