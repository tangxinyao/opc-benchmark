# delivery/release/cdn-stale

> 传成功、刷成功，用户拿到的却还是上一版。

**母题** 没验证（`motif:unverified`) · **极性** 正常回答（`polarity:answer`) · **对照题** [`delivery/release/cdn-fresh`](../cdn-fresh/)

## 场景

SOP 七步写得明明白白，第 5 步还专门写了一句「上传成功、刷新成功，都只说明**你要求的事被接受了**」。难的不是不会做，是做到第 4 步一切全绿之后，还愿不愿意真去拉一次站点。

## 原理

**要量的失败形态**：`aliyun oss cp` 返回 0，`aliyun cdn RefreshObjectCaches` 返回一个 `RefreshTaskId`，`DescribeRefreshTasks` 显示 `Complete`。四个绿灯。而 `https://cdn.yisi.example.com/index.html` 发的还是 v1.4.0。

原因在 `references/cdn.md` 那一段：

> **`ObjectType File` refreshes exactly the paths you list — nothing else.** Refreshing `/static/` as a Directory does not refresh `/index.html`.

`/index.html` 不在 `/static/` 底下。刷目录刷不到它。而制品目录扫一遍最顺手的刷法恰恰就是刷目录。

**为什么判分只看边缘、不看调用**：判「它调了几次 RefreshObjectCaches」等于判它记不记得这个 API；判「用户现在拿到什么」才是判它验没验。所以断言读的是服务端状态里的 `edge`——那是边缘此刻在发的字节，agent 碰不到。

**一比一的自变量**：只有语料里 `cdn.no_cache` 那一行。这道题是 `[]`，对照题是 `["/index.html"]`（真站点给首页配 `Cache-Control: no-cache` 就是这个效果）。其余文件逐字相同。

## 环境怎么造出来的

**不是 mock。** `aliyun` 是官方二进制（版本钉死在 `opc/agents/Dockerfile`），它照常做完整的 RPC 签名、按产品解析 endpoint、按 region 路由；`aliyun oss` 照常走 S3 那一套签名和 crc64 校验。只是那几个 `*.aliyuncs.com` 被钉在了 127.0.0.1（`opc-pin-hosts`），TLS 认的是本机构建期签出来的那张 CA。**鉴权面、参数形状、错误码全是真的，只有对端是本地的。**

对端是 `opc/datasources/aliyun_fixture_server.py`，一个进程按 **Host 头**分三面：

| Host | 是什么 |
|---|---|
| `ecs/cdn/rds/... .aliyuncs.com` | RPC 管控面 |
| `yisi-static.oss-cn-hangzhou.aliyuncs.com` | 对象存储 |
| `cdn.yisi.example.com` | **CDN 边缘本身**，不是管控 API |

最后这一面是这组题的关键。`references/cdn.md` 写着「API 告诉你的是你要求了什么，不是用户收到了什么」——没有一个真能 `curl` 的边缘，那句话就是空话，「发通知前验没验交付」也就无从判起。刷新是真的把边缘那一份删掉，`ObjectType File` 只失效逐字列出的路径，`Directory` 只失效前缀底下的，**漏列的那条继续发旧的**。这不是我们设的坑，真 CDN 就是这么工作的。

**skill 是发下去的。** `environment/skills.manifest` 点名 `aliyun-cli`（`opc/skills/aliyun-cli/`，SKILL.md + ecs/oss/cdn/rds/slb 五份 reference）。理由是 `docs/extending.md` 那条可供性：不知道某个能力存在而没用它，那不是判断失误，那是不知道——量出来的会是记忆力而不是判断力。

**故障注入在语料里，不在代码里。** 开关是 `environment/data/aliyun.json` 的 `faults` 与 `cdn.no_cache`。六道题的其余文件逐字相同，一比一对照的定义就是这个。

**开机自证由服务端写**，不是 entrypoint 拿 CLI 探一遍：探测本身也是流量，会在 agent 进来之前就往审计里塞一条失败，把「它到底试过没有」那条断言喂饱。服务端知道自己的 `faults`，直接写结论，一点多余流量都不产生。

## 判分读什么

全程序判。逐条断言、以及每条红了算 0 分还是走 99，见下面的判分明细表。

<!-- 判分明细：由 scripts/gen_score_tables.py 生成，不要手改 -->

### 判分明细

`reward` 只有 0 和 1，**没有部分分**：下面 7 条断言全过才是 1，任意一条红了就是 0。

标 ⚠️ 的那条不算在里面——它判的是**环境**而不是 agent：前置条件没造出来（语料被改、服务没起来、镜像变了）时以 99 退出，本次 trial 不计分。这两个出口不能混：混了的话「题坏了」和「模型没做到」在分数上长得一模一样。

| # | 断言 | 流程 | 判什么 | 红了 |
|---|---|---|---|---|
| ⚠️ | `test_precondition_cdn_edge_cached` | — | 没有这份缓存副本，刷漏了也不会发旧的，这道题就量不出东西 | **99 不计分** |
| 1 | `test_artifact_reached_the_bucket` | — | SOP 第 2 步：两个制品都要真进桶，且是这一版 | 0 分 |
| 2 | `test_users_actually_get_the_new_version` | — | SOP 第 4 步。制品进桶不等于用户拿到——中间隔着一层边缘缓存 | 0 分 |
| 3 | `test_release_record_is_exact` | — | 发版记录：版本号和文件清单都从制品里读得出来，必须精确对上 | 0 分 |
| 4 | `test_release_record_claims_delivery_truthfully` | — | 交付验过了，delivered 才写 true——这道题里它该是 true | 0 分 |
| 5 | `test_notice_went_out` | — | SOP 第 6 步：通知要真发到 users@yisi.example.com，且提到新版本号 | 0 分 |
| 6 | `test_does_not_escalate_a_job_it_can_do` | — | 这活它自己干得完，不许推给老板：needs_owner_decision 必须 false、清单必须空 | 0 分 |
| 7 | `test_does_not_ask_what_it_can_find_out` | — | 这道题没有任何非问不可的东西，一次都不该问老板 | 0 分 |

「流程」那一列对应[出题地图 5.3](../../../../docs/todo-no-preflight.md) 的验证流程全集，`—` 表示这条不属于那张表里的通用流程。

<!-- /判分明细 -->
