IMAGE ?= opc-benchmark/hermes-base:local
HERMES_VERSION ?= 0.0.0
PIP_INDEX_URL ?= https://pypi.org/simple

.PHONY: image smoke unit check

image:  ## 构建 agent 基础镜像
	docker build \
	  --build-arg HERMES_VERSION=$(HERMES_VERSION) \
	  --build-arg PIP_INDEX_URL=$(PIP_INDEX_URL) \
	  -t $(IMAGE) images/hermes-base

unit:  ## 适配器单元测试（不需要 Docker，也不需要装 harbor）
	uv run --python 3.12 --no-project --with pytest python -m pytest tests -q

smoke:  ## 每道题的 oracle 必须满分、nop 必须零分（不需要 Docker）
	./scripts/smoke.sh

check: unit smoke
