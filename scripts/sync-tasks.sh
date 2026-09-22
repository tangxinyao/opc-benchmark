#!/bin/bash
# 把 opc/ 里的工具与判分脚手架同步到每个任务目录。
#
#   discovery 文档 -> tasks/*/*/*/environment/data/discovery/（声明了 workspace.json 的题）
#   opc/common/skills/    -> tasks/*/*/*/environment/skills/  （按 skills.manifest 点名）
#   opc/verifier/  -> tasks/*/*/*/tests/               （进判分容器）
#
# opc/ 是唯一事实来源；改完跑这个脚本，然后两边一起提交。
#
#   scripts/sync-tasks.sh            扇出去
#   scripts/sync-tasks.sh --check    只比对，不写；有差异就非零退出（make lint 用）
#
# --check 存在的理由：改了 opc/ 忘了跑同步，题目录会留着旧拷贝，而
# 判分脚手架就在这里面——尺子悄悄变旧了，分数照常产出，没人会发现。
# 它不另写一份比对逻辑，而是复用下面同一个 sync_task，所以映射关系只有一份。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

# 把一道题该有的东西铺到 $2。$1 是题目录（读它来判断 opt-in），
# $2 是落点——正常模式就是题目录自己，--check 模式是个临时镜像。
sync_task() {
  local task="$1" dest="$2"
  mkdir -p "$dest/tests"

  # 内部命令（原 opc/tools/）不再从这里扇出：已经烘进 agent 基础镜像，
  # 见 opc/agent/Dockerfile 末尾那段 COPY bin/ lib/ etc/。
  # 22 道题曾各存一份逐字节相同的拷贝，而拷贝在题目录里和手写文件无从区分。

  cp "$ROOT"/opc/verifier/test.sh "$dest/tests/test.sh"
  cp "$ROOT"/opc/verifier/oracle.py "$dest/tests/oracle.py"        # 差分判分骨架
  cp "$ROOT"/opc/verifier/preflight.py "$dest/tests/preflight.py"  # 预检题的公共断言
  cp "$ROOT"/opc/verifier/outbox.py "$dest/tests/outbox.py"        # 外发邮件的公共断言
  cp "$ROOT"/opc/verifier/billing.py "$dest/tests/billing.py"      # 退款动作的公共断言
  cp "$ROOT"/opc/verifier/cloud.py "$dest/tests/cloud.py"          # 云端发布的公共断言
  cp "$ROOT"/opc/verifier/task-tests.Dockerfile "$dest/tests/Dockerfile"
  chmod +x "$dest/tests/test.sh"

  # 数据源服务不在这里扇出了——四份实现烘进了 agent 基础镜像的 /opt/opc/lib，
  # 见 opc/agent/Dockerfile。以前这里按题 opt-in 拷一份、顺手改个名
  # （dws_fixture_server.py -> environment/lib/datasource_server.py），于是同一个
  # 文件在三处三个名字，从题目反查实现得先知道这张映射表。
  # 起哪些数据源改由题目的 OPC_SERVICES 声明，见 opc/agent/svc/opc-entrypoint.sh。
  #
  # 仍然要发的只有 discovery 文档：真 gam 冷启动要拉它，而容器里没有外网，
  # 所以本地留一份官方文档的副本。
  if [ -f "$task/environment/data/workspace.json" ]; then
    mkdir -p "$dest/environment/data/discovery"
    cp "$ROOT"/opc/common/fixtures/google-discovery/*.json "$dest/environment/data/discovery/"
  fi

  # agent skills：**按名字点名下发**，清单在 environment/skills.manifest，
  # 一行一个，对应 opc/common/skills/ 下的目录名。
  #
  # 以前这里写死发 obsidian，任何声明了 skills/ 的题都会收到一堆 wikilink 知识。
  # 用不上的 skill 是纯噪声，还会诱 agent 去试不存在的工具——这条和
  # opc/common/skills/README.md 里排除 defuddle/knap 是同一个理由。
  #
  # 清单放在 skills/ 外面：题目的 Dockerfile 只 COPY skills/，所以它不进容器。
  #
  # 清单里有两种条目：
  #   <目录名>              -> opc/common/skills/<目录名>，在这里拷进 environment/skills/
  #   hermes:<相对路径>     -> hermes 自带的 skill，只有镜像里才有，拷不了
  #
  # 后者为什么不在这里拷：自带 skill 在 /usr/local/lib/hermes-agent/skills/ 下，
  # 那是镜像里的东西，宿主机上根本没有；就算 vendor 一份进仓库，也会和钉死的
  # HERMES_VERSION 各自漂，成了第二份事实。所以这里只把它们**记下来**，
  # 生成一份 environment/skills.bundled，真正的安装交给题目构建期的
  # opc-install-skills（它在基础镜像里，拿得到那些文件，也验得了路径还在不在）。
  local manifest="$task/environment/skills.manifest"
  if [ -f "$manifest" ]; then
    mkdir -p "$dest/environment/skills"
    local bundled="$dest/environment/skills.bundled"
    : > "$bundled.tmp"
    while read -r skill; do
      skill="${skill%%#*}"; skill="$(echo "$skill" | tr -d '[:space:]')"
      [ -z "$skill" ] && continue
      if [ "${skill#hermes:}" != "$skill" ]; then
        # 路径合法性在这里只做最粗的一层（非空、不越级），存不存在由构建期判——
        # 宿主机上没有那棵树，在这里装作能验是自欺。
        local rel="${skill#hermes:}"
        case "$rel" in
          ""|/*|*..*)
            echo "FAIL ${task#"$ROOT/tasks/"}: skills.manifest 里 '$skill' 的路径不合法" >&2
            return 1 ;;
        esac
        echo "$skill" >> "$bundled.tmp"
        continue
      fi
      if [ ! -d "$ROOT/opc/common/skills/$skill" ]; then
        echo "FAIL ${task#"$ROOT/tasks/"}: skills.manifest 点名了 '$skill'，" \
             "但 opc/common/skills/$skill 不存在" >&2
        return 1
      fi
      # opc/common/skills/<name>/ 有两种形状，落点必须都是 HERMES_HOME/skills/<skill>/：
      #   根下有 SKILL.md  -> 它本身就是一个 skill（aliyun-cli）
      #   根下没有        -> 它是个合集，里面每个子目录才是 skill（obsidian 三件套）
      # 分不清的话 obsidian 会被多套一层，hermes 就扫不到 SKILL.md 了。
      if [ -f "$ROOT/opc/common/skills/$skill/SKILL.md" ]; then
        mkdir -p "$dest/environment/skills/$skill"
        cp -r "$ROOT/opc/common/skills/$skill/." "$dest/environment/skills/$skill/"
      else
        cp -r "$ROOT/opc/common/skills/$skill/." "$dest/environment/skills/"
      fi
    done < "$manifest"
    # 没有 hermes: 条目就不留空文件——题目 Dockerfile 里那两行也就不该出现。
    if [ -s "$bundled.tmp" ]; then
      mv "$bundled.tmp" "$bundled"
    else
      rm -f "$bundled.tmp"
    fi
  fi

  # Obsidian vault 语料：两道 contract 题共用一份，别让它长出第二份拷贝。
  if [ -d "$task/environment/vault" ]; then
    mkdir -p "$dest/environment/vault"
    cp -r "$ROOT"/opc/common/fixtures/contract-vault/. "$dest/environment/vault/"
  fi
}

failed=0
count=0
for task in "$ROOT"/tasks/*/*/*/; do
  task="${task%/}"
  [ -f "$task/task.toml" ] || continue
  name="${task#"$ROOT/tasks/"}"
  count=$((count + 1))

  if [ "$CHECK" = 1 ]; then
    tmp="$(mktemp -d)"
    if ! sync_task "$task" "$tmp"; then failed=1; rm -rf "$tmp"; continue; fi
    # 只比对同步器管的那些文件——题目自己的 test_state.py、instruction.md 不在其列。
    while IFS= read -r -d '' produced; do
      rel="${produced#"$tmp/"}"
      if ! cmp -s "$produced" "$task/$rel"; then
        if [ -e "$task/$rel" ]; then
          echo "FAIL $name/$rel: 与 opc/ 里的源文件不一致"
        else
          echo "FAIL $name/$rel: 缺这个文件"
        fi
        failed=1
      fi
    done < <(find "$tmp" -type f -print0)
    rm -rf "$tmp"
  else
    if [ -f "$task/environment/skills.manifest" ]; then
      rm -rf "$task"/environment/skills/*
      rm -f "$task/environment/skills.bundled"
    fi
    [ -d "$task/environment/vault" ] && rm -rf "$task"/environment/vault/*
    sync_task "$task" "$task" || failed=1
    echo "synced $name"
  fi
done

if [ "$CHECK" = 1 ] && [ "$failed" = 0 ]; then
  echo "OK   $count 道题的同步内容与 opc/ 一致"
fi
exit "$failed"
