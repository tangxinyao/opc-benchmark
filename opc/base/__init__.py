"""烘进 agent 基础镜像的东西：全仓一份，构建期 COPY 进去。

改了这里面任何文件都要 `make image` 重建基底，否则题目容器里跑的还是旧的。
与之相对的是 opc/per-task/：那半由 scripts/sync-tasks.sh 按题扇出，改了跑
`make lint`（含 sync-tasks.sh --check）。
"""
