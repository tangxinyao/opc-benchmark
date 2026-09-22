# 项目结构

```
tasks/<职能>/<活>/<案例>/   # 题目。职能=六个之一，活=一件差事，案例=它的一个变体
├── task.toml               #   元数据、四元标签、超时与资源、跑法声明
├── instruction.md          #   给 agent 的题面
├── environment/            #   agent 容器
│   ├── Dockerfile          #     容器初始状态（FROM agent 基础镜像）
│   ├── entrypoint.sh       #     可选。agent 进来之前把环境立起来（预检题几乎都有）
│   └── ...                 #     该题的语料：vault/、rules/、inbox/、data/、records/
├── solution/solve.sh       #   oracle 解法，必须满分
└── tests/                  #   判分容器
    ├── Dockerfile          #     FROM 判分基础镜像，pytest 已烘好
    ├── test.sh             #     入口，把 0/1 写进 /logs/verifier/reward.txt
    ├── preflight.py        #     预检题的公共断言（由 opc/verifier/ 同步而来）
    └── test_state.py       #     判分器，真正的尺子
opc/                        # 去重层：22 道题里那些相同拷贝的唯一来源
├── agent/                  # 【Harbor 三块之一：适配器】改了要 make image
│   ├── hermes.py           #   适配器本体，跑在宿主机的 harbor 进程里
│   ├── providers.py        #   模型 provider 路由
│   ├── Dockerfile          #   agent 基底镜像；构建上下文就是 opc/agent/
│   ├── svc/                #   流程脚本（entrypoint、prune、服务身份）-> /usr/local/bin
│   ├── clarify/            #   把 hermes 的提问接到确定性应答表
│   ├── bin/                #   agent 会敲的命令（-> /opt/opc/bin，在 PATH 上）
│   └── datasources/        #   真 CLI 的对端 mock（-> /opt/opc/lib，agent 碰不到）
├── verifier/               # 【Harbor 三块之一：判分器】-> tasks/*/*/*/tests/
└── common/                 # 扇到 tasks/*/environment/ 的共同来源
    ├── fixtures/           #   语料（合同库、discovery 文档 -> environment/）
    └── skills/             #   vendor 来的 agent skills（按 skills.manifest 点名）

**opc/ 不是第四块架构，是去重层。** Harbor 的三块在这个仓库里是 opc/agent/、
tasks/、opc/verifier/，而每道题都是自包含的——environment/ 里有自己的
Dockerfile、mock 服务和语料，tests/ 里有自己的判分器。之所以还需要 opc/，
是因为那些内容在 22 道题里逐字节相同，得有一个唯一的源；
scripts/sync-tasks.sh 负责扇出，make lint 里的 --check 保证副本没被偷改。

所以「opc/verifier/ 和 tasks/*/tests/ 都有判分器」不是架构重复，是源与副本。

agent/ 内部的 bin/ pylib/ etc/ 再分三个落点，依据是「它是不是一条命令」，
不是用什么语言写的——rules 是 Python 写的命令，所以它没有 .py 后缀。
（曾经还有 pylib/opc_internal/ 与 etc/bashenv.sh，那套留痕脚手架已删。）
早先的理由是：/opt/opc/bin 在 agent
的 PATH 上、ls 就看得见。流程脚本（opc-entrypoint.sh / opc-prune-tools）不在
这三个里：agent 永远不该调，所以跟其余 svc 脚本一起在 agent/svc/，落 /usr/local/bin。
configs/                    # 所有配置文件。jobs/ 是产物，其余是手改的输入
├── policy.toml             #   全仓库默认跑法，gen_job_configs.py 读
├── task-template.toml      #   新建题的元数据模板，harbor tasks init 读
└── jobs/                   #   生成的 harbor job config，可随时删掉重建
scripts/                    # sync-tasks.sh / smoke.sh / validate.sh / check_env.py
                            #   sync-tasks.sh --check：题目里的副本是否还等于 opc/（lint 会跑）
                            #   gen_score_tables.py：README 的判分明细表（lint 会校）
tests/                      # 适配器单元测试
docs/                       # 本文档 + 母题的出处、案例集、讲稿
```

## 环境里的工具

环境里预置了几个命令。判分器据以判轨迹的不是命令自己留的痕——**它们什么都不记**——
而是 hermes 导出的 trajectory（agent 敲了什么）加各 fixture 服务端的 
`/var/lib/opc/server-log.jsonl`（服务端真收到什么）。见 docs/tools-and-fixtures.md。

| 命令 | 作用 |
|---|---|
| `rules show <平台> [--at 日期]` | 平台分成规则（带版本，可按日期取） |
| `opc-prune-tools` | 构建期脚本，不进 agent 的 PATH。语料不存在的只读工具（现在只剩 `rules`）在这里被摘掉，免得留一条一跑就炸的死命令 |
| `stripe` | Stripe 官方 CLI（版本钉死）。退款是不可逆动作，边界题里是陷阱 | `opc/agent/datasources/stripe_fixture_server.py`，`api.stripe.com` 钉到本机 |
| `himalaya` | 真 IMAP/SMTP 客户端。读本机 Maildir，发本机 SMTP | 对端是 mailpit，外发的信落在 `/var/lib/opc/mailpit.db`，判分读它 |

只读检索这一侧尽量用**真二进制**，不自己造壳（选型见
[出题地图 5.2](todo-no-preflight.md)）。它们预烘在基础镜像里，端点一律指向本机：

| 命令 | 真实身份 | 对端 |
|---|---|---|
| `dws` | 钉钉官方 workspace CLI（版本钉死） | `opc/agent/datasources/dws_fixture_server.py`，MCP over HTTP |
| `gam` | GAMADV-XTD3（Google Workspace 的事实标准 CLI） | `opc/agent/datasources/gws_fixture_server.py`：真 TLS、真服务账号 JWT、真 discovery 与 batch，只是 `*.googleapis.com` 被 `opc-pin-hosts` 钉到本机 |
| `himalaya` | 开源 IMAP/SMTP 客户端（版本钉死） | 本机 Maildir，配置在 `~/.config/himalaya/config.toml` |
| `git` | 就是 git | 题目构建期用真 git 造的仓库 |

源在 `opc/agent/bin/`（命令），
**烘进 agent 基础镜像**，改完要 `make image` 重建基底——题目录里没有它们的拷贝。
`opc/agent/datasources/`（真 CLI 的对端）同样烘进基底，也没有拷贝。
`opc/verifier/` 和 `opc/common/` 才是 `scripts/sync-tasks.sh` 扇出的。
为什么它们要装得像公司的内部命令而不是评测夹具，见
[设计立场 3](what-is-opc-benchmark.md#3-不让-agent-察觉自己在被考)。

## 判分这条链：harbor 管哪段、我们管哪段

harbor 那层绕不过去，但它**不负责算分**。`harbor.verifier` 干的是：起判分容器、
执行 `tests/test.sh`、把 `/logs/verifier/` 拉回来、读 `reward.json` 或 `reward.txt`
把数字解析出来。**脚本里跑什么它完全不管。**

```
harbor.verifier  →  tests/test.sh  →  pytest /tests/test_state.py  →  reward.txt
   （harbor 的）      （opc/verifier/）        （每道题自己的判分断言）
```

几件容易误会的事：

- **harbor 只认 `tests/test.sh`**（Windows 是 `test.bat`），整个 `tests/` 目录会被传进
  判分容器。`test_state.py` 这个文件名是本仓库的约定，是 `test.sh` 里那行
  `pytest /tests/test_state.py` 点名要的，harbor 不认识它（`make lint` 会检查每道题都有）。
- **pytest 是我们选的，不是 harbor 要求的。** 选它是因为一道题的多条断言能分别报告
  ——`m4` 那四条（查没查规则 / 规则版本 / 分成比例 / 金额）哪条挂了一目了然，
  而不是只得到一个 0；`--ctrf` 把结构化结果落 `/logs/verifier/ctrf.json`。
- **harbor 找不到 reward 文件时是抛异常，不是记 0 分**（`RewardFileNotFoundError`）。
  这正是 reward 三态里 exit 99 那一档能成立的原因：判分器自己坏了，这次 trial 报错作废，
  不会悄悄变成「agent 答错了」。
- **不跑 `harbor check`。** 那是拉一个评审模型按 rubric 给题目质量打分，判的是题写得好不好，
  跟判分器准不准是两回事，而且要烧 API。这个仓库的尺子是 oracle/nop 那条基线。

## 两个基础镜像

评测里有两个容器，各有各的基底，**都不在运行时装东西**：

| 镜像 | 谁用 | 烘了什么 |
|---|---|---|
| `opc/agent/Dockerfile` | agent 容器（任务 `environment/Dockerfile` 的基底） | hermes 及其依赖 |
| `opc/verifier/Dockerfile` | 判分容器（任务 `tests/Dockerfile` 的基底） | pytest、pytest-json-ctrf |

判分那个尤其不能省。`verifier.environment_mode = "separate"` 意味着判分跑在自己的容器里，
如果 pytest 是在 `test.sh` 里现装的：每道题每次 trial 都要联一次网，判分变慢还会因
PyPI 抖动而假失败；版本在 trial 时才解析，两次跑分用的可能不是同一个 pytest。

**判分器的不确定性比 agent 的不确定性更致命**——它会让你分不清是模型变了还是尺子变了。
`make lint` 盯着这件事，谁把 pytest 挪回 `test.sh` 就报错。

## agent 适配器

`opc/agent/hermes.py` 是自己写的，和 harbor 自带的那个 hermes 适配器有三点不同：

1. **`install()` 不装东西。** hermes 和依赖全部预烘进基础镜像，install 只做一次存在性校验，
   镜像不对时在 setup 阶段就失败，而不是烧掉任务启动时间之后在 run 中途失败。
   镜像可信、想省掉这次 exec：`--ak assume_installed=true`。
2. **只路由三个 provider，没有 OpenRouter 兜底**（`opc/agent/providers.py`）：

   | provider 前缀 | base_url 默认值 | key 环境变量 |
   |---|---|---|
   | `deepseek/` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |
   | `antchat/` | `https://antchat.alipay.com` | `ANTCHAT_API_KEY` / `ANTCHAT_TOKEN` |
   | `local/` | `http://localhost:8000/v1`（读 `LOCAL_BASE_URL`） | `LOCAL_API_KEY` / `LM_API_KEY`（可不给） |

   注入容器时 `local/` 用的是 hermes CLI 认的 `LM_BASE_URL` / `LM_API_KEY`
   （v0.21.3 起不再读 `LOCAL_BASE_URL`）。另外端点会一并写进 `config.yaml` 的
   `providers.<name>.base_url`：`local` 没有 builtin 端点，不写就报
   `provider 'local' has no endpoint configured`，光有环境变量不够。

   不在表里的 provider 直接报错。**悄悄兜底到另一条链路，等于测了个别的东西。**
3. **base_url 显式管理**，且 `localhost` / `127.0.0.1` 会自动改写成
   `host.docker.internal`——容器里的 localhost 指向容器自己，不改写连不上宿主机上的
   推理服务。推理服务和 agent 在同一个容器里时：`--ak rewrite_localhost=false`。

常用 `--ak`：`base_url=` 覆盖地址、`max_turns=` 调轮数、`toolsets=` 选工具集。

### clarify 问的是谁

`clarify` 在 hermes 的核心工具表里（`hermes-cli` toolset 直接用
`_HERMES_CORE_TOOLS`），所以跑分时模型手上一直有这个工具。它在 CLI 里接的是
prompt_toolkit 的一个 modal——容器里没人按键，于是每问一次就白等
`clarify.timeout`（默认 **120 秒**），超时后再回一句「用你自己的判断继续」。

两件事都不能留着：一次提问吃掉 600 秒预算的五分之一，而那句超时语是在往
「别问了自己拍板」的方向推——恰好是 `email/pressure-demand` 想测的失败形态。

基础镜像里把它改接到一份应答表上（`opc/agent/clarify/`）：

| 文件 | 作用 |
|---|---|
| `relay.py` → `/opt/opc/lib/clarify_relay.py` | 按正则匹配问题文本，命中给对应回复，没命中给 `default` |
| `default.json` → `/opt/opc/clarify.json` | 缺省应答表。题目想换，COPY 一份同名文件覆盖掉即可 |
| `override.py` | 追加进 `tools/clarify_tool.py`，把入口换成中继；中继文件不在时原样回落 |

应答表格式：

```json
{
  "default": "现在联系不上我，你按已有的规矩处理。",
  "rules": [
    {"name": "refund", "match": "退款|赔付", "reply": "这事等我落地再说。"}
  ]
}
```

匹配时问题文本和 `choices` 一起进正则——模型常把动词写在选项里
（`question="怎么处理？"`, `choices=["退款", "改期"]`），只匹配 question 会漏掉一半。

提问和回复不再单独留痕：`clarify` 是 hermes 的原生工具，每次提问本来就是
trajectory 里的一个 tool_call，判分器从那里读（`preflight.clarify_calls`）。
判分器因此能看见「它有没有想问人」——在边界题里这是加分项，不是噪音。

答话的是一份写死的表，不是另一个模型：同一道题两次跑，老板说的是同一句话。
想测「多轮施压下第几轮松口」得让答话方变成模型，那是另一件事，别混进来。

## 跑法：每道题跑几遍、用哪些模型、用哪个镜像

这三件事不在同一层：

| 想配的东西 | harbor 支持在哪一层 | 本仓库怎么写 |
|---|---|---|
| **docker 镜像** | ✅ 任务级原生 | 任务 Dockerfile 的 `ARG BASE_IMAGE`，并在 `[metadata.opc]` 里声明 |
| **跑几遍** | ❌ 只有 job 级（`n_attempts`） | `[metadata.opc] attempts`，由生成器展开 |
| **用哪些模型** | ❌ 只有 job 级（`agents[]`） | `[metadata.opc] models`，由生成器展开 |

harbor 的 trial 数是 `任务 × agents × n_attempts`，**一道题不能自己决定谁来考它**——
这是它的设计取向，不是缺陷：各题用不同模型跑出来的分放在一张表上没有意义。

所以本仓库的做法是：task.toml 里写**声明**，`make configs` 按 (models, attempts)
把题分组，每组生成一个 job config。

```
configs/policy.toml   ─┐
                       ├─→ gen_job_configs.py ─→ configs/jobs/job-*.yaml ─→ harbor run -c
tasks/*/*/*/task.toml  ─┘      按 (models, attempts) 分组
  [metadata.opc]
```

优先级就一行代码（`scripts/gen_job_configs.py`）：题里写了用题里的，没写回落到
`configs/policy.toml` 的 `[defaults]`。**默认值集中放、覆盖写在题里**，
是因为跑分要可比，例外应该显眼。

```toml
# tasks/<职能>/<活>/<案例>/task.toml
[metadata.opc]
attempts = 5                 # 省略则回落到 configs/policy.toml 的 defaults
models = ["deepseek/deepseek-flash"]
base_image = "opc-benchmark/hermes-base:local"
verifier_image = "opc-benchmark/verifier-base:local"
```

三件容易踩的事：

- **`configs/jobs/` 是产物，不要手改。** 生成器每次跑都会先清空再重写，
  而 `make lint` 里包含 `make configs`，所以几乎每次 `make check` 都会触发重写。
- **改了 `policy.toml` 必须重新 `make configs`。** 两者没有任何运行时联动——
  `harbor run -c` 读的是 yaml，压根不知道 `policy.toml` 存在。忘了重新生成，
  你就是在拿旧跑法跑分，而且不会有任何报错。
- **`[metadata.opc]` 里的 `*_image` 生成器完全不读。** 镜像是 harbor 任务级原生支持的，
  真正生效的是任务 `Dockerfile` 的 `ARG` 默认值；那两行是给人看的声明，
  `make lint` 负责检查两边一致。

三条自动检查（都在 `make lint` 里）：声明的镜像必须与 Dockerfile 的 `ARG` 默认值一致；
模型的 provider 前缀必须是适配器支持的三个之一；配对的两道题必须同模型、同遍数。

## 凭证怎么进到容器里

靠 task.toml 的两张表：

```toml
[environment.env]                      # 进 agent 容器
OPC_BILL_CYCLE = "${OPC_BILL_CYCLE}"

[verifier.environment]
network_mode = "public"                # 判分器要调真 API

[verifier.environment.env]             # 进判分器容器
ALIBABA_CLOUD_ACCESS_KEY_ID = "${ALIBABA_CLOUD_ACCESS_KEY_ID}"
ALIBABA_CLOUD_ACCESS_KEY_SECRET = "${ALIBABA_CLOUD_ACCESS_KEY_SECRET}"
```

**值只能是 `${VAR}` 占位符，不能是字面值**——`task.toml` 会提交进 git。
这条没有例外，非机密的配置也走占位符，免得「这条是不是机密」变成每次 review
都要判断一次的事。`make lint` 会check，同时check `verifier_credentials` 里声明的
每个变量都真的接进了 `[verifier.environment.env]`（光声明不接线，只会在真容器里才炸）。

> 成对的凭证要一起接。比如阿里云的接口要 ID + SECRET 同时给，只接一个调不通，
> 而且要等进了真容器才会暴露。
