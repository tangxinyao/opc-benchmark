# opc-benchmark 的 agent 基础镜像：hermes 及其依赖全部预先烘进来。
#
# 这样 Harbor 适配器的 install() 就不用再 exec 装任何东西——
# 每道题、每次 trial 都省掉一次装包，也不用在评测中途联网。
#
# 构建：make image        （make images 连判分镜像一起构建）
# 任务镜像用它作基底：FROM opc-benchmark/hermes-base:local

FROM python:3.12-slim-bookworm

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
 && rm -rf /var/lib/apt/lists/*

# --- hermes 本体 ---
# 官方安装脚本。--skip-setup 跳过交互式初始化（镜像里没有 tty，配置由适配器写）。
# HERMES_VERSION 非空时传给安装脚本的 --branch，把版本钉死——
# 评测里浮动的 hermes 版本等于浮动的结论，两次跑分不可比。
ARG HERMES_VERSION=
RUN set -euo pipefail; \
    branch_flag=""; \
    if [ -n "${HERMES_VERSION}" ]; then branch_flag=" --branch ${HERMES_VERSION}"; fi; \
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh \
      | bash -s -- --skip-setup${branch_flag}

# 安装脚本装到 $HOME/.local/bin（构建期 HOME=/root）。任务容器里 agent 可能
# 不是 root，所以把入口 symlink 到所有用户都在 PATH 上的位置，
# 省掉运行时到处 export PATH。
RUN ln -sf /root/.local/bin/hermes /usr/local/bin/hermes \
 && chmod -R a+rX /root/.local

# --- HERMES_HOME：配置、会话、skills 的落点 ---
# 必须与 opc_agents/hermes.py 里的 HERMES_HOME 常量一致（make lint 会check）。
# 放 /opt 而不是上游默认的 /tmp：/tmp 在某些环境里会被清理或挂成 tmpfs。
ENV HERMES_HOME=/opt/hermes \
    TERMINAL_ENV=local \
    PYTHONUNBUFFERED=1
RUN mkdir -p "${HERMES_HOME}/sessions" "${HERMES_HOME}/skills" "${HERMES_HOME}/memories" \
 && chmod -R 777 "${HERMES_HOME}"

# 构建期自检：镜像里没有可用的 hermes 就不该构建成功，
# 否则错误会推迟到评测中途才暴露。
RUN hermes version

WORKDIR /app
