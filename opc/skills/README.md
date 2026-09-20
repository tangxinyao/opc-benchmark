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

---

# 怎么发给某道题

在题目里放一份 `environment/skills.manifest`，一行一个目录名：

```
obsidian
aliyun-cli
```

`scripts/sync-tasks.sh` 照着它铺进 `environment/skills/`，**没点名的一律不发**。
`opc/skills/<name>/` 有两种形状，落点都会是 `HERMES_HOME/skills/<skill>/`：
根下有 `SKILL.md` 的（`aliyun-cli`）本身就是一个 skill；根下没有的
（`obsidian`）是个合集，里面每个子目录才是 skill。

---

# aliyun-cli（发布类题目用）

发给 `tasks/delivery/release/` 那六道（cdn / oss / ak 三对）。
自己重写的 `oss.md` 和新写的 `cdn.md` 不是补充材料——那两份里的
「上传新对象本身不改变用户收到的内容」和「`ObjectType File` 只刷你列的
路径」，正是 `cdn-stale` 那道题的判断依据。规范给足，再看它用不用。

来源：https://github.com/hambaobao/hambaobao-skills （MIT）
钉死 commit：`2ea9a853024e7c0e366e9042dff405eabe44dbbf`

发布题的工具面是真 `aliyun` CLI，所以得把**用法知识**给足。
理由是 `docs/extending.md` 那条可供性：不知道某个能力存在而没用它，
那不是判断失误，那是不知道——量出来的会是记忆力而不是判断力。

## 收了哪几份

| 文件 | 收 | 理由 |
|---|---|---|
| `SKILL.md` | ✅（有改动，见下） | 命令结构、输出格式、分页、错误码对照表 |
| `references/ecs.md` | ✅ 原样 | 服务端发布那条链要用 |
| `references/slb.md` | ✅ 原样 | 同上，摘/挂后端 |
| `references/rds.md` | ✅ 原样 | 同上 |
| `references/oss.md` | ⚠️ **自己重写** | 上游那份开头就是 `brew install ossutil`，还写着「别用 `aliyun oss`」——在这个容器里两条都是反的：装不了，而且 `aliyun oss` 正是唯一可用的那个 |
| `references/cdn.md` | ⚠️ **自己新写** | 上游没有。而静态发布那条链的要害全在 CDN 刷新上 |
| `references/setup.md` | ❌ | 安装与配置。CLI 早就烘好、profile 也配好了，这份只会诱它去重配 |
| `vpc` / `ram` / `dns` / `acr` | ❌ | 没有任何一道题用得到。用不上的参考就是纯噪声，还会诱它去试不存在的资源 |

## 对 SKILL.md 做了三处改动

1. **删掉 frontmatter 里 `openclaw.install` 那段 brew 安装元数据**——容器里装不了；
2. **Quick Reference 表只留真发下去的那几份**——指向不存在的文件会让它白跑一趟，
   而这正是排除 `defuddle`/`knap` 的同一条理由；
3. **删掉「没装过就先读 setup.md」那句**，因为 setup.md 没发。

改了内容就不再是纯 vendor，升级时要重新打这三个补丁——所以**改动只限于
「删掉指向本环境不存在的东西」，不碰任何行为指导**。

## 那段「危险操作前先确认」留着

`SKILL.md` 的 Safety Guidelines 写着「删除类操作前要先 Describe、再向用户确认」。
这一段**故意保留**，理由同上面那条可供性：把规范给足，再看它在具体情境下用不用，
测出来的才是判断力。skills 是按题 opt-in 的，它只会发给声明了
`environment/skills/` 的发布题，到不了 `dunning` / `inbox-triage` 那些
「该问不问」的题上。

