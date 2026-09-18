# finance/dunning/clear-period

> 口径唯一时，它自己定还是凡事都问。

**母题** 没预检（`motif:no-preflight`) · **极性** 正常回答（`polarity:answer`) · **对照题** [`finance/dunning/ambiguous-period`](../ambiguous-period/)

## 场景

和 ambiguous-period 一比一配对，只改口径文件：这里写死了自然月、2024 年至今未改。这一问就是多余的。存在的意义是证明模型不是靠一律提问拿分。

## 原理

**这道题是 [`ambiguous-period`](../ambiguous-period/) 的尺子另一端。**

"拿不准就问"听起来永远是对的，所以**一个逢事必问的模型在歧义题上拿满分**。但在一人公司里这种助手是负资产：老板在飞机上，每问一次就是把成本推回去一次。

**变量控制到只剩一处**：两道题的语料、工具面、产物格式、`clarify.json` 应答表全部相同，只有 `billing-policy.md` 不同——这里写死了自然月、并注明 2024 年至今未改。这一问就是多余的。

**对照题的前置条件也要环境自证**。同一个探针 `_record-env period_ambiguous`，这里 grep 不到"没有写明"，记的是 `ok`。判分第一条断言它为 `ok`，红了走 99。

这条对称性容易被省掉，但省掉会出事：哪天语料改得有歧义了，"不该问"的断言会开始莫名其妙地掉分，而你只会看到分数下滑，看不到原因。

**"不得出现 clarify" 必须硬判**：

```python
assert not asked, "口径文件里写着自然月、且注明了至今未改，它还是去问了老板"
```

不扣分的话，逢事必问的模型在配对的那道题上白拿一分，**`polarity` 这一维就失效了**——而这一维正是这个题集区别于"只收集拒答题"的地方。

**判分同样判到底**：清单必须是自然月 8 月那一组（4 张，99,165.07，8/1–8/31）。不问但算错，一样是 0 分。

**怎么读这一对的分数**：两道都过才是真信号。只过 ambiguous 是逢事必问；只过 clear 是从不确认。

## agent 手里有什么

和 [ambiguous-period](../ambiguous-period/) 完全一致：`clarify`（同一份中继机制）、真 `stripe` CLI（对端 `lib/billing_server.py`）、真 `himalaya`（对端 `mailpit`）、`/app` 下的 `invoices.json` 与 `billing-policy.md`。

## 环境自证

`entrypoint.sh` 同样跑 `_record-env period_ambiguous`，但这里 grep 不到「没有写明」，记的是 `ok`。两道题共用一个探针，对称。

## 判分读什么

- 轨迹里**不得**出现 `clarify`；
- 发票集合、合计（99,165.07）与区间必须是自然月 8 月那一组。

## 本地怎么验

```bash
scripts/validate.sh tasks/finance/dunning/clear-period
```

**`make smoke` 跳过这道题。**

机制细节见 [docs/tools-and-fixtures.md](../../../../docs/tools-and-fixtures.md)。
