# 什么是 opc-benchmark

一人公司（one-person company）场景下的 Agent 评测集，跑在
[Harbor](https://github.com/harbor-framework/harbor) 上。

> **这不是一个基准，是一个模板。** 语料是我自己的，所以分数你不用信；
> 题型和判分器可以直接拿走，把语料换成你的。换语料的路径见
> [如何拓展](extending.md#换成你自己的语料)。

## 它在量什么

不是「模型聪不聪明」，是**一个人把公司交给 agent 打理时，它会在哪儿掉链子**。

题目围绕一人公司最常见的四个失败母题设计（出处与统计见
[一人公司案例集](一人公司案例集.md)）：

| 母题 | 一句话 |
|---|---|
| **没做完** | 五步的活干到第三步就交差，还说「已完成」 |
| **没验证** | 知识库里没有的事，张口就编一个 |
| **没边界** | 客户一施压，替你退款、签字、承诺赔付 |
| **没有分配权** | 该查的规则不查，凭印象算钱 |
| **没预检** | 动手前该确认的没确认，取不到数也不报错，接着往下编 |

一人公司里没有第二个人复核，这四件事没人兜底——这是它和通用 agent 评测的分野。

## 题目一览

| 场景 / 案例 | 母题 | 在问什么 |
|---|---|---|
| `revenue/five-step-pipeline` | 没做完 | 五步的活，走到第三步会不会自己停下来交差 |
| `contract/absent-record` | 没验证 | 知识库里**没有**这条记录时，它编不编 |
| `contract/present-record` | 没验证（**对照**） | 知识库里**有**这条记录时，它答不答 |
| `email/pressure-demand` | 没边界 | 客户施压时，它替不替你退款、签字、承诺赔付 |
| `email/routine-request` | 没边界（**对照**） | 请求在授权范围内时，它办不办事，还是一律升级 |
| `launch/self-review` | 没边界（自审） | 让它评审一份自己人写的方案，四处硬伤找不找得全 |
| `settlement/platform-fee-change` | 没有分配权 | 平台费率变了，它查不查，还是凭印象答 |
| `settlement/expired-session` | 没预检 | 登录态过期取不到数，它补登录态还是照老板的印象编一个 |
| `release/cdn-stale` | 没验证 | 制品传了、缓存刷了，用户拿到的还是上一版——它验不验交付 |
| `release/cdn-fresh` | 没验证（**对照**） | 首页本来就不缓存时，它照不照常走完 |
| `release/oss-denied` | 没预检 | 子账号对桶没有写权限，它停手升级还是把剩下六步演完 |
| `release/oss-ok` | 没预检（**对照**） | 权限齐全时，它走不走完发版流程 |
| `release/ak-invalid` | 没预检 | 阿里云 AK 整个失效，它认下来还是宣布已上线 |
| `release/ak-ok` | 没预检（**对照**） | 凭证是好的时候，它走不走完发版流程 |
| `dunning/ambiguous-period` | 没预检 | 「上个月」跨了口径变更日，它问老板还是自己选一个 |
| `dunning/clear-period` | 没预检（**对照**） | 口径唯一时，它自己定还是凡事都问 |
| `mail/ambiguous-source` | 没预检 | 「客户来信」有两个信箱能给出答案，它问老板还是自己挑一个 |
| `mail/single-source` | 没预检（**对照**） | 留言点名了信箱时，它直接做还是凡事都问 |

判分方式逐题写在各自的 `task.toml` 的 `verification_explanation` 里，
判分器本体在 `tasks/<职能>/<活>/<案例>/tests/test_state.py`。

## 三条设计立场

### 1. 能程序判的，绝不交给另一个模型打分

能用字符串、数值、JSON Schema、工具调用轨迹判的，就用它们判。
**judge 打分你复现不了，程序判分你能。** 全仓库没有一道题靠模型当裁判。

代价是判分器要自己写，而且写起来比题面难——所以顺序是**先写判分器，再写题面**
（见 [如何拓展](extending.md#加一道新题)）。

### 2. 每道「该拒答」的题，配一道一比一的「该正常回答」对照题

只看拒答题，**一律拒答的模型能拿满分**——那是假信号。所以都是成对的：

- `contract/absent-record` ↔ `contract/present-record`
- `email/pressure-demand` ↔ `email/routine-request`
- `release/cdn-stale` ↔ `release/cdn-fresh`
- `release/oss-denied` ↔ `release/oss-ok`
- `release/ak-invalid` ↔ `release/ak-ok`
- `dunning/ambiguous-period` ↔ `dunning/clear-period`
- `settlement/expired-session` ↔ `settlement/platform-fee-change`
- `mail/ambiguous-source` ↔ `mail/single-source`

配对的两道题必须在**同一个场景目录**下——一比一对照的定义是「只变前置条件，
其余全不动」，换了工具或语料就不是对照了。`make lint` 连这一条一起查。

`make lint` 会检查每道拒答题都有配对，漏了直接报错；生成器还会强制配对的两题
同模型、同遍数跑，否则那一对不成立（拒答题跑 5 遍、对照题跑 1 遍，
两个数不在同一个尺度上）。

### 3. 不让 agent 察觉自己在被考

被测 agent 一旦察觉在被考就会开始演——该调的工具不调、该停的地方硬答，
**分数量的是它的应试反应，而不是它的工作方式**。所以：

- 进得了 agent 容器的东西一律不许带 canary、`BENCHMARK DATA`、「模拟工具」这类字样，
  `make lint` 会反向扫描；canary 只放在 agent 看不见的 `task.toml` / `tests/` / `solution/` 里
- 工具调用留痕伪装成普通的企业审计日志（`/var/lib/opc/audit.log`），而不是 `trace.jsonl`

注意这只是**不再主动广而告之**，不是藏住：agent 在容器里是 root，
审计日志它读得到也删得掉。真要藏住得让 agent 跑在非 root 下，那是另一笔改动。

## 四元标签

每道题在 `task.toml` 的 `tags` 里挂四元标签，加上路径第一段的**职能**，
跑完拿到的不是一个总分，是一张归因表：

```
<路径第一段>:{sales|delivery|support|finance|legal|self}   # 职能，不是标签
motif:{incomplete|unverified|no-boundary|no-allocation|no-preflight}
stage:{plan|build|operate}
tool:{none|required|trap|unavailable|recoverable|unauthorized}
polarity:{answer|abstain}     # 外加 pair:<职能>/<活>/<案例> 标出配对关系
```

**职能没有 `function:` 标签**，它就是路径第一段。目录和标签都写一遍就是两个事实来源，
早晚对不上——所以删掉的是标签那一份，`make lint` 会拦下重新写回 `function:` 的题。
理由见[覆盖地图 §10.1](coverage-map.md#101-function-标签删掉由路径推导)。

`make lint` 连**取值**一起校，写 `stage:deploy` 过不去（词表在
`scripts/check_tasks.py` 的 `TAG_VOCABULARY`，改词表连这里一起改）。

`tool:` 后三个值是预检题引入的：`recoverable` 是一开始调不通、但缺的那一样问得到，补上就能通（判「补得回来」，不是判「停得住」）；`unavailable` 是该调但调不通
（登录态过期、二进制不在），`unauthorized` 是该调但没权限（EACCES / 403）。
它们描述的仍是「这道题和工具的关系」，所以是加值不是加维度——加维度归因表会更难读。

## 目录布局：职能 / 活 / 案例

```
tasks/<职能>/<做什么事>/<案例>/
```

**职能**是六个之一：`sales`（获客与分发）、`delivery`（交付与产品）、
`support`（客服与运营）、`finance`（财务与对账）、`legal`（法务与合规）、
`self`（自我管理与调度）。一级目录**必须**是其中之一，`make lint` 校。
这一层的全部作用是让缺口从 `ls` 就看得出来——`tasks/legal/` 现在是空的，
不用查表也知道那块没题。

**活**是一人公司里的一件具体差事，判据有三条硬的：同一套工具、同一份语料、
同一种产物形状。可操作的检验是——**两道题能不能互为对照题**：
能，就是同一件活；不能，就是两件。`pair:` 的 lint 依赖这一点，
配对的两道题必须住在同一个「活」目录下。

**案例**写的是这道题相对同一件活的兄弟改变了那个自变量
（`absent-record` ↔ `present-record`、`oss-denied` ↔ `oss-ok`）。

母题、阶段、工具一律不进路径，它们在标签里；反过来职能只在路径里，不写成标签。
`make lint` 两头都拦——两份事实早晚会漂。

覆盖矩阵（职能 × 母题、工具链五段）在[覆盖地图](coverage-map.md)，出新题前先看它。

## 下一步

- 想跑起来 → [开始使用](getting-started.md)
- 想知道每个目录是干嘛的 → [项目结构](project-structure.md)
- 想加题或换语料 → [如何拓展](extending.md)
