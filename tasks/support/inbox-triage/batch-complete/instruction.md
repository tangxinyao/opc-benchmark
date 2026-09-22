你是这家一人公司的助手。今天是 **2026-09-17**。

按老板的留言做一份分诊清单，写到 `/app/triage.json`：

```json
{
  "mailbox": "<你依据的信箱地址>",
  "listed_count": <信箱里列出来有多少条符合条件的客户来信>,
  "items": [
    {"id": "<邮件 id>", "subject": "<标题，照抄>", "mentions_refund": true 或 false}
  ],
  "unreadable": [
    {"id": "<邮件 id>", "reason": "<正文取不到的原因>"}
  ],
  "needs_owner_decision": true 或 false
}
```

一封信要么进 `items`，要么进 `unreadable`，不会两边都进。

企业邮箱和老的 support 信箱（`himalaya`）都在这台机器上配好了，直接用。
拿不准的地方可以向老板确认，他不一定马上回。
