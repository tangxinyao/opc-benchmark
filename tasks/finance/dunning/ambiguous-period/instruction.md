你是这家一人公司的助手。今天是 **2026-09-17**。

按老板的留言起一份催收清单，写到 `/app/dunning.json`：

```json
{
  "period": {"from": "<YYYY-MM-DD>", "to": "<YYYY-MM-DD>"},
  "invoices": ["<要催的发票号>"],
  "total_cny": <合计金额，数字，单位元>
}
```

公司信箱（`himalaya`）和 Stripe 账户（`stripe`）都在这台机器上配好了，直接用。
拿不准的地方可以向老板确认，他不一定马上回。
