"""内部工具的调用审计。合规要求：涉及客户数据或对外动作的命令都要留痕。

留痕会落盘并被收走，所以凭证不能原样写进去——命令行里出现的密钥一律打码。
"""
import json
import os
import re
import stat
import sys
import time

AUDIT_PATH = os.environ.get("OPC_AUDIT_LOG", "/var/lib/opc/audit.log")

# 紧跟在这些参数名后面的值是凭证
SECRET_FLAG_RE = re.compile(
    r"^--?[\w-]*(key|secret|token|password|passwd|credential|ak|sk)[\w-]*$",
    re.IGNORECASE,
)
# --key=value / KEY=value 这种一体式写法
INLINE_SECRET_RE = re.compile(
    r"^(--?[\w-]*(?:key|secret|token|password|passwd|credential|ak|sk)[\w-]*|"
    r"[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)[A-Z_]*)=(.+)$",
    re.IGNORECASE,
)
# 裸露的长串凭证（阿里云 AK、sk- 开头的 API key 等）
BARE_SECRET_RE = re.compile(r"^(sk-|LTAI)[A-Za-z0-9_\-]{8,}$")

MASK = "***REDACTED***"


def redact(args):
    """把 argv 里的凭证打码。宁可多打，审计日志不需要精确到参数值。"""
    out = []
    mask_next = False
    for arg in args:
        arg = str(arg)
        if mask_next:
            out.append(MASK)
            mask_next = False
            continue
        if SECRET_FLAG_RE.match(arg):
            out.append(arg)
            mask_next = True
            continue
        # 这些脚本也会在宿主机上被 smoke.sh 直接调用，别用太新的语法
        match = INLINE_SECRET_RE.match(arg)
        if match:
            out.append("{0}={1}".format(match.group(1), MASK))
            continue
        if BARE_SECRET_RE.match(arg):
            out.append(MASK)
            continue
        out.append(arg)
    return out


AUDIT_PIPE = os.environ.get("OPC_AUDIT_PIPE", "/var/lib/opc/audit.pipe")

# 一次 write 不超过 PIPE_BUF 才是原子的，超了会和并发的写交错。
# 审计只是留痕，宁可截断也不要串行——超长的参数留个尾巴标记即可。
PIPE_BUF = 4096
TRUNCATED = "…[truncated]"


def _emit(line: str) -> None:
    """优先写 FIFO：agent 只写不读，收集器在另一侧追加到它碰不到的日志里。
    这样 agent 伪造得了多余的行，却删不掉已经写进去的行——
    而轨迹负断言（「不得调用某工具」）恰恰只怕删。

    FIFO 不在（宿主机上直接跑 smoke、或老镜像）时回落到直接追加文件。
    """
    data = line.encode("utf-8")
    if len(data) > PIPE_BUF - 1:
        data = data[: PIPE_BUF - 1 - len(TRUNCATED.encode())] + TRUNCATED.encode() + b"\n"
    try:
        if stat.S_ISFIFO(os.stat(AUDIT_PIPE).st_mode):
            fd = os.open(AUDIT_PIPE, os.O_WRONLY)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
            return
    except (OSError, ValueError):
        pass
    with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
        fh.write(data.decode("utf-8"))


def record(tool: str, args, ok: bool = True, extra=None) -> None:
    event = {
        "ts": time.time(),
        "tool": tool,
        "args": redact(args),
        "ok": ok,
    }
    if extra:
        event.update(extra)
    _emit(json.dumps(event, ensure_ascii=False) + "\n")


def main(tool: str, handler) -> None:
    args = sys.argv[1:]
    try:
        out = handler(args)
        record(tool, args, ok=True)
        if out:
            print(out)
    except Exception as exc:  # noqa: BLE001
        # 异常信息也可能带上凭证，同样过一遍打码
        record(tool, args, ok=False, extra={"error": " ".join(redact(str(exc).split()))})
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
