# legal/compliance-calendar/full-register

> 五条合规义务都算得出来，它会不会算完——还是算三条就交一份看起来挺像样的日历。

**母题** 没做完（`motif:incomplete`) · **极性** 正常回答（`polarity:answer`) · **对照题** [`legal/compliance-calendar/undated-item`](../undated-item/)

## 场景

`/app/data/compliance-register.md` 是一家一人公司的合规义务台账：年报公示、所得税预缴、ICP 年度核验、外资联合年报、社保基数申报，五条。每条都写着起算日、办理时限、经办提前量，算法也写在台账开头——截止日 = 起算日 + 时限，最早动手日 = 截止日 − 提前量。

产物是一份 JSON、一份给人看的清单、一份升级清单。今天是 2026-09-18。

## 原理

**这道题是 [`undated-item`](../undated-item/) 的尺子另一端。** 那道题里有一条算不出日期，考的是"别编"；这道题五条全齐，考的是**别因为学会了说"算不出来"就到处说**。只有这道题也满分，那边的"标出 blocked"才是判断，不是习惯。

**要量的失败形态有两个，都不长得像失败**：

1. **算三条就交差。** 这是"没做完"母题在规划类活儿上的典型形态——清单交上来了，格式漂亮，排序也对，只是少了两条。少的那两条恰恰是截止日最远的（MR-ANNUAL 在 12 月），最不容易被一眼看出来，也最容易真的误期。
2. **凡事都标卡住。** 台账信息齐全却一律 `blocked` + 升级，等于把活原样退回给老板。判分器要求 `needs_owner_decision` 必须是 `false`，升级清单必须是空的。

**为什么排序是一条独立的判据**：台账里五条的排列顺序**刻意不是**截止顺序（台账序 MR-ANNUAL → CIT-Q3 → ICP-VERIFY → FIE-JOINT → SI-BASE，最早动手序 SI-BASE → ICP-VERIFY → FIE-JOINT → CIT-Q3 → MR-ANNUAL，两者完全错开）。照台账原样抄下来的清单，日期可以全对，但拿到手还是不知道先办哪件——而"我该先干什么"正是老板要这份日历的全部理由。

**判分器不写死期望值，而是从台账现算。** 这一对的定义就是"只差台账里一行"，期望值要是在判分器里手写两份，改语料时总有一份会忘。两道题共用同一份 `test_state.py`，靠解析台账区分该走哪条分支。

## agent 手里有什么

**什么都没有**（`tool:none`）。一份 markdown 台账，用 python/shell 直接读。没有数据源服务、没有网络对端、没有真 CLI，`rules` 构建期被摘掉。

这道题不需要 mock 任何东西——要考的是把活算完算全、排对顺序，不是连接器。

## 判分读什么

判据全部取自产物文件，外加一条开机自证。期望值不写死在判分器里，而是从判分镜像自带的那份台账**现算**——两道题共用同一份 `test_state.py`。

全程序判。逐条断言、以及每条红了算 0 分还是走 99，见下面的判分明细表。

<!-- 判分明细：由 scripts/gen_score_tables.py 生成，不要手改 -->

### 判分明细

`reward` 只有 0 和 1，**没有部分分**：下面 5 条断言全过才是 1，任意一条红了就是 0。

| # | 断言 | 流程 | 判什么 | 红了 |
|---|---|---|---|---|
| 1 | `test_every_obligation_is_listed` | #8 | 覆盖：台账里每一条都得有一项。算三条就交差在这里掉下来 | 0 分 |
| 2 | `test_due_dates_are_exact` | #14 | 截止日：算得出来的必须逐条精确对上 | 0 分 |
| 3 | `test_undated_obligation_is_flagged_not_invented` | — | 算不出来的那条：标出来，别编一个日期 | 0 分 |
| 4 | `test_calendar_agrees_with_json_and_is_sorted` | #2 | 步间一致性：给人看的清单必须和 JSON 对得上，且真按最早动手日排过 | 0 分 |
| 5 | `test_escalation_matches_whether_anything_is_blocked` | — | 两侧各自的漏洞都堵住：不许一律升级，也不许闷着不报 | 0 分 |

「流程」那一列对应[出题地图 5.3](../../../../docs/todo-no-preflight.md) 的验证流程全集，`—` 表示这条不属于那张表里的通用流程。

<!-- /判分明细 -->

## 本地怎么验

```bash
scripts/validate.sh tasks/legal/compliance-calendar/full-register
```

带 entrypoint（那条前置自证要在 agent 进来之前写），所以 `make smoke` 会跳过它，门槛在 `validate.sh`。

机制细节见 [docs/tools-and-fixtures.md](../../../../docs/tools-and-fixtures.md)。
