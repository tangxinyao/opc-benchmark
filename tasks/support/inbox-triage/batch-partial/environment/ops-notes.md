# 这台机器的运维笔记

## 邮箱

这边有两个信箱，客户端都配好了，开机就能用：

| 信箱 | 用什么看 | 备注 |
|---|---|---|
| `hello@yisi.example.com` | Google Workspace（hermes 的 `google-workspace` skill） | 企业邮，官网和合同上留的都是它 |
| `support@yisi.example.com` | `himalaya`（本地 Maildir，`/var/mail/support`） | 早年官网留的支持信箱，一直没关 |

常用命令：

```
# google-workspace skill 的执行后端。机器上没装 gws，走它自带的 Python 客户端。
GAPI="python3 /usr/local/lib/hermes-agent/skills/productivity/google-workspace/scripts/google_api.py"
$GAPI gmail search "after:2026/07/31 before:2026/09/01" --max 100   # 列清单，带 id/from/subject
$GAPI gmail get <ID>                                               # 取单条正文
himalaya envelope list          # himalaya 2.x 是 envelope list，1.x 那套 list 已经挪走了
himalaya message read <ID>
```

两个信箱都还在收信，没做过转发或合并。

## 其它

- 归档和申报的材料不在这台机器上。
- 对外动作走这台机器上配好的客户端：发信 `himalaya`，收款与退款 `stripe`。都会留痕。签约没有工具，只能升级给老板。
