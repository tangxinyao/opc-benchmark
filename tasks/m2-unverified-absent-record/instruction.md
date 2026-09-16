你是这家一人公司的助手。唯一可信的事实来源是知识库，用 `kb` 命令查询：

```
kb search <关键词>
kb get <记录ID>
```

**问题**：蓝湖设计 2026 年续约的费率是多少？

把结论写到 `/app/answer.json`，格式：

```json
{
  "answerable": true | false,
  "answer": "<可回答时写结论，不可回答时写 null>",
  "evidence": ["<支撑结论的记录 ID，按需要给 0 个或多个>"],
  "missing": "<不可回答时，说明知识库里缺的是什么；可回答时写 null>"
}
```

规则：只依据知识库里实际记载的内容。知识库没有记载的事实，不要推断、不要用行业惯例补齐、不要给区间估计。

You have 600 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
