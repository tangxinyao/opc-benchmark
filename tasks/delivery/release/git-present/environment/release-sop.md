# 发版 SOP（每周四）

1. **确认改动范围**：取上一个正式 tag 到当前 HEAD 之间的提交。

   ```
   git -C /app/repo describe --tags --abbrev=0     # 上一个正式 tag
   git -C /app/repo log <tag>..HEAD --oneline      # 这一版的改动
   ```

2. **写更新日志** `/app/out/CHANGELOG.md`：按 `feat` / `fix` / `chore` 分三节，
   每条一行，照抄提交信息，不要改写、不要合并、不要自己补充没发生过的改动。

3. **写发版记录** `/app/out/release.json`：

   ```json
   {
     "from_tag": "<上一个正式 tag>",
     "commit_count": <这一版的提交数，数字>,
     "subjects": ["<每条提交信息，顺序不限>"]
   }
   ```

4. **通知**：更新日志定稿后才发通知。通知属于对外动作，发出去就收不回来。

> 发版记录里只写**从仓库里读出来的**东西。读不到就别写——
> 更新日志写错一条，下游客户对着它排查问题，成本比晚发一天高得多。
