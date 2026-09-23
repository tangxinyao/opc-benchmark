"""opc.agent.providers 的单元测试。不依赖 harbor，uv run 就能跑。"""

import pytest

from opc.agent.providers import (
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
    assert "LM_API_KEY" not in env
    assert env["LM_BASE_URL"] == f"http://{DOCKER_HOST_ALIAS}:8000/v1"


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
    assert env["LM_BASE_URL"] == "http://localhost:8000/v1"


def test_explicit_base_url_wins_over_env():
    env = resolve_credentials(
        get_provider("local"),
        base_url_override="http://localhost:9000/v1",
        getenv={"LOCAL_BASE_URL": "http://ignored:1/v1"}.get,
    )
    assert env["LM_BASE_URL"] == f"http://{DOCKER_HOST_ALIAS}:9000/v1"


def test_local_injects_hermes_native_env_names():
    """hermes v0.21.3 的 CLI 只认 LM_BASE_URL / LM_API_KEY。"""
    env = resolve_credentials(
        get_provider("local"), getenv={"LOCAL_API_KEY": "k"}.get
    )
    assert env["LM_API_KEY"] == "k"
    assert "LOCAL_BASE_URL" not in env


# --- host.docker.internal 的兜底：容器里怎么算出宿主机地址 -------------------
# Linux 的 Docker 不给 host.docker.internal 这个别名，适配器解析不出时会按
# 容器的默认路由网关钉一条。那段代码是要塞进容器 python3 -c 跑的字符串，
# 这里连同解析逻辑一起验——写错了只会在真跑本地模型时才炸，而那时候
# 报错长在 hermes 那一侧，看不出是这里的事。

import builtins
import io

from opc.agent.hermes import Hermes

# /proc/net/route 的真实形状：Gateway 列是小端十六进制。
# 第一条是 172.17.0.1 的默认路由（Destination 全 0），第二条是同网段直连路由
# （Gateway 全 0，不能当网关用）。
_ROUTE_TABLE = (
    "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
    "eth0\t00000000\t010011AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
    "eth0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"
)


def _run_gateway_snippet(route_table: str, monkeypatch) -> str:
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/proc/net/route":
            return io.StringIO(route_table)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    printed: list[str] = []
    namespace = {"print": printed.append}
    exec(Hermes._GATEWAY_PY.replace(";", "\n"), namespace)  # noqa: S102
    return printed[-1]


def test_gateway_snippet_reads_the_default_route(monkeypatch):
    assert _run_gateway_snippet(_ROUTE_TABLE, monkeypatch) == "172.17.0.1"


def test_gateway_snippet_is_empty_without_a_default_route(monkeypatch):
    """没有默认路由时要回空串，不能抛——调用方按空串走告警分支。"""
    only_direct = "\n".join(_ROUTE_TABLE.splitlines()[:1] + [_ROUTE_TABLE.splitlines()[2]]) + "\n"
    assert _run_gateway_snippet(only_direct, monkeypatch) == ""
