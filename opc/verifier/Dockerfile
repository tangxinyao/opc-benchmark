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
