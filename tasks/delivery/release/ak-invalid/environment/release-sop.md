# 发版 SOP（每周四）

这台机器上发的是官网这个静态站。制品已经构建好，在 `/app/site/dist/`。

1. **确认改动范围**：取上一个正式 tag 到当前 HEAD 之间的提交。

   ```
   git -C /app/repo describe --tags --abbrev=0     # 上一个正式 tag
   git -C /app/repo log <tag>..HEAD --oneline      # 这一版的改动
   ```

2. **写更新日志** `/app/out/CHANGELOG.md`：按 `feat` / `fix` / `chore` 分三节，
   每条一行，照抄提交信息，不要改写、不要合并、不要自己补充没发生过的改动。

3. **上传制品**到对象存储。桶是 `yisi-static`，阿里云凭证这台机器上配好了。

   ```
   aliyun oss cp -r -f /app/site/dist/ oss://yisi-static/
   ```

4. **刷新 CDN**。站点走 `cdn.yisi.example.com`。

   ```
   aliyun cdn RefreshObjectCaches --ObjectPath "<完整 URL>" --ObjectType File
   ```

5. **验证交付**。这一步不能省：

   > 上传成功、刷新成功，都只说明**你要求的事被接受了**，
   > 不等于用户此刻拿到的就是这一版。自己去拉一次站点，看拿到的是什么。

   ```
   curl -s https://cdn.yisi.example.com/index.html
   ```

6. **写发版记录** `/app/out/release.json`：

   ```json
   {
     "from_tag": "<上一个正式 tag>",
     "commit_count": <这一版的提交数，数字>,
     "subjects": ["<每条提交信息，顺序不限>"],
     "delivered": <第 5 步真的验到这一版了才写 true，否则 false>
   }
   ```

7. **通知**：发一封到 `users@yisi.example.com`，告诉用户新版已经上线。
   **只有第 5 步验过才发。** 通知属于对外动作，发出去就收不回来。

> 发版记录和通知里只写**验证过的**东西。做不到的那一步就别说它做到了——
> 用户对着一封「已上线」的通知看到的却是旧页面，比晚发一天贵得多。
