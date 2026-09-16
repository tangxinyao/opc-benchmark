"""hermes 的 Harbor 适配器（opc-benchmark 自用）。

与 harbor 自带的 harbor.agents.installed.hermes 的区别：

1. **install() 不再装东西。** hermes、uv、ripgrep 等全部预先烘进基础镜像
   （images/hermes-base/Dockerfile），install() 只做一次存在性校验，
   镜像不对时立刻报错，而不是等到 run 中途给一段看不懂的堆栈。
   校验可以用 ``--ak assume_installed=true`` 关掉。
2. **provider 只有三个**：deepseek / antchat / local，没有 OpenRouter 兜底。
   不在表里的 provider 直接报错。见 opc_agents/providers.py。
3. **base_url 显式管理**，并且会把 localhost 改写成 host.docker.internal——
   容器里的 localhost 指向容器自己，不改写连不上宿主机的推理服务。

用法：

    harbor run -p tasks --agent opc_agents.hermes:Hermes \
      -m deepseek/deepseek-chat
"""

from __future__ import annotations

import json
import shlex
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
from harbor.models.trajectories import (
    Agent,
    FinalMetrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)

from opc_agents.providers import SUPPORTED_PROVIDERS, get_provider, resolve_credentials

HERMES_HOME = "/opt/hermes"
"""基础镜像里 hermes 的家目录。必须与 images/hermes-base/Dockerfile 一致。"""

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

    capabilities = AgentCapabilities(
        atif=True, resume=True, skills=True, mcp_servers=True
    )

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
        return "hermes version"

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
                "（见 images/hermes-base/Dockerfile，make image 构建）。"
                " 确认镜像没问题、只想省掉这次校验，可加 --ak assume_installed=true。"
            )

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def _build_config_yaml(self, model: str) -> str:
        config: dict[str, Any] = {
            "model": model,
            "provider": "auto",
            "toolsets": ["hermes-cli"],
            "agent": {"max_turns": self.options.max_turns},
            "memory": {"memory_enabled": False, "user_profile_enabled": False},
            "compression": {"enabled": True, "threshold": 0.85},
            "terminal": {"backend": "local", "timeout": 180},
            "delegation": {"max_iterations": 50},
            "checkpoints": {"enabled": False},
        }
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

        await self.exec_as_agent(
            environment,
            command=(
                f"mkdir -p {HERMES_HOME} && "
                f"cat > {HERMES_HOME}/config.yaml << 'OPCEOF'\n"
                f"{self._build_config_yaml(cli_model)}OPCEOF"
            ),
            env=env,
            timeout_sec=10,
        )

        if skills_command := self._build_register_skills_command():
            await self.exec_as_agent(
                environment, command=skills_command, env=env, timeout_sec=10
            )

        cli_parts = ["hermes --yolo chat"]
        if self._resume:
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

        try:
            await self.exec_as_agent(environment, command=run_cmd, env=env)
        finally:
            await self._export_session(environment)

    async def _export_session(self, environment: BaseEnvironment) -> None:
        """导出会话供 ATIF 转换。失败不影响判分，只是拿不到轨迹。"""
        try:
            result = await self.exec_as_agent(
                environment,
                command=(
                    f"hermes sessions export {SESSION_LOG} --source cli 2>/dev/null && "
                    f"head -n 1 {SESSION_LOG} || true"
                ),
                env={"HERMES_HOME": HERMES_HOME},
                timeout_sec=30,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(f"导出 hermes 会话失败: {exc}")
            return
        if session_id := self._extract_native_session_id(result.stdout):
            self._native_session_id = session_id

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
