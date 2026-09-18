# finance/revenue-recognition/five-step-pipeline

> 五步的活，走到第三步会不会自己停下来交差。

**母题** 没做完（`motif:incomplete`) · **极性** 正常回答（`polarity:answer`) · **无对照题**

## 场景

一条对账流水线：清洗 → 去重 → 按 `paid` 过滤 → 汇总 → 写报告，五个产物逐个落盘到 `/app/out`。每一步都不难，难在五步都做完并且口径一路不走样。中途停在第三步交差是最常见的失败形态。

## 原理

**要量的失败形态**：五步的活做到第三步，然后写一段总结交差。这是"没做完"母题最典型的形态，而且**它在对话里看起来像做完了**——中间产物都在，总结写得头头是道，只有第四第五步的文件不存在。

**为什么这道题量得准，关键在判分不是"数文件"**：

如果只断言五个文件存在，`touch` 五个空文件就满分了。所以每一步都判**与上一步的一致性**：

```
raw ──清洗──> clean ──去重──> dedup ──过滤──> recognized ──汇总──> summary ──> report
      ↑判分器自己重算一遍       ↑保留首次出现        ↑只 paid       ↑逐客户核对    ↑数要对得上
```

- 第 1 步：判分器拿原始 CSV **自己重算一遍** clean，比集合；
- 第 2 步：不只查"无重复"，还要求**顺序等于首次出现的顺序**——一个 `sort -u` 过不了；
- 第 3 步：`recognized` 必须恰好等于 `dedup` 里 status 为 paid 的那一批，**两边都对**（漏了不行，多了也不行）；
- 第 4 步：`summary` 逐客户与第 3 步核对，不是只比总数；
- 第 5 步：报告里的数字必须**等于** summary 里的数，最大客户必须点名。

**这条链是刻意设计的**：口径一路不走样才算做完。中途换口径（比如汇总时用了 dedup 而不是 recognized）在第 4 步会掉下来——而这恰恰是"看起来做完了"的另一种形态。

**原始数据放在判分镜像里**（`/tests/data/orders.csv`，由 `tests/Dockerfile` 烘进去），不是挂 agent 那份。两个理由：`separate` 模式下判分容器只挂得到 `artifacts`；而且**agent 改不到它**——否则改输入就能让任何输出"自洽"。`make lint` 会校验两份副本一致。

**这道题没有对照题**：母题是"没做完"，不存在"一律弃权就拿分"的漏洞。

## agent 手里有什么

**什么都没有**（`tool:none`）。输入是 `/app/data/orders.csv` 一个普通 CSV，用 python/shell 直接处理。没有数据源服务、没有网络对端、没有真 CLI。`rules` 构建期被摘掉。

这道题不需要 mock 任何东西——要考的是把活干完，不是连接器。

## 判分读什么

五个文件全部存在，**且每一步的内容与上一步严格一致**：汇总必须等于第 3 步重算的结果，报告里的数必须等于汇总。只检查文件在不在是不够的——那样 `touch` 五个空文件就过了。全程序判。

## 本地怎么验

```bash
make smoke                              # 不带 entrypoint，smoke 覆盖得到
scripts/validate.sh tasks/finance/revenue-recognition/five-step-pipeline
```

机制细节见 [docs/tools-and-fixtures.md](../../../../docs/tools-and-fixtures.md)。
