#!/bin/bash
# 构建期用真 git 造出 /app/repo：四个 commit 压在 v1.4.0 之后。
# 时间、作者、提交信息全部写死——发版说明里的数是要被精确比对的，
# 造仓库这一步只要有一点随机，判分器的尺子就飘了。
set -euo pipefail

export GIT_AUTHOR_NAME="tangxinyao" GIT_AUTHOR_EMAIL="dev@example.com"
export GIT_COMMITTER_NAME="tangxinyao" GIT_COMMITTER_EMAIL="dev@example.com"

mkdir -p /app/repo && cd /app/repo
git init -q -b main
git config user.name tangxinyao
git config user.email dev@example.com

commit() {  # commit <日期> <信息> <文件> <内容>
  mkdir -p "$(dirname "$3")"   # src/ 这类子目录得先有，否则重定向直接 No such file
  echo "$4" >> "$3"
  git add -A
  GIT_AUTHOR_DATE="$1 +0800" GIT_COMMITTER_DATE="$1 +0800" git commit -q -m "$2"
}

commit "2026-08-20 10:12:00" "feat: 弹幕礼物连击的合并结算"       src/gift.py    "def combo(): ..."
commit "2026-08-22 16:40:00" "fix: 主播离线时结算任务不再重复入队" src/settle.py  "def settle(): ..."
git tag -a v1.4.0 -m "v1.4.0" 2>/dev/null || git tag v1.4.0

commit "2026-09-02 11:05:00" "feat: 开发者后台支持导出月度结算明细" src/export.py  "def export(): ..."
commit "2026-09-05 09:30:00" "fix: 修正通道费按 3% 计算时的四舍五入" src/fee.py     "def fee(): ..."
commit "2026-09-09 14:22:00" "chore: 依赖升级与构建脚本清理"        build.sh       "make all"
commit "2026-09-11 17:48:00" "fix: 导出明细在跨月边界上漏一天"      src/export.py  "def export_v2(): ..."
