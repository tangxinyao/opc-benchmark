"""opc.agents.providers 的单元测试。不依赖 harbor，uv run 就能跑。"""

import pytest

from opc.agents.providers import (
    DOCKER_HOST_ALIAS,
    SUPPORTED_PROVIDERS,
    get_provider,
    resolve_credentials,
    rewrite_loopback,
)


def test_only_three_providers():
    assert set(SUPPORTED_PROVIDERS) == {"deepseek", "antchat", "local"}


def test_unknown_provider_fails_loudly():
    """不兜底到 OpenRouter——悄悄换链路等于测了个别的东西。"""
    with pytest.raises(ValueError, match="不支持的 provider"):
        get_provider("anthropic")


def test_deepseek_defaults():
    env = resolve_credentials(
        get_provider("deepseek"), getenv={"DEEPSEEK_API_KEY": "sk-x"}.get
    )
    assert env == {
        "DEEPSEEK_API_KEY": "sk-x",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    }


def test_antchat_accepts_token_alias():
    env = resolve_credentials(
        get_provider("antchat"), getenv={"ANTCHAT_TOKEN": "t-1"}.get
    )
    assert env["ANTCHAT_API_KEY"] == "t-1"
    assert env["ANTCHAT_BASE_URL"] == "https://antchat.alipay.com"


def test_missing_key_is_an_error_for_remote_providers():
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        resolve_credentials(get_provider("deepseek"), getenv={}.get)


def test_local_provider_needs_no_key():
    """本地 vLLM / Ollama 多半不校验 key，缺 key 不该拦住运行。"""
    env = resolve_credentials(get_provider("local"), getenv={}.get)
    assert "LOCAL_API_KEY" not in env
    assert env["LOCAL_BASE_URL"] == f"http://{DOCKER_HOST_ALIAS}:8000/v1"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("http://localhost:8000/v1", f"http://{DOCKER_HOST_ALIAS}:8000/v1"),
        ("http://127.0.0.1:11434", f"http://{DOCKER_HOST_ALIAS}:11434"),
        ("http://0.0.0.0/v1", f"http://{DOCKER_HOST_ALIAS}/v1"),
        # 非回环地址原样保留
        ("https://api.deepseek.com", "https://api.deepseek.com"),
        ("http://10.0.0.7:8000/v1", "http://10.0.0.7:8000/v1"),
    ],
)
def test_rewrite_loopback(given, expected):
    assert rewrite_loopback(given) == expected


def test_rewrite_can_be_disabled():
    """推理服务和 agent 在同一个容器里时，localhost 才是对的。"""
    env = resolve_credentials(
        get_provider("local"), rewrite_localhost=False, getenv={}.get
    )
    assert env["LOCAL_BASE_URL"] == "http://localhost:8000/v1"


def test_explicit_base_url_wins_over_env():
    env = resolve_credentials(
        get_provider("local"),
        base_url_override="http://localhost:9000/v1",
        getenv={"LOCAL_BASE_URL": "http://ignored:1/v1"}.get,
    )
    assert env["LOCAL_BASE_URL"] == f"http://{DOCKER_HOST_ALIAS}:9000/v1"
