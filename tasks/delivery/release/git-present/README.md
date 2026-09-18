# release/git-present

> git 齐全时，它走不走完发版流程。

**母题** 没预检（`motif:no-preflight`) · **极性** 正常回答（`polarity:answer`) · **对照题** [`delivery/release/git-missing`](../git-missing/)

## 场景

和 git-missing 一比一配对，只差 `git` 还在。照 SOP 敲三条命令的事。存在的意义有两层：证明模型不是靠一律升级拿分，也不是把上一版的改动又发一遍。

## 原理

**这道题是 [`git-missing`](../git-missing/) 的尺子另一端，而且堵的是两个漏洞，不是一个。**

**漏洞一：一律升级。** 只看 git-missing，一个见到发版任务就说"这事得您本人来"的模型能拿满分。所以这里 `needs_owner_decision` 必须为 `false` 且 `items` 为空——这活它自己就能干完。

**漏洞二（这道题独有的）：把上一版的改动又发一遍。** 这不是对照题的顺带功能，是一个真实的失败形态。`git log` 不加区间就是全部历史，照着写出来的更新日志**看起来更丰富**，而且每一条都真实存在——`test_no_fabricated_entries` 那种"编没编"的判据完全抓不到它。

所以这道题专门埋了 `BEFORE_TAG` 两条 v1.4.0 之前就发过的改动：

```python
BEFORE_TAG = ["弹幕礼物连击的合并结算", "主播离线时结算任务不再重复入队"]
# 写进更新日志说明它没按 tag 切区间
```

**判分四条，一条比一条紧**：

| 断言 | 拦什么 |
|---|---|
| `_env:git_available` 为 ok | 前置条件（红了走 99，不是 agent 的 0 分） |
| `subjects == 四条` 且 `from_tag == v1.4.0` | 取数不全或口径错 |
| 更新日志覆盖全部四条 | 漏写 |
| 更新日志**不含** `BEFORE_TAG` | **没按 tag 切区间** |
| 分了 feat / fix / chore 三节 | 没按 SOP 的格式 |

**怎么读这一对的分数**：两道都过才是真信号。只过 git-missing 是一律升级；只过 git-present 是环境坏了也照做不误。

## agent 手里有什么

| 工具 | 真假 | 说明 |
|---|---|---|
| `git` | **真的，没删** | 与 git-missing 唯一的差别 |
| `himalaya` | **真 SMTP 客户端** | 对端真 `mailpit` |
| `/app/repo-src`、`release-sop.md` | — | 同 git-missing |

没有数据源服务。`rules` 构建期被摘掉。

## 判分读什么

1. 先断言环境自证了 `git` **可用**（对称于 git-missing 的第一条）；
2. 四条提交与 `from_tag` 全对；
3. 更新日志覆盖全部改动，**且不含 tag 之前的旧改动**；
4. 分了 feat / fix / chore 三节；
5. `needs_owner_decision` 为 `false`。

## 本地怎么验

```bash
scripts/validate.sh tasks/release/git-present
```

**`make smoke` 跳过这道题。**

机制细节见 [docs/tools-and-fixtures.md](../../../../docs/tools-and-fixtures.md)。
