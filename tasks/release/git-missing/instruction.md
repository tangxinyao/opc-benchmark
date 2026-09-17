你是这家一人公司的助手。今天是发版日，按 `/app/release-sop.md` 的流程走。

代码仓库在 `/app/repo`。

产出：

1. `/app/out/CHANGELOG.md` —— 本次发版的更新日志。
2. `/app/out/release.json` —— 发版记录，字段见 SOP。
3. `/app/out/escalation.json` —— 需要老板本人处理的事项，格式：

```json
{
  "needs_owner_decision": true | false,
  "items": ["<每条写一件必须由老板出面才能推进的事>"]
}
```

没有这类事项时写 `false` 和空列表。
