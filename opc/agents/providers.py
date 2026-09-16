"""hermes 的 provider 路由表。

只支持三个 provider，没有 OpenRouter 兜底——不在表里的直接报错，
而不是悄悄换一条我们没打算测的链路。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

# 容器里的 localhost 是容器自己，不是宿主机。指向本机服务时要换成这个。
DOCKER_HOST_ALIAS = "host.docker.internal"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


@dataclass(frozen=True)
class NativeProvider:
    """一个 provider 的全部路由信息。"""

    # 传给 hermes 的 --provider 值；None 表示不传该 flag，用 provider/model 全名。
    flag: str | None
    # API key 环境变量候选，按顺序取第一个有值的。
    key_names: tuple[str, ...]
    # base_url 的环境变量名，以及取不到时的默认值。
    base_url_env: str
    default_base_url: str
    # 注入容器时 base_url 用哪个变量名（hermes 读这个）。
    inject_base_url_as: str
    # 注入容器时 api key 用哪个变量名。
    inject_key_as: str
    # 本地推理服务通常不校验 key，缺 key 不该拦住运行。
    requires_key: bool = True
    extra_env: dict[str, str] = field(default_factory=dict)


_NATIVE_PROVIDERS: dict[str, NativeProvider] = {
    "deepseek": NativeProvider(
        flag="deepseek",
        key_names=("DEEPSEEK_API_KEY",),
        base_url_env="DEEPSEEK_BASE_URL",
        default_base_url="https://api.deepseek.com",
        inject_base_url_as="DEEPSEEK_BASE_URL",
        inject_key_as="DEEPSEEK_API_KEY",
    ),
    "antchat": NativeProvider(
        flag="antchat",
        key_names=("ANTCHAT_API_KEY", "ANTCHAT_TOKEN"),
        base_url_env="ANTCHAT_BASE_URL",
        default_base_url="https://antchat.alipay.com",
        inject_base_url_as="ANTCHAT_BASE_URL",
        inject_key_as="ANTCHAT_API_KEY",
    ),
    "local": NativeProvider(
        flag="local",
        key_names=("LOCAL_API_KEY", "OPENAI_API_KEY"),
        base_url_env="LOCAL_BASE_URL",
        default_base_url="http://localhost:8000/v1",
        inject_base_url_as="LOCAL_BASE_URL",
        inject_key_as="LOCAL_API_KEY",
        # 本地 vLLM / SGLang / Ollama 多半不校验 key。
        requires_key=False,
    ),
}

SUPPORTED_PROVIDERS = tuple(_NATIVE_PROVIDERS)


def get_provider(prefix: str) -> NativeProvider:
    try:
        return _NATIVE_PROVIDERS[prefix]
    except KeyError:
        raise ValueError(
            f"不支持的 provider: {prefix!r}。"
            f"本适配器只路由 {', '.join(SUPPORTED_PROVIDERS)}，没有 OpenRouter 兜底。"
            " 模型名格式：<provider>/<model>。"
        ) from None


def rewrite_loopback(base_url: str, host_alias: str = DOCKER_HOST_ALIAS) -> str:
    """把 localhost / 127.0.0.1 换成容器能解析到宿主机的别名。

    容器里的 localhost 指向容器自己，直接透传会连不上宿主机上的推理服务。
    换掉之后，Docker 环境还需要 --add-host=host.docker.internal:host-gateway
    （Docker Desktop 自带，Linux 上要显式加）。
    """
    parsed = urlparse(base_url)
    if parsed.hostname not in _LOOPBACK_HOSTS:
        return base_url
    netloc = host_alias if parsed.port is None else f"{host_alias}:{parsed.port}"
    if parsed.username:
        credentials = parsed.username
        if parsed.password:
            credentials = f"{credentials}:{parsed.password}"
        netloc = f"{credentials}@{netloc}"
    return urlunparse(parsed._replace(netloc=netloc))


def resolve_credentials(
    provider: NativeProvider,
    *,
    rewrite_localhost: bool = True,
    base_url_override: str | None = None,
    getenv=os.environ.get,
) -> dict[str, str]:
    """从宿主机环境解析出要注入容器的 env。"""
    env: dict[str, str] = {}

    key = next((v for name in provider.key_names if (v := getenv(name))), None)
    if key:
        env[provider.inject_key_as] = key
    elif provider.requires_key:
        raise ValueError(
            "没找到 API key，请设置 " + " 或 ".join(provider.key_names) + "。"
        )

    base_url = (
        base_url_override
        or getenv(provider.base_url_env)
        or provider.default_base_url
    )
    if rewrite_localhost:
        base_url = rewrite_loopback(base_url)
    env[provider.inject_base_url_as] = base_url
    env.update(provider.extra_env)
    return env
