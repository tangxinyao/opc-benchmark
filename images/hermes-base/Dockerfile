# opc-benchmark 的 agent 基础镜像：hermes 及其依赖全部预先烘进来。
#
# 这样 Harbor 适配器的 install() 就不用再 exec 装任何东西——
# 每道题、每次 trial 都省掉一次装包，也不用在评测中途联网。
#
# 构建：make image        （等价于 docker build -t opc-benchmark/hermes-base:local .）
# 任务镜像用它作基底：FROM opc-benchmark/hermes-base:local

FROM python:3.12-slim-bookworm

# --- 系统依赖：适配器里那个 ensure_system_dependencies 需要的东西，一次装好 ---
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
# ⚠️ 改成你自己的安装方式，三选一：
#   a) 从内网 registry 装：  RUN pip install --no-cache-dir hermes-agent==<版本>
#   b) 从私有仓库装：        RUN --mount=type=ssh pip install git+ssh://...
#   c) 直接 COPY 构建产物：  COPY dist/hermes /usr/local/bin/hermes
# 下面是 (a) 的形态，版本必须钉死——评测里浮动的版本号等于浮动的结论。
ARG HERMES_VERSION=0.0.0
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" \
      "hermes-agent==${HERMES_VERSION}"

# --- HERMES_HOME：必须与 opc_agents/hermes.py 里的 HERMES_HOME 一致 ---
ENV HERMES_HOME=/opt/hermes \
    TERMINAL_ENV=local \
    PYTHONUNBUFFERED=1
RUN mkdir -p "${HERMES_HOME}/sessions" "${HERMES_HOME}/skills" "${HERMES_HOME}/memories" \
 && chmod -R 777 "${HERMES_HOME}"

# 构建期自检：镜像里没有可用的 hermes 就不该构建成功，
# 否则错误会推迟到评测中途才暴露。
RUN command -v hermes >/dev/null && hermes version

WORKDIR /app
