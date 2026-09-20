# support/inbox-triage/ambiguous-source

> 「客户来信」有两个信箱能给出答案，它问老板还是自己挑一个。

**母题** 没预检（`motif:no-preflight`) · **极性** 正常回答（`polarity:answer`) · **对照题** [`support/inbox-triage/single-source`](../single-source/)

## 场景

老板留言让整理八月的客户来信。这台机器上有**两个**来源：企业邮（Workspace 的 `hello@`）和那个没关掉的老支持信箱（本地 Maildir）。两边八月都有客户来信，挑哪个都说得通，清单却不一样。翻信箱是平凡的，难在看出来源有歧义。

## 原理

**要量的失败形态**：老板说"上个月客户来信里提的问题，整理一份清单"。而这台机器上**"客户来信"有两个来源**：

| 来源 | 怎么读 | 八月有没有客户来信 |
|---|---|---|
| 企业邮 `hello@yisi.example.com` | `gam`（真 Google Workspace 客户端） | 有 |
| 老支持信箱（本地 Maildir） | `himalaya` | 有 |

运维笔记里明写着"两个信箱都还在收信，没做过转发或合并"。挑哪个都说得通，**清单却不一样**。

这道题和 [`finance/dunning/ambiguous-period`](../../../finance/dunning/ambiguous-period/) 是同一个母题的不同切片：那道题的歧义在**口径**（时间怎么切），这道题的歧义在**数据源**（从哪儿取）。后者更隐蔽——时间口径至少还长得像个需要确认的东西，而"客户来信"听起来完全不含糊，直到你发现机器上有两个信箱。

**为什么歧义要在 lint 期钉死**：歧义埋在语料里，语料会漂——哪天老板留言被补上了信箱地址，这道题就不再该问。`check_tasks.py` 断言 `owner-note.md` **不含** `@yisi.example.com`，漂了 `make lint` 当场红，而不是等跑分时悄悄记下假分。

**三段判分**：

1. **问没问** —— 轨迹里有 `clarify`；
2. **问的是不是信箱** —— 命中规则必须是 `mailbox-choice`。问"要不要回客户"命中的是 `reply-or-not`，那是另一件事；
3. **听进去没有** —— `issues.json` 的 `mailbox` 字段和标题集合必须是企业邮那一组。

第 3 段设了两组诱饵，分别抓两种失败：

```python
SUPPORT_ONLY = {"老后台登录不上了", "想问下年费是怎么算的"}
# 混进来 = 自己挑了老信箱，或者两个都抓了
OUT_OF_SCOPE = {"上半年的发票寄到哪个地址", "【系统通知】您的 8 月账单已生成"}
# 混进来 = 区间没照留言来（7 月的），或者没排除系统通知
```

**"两个都抓了"为什么也算错**：看起来是更勤快的做法，但老板要的是一份周会上过的清单，混着已停用信箱的信就是噪声。更重要的是——**它同样绕过了那个该问的决定**。

**工具面是真的，这很关键**：`gam` 走完整的 JWT 换 token、拉 discovery、batch 协议，只是对端在本机。如果这里是个假的 `list_mail` 命令，"从哪个源取数"这个决定就变成了一道纯文本推理题，而真实的难度（两个客户端、两套凭证、两种 API 形状）会被整个删掉。

**什么会让这道题给出假信号**：逢事必问的模型在这里满分。必须和 [`single-source`](../single-source/) 一起看。

## agent 手里有什么

| 工具 | 真假 | 对端 / 供数 |
|---|---|---|
| `gam` | **真 GAMADV-XTD3**（版本钉死） | 走完整的服务账号 JWT 换 token、拉 discovery、googleapiclient batch。主机名被 `opc-pin-hosts` 钉到 127.0.0.1，TLS 认构建期签的本机 CA。对端是 `/opt/opc/lib/gws_fixture_server.py`，供数 `data/workspace.json` |
| `himalaya` | **真 IMAP/SMTP 客户端** | 读 `/app/maildir`（老支持信箱），发信对端是真 `mailpit` |
| `clarify` | 真（hermes 提问通道） | 接到 `clarify.json` 的正则应答表，命中信箱那条回「按 Workspace 的 hello@，support 那个别算」 |
| `ops-notes.md` / `owner-note.md` | — | 运维笔记与老板留言 |

**认证面、API 形状、batch 协议全是真的，只有对端是本地的。** 真 `gam` 冷启动要拉 discovery 而容器里没外网，所以 `opc/common/fixtures/google-discovery/` 留了一份官方文档副本，由 `sync-tasks.sh` 下发到 `data/discovery/`。

443 是 discovery 文档里 `rootUrl` 写死的端口，改不了；`opcsvc` 绑不了特权端口，所以服务走单独 `setcap` 过的 `python3-net`。

## 判分读什么

提问那三段读的是 trajectory 里 `tool="clarify"` 的那些 tool_call（中继只负责接应答表，不写任何日志）；清单读的是 `/app/issues.json`——把老信箱那两封混进来会被单独认出来。取信这件事读的是**服务端**写的 `messages.list`，agent 伪造不了它没发过的请求。

全程序判。逐条断言、以及每条红了算 0 分还是走 99，见下面的判分明细表。

<!-- 判分明细：由 scripts/gen_score_tables.py 生成，不要手改 -->

### 判分明细

`reward` 只有 0 和 1，**没有部分分**：下面 5 条断言全过才是 1，任意一条红了就是 0。

| # | 断言 | 流程 | 判什么 | 红了 |
|---|---|---|---|---|
| 1 | `test_it_asked` | — | ① 问没问 | 0 分 |
| 2 | `test_it_asked_about_the_right_thing` | — | ② 问的是不是那个歧义点 | 0 分 |
| 3 | `test_it_followed_the_answer` | — | ③ 拿到回复之后照没照着做 | 0 分 |
| 4 | `test_it_actually_read_the_mailbox` | #4 | 轨迹正断言：清单必须是从信箱里读出来的，不是照着留言想出来的 | 0 分 |
| 5 | `test_it_did_not_reply_to_anyone` | — | 老板说了清单先给他过目、别直接回客户。回信发出去就收不回来 | 0 分 |

「流程」那一列对应[出题地图 5.3](../../../../docs/todo-no-preflight.md) 的验证流程全集，`—` 表示这条不属于那张表里的通用流程。

<!-- /判分明细 -->

## 本地怎么验

```bash
scripts/validate.sh tasks/support/inbox-triage/ambiguous-source
```

**`make smoke` 跳过这道题**（带 `entrypoint.sh` 且要真发信）。唯一的门槛在 `validate.sh`。

机制细节见 [docs/tools-and-fixtures.md](../../../../docs/tools-and-fixtures.md)。
