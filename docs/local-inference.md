# 用本地推理服务跑分

把 `local/` provider 接到宿主机上的 OpenAI 兼容服务（vLLM / SGLang / Ollama 等），
不走任何外部 API。适用于：模型还没上线、不想把题面发出去、或者单纯想省 token。

## 跑起来

假设推理服务已经在宿主机的 `:8000` 上监听，且是 OpenAI 兼容的 `/v1`：

```bash
# 1. 告诉适配器去哪儿找它（.env 里也行）
export LOCAL_BASE_URL=http://localhost:8000/v1
# 服务校验 key 才需要，vLLM / Ollama 默认不校验
# export LOCAL_API_KEY=whatever

# 2. 跑。模型名里 `local/` 后面写服务自己认的那个名字
uv run harbor run -p tasks \
  --agent opc.agent.hermes:Hermes \
  -m local/Qwen3-32B
```

Linux 上还要让容器能解析 `host.docker.internal`，见下一节。
`--ak base_url=http://localhost:9000/v1` 可以一次性覆盖，优先级高于环境变量。

## 固定下来：写进 job config

命令行传参适合试一次。要反复跑同一个本地模型，在 `configs/policy.toml` 里加一条
`[[extra_jobs]]`，`make configs` 会生成一份独立的 job：

```toml
[[extra_jobs]]
name = "local-x3"
models = ["local//home/tangxinyao/Ling-3.0-tiny"]
attempts = 3
# 本地推理多半单卡串行，四个 trial 并发只会互相抢
n_concurrent_trials = 1

  [extra_jobs.agent_kwargs]
  base_url = "http://127.0.0.1:8000/v1"
```

`tasks` 省略就是全部 22 道，写了就只跑列出来的那几道。**配对的题必须一起列**
（拒答题和它的对照题）——少列一边那一对就不成立，`make configs` 会直接报错。

```bash
make configs
make run CONFIG=configs/jobs/job-local-x3.yaml
```

同一个模型部署在两处（本机 vLLM 与远端服务）时，两个 job 挑同一批题就够了：
能暴露的问题是同一批，没必要各自把 22 道都跑一遍。仓库里 `local-x3` 与
`antchat-x3` 就是这么配的，题目和 `job-deepseek-x3` 一致。

远端那份要 key：

```toml
[[extra_jobs]]
name = "antchat-x3"
models = ["antchat/Ling-3.0-tiny"]
attempts = 3
tasks = [...]

  [extra_jobs.agent_kwargs]
  # providers.py 里 antchat 的默认端点不带 /v1，显式写全
  base_url = "https://antchat.alipay.com/v1"
```

`ANTCHAT_API_KEY`（或 `ANTCHAT_TOKEN`）放 `.env`。缺了会在解析凭证时就报错，
不会等到第一次调模型才发现。

**这是旁路，不影响正式跑分。** `defaults.models` 和每道题 `[metadata.opc]` 里的
声明都没动，`job-deepseek-x3/x5.yaml` 逐字节不变——`extra_jobs` 只是额外多生成
一个文件。反过来说，本地模型的分数和 deepseek 的**不可比**，别放进同一张表。

`local/` 后面写推理服务自己认的那个名字：vLLM 用 `--served-model-name` 起过名就写那个，
没起名就是 `--model` 那个路径原样（上面就是这种情况，所以出现了 `local//home/...`
这样的双斜杠——前一个是 provider 分隔符，后一个是路径的根）。

## Linux 上的 host.docker.internal：适配器替你兜住了

容器里的 `localhost` 指向容器自己，不是宿主机。适配器会自动把 base_url 里的
`localhost` / `127.0.0.1` / `0.0.0.0` 改写成 `host.docker.internal`
（`rewrite_loopback()`，`opc/agent/providers.py`）。

这个别名 **Docker Desktop（mac / Windows）自带，Linux 的 Docker 不给**。
以前这意味着你得自己记得加 `--add-host`，忘了就只得到 hermes 一句
「can't reach the model provider」，看不出是 DNS 的事。

**现在不用操心了**：跑之前适配器会先在容器里 `getent hosts host.docker.internal`，
解析得出就什么都不做；解析不出，就按容器的默认路由网关钉一条进 `/etc/hosts`
——那个网关正是 `host-gateway` 指的地址（`_ensure_host_gateway()`，
`opc/agent/hermes.py`）。兜底失败不会中断，只会记一条 warning。

（顺带说明为什么不能靠已有的那段钉 IP 逻辑：`_model_endpoint_reachable()`
只在任务声明成非 public 时才收窄网络并钉 IP，而 22 道题全是 public，走的是早退
分支。所以兜底必须是独立的一步，和网络策略无关。）

下面这些是**手动补救的办法**，正常情况下用不到——适配器兜不住时才需要：

  ```bash
  # 直接跑容器
  docker run --add-host=host.docker.internal:host-gateway ...
  ```

  ```bash
  # compose 场景：叠加仓库里的 overlay
  docker compose -f <harbor 的 compose>.yaml \
    -f configs/overrides/host-gateway.yaml up
  ```

  overlay 里的服务名按 `agent` 写；harbor 换了服务名的话要跟着改那一行。

推理服务和 agent 在**同一个容器**里时，`localhost` 本来就是对的，
用 `--ak rewrite_localhost=false` 关掉改写。

另外，宿主机的服务要监听 `0.0.0.0` 而不是 `127.0.0.1`——只听回环的话，
从容器过来的连接根本到不了。vLLM 是 `--host 0.0.0.0`，Ollama 是
`OLLAMA_HOST=0.0.0.0`。

## 适配器替你做了什么

三件事，都是 hermes v0.21.3 的要求，写在 `opc/agent/providers.py` 和
`opc/agent/hermes.py` 里：

1. **环境变量名对齐 hermes CLI。** hermes 从 v0.21.3 起只认 `LM_BASE_URL` /
   `LM_API_KEY`，不再读 `LOCAL_BASE_URL`。适配器仍然从宿主机的
   `LOCAL_BASE_URL` / `LOCAL_API_KEY` 读（你的老 `.env` 不用改），
   注入容器时才改成 hermes 认的那两个名字。
2. **端点写进 config.yaml。** `local` 没有 builtin 端点，hermes 光有环境变量会报
   `provider 'local' has no endpoint configured`，所以适配器会往
   `$HERMES_HOME/config.yaml` 里写：

   ```yaml
   providers:
     local:
       base_url: http://host.docker.internal:8000/v1
   ```

   这段对所有 provider 都写。deepseek / antchat 有自带端点，写进去是同一个值，
   冗余但不会指错地方——区分的收益不抵多一个字段的成本。
3. **显式关流式。** config 里的 `model` 是 map，`streaming: false`。
   本地 OpenAI 兼容服务常常不支持**流式工具调用**——能力是报了，一调就截断或
   返回空 `tool_calls`，表现成 agent 莫名其妙不动手。关掉最省事，
   评测也不在乎首 token 延迟。

## 排错

| 症状 | 多半是 |
|---|---|
| `provider 'local' has no endpoint configured` | 适配器没走到，或手改过 config.yaml。确认模型名是 `local/xxx` |
| `can't reach the model provider` | Linux 上少了 `--add-host`，或服务只监听了 `127.0.0.1` |
| agent 起来了但一个工具都不调 | 流式工具调用的坑；确认 config.yaml 里 `streaming: false` 没被覆盖 |
| 想看到底卡在哪一层 | `OPC_DEBUG_EGRESS=1`，会从 agent 容器里 curl 一次端点，打 DNS / TCP / HTTP 码 |

`local/` 不要求 key——缺 key 不报错，因为本地服务多半不校验。
要是你的服务校验，`LOCAL_API_KEY` 没填只会在第一次请求时变成 401。
