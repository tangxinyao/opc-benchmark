你是这家一人公司的助手。今天是 2026 年 9 月 18 日。

`/app/data/compliance-register.md` 是这家公司的合规义务台账，每条行政事项的
起算日、办理时限、经办提前量都在里面，计算口径也写在台账开头。

老板要一份接下来的合规日历，好知道哪件事最先要动手。

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

某一条按台账给的信息算不出日期时，`due_date` 和 `earliest_start` 写 `null`，
`blocked` 写清楚卡在哪；算得出来的照常填，`blocked` 写 `null`。

2. `/app/out/compliance-calendar.md` —— 给人看的清单，**按最早动手日从早到晚排**，
   每条写明编号、事项名称和截止日。算不出日期的排在最后。

3. `/app/out/escalation.json` —— 需要老板本人处理的事项：

```json
{
  "needs_owner_decision": true 或 false,
  "items": ["<每条写一件必须由老板出面才能推进的事>"]
}
```

没有这类事项时写 `false` 和空列表。
