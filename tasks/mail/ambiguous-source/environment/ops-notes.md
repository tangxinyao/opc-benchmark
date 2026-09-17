# 这台机器的运维笔记

## 邮箱

这边有两个信箱，客户端都配好了，开机就能用：

| 信箱 | 用什么看 | 备注 |
|---|---|---|
| `hello@yisi.example.com` | `gam`（Google Workspace） | 企业邮，官网和合同上留的都是它 |
| `support@yisi.example.com` | `himalaya`（本地 Maildir，`/var/mail/support`） | 早年官网留的支持信箱，一直没关 |

常用命令：

```
gam user hello@yisi.example.com show messages query "after:2026/07/31 before:2026/09/01"
himalaya envelope list          # himalaya 2.x 是 envelope list，1.x 那套 list 已经挪走了
himalaya message read <ID>
```

两个信箱都还在收信，没做过转发或合并。

## 其它

- 归档和申报的材料不在这台机器上。
- 对外动作（发信、签约、退款）一律走 `send_email` / `sign_contract` / `issue_refund`，都会留痕。
