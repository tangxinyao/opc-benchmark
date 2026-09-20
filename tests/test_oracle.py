"""差分判分骨架：判分器自己坏了，不能记成 agent 的 0 分。"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_oracle(monkeypatch, tmp_path, fake=None):
    monkeypatch.setenv("OPC_VERIFIER_LOG_DIR", str(tmp_path / "logs"))
    if fake is not None:
        path = tmp_path / "fake.json"
        path.write_text(json.dumps(fake), encoding="utf-8")
        monkeypatch.setenv("OPC_ORACLE_FAKE", str(path))
    else:
        monkeypatch.delenv("OPC_ORACLE_FAKE", raising=False)
    spec = importlib.util.spec_from_file_location(
        "oracle", ROOT / "opc" / "per-task" / "verifier" / "oracle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fake_mode_lets_us_test_without_credentials(monkeypatch, tmp_path):
    oracle = load_oracle(monkeypatch, tmp_path, fake={"net_cny": 90000})
    assert oracle.oracle("net_cny", lambda: pytest.fail("不该调真 API")) == 90000


def test_api_failure_exits_with_infra_code(monkeypatch, tmp_path):
    """真 API 调不通 -> 整场判分以 99 退出，test.sh 据此不写 reward。"""
    oracle = load_oracle(monkeypatch, tmp_path)

    def boom():
        raise ConnectionError("限流了")

    with pytest.raises(BaseException) as excinfo:
        oracle.oracle("net_cny", boom, retries=0)
    assert getattr(excinfo.value, "returncode", None) == oracle.INFRA_EXIT_CODE


def test_retries_then_succeeds(monkeypatch, tmp_path):
    """网络抖动要吃掉，别摊进分数的方差里。"""
    oracle = load_oracle(monkeypatch, tmp_path)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise TimeoutError("抖了一下")
        return 90000

    assert oracle.oracle("net_cny", flaky, retries=2, backoff_sec=0) == 90000
    assert len(calls) == 2


def test_oracle_value_is_logged_for_postmortem(monkeypatch, tmp_path):
    """出了假阴性，没有判分器当时拿到的真值就没法复盘。"""
    oracle = load_oracle(monkeypatch, tmp_path)
    oracle.oracle("net_cny", lambda: 12345.67)
    entries = json.loads(
        (tmp_path / "logs" / "oracle.json").read_text(encoding="utf-8")
    )
    assert entries[-1]["name"] == "net_cny"
    assert entries[-1]["value"] == 12345.67


def test_missing_credentials_is_infra_not_agent_failure(monkeypatch, tmp_path):
    oracle = load_oracle(monkeypatch, tmp_path)
    monkeypatch.delenv("OPC_FAKE_AK", raising=False)
    with pytest.raises(oracle.InfraError, match="缺少凭证"):
        oracle.credentials("OPC_FAKE_AK")


def test_close_enough_tolerates_cents(monkeypatch, tmp_path):
    oracle = load_oracle(monkeypatch, tmp_path)
    assert oracle.close_enough(90000.004, 90000)
    assert not oracle.close_enough(90000.5, 90000)
