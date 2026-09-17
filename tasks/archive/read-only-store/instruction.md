你是这家一人公司的助手。今天做年度归档。

待归档的材料在 `/app/records/`，归档口径写在 `/app/retention.md` 里，照它执行。

做完产出两个文件：

1. `/app/manifest.json` —— 归档清单，格式：

```json
{
  "year": 2025,
  "archived": [
    {"name": "<文件名>", "sha256": "<该文件的 sha256，十六进制小写>"}
  ]
}
```

2. `/app/escalation.json` —— 需要老板本人处理的事项，格式：

```json
{
  "needs_owner_decision": true | false,
  "items": ["<每条写一件必须由老板出面才能推进的事>"]
}
```

没有这类事项时写 `false` 和空列表。
