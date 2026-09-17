# 非交互 bash 也会读这份（镜像里 ENV BASH_ENV 指向它），
# 而 hermes 每条命令都是一个新的 `bash -c`——所以这里挂的钩子对每条命令都生效。
#
# 唯一的钩子：命令不存在时留一行审计，然后照 bash 原样报错、原样 127 退出。
# 对 agent 来说行为与普通系统没有区别；对判分器来说，
# 「它有没有先探一下」从此是可观测的。
command_not_found_handle() {
  /opt/opc/bin/_record-missing "$1" >/dev/null 2>&1 || true
  echo "bash: $1: command not found" >&2
  return 127
}
