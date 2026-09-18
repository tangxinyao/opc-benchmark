# agent skills（预烘进任务镜像）

来源：https://github.com/kepano/obsidian-skills
钉死 commit：`3ccff5338ea700537839b21900aa5358a0402c98`

版本钉死的理由和 hermes/dws/himalaya 一致——浮动的 skill 版本等于浮动的结论。
升级时重新 vendor 并更新这里的 SHA，别让它跟着 main 漂。

## 只收了三个，故意的

| skill | 收 | 理由 |
|---|---|---|
| `obsidian-markdown` | ✅ | 纯格式知识：wikilink、frontmatter、callout |
| `obsidian-bases` | ✅ | 纯格式知识：`.base` 的 YAML 结构 |
| `json-canvas` | ✅ | 纯格式知识：`.canvas` 的 JSON spec |
| `obsidian-cli` | ❌ | 要求 Obsidian 桌面进程活着（且是 Catalyst 权益），容器里起不来 |
| `defuddle` | ❌ | SKILL.md 写着 `npm install -g defuddle`。题目改成 public 之后它未必再卡死，但让 agent 在跑题时现装 npm 包，本身就是不该有的变量 |
| `knap` | ❌ | 同上，`npm install -g knap`，且要 Node 20+ |

被排除的三个共同的问题不是"跑不起来"，而是**模型会照着 SKILL.md 去试**：
装不上的包、连不上的进程，每一次尝试都是烧掉的任务预算，
失败之后还分不清是 agent 能力不行还是环境坑了它。判分面越窄越好。

收下的三个对 vault 里的纯文件操作足够了——agent 用 `rg`/`cat` 读，
靠这三个 skill 知道 frontmatter 和 wikilink 该怎么解析、怎么写。
