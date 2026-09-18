#!/bin/bash
# 把 opc/ 里的工具与判分脚手架同步到每个任务目录。
#
#   opc/tools/     -> tasks/*/*/*/environment/tools/   （进 agent 容器）
#   数据源服务     -> tasks/*/*/*/environment/lib/     （只有声明了 lib/ 的题）
#   opc/verifier/  -> tasks/*/*/*/tests/               （进判分容器）
#
# opc/ 是唯一事实来源；改完跑这个脚本，然后两边一起提交。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for task in "$ROOT"/tasks/*/*/*/; do
  [ -f "$task/task.toml" ] || continue
  mkdir -p "$task/environment/tools" "$task/tests"
  rm -f "$task"/environment/tools/*   # 先清，避免 opc/tools/ 改名后留下孤儿脚本
  # fixture server 不进 tools/：那个目录会被 COPY 进 /opt/opc/bin，agent 读得到。
  # 它们只该以 environment/lib/ 的身份下发（见下面两个 opt-in 分支），
  # 否则等于把数据源的认证逻辑、fixture 路径和错误形状白送给 agent。
  find "$ROOT/opc/tools" -maxdepth 1 -type f \
    -not -name '*_fixture_server.py' \
    -exec cp {} "$task/environment/tools/" \;
  cp "$ROOT"/opc/verifier/test.sh "$task/tests/test.sh"
  cp "$ROOT"/opc/verifier/oracle.py "$task/tests/oracle.py"   # 差分判分骨架
  cp "$ROOT"/opc/verifier/preflight.py "$task/tests/preflight.py"  # 预检题的公共断言
  cp "$ROOT"/opc/verifier/outbox.py "$task/tests/outbox.py"        # 外发邮件的公共断言
  cp "$ROOT"/opc/verifier/billing.py "$task/tests/billing.py"      # 退款动作的公共断言
  cp "$ROOT"/opc/verifier/task-tests.Dockerfile "$task/tests/Dockerfile"
  # 数据源服务：题目里那份是 opc/tools/ 的拷贝，别让它自己长出第二份实现。
  # 它不进 tools/（那个目录 agent 看得见），而是进 environment/lib/，
  # 由 entrypoint 经 sudo 以 opcsvc 拉起。
  if [ -f "$task/environment/data/dingtalk.json" ]; then
    cp "$ROOT"/opc/tools/dws_fixture_server.py "$task/environment/lib/datasource_server.py"
  fi
  # Google Workspace 数据源：同上，题目声明了 data/workspace.json 才发。
  # 真 gam 冷启动要拉 discovery，容器里没有外网，所以本地留一份官方文档的副本。
  if [ -f "$task/environment/data/workspace.json" ]; then
    cp "$ROOT"/opc/tools/gws_fixture_server.py "$task/environment/lib/workspace_server.py"
    mkdir -p "$task/environment/data/discovery"
    cp "$ROOT"/opc/fixtures/google-discovery/*.json "$task/environment/data/discovery/"
  fi
  # 计费数据源：题目声明了 data/stripe.json 才发。真 stripe CLI 的对端。
  if [ -f "$task/environment/data/stripe.json" ]; then
    cp "$ROOT"/opc/tools/stripe_fixture_server.py "$task/environment/lib/billing_server.py"
  fi
  # agent skills：同样是 opt-in，只发给声明了 environment/skills/ 的题。
  # 不进基础镜像——那样每道题的 agent 都会在技能清单里看到 obsidian，
  # 对用不上 vault 的题就是纯噪声，还会诱它去试不存在的工具。
  if [ -d "$task/environment/skills" ]; then
    rm -rf "$task"/environment/skills/*
    cp -r "$ROOT"/opc/skills/obsidian/. "$task/environment/skills/"
  fi
  # Obsidian vault 语料：两道 contract 题共用一份，别让它长出第二份拷贝。
  if [ -d "$task/environment/vault" ]; then
    rm -rf "$task"/environment/vault/*
    cp -r "$ROOT"/opc/fixtures/contract-vault/. "$task/environment/vault/"
  fi
  chmod +x "$task/tests/test.sh"
  name="${task#"$ROOT/tasks/"}"
  echo "synced ${name%/}"
done
