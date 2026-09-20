IMAGE ?= opc-benchmark/hermes-base:local
VERIFIER_IMAGE ?= opc-benchmark/verifier-base:local
HERMES_VERSION ?=
PIP_INDEX_URL ?= https://pypi.org/simple
# 依赖由 pyproject.toml + uv.lock 钉死，uv run 会自动同步 .venv。
# 不再用 --with 现装：那等于每次跑分的工具版本都重新解析一遍。
UV_RUN := uv run

# 需要凭证的目标统一走这个前缀：先 source .env，再跑。
# 用 bash -c 是因为 make 每行起一个新 shell，source 的效果不跨行。
WITH_ENV := bash -c '. scripts/load-env.sh;

.PHONY: images image verifier-image configs lint unit smoke check env-check run sync

sync:  ## 按 uv.lock 装依赖到 .venv
	uv sync

images: image verifier-image  ## 构建两个基础镜像

image:  ## agent 基础镜像（hermes 预烘）
	docker build \
	  --build-arg HERMES_VERSION=$(HERMES_VERSION) \
	  --build-arg PIP_INDEX_URL=$(PIP_INDEX_URL) \
	  -f opc/base/agents/Dockerfile -t $(IMAGE) opc/base

verifier-image:  ## 判分基础镜像（pytest 预烘）
	docker build -f opc/per-task/verifier/Dockerfile -t $(VERIFIER_IMAGE) opc/per-task/verifier

configs:  ## 由 task.toml 的 [metadata.opc] 生成 harbor job config
	$(UV_RUN) python scripts/gen_job_configs.py

lint:  ## 任务目录静态检查（canary、标签、判分工具是否烘好、拒答题是否配对）
	$(UV_RUN) python scripts/check_tasks.py
	$(UV_RUN) python scripts/gen_job_configs.py
	./scripts/sync-tasks.sh --check

unit:  ## 适配器单元测试
	$(UV_RUN) python -m pytest tests -q

smoke:  ## 每道题的 oracle 必须满分、nop 必须零分
	$(WITH_ENV) PYTHON="$$(uv run python -c "import sys;print(sys.executable)")" ./scripts/smoke.sh'

check: lint unit smoke  ## 以上全部，都不需要 Docker

env-check:  ## 检查每道题声明要的环境变量是否都已就位（不打印值）
	$(WITH_ENV) $(UV_RUN) python scripts/check_env.py'

run:  ## 跑一个 job config：make run CONFIG=configs/jobs/job-xxx.yaml
	@test -n "$(CONFIG)" || (echo "用法: make run CONFIG=configs/jobs/job-xxx.yaml"; exit 1)
	$(WITH_ENV) uv run harbor run -c $(CONFIG)'
