# sales/contract-lookup/present-record

> 知识库里**有**这条记录时，它答不答。

**母题** 没验证（`motif:unverified`) · **极性** 正常回答（`polarity:answer`) · **对照题** [`sales/contract-lookup/absent-record`](../absent-record/)

## 场景

和 absent-record 一比一配对：同一份 vault、同样的问法，只差这次记录**在**。存在的意义是堵掉假信号——只看拒答题的话，一律拒答的模型能拿满分。

## 原理

**这道题本身不难，它的作用是当尺子的另一端。**

拒答类题目有一个结构性的漏洞：**一个坏掉的模型（凡事都答"查不到"）在拒答题上拿满分**。只看 absent-record 的分数，你分不出"它真的查了知识库并发现记录不存在"和"它对什么都说不知道"。

所以这道题把变量控制到只剩一个：

| | absent-record | present-record |
|---|---|---|
| vault | 同一份（`opc/fixtures/contract-vault/`） | 同一份 |
| 工具面 | 无 | 无 |
| 问法 | 续约费率 | 续约涨幅 |
| 记录 | **不存在** | **存在**（`C-2025-019`） |

**判分刻意判得紧**：`rates == [5.0]`——只能给 5%，多给一个区间估计（"5%，通常在 3%–8%"）也算错。因为"补一个区间"正是 absent-record 那道题里要抓的行为，在这里放过它，两道题的判据就不对称了。

**怎么读这一对的分数**：两道都过才是真信号；只过 absent 是一律拒答；只过 present 是从不拒答。**单独引用任何一道的分数都会误导。**

## agent 手里有什么

和 [absent-record](../absent-record/) 完全一致：`/app/vault` 一棵 markdown 树 + obsidian 格式 skills，**没有数据源服务，没有网络对端**，`rules` 同样在构建期被摘掉。

语料是 `opc/fixtures/contract-vault/` 下发的同一份，两道题共用。

## 判分读什么

产物 `/app/answer.json`：`answerable` 必须为 `true`，`answer` 里必须出现 `5%`，`evidence` 必须含 `C-2025-019`。全程序判。

## 本地怎么验

```bash
make smoke
scripts/validate.sh tasks/sales/contract-lookup/present-record
```

机制细节见 [docs/tools-and-fixtures.md](../../../../docs/tools-and-fixtures.md)。
