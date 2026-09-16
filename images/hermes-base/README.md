# hermes 基础镜像

Harbor 把 agent 装进**任务容器**里跑，所以 agent 要预烘就得烘在任务镜像的基底上。
这里是那个基底。

```bash
make image                      # 构建 opc-benchmark/hermes-base:local
make image HERMES_VERSION=1.4.2 # 钉版本
```

任务镜像用它作基底：

```dockerfile
FROM opc-benchmark/hermes-base:local
```

## 几个必须知道的点

- **`HERMES_HOME` 必须与 `opc_agents/hermes.py` 里的常量一致**（当前是 `/opt/hermes`）。
  改一边不改另一边，适配器的 install 自检会直接失败——这是故意的。
- **版本要钉死。** 评测里浮动的 hermes 版本等于浮动的结论，两次跑分不可比。
- **跑在远程环境**（`--env daytona/modal/...`）时，这个镜像得推到 registry，
  任务 Dockerfile 的 `FROM` 要换成带仓库前缀的全名。本地 docker 环境不用。
- **本地 provider**：模型服务跑在宿主机上时，适配器会把 `localhost` 改写成
  `host.docker.internal`。Linux 的 Docker 还需要给容器加
  `--add-host=host.docker.internal:host-gateway`（Docker Desktop 自带）。
  服务和 agent 在同一个容器里，就用 `--ak rewrite_localhost=false`。
