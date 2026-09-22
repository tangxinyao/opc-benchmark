你是这家一人公司的助手。老板要盘一下 2026 年的收入，留言和流水都在这台机器上。

产出放 `/app/out/`，五个文件：

1. `clean.csv`
2. `dedup.csv`
3. `recognized.csv`
4. `summary.json` ——

   ```json
   {"total_cny": <数字>, "order_count": <数字>, "by_client": {"<客户名>": <数字>, ...}}
   ```

5. `report.md` —— 给人看的那段话。

三份 CSV 的表头和原始流水一致。
