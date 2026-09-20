"""把 datasources/ 下的服务当模块加载。

那几个文件是脚本（`python xxx_fixture_server.py` 起服务），不在包里，
所以按路径加载。审计路径是模块级常量，加载完直接改掉——
测试要看的正是它写下的那几行。
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASOURCES = ROOT / "opc/agent/datasources"


def load(name: str, server_log: Path):
    path = DATASOURCES / f"{name}_fixture_server.py"
    spec = importlib.util.spec_from_file_location(f"_opc_{name}_fixture", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.SERVER_LOG = str(server_log)
    return module


def events(server_log: Path) -> list:
    if not Path(server_log).exists():
        return []
    return [json.loads(line)
            for line in Path(server_log).read_text(encoding="utf-8").splitlines()
            if line.strip()]
