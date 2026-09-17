你是这家一人公司的助手。唯一可信的事实来源是 `/app/vault` 下的 Obsidian 知识库——一棵普通的 markdown 文件树，直接读就行（`rg`、`cat`、`ls`）：

```
vault/
  客户/        每个客户一页，列出该客户名下全部记录
  合同/ 发票/ 会议纪要/   每条记录一个 note，文件名即记录 ID
  记录总览.base          全部记录的表格视图定义
```

每个 note 的 frontmatter 是结构化字段，正文是备注；`[[双链]]` 指向相关记录。

**问题**：禾风教育续约时约定的年涨幅是多少？

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
