# 如何拓展

## 加一道新题

题目放在 `tasks/<职能>/<活>/<案例>/`。

先定**职能**：六个目录之一（`sales` / `delivery` / `support` / `finance` /
`legal` / `self`），一级目录必须是其中之一，不许新开。职能不再写成 `function:` 标签
——路径就是它唯一的事实来源。

再定**活**：这道题和哪道现成的题**同工具、同语料、同产物形状**？
是，就放进那件活的目录；不是，就在该职能下开一件新的活。
判据和命名规矩见[目录布局](what-is-opc-benchmark.md#目录布局职能--活--案例)。
还缺哪块题，看[覆盖地图](coverage-map.md)的覆盖矩阵，别凭印象挑。

```bash
harbor tasks init <案例名> --metadata-template configs/task-template.toml \
  --include-canary-strings -p tasks/<职能>/<活>/
scripts/sync-tasks.sh
```

然后按这个顺序写：

1. **先写判分器**（`tests/test_state.py`）
2. 再写题面（`instruction.md`）
3. 写 oracle 解法（`solution/solve.sh`）
4. `make check` 必须全绿，再 `scripts/validate.sh` 进真容器验一遍

**顺序不要反。** 先写题面十有八九会写出一道判不了的题——你会写出一个漂亮的场景，
然后发现「做得好不好」没法用字符串、数值或工具轨迹表达，最后只能退回去让模型当裁判。
先写判分器相当于先回答「我到底要量什么、量得出来吗」。

## 题面写多少

题面只写三样东西：

1. **处境** —— 你是谁、今天几号、老板在不在。这些推不出来。
2. **可供性** —— 机器上有哪些工具配好了、能不能向老板确认。这些**也推不出来**，
   而且删了会废掉判分：不知道退款工具存在而没退款，那不是克制；
   不知道可以问老板而没问，那不是自作主张。
3. **产物契约** —— 写到哪个绝对路径、什么 JSON 形状。判分器按这个读。
   输出路径一律写绝对路径：模型 `cd` 过一次，相对路径就落错地方，那是假红。

其余一律不写，包括这三类容易手滑写进去的：

| 不写 | 为什么 |
|---|---|
| 材料在哪个文件、目录长什么样 | `ls` 一下就有。写了等于替它想好了第一步 |
| 语料的格式说明（frontmatter、双链、CSV 有脏数据） | 打开文件就看得见；格式知识该由 skill 提供 |
| **该怎么做**（「不要用行业惯例补齐」「该办就办掉」「不能只做前几步」） | **这是在把答案写在题上。** 一个只有被叮嘱才守规矩的模型，量不出任何东西 |

最后一类最要命，因为它读起来最像"把题目说清楚"。判断方法：
**把这句话删掉，题目还量得出东西吗？** 量不出来，说明你量的本来就是"听不听话"，
不是那个母题。

（`decoy_prior` 是唯一的例外——诱饵先验必须是题面原文，见下。）

新题必须满足的硬条件（`make lint` 会逐条检查）：

- 挂全[四元标签](what-is-opc-benchmark.md#四元标签)
- `instruction.md` 和 `environment/`（Dockerfile 除外）里不许出现 canary、
  `BENCHMARK DATA`、「模拟工具」这类字样
- 拒答题必须有配对的对照题，且两者同模型、同遍数
- `pair:` 双向写死，且必须指向**同一件活的目录**里的题
- 一级目录必须是六个职能之一（`sales`/`delivery`/`support`/`finance`/`legal`/`self`）
- 二、三级目录名不许用标签取值（`motif`/`stage`/`tool`/`polarity` 的值）
- 不许写 `function:` 标签——职能由路径第一段唯一决定
- 题目里从 `opc/` 同步下来的那些副本必须是最新的（改完 `opc/` 要跑
  `scripts/sync-tasks.sh`，`make lint` 会用 `--check` 比对）
- `[metadata.opc]` 声明的镜像与 `Dockerfile` 的 `ARG` 默认值一致
- `tests/` 里有 `test.sh` 和 `test_state.py`，且 pytest 不在 `test.sh` 里现装
- README 里那张判分明细表与 `test_state.py` 一致（改完判分器跑
  `uv run python scripts/gen_score_tables.py` 重新生成，见下）

## 要用 skill 的题

skills **按名字点名下发**，在题目里放一份 `environment/skills.manifest`，
一行一个，对应 `opc/per-task/skills/` 下的目录名：

```
obsidian
```

然后 `scripts/sync-tasks.sh` 会把它铺进 `environment/skills/`。
**不点名就不发**——用不上的 skill 是纯噪声，还会诱 agent 去试不存在的工具，
理由见 [opc/per-task/skills/README.md](../opc/per-task/skills/README.md)。

清单放在 `skills/` 外面是有意的：题目的 Dockerfile 只 `COPY skills/`，
所以清单本身不进容器。

## 判分明细表

每份任务 README 的「判分读什么」一节里有一张**逐条判分表**：哪条断言、判什么、
红了是 0 分还是走 99。它由脚本从 `tests/test_state.py` 现读生成，不要手改：

```bash
uv run python scripts/gen_score_tables.py    # 改完判分器重跑
```

`make lint` 会重新生成一遍并比对，对不上就报错——判分表是最不能撒谎的那份文档，
看的人拿它判断「这道题到底在量什么」。

判分器里的测试函数**写不写 docstring 都行，但最好写**：第一行会直接进表的
「判什么」那一列。没写的话要在 `scripts/gen_score_tables.py` 的 `DESCRIPTIONS`
里补一句，否则生成时会报错——这是故意的，免得表里出现一行空白。

docstring 第一行以 `#<数字>` 开头时，那个编号会被拆进「流程」列，对应
[出题地图 5.3](todo-no-preflight.md) 的验证流程全集。

## 换成你自己的语料

题型和判分器与语料是分开的，这也是这个仓库真正想给你的东西。最快的路径：

1. 挑一道结构最接近你业务的题，复制整个任务目录
2. 只换 `environment/` 下的语料（`vault/`、`rules/`、`data/`、`inbox/`）和题面里的具体问题。
   只读工具按语料定去留：`environment/rules/platform_rules.json` 不在，`rules` 就不会
   出现在 agent 的 PATH 上（`opc/base/agents/svc/opc-prune-tools` 在构建期摘的）
3. 判分器里改掉写死的期望值（合同号、费率、金额）
4. `scripts/smoke.sh` 跑通。带 `environment/entrypoint.sh` 的题它会跳过——
   那类题的环境要在 agent 进来之前立起来（拉服务、摆权限、换登录态、删二进制），
   宿主机上复刻不了，门槛在 `scripts/validate.sh`

拒答题改完，**记得把它的对照题一起改**——那一对必须同源，否则对照就不成立了。

## 差分判分：换谁的账号都能程序判分

程序判分靠钉死的期望值，而期望值绑在「语料是我的」这个前提上。别人拿自己的账号跑，
`5%`、合同号、90000 这些全部失效，判分只能退回去让模型当裁判——那是这个仓库拒绝的东西。

**差分判分**绕开这一点：不预设答案，判分器用同一套凭证调同一个真 API 现场取真值，再比对。
声明方式见 `configs/task-template.toml` 的 `[metadata.opc]`，骨架在 `opc/per-task/verifier/oracle.py`。

三条硬约束（前两条 `make lint` 会check）：

1. **题面必须埋诱饵先验**（`decoy_prior`，且必须是 `instruction.md` 里的原文）。
   判分器调 API、agent 也调 API，比的是 API 跟它自己，只测得出「会不会用这个 API」。
   让它仍然是一道母题的，是那个具体、可算、且是错的先验——
   `m4` 题面里的「我印象里平台抽 50%、主播分 40%、通道费 2%」就是。
2. **判分器要声明它需要哪些凭证**（`verifier_credentials`），
   并且真的接进 `[verifier.environment.env]`。
3. **查询口径逐字对齐。** agent 和判分器的参数差一点，数字就对不上，
   而差异来自口径不是编造。口径写死在题面里，判分器用完全相同的参数调用。

判分因此变成三态，不再是两态：

| 情况 | reward |
|---|---|
| pytest 通过 | `1` |
| pytest 失败（agent 没做到） | `0` |
| 退出码 `99`：判分器自身失败（网络、凭证、限流） | **不写**，本次 trial 作废 |

第三态不能省。判分器调不通 API 跟 agent 答错是两回事，混成一个 0 分，
你从分数上看不出来，x5 重复下方差里混的全是网络。判分器拿到的真值会落
`/logs/verifier/oracle.json`，出了假阴性靠它复盘。

没有凭证时，题目自带 `tests/oracle_fake.json` 就能让 `make smoke` 照常钉基线——
那验证的是判分逻辑，真 API 的连通性由 `scripts/validate.sh` 在容器里验。

## 加一个新的 provider

改 `opc/base/agents/providers.py`：加前缀、base_url 默认值、key 环境变量，
并在 `tests/test_providers.py` 里补上路由测试。

**不要加兜底。** 现在不在表里的 provider 直接报错，这是故意的——
悄悄兜底到另一条链路，等于测了个别的东西，而你从分数上看不出来。

## 加一个新的 agent

`opc/base/agents/` 一个子模块一种 agent。新 agent 需要：

1. 一个 harbor 适配器（照 `hermes.py` 的样子写，`install()` 只做存在性校验）
2. 一个预烘好它的基础镜像（照 `opc/base/agents/Dockerfile`）
3. 在 `Makefile` 里加构建目标

**别在 `install()` 里装东西。** 运行时装包意味着每道题每次 trial 都联一次网，
而且版本在 trial 时才解析——两次跑分用的可能不是同一个 agent。

## 改完之后

```bash
make check                    # lint + unit + smoke，不需要 Docker
scripts/validate.sh           # 需要 Docker，在真容器里再验一遍
```

改了 `opc/per-task/datasources/` 或 `opc/per-task/verifier/` 的话，先 `scripts/sync-tasks.sh`；
改了 `opc/base/bin/`、`opc/base/pylib/`、`opc/base/etc/` 的话，要重建基础镜像 `make image`
同步到各任务目录，否则你改的是源、跑的是旧副本。

## 预检题：动手之前的那一步

预检题判的是「动手前该确认的确认没确认」，它和别的题型有一条额外的硬约束：
**判分第一步必须先证明前置条件真的塌了**。镜像哪天变了、token 意外没过期、
二进制意外还在，agent 顺顺当当做完也会被判成「做了预检」——拿的是假分。

三件配套设施都在仓库里，照抄即可：

| 要什么 | 用什么 | 在哪 |
|---|---|---|
| 前置失败/补救/编造/绕行的公共断言 | `import preflight` | `opc/per-task/verifier/preflight.py`，`sync-tasks.sh` 铺进每道题的 `tests/` |
| 「环境此刻是坏的」这条事实 | `_record-env <事实名> ok\|fail [说明]` | 在 `environment/entrypoint.sh` 里调，agent 进来之前就写死 |
| 「agent 敲了个不存在的命令」 | `BASH_ENV=/opt/opc/bashenv.sh` | 挂 `command_not_found_handle`，留痕后照常 127 |
| 「该问老板而没问」 | `environment/clarify.json` 应答表 + `OPC_CLARIFY_SCRIPT` | 判三段：问没问 / 命中的是不是那条规则 / 有没有照答复做。歧义可以长在业务口径上（`dunning`），也可以长在工具与数据源的选择上（`mail`：两个信箱都能给出答案） |

两条铁律：

1. **失败必须由环境确定性地造出来**，不能靠题面描述——过期 token 写死在 entrypoint、
   二进制从镜像里删掉、目录 `chmod 0555`。设计意图担保不了「换个场景也失败」。
2. **对照题必须同工具**。前置条件是绑在具体工具上的：token 过期是 401、
   二进制不在是 127、目录只读是 EACCES，失败面各不相同，能力在工具之间不传递。
   歧义类的也一样：`mail` 那一对两边都装着 `gam` 和 `himalaya`、语料一模一样，
   只差老板留言里那一句有没有点名信箱。
