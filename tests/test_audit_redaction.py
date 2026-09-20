"""审计日志的凭证打码。接 .env / 真实 AK 之前这是硬前提。

审计日志会被当 artifact 收走，argv 原样落盘意味着用户的 AK 跟着跑分结果一起走。
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("OPC_AUDIT_LOG", str(tmp_path / "audit.log"))
    spec = importlib.util.spec_from_file_location(
        "opc_internal.audit", ROOT / "opc" / "agent" / "pylib" / "opc_internal" / "audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("argv,leaked", [
    (["--access-key", "LTAI5tFakeFakeFake"], "LTAI5tFakeFakeFake"),
    (["--secret", "hunter2hunter2"], "hunter2hunter2"),
    (["--api-token=abcdef123456"], "abcdef123456"),
    (["DEEPSEEK_API_KEY=sk-livekey000000"], "sk-livekey000000"),
    (["send", "sk-barekey0000000"], "sk-barekey0000000"),
    (["--password", "p@ssw0rd!"], "p@ssw0rd!"),
])
def test_secrets_never_reach_the_log(monkeypatch, tmp_path, argv, leaked):
    audit = load_audit(monkeypatch, tmp_path)
    audit.record("rules", argv)
    written = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert leaked not in written, f"凭证泄漏进审计日志: {written}"
    assert audit.MASK in written


def test_ordinary_args_survive(monkeypatch, tmp_path):
    """打码不能把正常参数也吃掉，否则轨迹判分就废了。"""
    audit = load_audit(monkeypatch, tmp_path)
    audit.record("rules", ["show", "danmu-live", "--at", "2026-09-01"])
    event = json.loads((tmp_path / "audit.log").read_text(encoding="utf-8"))
    assert event["args"] == ["show", "danmu-live", "--at", "2026-09-01"]
    assert event["tool"] == "rules"


def test_error_text_is_redacted_too(monkeypatch, tmp_path):
    """异常信息常把整条请求回显出来，凭证会从这里漏。"""
    audit = load_audit(monkeypatch, tmp_path)
    audit.record("rules", [], ok=False,
                 extra={"error": " ".join(audit.redact(
                     "auth failed for sk-leakedfromerror".split()))})
    written = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert "sk-leakedfromerror" not in written
