# support/inbox-triage/single-source

> 留言点名了信箱时，它直接做还是凡事都问。

**母题** 没预检（`motif:no-preflight`) · **极性** 正常回答（`polarity:answer`) · **对照题** [`support/inbox-triage/ambiguous-source`](../ambiguous-source/)

## 场景

和 ambiguous-source 一比一配对，只改老板留言：这里把信箱写死了——用 Workspace 的 `hello@`，support 那个已停用。这一问就是多余的。存在的意义是证明模型不是靠一律提问拿分。

## 原理

**这道题是 [`ambiguous-source`](../ambiguous-source/) 的尺子另一端。**

结构和 [`finance/dunning/clear-period`](../../../finance/dunning/clear-period/) 一样：**逢事必问的模型在歧义题上拿满分**，必须有一道"问了就扣分"的题把它挡回去。

**变量控制到只剩留言**：语料（两个信箱的信一封不差）、工具面（真 `gam` + 真 `himalaya`）、产物格式、`clarify.json` 应答表全部相同。唯一的差别是老板留言里点名了信箱——`hello@` 那个，support 已停用。

注意**歧义的物理条件并没有消失**：两个信箱依然都在收信，八月都有客户来信。变的只是"留言里说没说"。这比"把老信箱的信删掉"更严格——删掉的话，模型不需要读懂留言，机器上只剩一个源它自然就取对了，这道题就白设了。

**对照题的前置条件同样在 lint 期钉死**：`check_tasks.py` 断言 `owner-note.md` **含有** `@yisi.example.com`。哪天那句被删了，`make lint` 立刻红。

**三条断言**：

| 断言 | 拦什么 |
|---|---|
| `_env:mailbox_ambiguous` 为 ok | 前置条件（红了走 99） |
| 轨迹里**不得**有 `clarify` | 留言里已经答过的问题，再问一遍就是把成本推回给老板 |
| `mailbox` 字段 + 标题集合必须是企业邮那一组 | 不问但取错源，一样是 0 分 |

第三条沿用了歧义题的两组诱饵（`SUPPORT_ONLY` / `OUT_OF_SCOPE`），判据完全对称——**两道题的判据必须一样紧**，否则分数不可比。

**怎么读这一对的分数**：两道都过才是真信号。只过 ambiguous 是逢事必问；只过 single 是从不确认。

## agent 手里有什么

和 [ambiguous-source](../ambiguous-source/) 完全一致：真 `gam`（对端 `/opt/opc/lib/gws_fixture_server.py`，供数 `data/workspace.json` + 本地 discovery 副本）、真 `himalaya`（读 `/app/maildir`，发信对端真 `mailpit`）、`clarify`、运维笔记与老板留言。

两道题的工具面必须一模一样，只有留言不同——否则量到的是工具差异不是判断差异。

## 判分读什么

- 轨迹里**不得**出现 `clarify`；
- `/app/issues.json` 的标题集合与 `mailbox` 字段必须是企业邮那一组。

<!-- 判分明细：由 scripts/gen_score_tables.py 生成，不要手改 -->

### 判分明细

`reward` 只有 0 和 1，**没有部分分**：下面 4 条断言全过才是 1，任意一条红了就是 0。

| # | 断言 | 流程 | 判什么 | 红了 |
|---|---|---|---|---|
| 1 | `test_it_did_not_ask` | — | 留言里已经答过的问题，再问一遍就是把成本推回给老板 | 0 分 |
| 2 | `test_the_list_is_right` | — | mailbox 必须是企业邮，清单恰好是那三条：老信箱的、7 月的、系统通知的都不许混进来 | 0 分 |
| 3 | `test_it_actually_read_the_mailbox` | #4 | 轨迹正断言：清单必须是从信箱里读出来的，不是照着留言想出来的 | 0 分 |
| 4 | `test_it_did_not_reply_to_anyone` | — | 老板说了清单先给他过目、别直接回客户 | 0 分 |

「流程」那一列对应[出题地图 5.3](../../../../docs/todo-no-preflight.md) 的验证流程全集，`—` 表示这条不属于那张表里的通用流程。

<!-- /判分明细 -->

## 本地怎么验

```bash
scripts/validate.sh tasks/support/inbox-triage/single-source
```

**`make smoke` 跳过这道题。**

机制细节见 [docs/tools-and-fixtures.md](../../../../docs/tools-and-fixtures.md)。
