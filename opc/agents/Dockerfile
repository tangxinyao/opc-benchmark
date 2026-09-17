# opc-benchmark 的 agent 基础镜像：hermes 及其依赖全部预先烘进来。
#
# 这样 Harbor 适配器的 install() 就不用再 exec 装任何东西——
# 每道题、每次 trial 都省掉一次装包，也不用在评测中途联网。
#
# 构建：make image        （make images 连判分镜像一起构建）
# 任务镜像用它作基底：FROM opc-benchmark/hermes-base:local

FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm

# --- 系统依赖：hermes 的安装脚本和运行都要用 ---
# stdbuf 来自 coreutils，适配器用它做行缓冲；ripgrep 是 hermes 的检索后端。
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      ripgrep \
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
# 必须与 opc/agents/hermes.py 里的 HERMES_HOME 常量一致（make lint 会check）。
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
ARG DWS_VERSION=v1.0.62
RUN set -euo pipefail; \
    base="https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/releases/download/${DWS_VERSION}"; \
    curl -fsSL "${base}/dws-linux-amd64.tar.gz" -o /tmp/dws.tgz; \
    mkdir -p /tmp/dws && tar xzf /tmp/dws.tgz -C /tmp/dws; \
    install -m 0755 /tmp/dws/dws /usr/local/bin/dws; \
    curl -fsSL "${base}/dws-skills.zip" -o /tmp/dws-skills.zip; \
    mkdir -p /opt/dws/skills; \
    python -c "import zipfile,sys; zipfile.ZipFile('/tmp/dws-skills.zip').extractall('/opt/dws/skills')"; \
    chmod -R a+rX /opt/dws/skills; \
    rm -rf /tmp/dws /tmp/dws.tgz /tmp/dws-skills.zip; \
    dws --version

# --- 开源工具预烘（真二进制、零账号、版本钉死） ---
# 选型见 docs/todo-no-preflight.md 5.2：接法 A 只收开源可自托管、注册成本为零的。
# 版本一律钉死——浮动的 CLI 版本等于浮动的结论，这条和上面 dws/hermes 一致。
#   himalaya  真实 IMAP/SMTP 客户端，配置文件与认证面都是真的
#   mailpit   本地 SMTP/IMAP 服务端，给 himalaya 当对端，全程不出容器
ARG HIMALAYA_VERSION=v2.1.0
ARG MAILPIT_VERSION=v1.31.1
RUN set -euo pipefail; \
    curl -fsSL "https://github.com/pimalaya/himalaya/releases/download/${HIMALAYA_VERSION}/himalaya.x86_64-linux.tgz" \
      -o /tmp/himalaya.tgz; \
    mkdir -p /tmp/himalaya && tar xzf /tmp/himalaya.tgz -C /tmp/himalaya; \
    install -m 0755 "$(find /tmp/himalaya -type f -name himalaya | head -1)" /usr/local/bin/himalaya; \
    curl -fsSL "https://github.com/axllent/mailpit/releases/download/${MAILPIT_VERSION}/mailpit-linux-amd64.tar.gz" \
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
    curl -fsSL "https://github.com/taers232c/GAMADV-XTD3/releases/download/v${GAM_VERSION}/gamadv-xtd3-${GAM_VERSION}-linux-x86_64-glibc2.35.tar.xz" \
      -o /tmp/gam.tar.xz; \
    mkdir -p /opt/gam && tar xf /tmp/gam.tar.xz -C /opt/gam --strip-components=1; \
    rm -f /tmp/gam.tar.xz; \
    ln -sf /opt/gam/gam /usr/local/bin/gam; \
    chmod -R a+rX /opt/gam

# --- Stripe 官方 CLI ---
# 退款这个不可逆动作，现实里长的就是 `stripe refunds create --charge ... --amount ...`，
# 不是我们自己造的 `issue_refund`。用真 CLI 的理由和 gam/dws 一样：
# 自造一个假命令等于把真实难度（要先查到 charge id、要带币种、要确认）全删掉，
# 而且 agent 认不出那是真工具时，「忍住没退款」量到的就不是克制。
# 对端是 stripe_fixture_server.py，api.stripe.com 由 opc-pin-hosts 钉到本机。
ARG STRIPE_VERSION=1.21.8
RUN set -euo pipefail; \
    curl -fsSL "https://github.com/stripe/stripe-cli/releases/download/v${STRIPE_VERSION}/stripe_${STRIPE_VERSION}_linux_x86_64.tar.gz" \
      -o /tmp/stripe.tgz; \
    mkdir -p /tmp/stripe && tar xzf /tmp/stripe.tgz -C /tmp/stripe; \
    install -m 0755 /tmp/stripe/stripe /usr/local/bin/stripe; \
    rm -rf /tmp/stripe /tmp/stripe.tgz; \
    stripe version

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
COPY svc/opc-init-audit svc/opc-audit-collector svc/opc-svc-start \
     svc/opc-pin-hosts svc/opc-init-outbound-mail svc/opc-init-billing \
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

# agent 从这里起不再是 root。题目镜像里凡是 agent 要写的目录，
# 都要在 environment/Dockerfile 里 chown 给 opc（`opc-init-audit` 之后那行）。
USER opc
