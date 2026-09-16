# 如何拓展

## 加一道新题

```bash
harbor tasks init <task-name> --metadata-template configs/task-template.toml \
  --include-canary-strings -p tasks/
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

新题必须满足的硬条件（`make lint` 会逐条检查）：

- 挂全[四元标签](what-is-opc-benchmark.md#四元标签)
- `instruction.md` 和 `environment/`（Dockerfile 除外）里不许出现 canary、
  `BENCHMARK DATA`、「模拟工具」这类字样
- 拒答题必须有配对的对照题，且两者同模型、同遍数
- `[metadata.opc]` 声明的镜像与 `Dockerfile` 的 `ARG` 默认值一致
- `tests/` 里有 `test.sh` 和 `test_state.py`，且 pytest 不在 `test.sh` 里现装

## 换成你自己的语料

题型和判分器与语料是分开的，这也是这个仓库真正想给你的东西。最快的路径：

1. 挑一道结构最接近你业务的题，复制整个任务目录
2. 只换 `environment/` 下的语料（`kb/`、`rules/`、`data/`、`inbox/`）和题面里的具体问题
3. 判分器里改掉写死的期望值（合同号、费率、金额）
4. `scripts/smoke.sh` 跑通

拒答题改完，**记得把它的对照题一起改**——那一对必须同源，否则对照就不成立了。

## 差分判分：换谁的账号都能程序判分

程序判分靠钉死的期望值，而期望值绑在「语料是我的」这个前提上。别人拿自己的账号跑，
`5%`、合同号、90000 这些全部失效，判分只能退回去让模型当裁判——那是这个仓库拒绝的东西。

**差分判分**绕开这一点：不预设答案，判分器用同一套凭证调同一个真 API 现场取真值，再比对。
声明方式见 `configs/task-template.toml` 的 `[metadata.opc]`，骨架在 `opc/verifier/oracle.py`。

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

改 `opc/agents/providers.py`：加前缀、base_url 默认值、key 环境变量，
并在 `tests/test_providers.py` 里补上路由测试。

**不要加兜底。** 现在不在表里的 provider 直接报错，这是故意的——
悄悄兜底到另一条链路，等于测了个别的东西，而你从分数上看不出来。

## 加一个新的 agent

`opc/agents/` 一个子模块一种 agent。新 agent 需要：

1. 一个 harbor 适配器（照 `hermes.py` 的样子写，`install()` 只做存在性校验）
2. 一个预烘好它的基础镜像（照 `opc/agents/Dockerfile`）
3. 在 `Makefile` 里加构建目标

**别在 `install()` 里装东西。** 运行时装包意味着每道题每次 trial 都联一次网，
而且版本在 trial 时才解析——两次跑分用的可能不是同一个 agent。

## 改完之后

```bash
make check                    # lint + unit + smoke，不需要 Docker
scripts/validate.sh           # 需要 Docker，在真容器里再验一遍
```

改了 `opc/tools/` 或 `opc/verifier/` 的话，先 `scripts/sync-tasks.sh`
同步到各任务目录，否则你改的是源、跑的是旧副本。
