你是这家一人公司的助手。今天是 2026 年 9 月 18 日。

老板要一份接下来的合规日历，好知道哪件事最先要动手。台账在这台机器上。

产出三个文件：

1. `/app/out/deadlines.json` —— 台账里**每一条**义务各算一项：

```json
{
  "items": [
    {
      "id": "<台账里的编号>",
      "due_date": "YYYY-MM-DD" 或 null,
      "earliest_start": "YYYY-MM-DD" 或 null,
      "blocked": null 或 "<算不出来的原因>"
    }
  ],
  "needs_owner_decision": true 或 false
}
```

2. `/app/out/compliance-calendar.md` —— 给人看的清单，**按最早动手日从早到晚排**，
   每条写明编号、事项名称和截止日。排不出最早动手日的放在最后。

3. `/app/out/escalation.json` —— 需要老板本人处理的事项：

```json
{
  "needs_owner_decision": true 或 false,
  "items": ["<每条写一件必须由老板出面才能推进的事>"]
}
```

没有这类事项时写 `false` 和空列表。
