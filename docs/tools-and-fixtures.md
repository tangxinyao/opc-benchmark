# 工具与供数：14 道题分别用了什么，以及它们是怎么接上的

每道题的 `README.md` 只写「这道题用了哪几样」，机制写在这里，一处维护。

## 先说一件事：这里基本没有 mock

容易被叫成 mock 的那几样东西，客户端全都是**真的**：

| 工具 | 是什么 | 版本钉在哪 |
|---|---|---|
| `dws` | 钉钉官方 CLI | `opc/agent/Dockerfile`（v1.0.60，gitee 镜像） |
| `gam` | GAMADV-XTD3，真 Google Workspace 客户端 | `opc/agent/Dockerfile` |
| `stripe` | Stripe 官方 CLI | `opc/agent/Dockerfile` |
| `himalaya` | 真 IMAP/SMTP 客户端 | `opc/agent/Dockerfile` |
| `git` | 发行版自带 | `opc/agent/Dockerfile` |

被换掉的只有**对端**。做法统一是三步：

1. 构建期用 `openssl` 签一张本机 CA，签出目标主机名的证书，`update-ca-certificates` 装进信任链；
2. 目标主机名写进 `/opt/opc/hosts.pin`（root 0644，agent 改不了），运行期由 `opc-pin-hosts` 解到 `127.0.0.1`；
3. 本地起一个按真 API 形状供数的 HTTP 服务。

所以 **JWT 换 token、TLS 校验、分页契约、错误码、batch 协议全是真的走了一遍**，只有最后一跳落在本机。这是刻意的：自造一个假 CLI 等于把连接器的真实难度（鉴权、分页、错误码）整个删掉，而那恰恰是要考的东西。

## 四个数据源服务

实现在 `opc/agent/datasources/`，**烘进 agent 基础镜像**的 `/opt/opc/lib`，题目录里没有拷贝：

| 实现 | 对端 | 端口 | `OPC_SERVICES` 里叫 |
|---|---|---|---|
| `dws_fixture_server.py` | `dws` CLI | 18080（MCP over HTTP JSON-RPC） | `datasource` |
| `gws_fixture_server.py` | `gam` | 443（discovery 的 rootUrl 写死） | `workspace` |
| `stripe_fixture_server.py` | `stripe` CLI | 443（CLI 认 `api.stripe.com`） | `billing` |
| `aliyun_fixture_server.py` | `aliyun` CLI | 443（按 Host 头分流，兼做 CDN 边缘） | `cloud` |

**起哪些由题目声明，不看文件在不在。** 题目在 `environment/Dockerfile` 里写
`ENV OPC_SERVICES="billing"`（空格分隔可多个），entrypoint 照着起。自带
`entrypoint.sh` 的题直接写死要起的那个，不用这个变量。

以前这四份是 `scripts/sync-tasks.sh` 按 opt-in 拷到题目的 `environment/lib/` 的，
而且**改名**下发：`dws_fixture_server.py` → `lib/datasource_server.py`，四个全这样。
于是同一个文件在三处三个名字，`grep dws_fixture_server tasks/` 一条都搜不到。
省下的只是给用不上的题少塞几十 KB 只读文件——四份都是通用机制，故障注入与语料
全在 `/opt/opc/data`（`opcsvc:opcsvc 0700`，agent 读不到），多读几份源码拿不到
任何一道题的答案。不划算，所以烘进基底、删掉扇出层。

它们**不进 `/opt/opc/bin`**：那个目录在 agent 的 PATH 上，混进去等于把认证逻辑、
fixture 路径和错误形状摆到它面前。落 `/opt/opc/lib`（`opcsvc:opc`，目录 `0550`、
文件 `0440`），由 entrypoint 经 `sudo -u opcsvc` 拉起。

外发邮件那一路不是自研服务：对端是真 `mailpit`，由 `opc-svc-start mailpit` 拉起，收走所有外发信，落 `/var/lib/opc/mailpit.db`。

## 谁拉起这些服务，agent 碰不碰得到

agent 是 `opc`，服务是 `opcsvc`。sudoers 只放行两个目标：

- `opc-svc-start {datasource|workspace|mailpit|billing|cloud}` —— 以 `opcsvc` 跑，只能拉这五样，不能借 sudo 读语料或提权做别的事；
- `opc-pin-hosts` —— 唯一以 root 放行的，不收参数，钉哪些名字由 root 拥有的 `/opt/opc/hosts.pin` 决定。

语料与私钥在 `/opt/opc/data`，`opcsvc:opcsvc 0700`——agent 读不到，只能经 CLI 走接口。443 是特权端口，`opcsvc` 绑不了，所以走一份单独 `setcap` 过的 python 副本（`/usr/local/lib/opc/python3-net`），agent 自己那个 python 不给任何 capability。

## 证据：两处，可信度不同

判分只认两份文件，都由 `task.toml` 的 `artifacts` 带进判分容器：

| 证据 | 谁写的 | 管什么 | agent 能不能改 |
|---|---|---|---|
| `/logs/agent/hermes-session.jsonl` | hermes 自己导出的会话 | **agent 干了什么**：每次工具调用和它的回显 | 理论上能——同一个身份下的文件 |
| `/var/lib/opc/server-log.jsonl` | `dws` / `gam` / `stripe` / `aliyun` 四个 fixture 服务端 | **服务端真收到了什么**（换成 `curl` 也跑不掉），外加 agent 进来之前的开机自证 `_env:<名字>` | 不能——`opcsvc` 持有，`/var/lib/opc` 是 `opcsvc:opc 0750` |

于是分层照旧，只是「贵的那档」现在明确指服务端日志：

- **贵的一档（服务端写的）**：四个数据源服务、`mailpit` 落的库。agent 删不掉已经落下的行，**正断言、负断言都该往这儿写**。凡是服务端看得见的事（发过请求没有、退过款没有、发过信没有），断言就不该只靠轨迹。
- **便宜的一档（trajectory）**：agent 敲了什么命令、`clarify` 问了什么、撞上过什么回显。够用来判「它探过没有」「它问过没有」，但伪造成本低，别拿它当唯一依据。

两份的事件形状被 `opc/verifier/preflight.py` 拍平成同一个字典（`tool` / `args` / `ok`），合成一条流，题目里的断言只跟这一个接口打交道。

**轨迹那半的 `ok` 是推断的。** 从前有命令包装器，拿得到真实退出码；现在只有工具回显，只能按失败特征串判断（见 `preflight._FAILURE_MARKERS`）。宁可漏判失败也不误判成功——假红比漏判更贵。服务端那半的 `ok` 仍是服务端的真实结论。

**曾经还有第三处。** `/var/lib/opc/audit.log`：`/opt/opc/bin` 下的命令包装器写 FIFO，`opc-audit-collector` 以 `opcsvc` 在另一侧收，外加 `bashenv.sh` 的 `command_not_found_handle` 记「敲了个不存在的命令」。整套删了——它记的是 trajectory 里本来就有的同一件事。

判分片段按这个分层写在 `opc/verifier/` 下：`preflight.py`（证据层 + 预检四条）、`outbox.py`（读 mailpit 库）、`billing.py`（读 stripe 服务端的 refund 行）、`oracle.py`（差分判分骨架）。

## agent 侧的小工具

源在 `opc/agent/bin/`，烘进基础镜像（题目录里没有拷贝）。现在只剩一个：

- `rules` —— 平台规则/费率查询，题目语料的读取口，跟 `dws`/`stripe` 那些真 CLI 同一个位置。语料不在就由 `opc-prune-tools` 在构建期从 PATH 上摘掉。

以前这里还有 `opc_internal/audit.py`（写审计的库）、`_record-missing`（记「命令不存在」）、`etc/bashenv.sh`（挂钩子的 `BASH_ENV`），合起来是那套留痕脚手架。全删了，理由见上一节。

`opc-entrypoint.sh` / `opc-prune-tools` 是启动与构建期脚手架，agent 永远不该调，所以在 `opc/agent/svc/`、落 `/usr/local/bin`，不在它的 PATH 上。

另有 `clarify`：hermes 的提问通道，由 `opc/agent/clarify/relay.py` 接到一份按正则应答的留言表（`OPC_CLARIFY_SCRIPT`，题目的 `clarify.json`），不等真人、结果确定。中继本身不再留痕——`clarify` 是 hermes 的原生工具，每次提问本来就是 trajectory 里的一个 tool_call。

## 怎么确认这些供数没坏

- `make lint` —— 静态检查（canary、标签词表、判分工具是否烘好、拒答题是否配对）。
- `make unit` —— 适配器单元测试，四个数据源服务各有一份（`tests/test_*_fixture_server.py`）。
  不起 TLS、不起容器：`dws` 那份跑真进程（它本来就是明文 18080），另外三份在进程内
  直接驱动 `Router` / `ObjectStore` / `Edge`，只有 gam 的 `/batch` 为了拆 multipart
  起了一个明文的本机 HTTP。测的是**判分会直接读的那几处语义**（错误形状、服务端留痕、
  CDN 刷新范围、AK 换对了能不能过），不是「接口通不通」。
- `make smoke` —— 宿主机上跑 oracle/nop 基线。**注意：凡是带 `entrypoint.sh` 或要真发信的题一律 SKIP，正好就是所有用到数据源服务的题。**
- `scripts/validate.sh` —— 容器里跑，oracle 必须满分、nop 必须零分。**用到数据源服务的题只有这一关能兜住。**

预检题还有一层：每道题的第一条断言是 `preflight.assert_precondition_failed`，先证明前置条件真的塌了（401 真的发生过、git 真的不在），再判 agent 怎么应对。环境哪天没坏，这条会红——但**目前它红了写的是 `reward 0`，跟「agent 没做预检」混在一起**，`test.sh` 的 99 号 infra 出口只有 `oracle.py` 在用。
