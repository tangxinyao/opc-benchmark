# 覆盖地图与目录重组方案

**状态：第九节的第 1、2 步已执行（`b6fa6b3` 起）。** 目录已是三级，`function:` 标签已删，`todo-no-preflight.md` 第二节已改成指向本文。
剩下的是第 3 步：按第六节的 backlog 出新题，一对一对来。四条决策见第十节。

这篇管两件事：

1. **目录按职能重组**——让「哪块活没人做」从 `ls` 就看得出来，而不是查表；
2. **覆盖矩阵**——树只能按一个轴组织，其余的轴（母题、阶段、工具链五段）在这里管。

它取代 [出题地图](todo-no-preflight.md) 第二节那张覆盖表——那张表已经过时
（`legal × no-preflight` 还写着 `archive ×2`，那对题在 `58bf603` 删掉了）。

---

## 一、为什么要改

现在是 `<场景>/<案例>` 两级，分类维度全在标签里。这个设计当初是对的，理由也写清楚了：
**两边都写，迟早对不上。**

但它有个代价，这次盘覆盖时暴露出来了：**缺口在标签里看不见。**
`ls tasks/` 看到八个场景，看不出「法务与合规一道题都没有」。要发现这件事，
得把 14 个 `task.toml` 的标签统计一遍——也就是说，**没人会定期发现它**。

分布现状（14 道题）：

```
function  ops 5 · finance 5 · sales 3 · legal 1 · self 0
stage     operate 11 · build 2 · plan 1
motif     no-preflight 6 · no-boundary 3 · unverified 2 · incomplete 1 · no-allocation 1
tool      required 9 · unavailable 2 · none 2 · trap 1
```

## 二、和现有规则的冲突，以及解法

`scripts/check_tasks.py` 现在强制：

```python
RESERVED_PATH_WORDS = {v for values in TAG_VOCABULARY.values() for v in values}
# 路径只说「这是哪件活」，分类维度一律在 tags 里。两边都写，迟早对不上。
```

一级目录改成职能，恰好就是 `function` 的取值——正是这条规则禁掉的事。

**解法不是放宽规则，是删掉标签那一份。** 让路径成为 `function` 的唯一事实来源，
`task.toml` 里不再写 `function:`。这样原规则的本意（不要有两个事实来源）反而被更严格地守住了。

规则相应反转：

| | 旧 | 新 |
|---|---|---|
| 一级目录 | 不许用标签取值 | **必须**是六个职能之一 |
| 二、三级目录 | 不许用标签取值 | 不变 |
| `function:` 标签 | 必写 | **删除**，由路径推导 |
| `pair:` | 必须同**场景**目录 | 必须同**一件活**目录 |

## 三、目录结构

对照题必须住在同一个目录下（`pair:` 的 lint 依赖这一点），所以要三级：

```
tasks/<职能>/<做什么事>/<案例>/
       │        │          └─ 一道题：instruction.md / task.toml / tests/ / solution/ / environment/
       │        └─ 一件活：一比一的对照题住在一起
       └─ 六个职能之一
```

六个职能直接对应[出题地图第一节](todo-no-preflight.md)：

| 目录 | 地图里的名字 | 原 `function` 值 |
|---|---|---|
| `sales/` | 获客与分发 | `sales` |
| `delivery/` | 交付与产品 | `ops` + `stage:build` |
| `support/` | 客服与运营 | `ops` |
| `finance/` | 财务与对账 | `finance` |
| `legal/` | 法务与合规 | `legal` |
| `self/` | 自我管理与调度 | 无（`function:self` 一直挂着没定） |

**注意 `ops` 要拆成两块。** 现在一个 `ops` 同时盖着「交付与产品」和「客服与运营」，
这两块的活、工具、坏法都不一样，混在一个值里看不出哪块空。

## 四、14 道老题迁移映射

全部 `git mv`，保历史。**一道不删、内容一个字不改**，只动位置和标签。

| 现在 | 迁到 |
|---|---|
| `contract/absent-record`、`contract/present-record` | `sales/contract-lookup/` |
| `email/pressure-demand`、`email/routine-request` | `support/customer-email/` |
| `mail/ambiguous-source`、`mail/single-source` | `support/inbox-triage/` |
| `dunning/ambiguous-period`、`dunning/clear-period` | `finance/dunning/` |
| `settlement/expired-session`、`settlement/platform-fee-change` | `finance/settlement/` |
| `revenue/five-step-pipeline` | `finance/revenue-recognition/` |
| `release/git-missing`、`release/git-present` | `delivery/release/` |
| `launch/self-review` | `self/plan-review/` |

`contract` 那一对归 `sales` 而不是 `legal`，依据是地图 §1：
获客的坏法就是「客户问的合同条款知识库里没有，张口安一个」。

### 迁移会逼出一个既存错误

`email/pressure-demand` 挂 `function:legal`，`email/routine-request` 挂 `function:sales`
——**一对一比一的对照题，职能标签不一样**。

一比一对照的定义是「只变前置条件，其余全不动」，职能当然也不该变。现在两边都写所以没人发现；
改成目录树之后它们必须住在同一个目录里，冲突藏不住。这是重组的附带收益，不是新增的工作量。

## 五、迁完之后的树

```
tasks/
  sales/       contract-lookup/     (2)
  delivery/    release/             (2)
  support/     customer-email/      (2)
               inbox-triage/        (2)
  finance/     dunning/             (2)
               settlement/          (2)
               revenue-recognition/ (1)
  legal/       ← 空
  self/        plan-review/         (1)
```

**`legal/` 是空的。** 这就是这次重组要的效果：缺口不用查表，`ls` 一下就在那儿。

## 六、backlog 落位

[出题地图](todo-no-preflight.md)「下一批候选」四条，加上按工具链五段盘出来的五条：

| 职能 | 活 | 案例 | 来源 | 填哪个空 | 成本 |
|---|---|---|---|---|---|
| `sales` | `quote-consistency` | 2 | A4 | sales × unverified，断言 #16 | 低 |
| | `content-publish` | 2 | A9+A6 | **真获客**（twurl），429 退避 | 高 |
| | `funnel-review` | 2 | A10 | sales·operate 漏斗 | 高 |
| `delivery` | `publish` | 2 | A5 | **登录段**（`gh` 未登录），build 加厚 | **最低** |
| `support` | `inbox-triage` | +2 | A7 | **查询段**（batch 部分失败），断言 #15 | 低 |
| | `vendor-approval` | 2 | A2 | ops × no-boundary 的**上游方向** | 中 |
| `finance` | `reconciliation` | 2 | A3 | 不平不许凑平，断言 #15/#17 | 中 |
| `legal` | `compliance-calendar` | 2 | A1 | **legal 整块空白**，断言 #14 | 低 |
| `self` | `self-check` | 2 | A8 | **验证段（全空）** | 中 |

**总数：14 现有 + 18 新增 = 32 道题，6 个职能，14 件活。**

（`content-publish` 把「内容发布」这个载体和「429 限流」这个失败面合成了一对。
将来要把「该不该发」这条边界也考进去，它可以长到 4 个案例。）

## 七、覆盖矩阵

树按职能组织，所以其余的轴在这里管。**这张表是判断「还缺什么题」的尺子**，
出新题前先看它。

### 7.1 职能 × 母题

`+` 是 backlog，空格是缺口。

| | incomplete | unverified | no-boundary | no-allocation | no-preflight |
|---|---|---|---|---|---|
| sales | | contract ×2<br>+quote-consistency | | +funnel-review | +content-publish |
| delivery | | | | | release ×2<br>+publish |
| support | | | customer-email ×2<br>+vendor-approval | | inbox-triage ×2<br>+inbox-triage(batch) |
| finance | revenue | | | settlement/fee-change<br>+reconciliation | settlement/expired<br>dunning ×2 |
| legal | +compliance-calendar | | | | |
| self | | +self-check | plan-review | | |

做完 backlog 之后仍然空的：**sales × incomplete / no-boundary**、
**delivery × 前四个母题**、**legal × 后四个母题**、**self × 两个**。

### 7.2 工具链五段

一次真实的连接器调用分五段。现状：

| 段 | 现有覆盖 | backlog 补上 | 仍缺 |
|---|---|---|---|
| **登录** | 1 道（`settlement/expired` 的 401→补登录态） | +`delivery/publish`（`gh` 未登录） | scope 不足、OAuth 授权过期、多账号选错 |
| **查询** | 1 道（`settlement/fee-change` 的分页） | +`inbox-triage(batch)`、+`content-publish`(429) | 游标失效、结果为空 vs 查询写错 |
| **推理** | 4 道（settlement ×2、dunning ×2） | +`reconciliation` | — |
| **验证** | **0 道** | +`self-check` | 交叉验证、异常值自检 |
| **展示** | **0 道** | — | 程序判分的天花板，见 7.3 |

### 7.3 两个说清楚的天花板

- **展示测不了。** 判分器只读产物文件和审计日志，`report.md` / `CHANGELOG.md` 都只能判
  「数值出现没出现」。要判展示质量就得让模型当裁判，那违反本仓库第一条铁律。
- **「做什么」永远是给定的。** 14 道题的题面都附了产物契约（写到哪、什么 JSON 形状）。
  真实的一人公司最难的是决定今天该干什么；程序判分要求有契约，所以这一层测不到。
  这是设计代价，不是疏漏。

## 八、要改的代码

路径从两级变三级，所有按 `tasks/*/*/` 遍历的地方都要动：

| 文件 | 改什么 |
|---|---|
| `scripts/sync-tasks.sh` | `tasks/*/*/` → `tasks/*/*/*/` |
| `scripts/smoke.sh` | 同上 |
| `scripts/validate.sh` | `find -maxdepth 2 -mindepth 2` → `3 / 3` |
| `scripts/check_tasks.py` | 路径解析；`RESERVED_PATH_WORDS` 规则反转；`pair:` 改成同「活」校验；`REQUIRED_TAG_PREFIXES` 与 `TAG_VOCABULARY` 去掉 `function` |
| `scripts/gen_job_configs.py` | 任务路径 |
| `configs/jobs/*.yaml` | 写死的任务路径 |
| 14 份 `task.toml` | 删掉 `function:` 那一项（见 10.1） |
| 14 份 `tasks/**/README.md` | 相对链接 `../../../docs/` → `../../../../docs/` |
| `README.md`、`docs/` ×5 | 目录布局那几节，含 `extending.md` 里「目录名不许用标签取值」那条 |

`environment/` 和 `tests/` 内部不受影响——它们用的都是容器内绝对路径
（`/app`、`/var/lib/opc`、`/tests`）。

## 九、执行顺序

**迁移和出新题分两步走，各自提交。** 混在一起的话基线红了分不清是谁弄的。

1. ~~`git mv` 14 道题 + 改脚本 + 改文档 → `make check` 全绿 → 提交~~ ✅ `b6fa6b3`
2. ~~订正 `todo-no-preflight.md` 第二节那张过时的覆盖表，改成指向本文~~ ✅
3. ← **在这里**。按「解锁 ÷ 成本」出新题，一对一对来，每对都全绿再进下一对。
   建议第一批：`delivery/publish`（最低成本，补登录段）、
   `support/inbox-triage(batch)`（补查询段）、
   `legal/compliance-calendar`（legal 整块空白）

## 十、已决策

四条都定了，理由记在这里——推翻它要先驳倒理由，不要重新提案。

### 10.1 `function` 标签删掉，由路径推导 ✅

一级目录就是职能，标签再写一遍就是两个事实来源，而
`RESERVED_PATH_WORDS` 那条规则存在的全部理由就是「两边都写，迟早对不上」。
删掉标签这一份，规则的本意守得更严，不是更松。

**下游影响确认过了，很小**：`gen_job_configs.py` 读 tags 只用于按 `pair:` 分组
（第 47 行），并不写进 job yaml（第 114 行只输出 `path`）。所以改动面只有三处：
`check_tasks.py` 的 `REQUIRED_TAG_PREFIXES` 和 `TAG_VOCABULARY`，加 14 份 `task.toml`。

归因分析要按职能分组时从路径第一段取，和从标签取是同一个值，但**不会再出现两者不一致**。

保留的标签：`motif:` / `stage:` / `tool:` / `polarity:` / `pair:`。
它们都推不出来——`stage` 尤其不行，`delivery/` 下面既可以有 `build` 的活（发版），
也可以有 `operate` 的活（线上巡检）。

### 10.2 `ops` 拆成 `delivery` / `support` ✅

两块的活、工具、坏法都不一样：交付的坏法是**半成品当成品**，客服的坏法是**越界**。
混在一个 `ops` 值里，正好把 `stage:build` 那个空格盖住了——这次盘覆盖之前没人发现。

**因为 10.1 已经决定删标签，这一条几乎是免费的**：不需要改 5 道题的 `function:` 值，
只是目录分成两个。原先估的「会动 5 道现有题的标签」不成立。

### 10.3 `function:self` 这个问题消失了 ✅

`docs/todo-no-preflight.md` 的「待决策」里挂了很久的「要不要给 `function:` 加第五个值」，
随 10.1 一起解决：**`function:` 这一维整个没了，也就不存在加不加值的问题。**
`self/` 作为目录确立，`launch/self-review` 迁进去，不再借挂在 `finance` 下。

这是本次重组一个没预料到的收益——那个问题之所以难定，是因为它长在一根本来就多余的轴上。

### 10.4 迁移和出新题分两步，各自提交 ✅

混在一起的话基线红了分不清是迁移弄的还是新题弄的，而这个仓库的整条纪律就是
oracle 满分 / nop 零分那条基线。第九节的顺序照此执行。

**迁移那一步的验收标准**：`make check` 全绿，且 14 道题的 `reward` 与迁移前逐题一致
——迁移不该改变任何一道题的判分结果。
