"""hermes 的 Harbor 适配器（opc-benchmark 自用）。

与 harbor 自带的 harbor.agents.installed.hermes 的区别：

1. **install() 不再装东西。** 官方安装脚本
   （https://hermes-agent.nousresearch.com/install.sh）在构建基础镜像时就跑完了
   （opc/agent/Dockerfile），版本由构建参数钉死。install() 只做一次存在性校验，
   镜像不对时立刻报错，而不是等到 run 中途给一段看不懂的堆栈。
   校验可以用 ``--ak assume_installed=true`` 关掉。
2. **provider 只有三个**：deepseek / antchat / local，没有 OpenRouter 兜底。
   不在表里的 provider 直接报错。见 opc/agent/providers.py。
3. **base_url 显式管理**，并且会把 localhost 改写成 host.docker.internal——
   容器里的 localhost 指向容器自己，不改写连不上宿主机的推理服务。

用法：

    harbor run -p tasks --agent opc.agent.hermes:Hermes \
      -m deepseek/deepseek-flash
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import socket
import uuid
from pathlib import Path
from typing import Annotated, Any, override

import yaml
from pydantic import Field

from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.agents.options import Cli, InstalledAgentOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.task.config import NetworkMode, NetworkPolicy
from harbor.models.trajectories import (
    Agent,
    FinalMetrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)

from opc.agent.providers import (
    DOCKER_HOST_ALIAS,
    SUPPORTED_PROVIDERS,
    NativeProvider,
    get_provider,
    provider_host,
    resolve_credentials,
)

HERMES_HOME = "/opt/hermes"
"""基础镜像里 hermes 的家目录。必须与 opc/agent/Dockerfile 一致。"""

SESSION_LOG = "/logs/agent/hermes-session.jsonl"


class HermesOptions(InstalledAgentOptions):
    toolsets: Annotated[str | None, Cli("--toolsets")] = Field(
        default=None, description="逗号分隔的 hermes toolset 名。"
    )
    max_turns: int = Field(default=90, description="agent loop 的最大轮数。")
    base_url: str | None = Field(
        default=None,
        description="覆盖该 provider 的 base_url。留空则读环境变量，再退到默认值。",
    )
    rewrite_localhost: bool = Field(
        default=True,
        description=(
            "把 base_url 里的 localhost/127.0.0.1 改写成 host.docker.internal。"
            "推理服务与 agent 在同一个容器里时设为 false。"
        ),
    )
    assume_installed: bool = Field(
        default=False,
        description="跳过 install() 的镜像自检。镜像可信且想省掉一次 exec 时用。",
    )


class Hermes(BaseInstalledAgent):
    """跑在预烘镜像里的 hermes。"""

    # harbor 0.23 的 AgentCapabilities 只有这几个字段：
    #   atif / resume / load_native_trajectory / load_atif_trajectory
    #   handoff / native_config / windows / bridges
    # 原来这里还传了 skills=True, mcp_servers=True，但 harbor 从来没有这两个字段
    # （0.20~0.22 连 AgentCapabilities 这个类都没有），pydantic 会直接拒掉。
    # 去掉声明不影响 skills 本身——skills 由 _build_register_skills_command()
    # 往 HERMES_HOME/skills 里铺，不依赖这个 capability 标志。
    capabilities = AgentCapabilities(atif=True, resume=True)

    options_model = HermesOptions
    options: HermesOptions

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._native_session_id: str | None = None
        super().__init__(*args, **kwargs)

    @staticmethod
    @override
    def name() -> str:
        return "opc-hermes"

    @override
    def get_version_command(self) -> str | None:
        return "hermes --version"

    # ------------------------------------------------------------------
    # install：不装东西，只确认镜像是对的
    # ------------------------------------------------------------------

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        """基础镜像已经带好一切，这里只做一次存在性校验。

        不装包、不联网、不写文件。镜像不对时在 setup 阶段就失败，
        比在 run 中途失败便宜得多——那时已经烧掉了任务的启动时间。
        """
        if self.options.assume_installed:
            return

        result = await environment.exec(
            command=(
                f"command -v hermes >/dev/null 2>&1 && [ -d {shlex.quote(HERMES_HOME)} ]"
            ),
        )
        if result.return_code != 0:
            raise RuntimeError(
                "环境里没有 hermes，或 HERMES_HOME 不存在。"
                "任务镜像必须 FROM opc-benchmark/hermes-base"
                "（见 opc/agent/Dockerfile，make image 构建）。"
                " 确认镜像没问题、只想省掉这次校验，可加 --ak assume_installed=true。"
            )

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def _build_config_yaml(
        self, model: str, *, provider_name: str, base_url: str
    ) -> str:
        config: dict[str, Any] = {
            # hermes v0.21.3 起 model 可以是 map。显式关流式：本地 OpenAI 兼容
            # 服务（vLLM / SGLang 等）常常不支持流式工具调用。
            "model": {"default": model, "streaming": False},
            "provider": "auto",
            "toolsets": ["hermes-cli"],
            "agent": {"max_turns": self.options.max_turns},
            "memory": {"memory_enabled": False, "user_profile_enabled": False},
            "compression": {"enabled": True, "threshold": 0.85},
            "terminal": {"backend": "local", "timeout": 180},
            "delegation": {"max_iterations": 50},
            "checkpoints": {"enabled": False},
        }
        # 端点一律写进来。local 这类没有 builtin 端点的 provider 不写就报
        # "provider 'local' has no endpoint configured"——光有环境变量不够；
        # deepseek/antchat 写的是同一个值，冗余但不会指错地方。
        config["providers"] = {provider_name: {"base_url": base_url}}
        if self.mcp_servers:
            config["mcp_servers"] = {
                server.name: (
                    {"command": server.command, "args": server.args}
                    if server.transport == "stdio"
                    else {"url": server.url}
                )
                for server in self.mcp_servers
            }
        return yaml.dump(config, default_flow_style=False, allow_unicode=True)

    def _build_register_skills_command(self) -> str | None:
        if not self.skills_dir:
            return None
        return (
            f"mkdir -p {HERMES_HOME}/skills && "
            f"cp -r {shlex.quote(self.skills_dir)}/* {HERMES_HOME}/skills/ "
            "2>/dev/null || true"
        )

    # ------------------------------------------------------------------
    # 运行
    # ------------------------------------------------------------------

    async def _probe_egress(
        self,
        environment: BaseEnvironment,
        env: dict[str, str],
        provider: NativeProvider,
        host: str,
    ) -> None:
        """OPC_DEBUG_EGRESS=1 时，从 agent 容器里探一次模型端点。

        hermes 把所有 API 失败都归成一句「can't reach the model provider」，
        分不出是 DNS 挂了、TCP 被拦了、还是 4xx/5xx。这里直接看 curl 的
        退出码和 HTTP 状态码。只在显式开关下跑，正常跑分不额外发请求。
        """
        base_url = env[provider.inject_base_url_as]
        script = (
            "echo \"--- resolv.conf\"; cat /etc/resolv.conf; "
            "echo \"--- hosts\"; grep %(host)s /etc/hosts || echo 'no pin'; "
            "echo \"--- resolve\"; getent hosts %(host)s || echo 'DNS FAILED'; "
            "echo \"--- tcp+tls\"; "
            "curl -sS -o /dev/null -m 20 "
            "-w 'http=%%{http_code} exit=%%{exitcode} err=%%{errormsg}\\n' "
            "-H \"Authorization: Bearer $%(key_var)s\" "
            "%(base_url)s/models || echo \"curl rc=$?\""
        ) % {
            "host": shlex.quote(host),
            "key_var": provider.inject_key_as,
            "base_url": shlex.quote(base_url.rstrip("/")),
        }
        try:
            result = await self.exec_as_agent(
                environment, command=script, env=env, timeout_sec=60
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("出网探针没跑成: %s", exc)
            return
        self.logger.warning("出网探针（%s）:\n%s", host, getattr(result, "stdout", result))

    HOSTS_MARKER = "# opc-model-endpoint"
    """写进 agent 容器 /etc/hosts 的标记，跑完按它删干净。"""

    async def _pin_model_endpoint_dns(
        self, environment: BaseEnvironment, host: str
    ) -> list[str]:
        """把模型端点的 IP 钉进 agent 容器的 /etc/hosts。

        为什么需要这一步：agent 容器与 egress sidecar 共享 netns，但 /etc/hosts
        和 /etc/resolv.conf 还是各自的。sidecar 的 nftables 只放行
        **sidecar 自己** resolv.conf 里那几个 nameserver（Docker 的内嵌 DNS
        127.0.0.11），而 agent 容器的 resolv.conf 指向宿主机那几个外部
        nameserver——不在放行名单里，UDP 53 被 `meta l4proto != tcp reject` 拦掉，
        于是解析直接失败，连 gost 的 SNI 白名单都走不到。

        解析放在宿主机做（那里 DNS 是通的），把结果钉进容器。之后 TCP 仍然全部
        被 redirect 到 gost，由 gost 按 SNI 对白名单做最终判定——钉 IP 不会绕过
        白名单，只是把「解析」这一步挪走。
        """
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, 443, 0, socket.SOCK_STREAM
        )
        ips = list(dict.fromkeys(info[4][0] for info in infos))
        if not ips:
            raise ValueError(f"宿主机也解析不出 {host}")

        lines = "".join(
            f"{ip}\t{host}\t{self.HOSTS_MARKER}\n" for ip in ips
        )
        await self.exec_as_root(
            environment,
            command=(
                f"cat >> /etc/hosts << 'OPCHOSTS'\n{lines}OPCHOSTS"
            ),
            timeout_sec=10,
        )
        return ips

    async def _unpin_model_endpoint_dns(self, environment: BaseEnvironment) -> None:
        with contextlib.suppress(Exception):
            await self.exec_as_root(
                environment,
                command=(
                    f"sed -i '/{self.HOSTS_MARKER}$/d' /etc/hosts"
                ),
                timeout_sec=10,
            )

    GATEWAY_MARKER = "# opc-host-gateway"
    """给 host.docker.internal 兜底时写进 /etc/hosts 的标记。"""

    # 在容器里算出「宿主机」的地址：默认路由的网关就是它。
    # 不用 `ip route`——基础镜像没装 iproute2（见 opc/agent/Dockerfile 的 apt 列表），
    # 而 python3 一定在。/proc/net/route 的 Gateway 列是小端十六进制。
    _GATEWAY_PY = (
        "import socket,struct;"
        "rows=[l.split() for l in open('/proc/net/route').read().splitlines()[1:]];"
        "gw=[r[2] for r in rows if r[1]=='00000000' and r[2]!='00000000'];"
        "print(socket.inet_ntoa(struct.pack('<L',int(gw[0],16))) if gw else '')"
    )

    async def _ensure_host_gateway(
        self, environment: BaseEnvironment, host: str
    ) -> None:
        """Linux 上给 host.docker.internal 兜底，让用户不必自己加 --add-host。

        rewrite_loopback() 把本地推理服务的 localhost 改写成了
        host.docker.internal，但**这个别名是 Docker Desktop 才自带的**。
        Linux 的 Docker 不给，要么 run 时 --add-host=host.docker.internal:host-gateway，
        要么 compose 里 extra_hosts——两条都要用户自己记得，忘了就只得到
        hermes 一句「can't reach the model provider」，看不出是 DNS 的事。

        这里改成自动：解析得出就什么都不做（Docker Desktop、或者用户已经加过），
        解析不出才按容器的默认路由网关钉一条。网关正是 host-gateway 指的那个地址。

        失败不抛：这条只是兜底，硬失败会把本来能跑的情况（别名已经有了、
        或者根本没用本地模型）一起拖死。真连不上的话，报错仍然会出现在
        hermes 那一侧，只是少了这一层帮助。
        """
        if host != DOCKER_HOST_ALIAS:
            return
        try:
            probe = await self.exec_as_root(
                environment,
                command=f"getent hosts {shlex.quote(host)} > /dev/null && echo HIT || echo MISS",
                timeout_sec=10,
            )
            if "HIT" in str(getattr(probe, "stdout", probe)):
                self.logger.debug("%s 本来就解析得出，不动 /etc/hosts", host)
                return

            result = await self.exec_as_root(
                environment,
                command=f"python3 -c {shlex.quote(self._GATEWAY_PY)}",
                timeout_sec=10,
            )
            gateway = str(getattr(result, "stdout", result)).strip().splitlines()
            gateway = gateway[-1].strip() if gateway else ""
            if not gateway:
                self.logger.warning(
                    "%s 解析不出，也没找到默认路由网关——本地模型多半连不上。"
                    " 手动补救：--add-host=%s:host-gateway",
                    host, host,
                )
                return

            await self.exec_as_root(
                environment,
                command=(
                    f"printf '%s\\t%s\\t%s\\n' {shlex.quote(gateway)} "
                    f"{shlex.quote(host)} {shlex.quote(self.GATEWAY_MARKER)} >> /etc/hosts"
                ),
                timeout_sec=10,
            )
            self.logger.debug("%s 解析不出，已钉到默认路由网关 %s", host, gateway)
        except Exception as exc:  # noqa: BLE001 - 兜底不该拖死正常路径
            self.logger.warning("给 %s 兜底失败（%s），继续跑", host, exc)

    @contextlib.asynccontextmanager
    async def _model_endpoint_reachable(
        self,
        environment: BaseEnvironment,
        env: dict[str, str],
        provider: NativeProvider,
    ):
        """临时放行模型端点，跑完恢复原策略。

        任务声明成 no-network 时——题目不该让 agent 上网找答案——hermes 自己
        跑在 agent 容器里，模型请求也要从这个容器出去，一点都不放行的话第一次
        API 调用就挂在「can't reach the model provider」上。
        题目当前默认 public，走的是下面那条早退分支；这段留着是为了改回断网时还能用。

        放行的范围是本次真正用到的那一个 provider 主机，不是整张 provider 表：
        task.toml 里不写任何 provider 主机名，换 provider 不用改题。
        """
        original = environment.network_policy
        if original.network_mode == NetworkMode.PUBLIC:
            # 已经全放开了（差分判分那类题），不用也不能收窄——
            # 全放开的环境根本没起 egress sidecar。
            yield
            return

        host = provider_host(env, provider)
        if not environment.capabilities.dynamic_network_policy:
            raise ValueError(
                f"环境 {environment.type()} 不支持运行时改网络策略，"
                f"而任务声明的是 {original.network_mode.value}——"
                f"hermes 连不上 {host}。"
                " 要么换支持的环境，要么在 task.toml 里把 [environment] 写成"
                f' network_mode = "allowlist" / allowed_hosts = ["{host}"]。'
            )

        ips = await self._pin_model_endpoint_dns(environment, host)
        await environment.set_network_policy(
            NetworkPolicy(
                network_mode=NetworkMode.ALLOWLIST, allowed_hosts=[host, *ips]
            )
        )
        self.logger.debug(
            "已放行模型端点 %s（%s），其余出网仍然封着", host, ", ".join(ips)
        )
        if os.environ.get("OPC_DEBUG_EGRESS"):
            await self._probe_egress(environment, env, provider, host)
        try:
            yield
        finally:
            # 恢复原策略，别把判分阶段也留在放行状态。
            with contextlib.suppress(Exception):
                await environment.set_network_policy(original)
            await self._unpin_model_endpoint_dns(environment)

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        if not self.model_name or "/" not in self.model_name:
            raise ValueError(
                "模型名必须是 <provider>/<model> 格式，"
                f"provider 取值：{', '.join(SUPPORTED_PROVIDERS)}"
            )

        prefix, model = self.model_name.split("/", 1)
        provider = get_provider(prefix)

        env: dict[str, str] = {
            "HERMES_HOME": HERMES_HOME,
            "TERMINAL_ENV": "local",
            "HARBOR_INSTRUCTION": instruction,
        }
        env.update(
            resolve_credentials(
                provider,
                rewrite_localhost=self.options.rewrite_localhost,
                base_url_override=self.options.base_url,
            )
        )

        cli_model = model if provider.flag else self.model_name

        # 用改写过 localhost 的端点（容器里 localhost 指向容器自己）。
        config_yaml = self._build_config_yaml(
            cli_model,
            provider_name=provider.flag or prefix,
            base_url=env[provider.inject_base_url_as],
        )

        await self.exec_as_agent(
            environment,
            command=(
                f"mkdir -p {HERMES_HOME} && "
                f"cat > {HERMES_HOME}/config.yaml << 'OPCEOF'\n"
                f"{config_yaml}OPCEOF"
            ),
            env=env,
            timeout_sec=10,
        )

        if skills_command := self._build_register_skills_command():
            await self.exec_as_agent(
                environment, command=skills_command, env=env, timeout_sec=10
            )

        # CLI 形态与 harbor 自带的 hermes 适配器保持一致：
        #   hermes --yolo chat [--resume ID] -q <prompt> -Q --model M [--provider P] [--toolsets T]
        # hermes 已 symlink 到 /usr/local/bin，不需要再 export PATH。
        cli_parts = ["hermes --yolo chat"]
        if self._resume:
            if self._native_session_id is None:
                # 上一轮没导出成会话 ID 就只能赌 latest——记一笔，
                # 否则续跑串了会话都查不出原因。
                self.logger.debug("没有原生会话 ID，--resume 回落到 latest")
            cli_parts.extend(
                ["--resume", shlex.quote(self._native_session_id or "latest")]
            )
        cli_parts.extend(
            ['-q "$HARBOR_INSTRUCTION"', "-Q", f"--model {shlex.quote(cli_model)}"]
        )
        if provider.flag:
            cli_parts.append(f"--provider {shlex.quote(provider.flag)}")
        if self.options.toolsets:
            cli_parts.append(f"--toolsets {shlex.quote(self.options.toolsets)}")

        run_cmd = (
            f"{' '.join(cli_parts)} 2>&1 | stdbuf -oL tee /logs/agent/hermes.txt"
        )

        # 在跑之前兜底解析。这一步和网络策略无关——22 道题都是 public，
        # 走不到 _model_endpoint_reachable 里那段钉 IP 的逻辑，而 Linux 上
        # host.docker.internal 照样解析不出来。
        await self._ensure_host_gateway(
            environment, provider_host(env, provider)
        )

        try:
            async with self._model_endpoint_reachable(environment, env, provider):
                await self.exec_as_agent(environment, command=run_cmd, env=env)
        finally:
            await self._export_session(environment)

    async def _export_session(self, environment: BaseEnvironment) -> None:
        """导出会话供 ATIF 转换。失败不影响判分，只是拿不到轨迹。

        **不要加 `--source cli`。** hermes 的 `sessions export` 一旦带上任何一个
        过滤条件（--source 也算），就改走 prune 那套候选查询，而那套查询第一条
        就是 ``s.ended_at IS NOT NULL``——「只挑已经结束的会话，免得删到活的」。
        `hermes chat -q ... -Q` 是一次性跑，退出时不写 ended_at，于是这条刚跑完
        的会话永远不在候选里：导出照样成功、照样打印 "Exported 0 sessions"、
        照样把文件写成 0 字节。这正是整批 trajectory 全空的原因（本地 hermes
        上可复现：带 --source 导 0 条，不带导 1 条）。

        不带过滤等于导出这个容器里的全部会话——容器是一次性的、只跑这一道题，
        所以「全部」就是「这次的」。导出按 last_active 倒序，第一行即最新一条，
        _extract_native_session_id 取它做 --resume 的锚点。

        stderr 不再吞掉：导出出问题时得在 trial.log 里看得见，而不是留下一个
        没人解释得了的空文件。
        """
        try:
            result = await self.exec_as_agent(
                environment,
                command=(
                    f"hermes sessions export {SESSION_LOG}; "
                    f"echo '--- bytes:' $(wc -c < {SESSION_LOG} 2>/dev/null || echo 0); "
                    f"head -n 1 {SESSION_LOG} 2>/dev/null || true"
                ),
                env={"HERMES_HOME": HERMES_HOME},
                timeout_sec=60,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"导出 hermes 会话失败: {exc}")
            return
        if session_id := self._extract_native_session_id(result.stdout):
            self._native_session_id = session_id
        else:
            # 空轨迹 = 这次跑没有正式证据，判分与复现都少一条腿。不能只 debug。
            self.logger.warning(
                "hermes 会话导出没拿到任何会话，trajectory 会是空的。"
                f"导出输出：{(result.stdout or '').strip()[:500]}"
            )

    # ------------------------------------------------------------------
    # 轨迹转换
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_native_session_id(export_output: str) -> str | None:
        for line in (export_output or "").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and isinstance(record.get("id"), str):
                return record["id"]
        return None

    @staticmethod
    def _text_of(content: Any) -> str:
        if isinstance(content, list):
            return " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        return str(content) if content else ""

    def _convert_session_to_atif(
        self, jsonl_text: str, session_id: str
    ) -> Trajectory | None:
        """把 hermes 的会话导出转成 ATIF。

        假定导出是 OpenAI 风格的 messages（整体一个带 messages 的对象，
        或者每行一条消息）。hermes 换了导出格式的话，改这里。
        """
        messages: list[dict[str, Any]] = []
        for line in jsonl_text.strip().split("\n"):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and "messages" in parsed:
                messages.extend(parsed["messages"])
            elif isinstance(parsed, dict):
                messages.append(parsed)

        steps: list[Step] = []
        prompt_tokens = completion_tokens = 0
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role", "")
            step_id = len(steps) + 1

            if role == "user":
                if text := self._text_of(msg.get("content")):
                    steps.append(Step(step_id=step_id, source="user", message=text))

            elif role == "assistant":
                text = self._text_of(msg.get("content"))
                tool_calls = [
                    ToolCall(
                        tool_call_id=tc.get("id", str(uuid.uuid4())[:8]),
                        function_name=tc.get("function", {}).get("name", "unknown"),
                        arguments=self._parse_arguments(
                            tc.get("function", {}).get("arguments", "")
                        ),
                    )
                    for tc in msg.get("tool_calls") or []
                ]

                if tool_calls:
                    results: list[ObservationResult] = []
                    while i + 1 < len(messages) and messages[i + 1].get("role") == "tool":
                        i += 1
                        results.append(
                            ObservationResult(
                                source_call_id=messages[i].get("tool_call_id"),
                                content=self._text_of(messages[i].get("content")) or None,
                            )
                        )
                    steps.append(
                        Step(
                            step_id=step_id,
                            source="agent",
                            message=text or "[tool call]",
                            tool_calls=tool_calls,
                            observation=Observation(results=results) if results else None,
                        )
                    )
                elif text:
                    steps.append(Step(step_id=step_id, source="agent", message=text))

                usage = msg.get("usage") or {}
                prompt_tokens += usage.get("prompt_tokens", 0)
                completion_tokens += usage.get("completion_tokens", 0)

            i += 1

        if not steps:
            return None

        return Trajectory(
            schema_version="ATIF-v1.2",
            session_id=session_id,
            agent=Agent(
                name=self.name(),
                version=self.version() or "unknown",
                model_name=self.model_name,
            ),
            steps=steps,
            final_metrics=FinalMetrics(
                total_steps=len(steps),
                total_prompt_tokens=prompt_tokens or None,
                total_completion_tokens=completion_tokens or None,
            ),
        )

    @staticmethod
    def _parse_arguments(raw: Any) -> Any:
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        session_path = self.logs_dir / "hermes-session.jsonl"
        if not session_path.exists():
            return
        try:
            trajectory = self._convert_session_to_atif(
                session_path.read_text(), str(uuid.uuid4())
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(f"转 ATIF 失败: {exc}")
            return
        if not trajectory:
            return
        (self.logs_dir / "trajectory.json").write_text(
            json.dumps(trajectory.to_json_dict(), indent=2, ensure_ascii=False)
        )
        if trajectory.final_metrics:
            context.n_input_tokens = trajectory.final_metrics.total_prompt_tokens or 0
            context.n_output_tokens = (
                trajectory.final_metrics.total_completion_tokens or 0
            )
