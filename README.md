# opc-benchmark

一人公司（one-person company）场景下的 **Agent 评测集**，跑在
[Harbor](https://github.com/harbor-framework/harbor) 上。

题目围绕一人公司最常见的四个失败母题设计——**没做完、没验证、没边界、没有分配权**。
每道题都**程序判分**，没有一道靠模型当裁判。

> 这不是一个基准，是一个**模板**。语料是我自己的，所以分数你不用信；
> 题型和判分器可以直接拿走，把语料换成你的。

## 快速开始

前置：**Docker** 和 **uv**。全程在仓库根目录执行。

```bash
uv sync                                   # 1. 装依赖
make images HERMES_VERSION=v2026.9.14     # 2. 构建 agent / 判分两个基础镜像
cp .env.example .env && $EDITOR .env      # 3. 填模型凭证
scripts/validate.sh                       # 4. 钉基线：oracle 满分、nop 零分
make run CONFIG=configs/jobs/job-deepseek-x3.yaml   # 5. 跑
```

**第 4 步不要跳。** nop 能通过的题量不出任何东西，oracle 过不了的题量的是你的判分器。
每一步的细节、三个测试级别、以及会绊人的坑，见 [开始使用](docs/getting-started.md)。

## 七道题

| 任务 | 母题 | 在问什么 |
|---|---|---|
| `m1-incomplete-five-step-pipeline` | 没做完 | 五步的活，走到第三步会不会自己停下来交差 |
| `m2-unverified-absent-record` | 没验证 | 知识库里**没有**这条记录时，它编不编 |
| `m2-unverified-present-record` | 没验证（**对照**） | 知识库里**有**这条记录时，它答不答 |
| `m3-boundary-customer-pressure` | 没边界 | 客户施压时，它替不替你退款、签字、承诺赔付 |
| `m3-boundary-routine-request` | 没边界（**对照**） | 请求在授权范围内时，它办不办事，还是一律升级 |
| `m3-boundary-self-review` | 没边界（自审） | 让它评审一份自己人写的方案，四处硬伤找不找得全 |
| `m4-no-allocation-platform-fee` | 没有分配权 | 平台费率变了，它查不查，还是凭印象答 |

每道「该拒答」的题都配一道一比一的「该正常回答」对照题——**只看拒答题，
一律拒答的模型能拿满分**，那是假信号。

## 文档

| 文档 | 讲什么 |
|---|---|
| [什么是 opc-benchmark](docs/what-is-opc-benchmark.md) | 它在量什么、题目一览、三条设计立场、四元标签 |
| [开始使用](docs/getting-started.md) | 五步跑起来、三个测试级别、凭证、排错、常见的坑 |
| [项目结构](docs/project-structure.md) | 每个目录干嘛的、判分链 harbor 管哪段、跑法怎么配 |
| [如何拓展](docs/extending.md) | 加新题、换成你自己的语料、差分判分、加 provider / agent |

背景材料：[一人公司案例集](docs/一人公司案例集.md)（母题的出处与统计）、
[初创公司智能化全套材料](docs/初创公司智能化全套材料.md)（讲稿）。

## 常用命令

```bash
make check       # lint + unit + smoke，不需要 Docker，改完先跑这个
make configs     # 由 configs/policy.toml 和各题声明生成 configs/jobs/
make env-check   # 检查凭证是否就位（只报在不在，不打印值）
make images      # 构建两个基础镜像
```
