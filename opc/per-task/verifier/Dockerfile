# opc-benchmark 的判分基础镜像。
#
# separate 模式下 verifier 跑在自己的容器里（不是 agent 容器），
# 所以判分工具必须在构建期烘好——在 test.sh 里现装意味着：
#   1. 每道题每次 trial 都要联一次网，判分变慢且会因 PyPI 抖动而假失败；
#   2. 版本在 trial 时解析，两次跑分用的可能不是同一个 pytest。
# 判分器的不确定性比 agent 的不确定性更致命：它会让你分不清是模型变了还是尺子变了。
#
# 构建：make verifier-image

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

# 版本必须钉死，理由同上。
ARG PYTEST_VERSION=8.4.1
ARG CTRF_VERSION=0.3.5
RUN pip install --no-cache-dir \
      "pytest==${PYTEST_VERSION}" \
      "pytest-json-ctrf==${CTRF_VERSION}"

# 构建期自检：工具装不上就不该构建成功。
# 直接check test.sh 真正依赖的那个开关是否注册好——pytest-json-ctrf 的顶层模块
# 叫 ctrf 而不是 pytest_ctrf，import 名字写错会check了个不存在的东西。
RUN pytest --version && pytest --help | grep -q -- '--ctrf'

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
