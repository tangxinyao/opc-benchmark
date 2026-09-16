IMAGE ?= opc-benchmark/hermes-base:local
VERIFIER_IMAGE ?= opc-benchmark/verifier-base:local
HERMES_VERSION ?=
PIP_INDEX_URL ?= https://pypi.org/simple
UV_RUN := uv run --python 3.12 --no-project

.PHONY: images image verifier-image configs lint unit smoke check

images: image verifier-image  ## 构建两个基础镜像

image:  ## agent 基础镜像（hermes 预烘）
	docker build \
	  --build-arg HERMES_VERSION=$(HERMES_VERSION) \
	  --build-arg PIP_INDEX_URL=$(PIP_INDEX_URL) \
	  -t $(IMAGE) images/hermes-base

verifier-image:  ## 判分基础镜像（pytest 预烘）
	docker build -t $(VERIFIER_IMAGE) images/verifier-base

configs:  ## 由 task.toml 的 [metadata.opc] 生成 harbor job config
	$(UV_RUN) --with pyyaml python scripts/gen_job_configs.py

lint:  ## 任务目录静态检查（canary、标签、判分工具是否烘好、拒答题是否配对）
	$(UV_RUN) python scripts/check_tasks.py
	$(UV_RUN) --with pyyaml python scripts/gen_job_configs.py

unit:  ## 适配器单元测试
	$(UV_RUN) --with pytest python -m pytest tests -q

smoke:  ## 每道题的 oracle 必须满分、nop 必须零分
	./scripts/smoke.sh

check: lint unit smoke  ## 以上全部，都不需要 Docker
