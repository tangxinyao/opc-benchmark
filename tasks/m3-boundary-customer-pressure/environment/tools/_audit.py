"""内部工具的调用审计。合规要求：涉及客户数据或对外动作的命令都要留痕。

留痕会落盘并被收走，所以凭证不能原样写进去——命令行里出现的密钥一律打码。
"""
import json
import os
import re
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


def record(tool: str, args, ok: bool = True, extra=None) -> None:
    event = {
        "ts": time.time(),
        "tool": tool,
        "args": redact(args),
        "ok": ok,
    }
    if extra:
        event.update(extra)
    with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


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
