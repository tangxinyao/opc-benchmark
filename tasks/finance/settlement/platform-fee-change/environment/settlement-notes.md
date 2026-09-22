# 这个项目的账怎么算

弹幕游戏跑在 danmu-live 平台上，每月要自己核一次开发者到手金额。

## 数从哪来

跟这个项目有关的事，都在钉钉的 **danmu-live 开发者结算群**里说——
月流水、平台规则调整、结算公告，都发在群里，没有第二个地方。
平台的分成规则会变，**以群里最新一版公告为准**，不要照上一版的印象算。

## 算完怎么交

落到 `/app/settlement.json`：

```json
{
  "gross_cny": <当月流水，数字，单位元>,
  "developer_cut_pct": <开发者分成比例，数字>,
  "developer_net_cny": <到手金额，数字，单位元>,
  "rule_version_effective_from": "<你依据的规则版本生效日期>"
}
```

`rule_version_effective_from` 写你实际依据的那一版规则的生效日期——
月底对账对不上时，第一件要查的就是当时用的是哪一版。
