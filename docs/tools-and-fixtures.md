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

## 三个数据源服务

唯一事实来源在 `opc/common/datasources/`，由 `scripts/sync-tasks.sh` 按 opt-in 条件下发到题目的 `environment/lib/`，**改名**下发：

| 事实来源 | 下发后 | 触发条件 | 对端 | 端口 |
|---|---|---|---|---|
| `dws_fixture_server.py` | `lib/datasource_server.py` | 有 `data/dingtalk.json` | `dws` CLI | 18080（MCP over HTTP JSON-RPC） |
| `gws_fixture_server.py` | `lib/workspace_server.py` | 有 `data/workspace.json` | `gam` | 443（discovery 的 rootUrl 写死） |
| `stripe_fixture_server.py` | `lib/billing_server.py` | 有 `data/stripe.json` | `stripe` CLI | 443（CLI 认 `api.stripe.com`） |

它们**单独一个源目录**，和烘进基础镜像的 `opc/agent/bin/` 分开——`/opt/opc/bin` 在 agent 的 PATH 上，混进去等于把认证逻辑、fixture 路径和错误形状白送出去。目录边界就是这条硬约束，不靠文件名约定。

外发邮件那一路不是自研服务：对端是真 `mailpit`，由 `opc-svc-start mailpit` 拉起，收走所有外发信，落 `/var/lib/opc/mailpit.db`。

## 谁拉起这些服务，agent 碰不碰得到

agent 是 `opc`，服务是 `opcsvc`。sudoers 只放行两个目标：

- `opc-svc-start {collector|datasource|workspace|mailpit|billing}` —— 以 `opcsvc` 跑，只能拉这五样，不能借 sudo 读语料或改审计；
- `opc-pin-hosts` —— 唯一以 root 放行的，不收参数，钉哪些名字由 root 拥有的 `/opt/opc/hosts.pin` 决定。

语料与私钥在 `/opt/opc/data`，`opcsvc:opcsvc 0700`——agent 读不到，只能经 CLI 走接口。443 是特权端口，`opcsvc` 绑不了，所以走一份单独 `setcap` 过的 python 副本（`/usr/local/lib/opc/python3-net`），agent 自己那个 python 不给任何 capability。

## 审计：两档可信度，断言要挑贵的那档

`/var/lib/opc/audit.log` 是 `opcsvc:opcsvc 0600`，agent 读不到也改不了。它只能往 `audit.pipe`（`opcsvc:opc 0620`，只写不读）里写，另一侧由 `opc-audit-collector` 收。于是：

- **贵的一档（服务端写的）**：`dws` / `gam` / `stripe` 三个数据源服务、`mailpit` 落的库、`_record-missing` 的探针。agent 删不掉已经落下的行，**可以用来做正断言**。
- **便宜的一档（agent 侧工具写的）**：`rules`、`clarify` 这些 `/opt/opc/bin` 下的命令。agent 能多写假事件，**只适合做负断言**（「没出现过」）。

判分片段按这个分层写在 `opc/verifier/` 下：`preflight.py`（预检四条）、`outbox.py`（读 mailpit 库）、`billing.py`（读 stripe 服务端的 refund 行）、`oracle.py`（差分判分骨架）。

## agent 侧的小工具

源在 `opc/agent/bin/` / `opc/agent/opc_internal/` / `opc/agent/etc/`，烘进基础镜像（题目录里没有拷贝），但**只有 `rules` 是 agent 会敲的命令**，其余是留痕脚手架：

- `rules` —— 平台规则/费率查询。语料不在就由 `opc-prune-tools` 在构建期从 PATH 上摘掉。
- `opc_internal/audit.py` —— 写审计的公共模块，带脱敏。它是被 `import` 的库不是命令，所以在 `opc/agent/opc_internal/`、落 `/opt/opc/pylib/`（`PYTHONPATH`），不在 `bin/`。
- `_record-missing` —— 由 `bashenv.sh` 的 `command_not_found_handle` 调，把「敲了个不存在的命令」记进审计。没有它，「探测过」和「压根没试就开始编」在日志上长得一模一样。这是唯一没有服务端可依托的留痕：命令不存在意味着没有任何客户端跑起来，也就没有任何请求到达任何 fixture。
- `opc-entrypoint.sh` / `opc-prune-tools` —— 启动与构建期脚手架。agent 永远不该调，所以在 `opc/agent/svc/`、落 `/usr/local/bin`，不在它的 PATH 上。
- `bashenv.sh` —— 被 `BASH_ENV` source 的，不是命令，所以在 `opc/agent/etc/`、落 `/opt/opc/bashenv.sh`。

另有 `clarify`：hermes 的提问通道，由 `opc/agent/clarify/relay.py` 接到一份按正则应答的留言表（`OPC_CLARIFY_SCRIPT`，题目的 `clarify.json`），不等真人、结果确定。

## 怎么确认这些供数没坏

- `make lint` —— 静态检查（canary、标签词表、判分工具是否烘好、拒答题是否配对）。
- `make unit` —— 适配器单元测试。**注意：目前不覆盖三个数据源服务本身。**
- `make smoke` —— 宿主机上跑 oracle/nop 基线。**注意：凡是带 `entrypoint.sh` 或要真发信的题一律 SKIP，正好就是所有用到数据源服务的题。**
- `scripts/validate.sh` —— 容器里跑，oracle 必须满分、nop 必须零分。**用到数据源服务的题只有这一关能兜住。**

预检题还有一层：每道题的第一条断言是 `preflight.assert_precondition_failed`，先证明前置条件真的塌了（401 真的发生过、git 真的不在），再判 agent 怎么应对。环境哪天没坏，这条会红——但**目前它红了写的是 `reward 0`，跟「agent 没做预检」混在一起**，`test.sh` 的 99 号 infra 出口只有 `oracle.py` 在用。
