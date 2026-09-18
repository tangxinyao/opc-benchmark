这家一人公司 2026 年的订单流水在一个 CSV 里。按下面五步做：

1. **清洗** → `/app/out/clean.csv`
   丢掉任何一个必填字段为空、金额非正数或非数字的行。表头保持不变。
2. **去重** → `/app/out/dedup.csv`
   按 `order_id` 去重，保留首次出现的那行。
3. **口径过滤** → `/app/out/recognized.csv`
   只保留 `status == "paid"` 的行，这才是可确认收入。
4. **汇总** → `/app/out/summary.json`
   ```json
   {"total_cny": <数字>, "order_count": <数字>, "by_client": {"<客户名>": <数字>, ...}}
   ```
   口径以第 3 步的结果为准。
5. **报告** → `/app/out/report.md`
   一段话，写进总金额、订单数，以及金额最高的那个客户的名字。

You have 900 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
