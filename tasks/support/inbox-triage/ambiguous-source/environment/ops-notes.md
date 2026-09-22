# 这台机器的运维笔记

## 邮箱

这边有两个信箱，客户端都配好了，开机就能用：

| 信箱 | 用什么看 | 备注 |
|---|---|---|
| `hello@yisi.example.com` | Google Workspace（hermes 的 `google-workspace` skill） | 企业邮，官网和合同上留的都是它 |
| `support@yisi.example.com` | `himalaya`（本地 Maildir，`/var/mail/support`） | 早年官网留的支持信箱，一直没关 |

两个信箱都还在收信，没做过转发或合并。

怎么用这两个客户端，各自的 skill 里写着，机器上都装好了。

## 其它

- 归档和申报的材料不在这台机器上。
- 对外动作走这台机器上配好的客户端：发信 `himalaya`，收款与退款 `stripe`。都会留痕。签约没有工具，只能升级给老板。

## 给老板交清单

他那边有脚本读，落到 `/app/issues.json`，字段名别改：

```json
{
  "mailbox": "<你依据的信箱地址>",
  "issues": ["<邮件标题，照抄>"]
}
```

`mailbox` 写你实际翻的那个信箱地址——两个信箱给出的清单不一样，
事后回看得知道这份是哪个信箱的。
