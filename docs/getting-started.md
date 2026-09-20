# 开始使用

前置：**Docker** 和 **uv**。下面的路径都按仓库根目录写，所以在根目录跑最省事；
`uv sync` 会把 `opc` 可编辑安装进 `.venv`，import path 在哪个目录都解析得到。

## 五步跑起来

```bash
# 1. 装依赖（harbor、pyyaml、pytest；版本由 uv.lock 钉死）
uv sync

# 2. 构建两个基础镜像（agent 用 + 判分用，各约几分钟）
#    HERMES_VERSION 留空装最新版；正式跑分请钉死版本。
make images HERMES_VERSION=v2026.9.14

# 3. 给模型凭证：填 .env（模板 .env.example，.env 不会被提交）
cp .env.example .env && $EDITOR .env
make env-check            # 确认要用的变量都就位（只报在不在，不打印值）

# 4. 钉基线：每道题 oracle 必须满分、nop 必须零分
scripts/validate.sh

# 5. 跑
make configs
make run CONFIG=configs/jobs/job-deepseek-x5.yaml
make run CONFIG=configs/jobs/job-deepseek-x3.yaml
```

## 测试的三个级别

改完东西之后按这个顺序验，**一级没过别跑下一级**。

### 第 1 级：`make check`（不需要 Docker，秒级）

```bash
make check        # = make lint + make unit + make smoke
```

| 目标 | 验什么 |
|---|---|
| `make lint` | 任务目录静态检查：canary、四元标签、判分工具是否烘进镜像、每道拒答题是否都有配对、`[metadata.opc]` 与 Dockerfile 是否一致，并重新生成 `configs/jobs/` |
| `make unit` | 适配器的 provider 路由单元测试 |
| `make smoke` | 每道题 oracle 必须满分、nop 必须零分（在宿主机上直接跑判分逻辑） |

这一级快，改一行就可以跑一次。但它**只验证了解法与判分器的逻辑**，
没验证 Dockerfile 和 harbor 集成。

### 第 2 级：`scripts/validate.sh`（需要 Docker，不烧 API）

```bash
. scripts/load-env.sh
scripts/validate.sh tasks/finance/settlement/platform-fee-change   # 先单跑一道探路
scripts/validate.sh                                        # 7 道全跑
```

对每道题跑两次 `harbor run`：`--agent oracle`（执行 `solution/solve.sh`）和
`--agent nop`（什么都不做）。**两个都是假 agent，不调模型，不花钱**，可以随便重跑。

两条硬线：

- **oracle 必须 1 分**——挂了说明你的判分器有问题，不是模型有问题
- **nop 必须 0 分**——nop 能拿分的题量不出任何东西，这条比分数本身重要

**这一步不要跳。** 它验的正是第 1 级验不到的东西：Dockerfile 能不能构建、
工具在容器里有没有执行权限、审计日志写不写得进去、判分容器读不读得到 agent 的产物。
第一次进真容器大概率有路径或权限的小毛病要修，那是正常的，就是来抓这个的。

### 第 3 级：真模型（开始烧 API）

先单跑一道，确认适配器这条链通：

```bash
. scripts/load-env.sh
harbor run -p tasks/finance/settlement/platform-fee-change \
  --agent opc.agent.hermes:Hermes -m deepseek/deepseek-flash
```

这一步验的是前两级都验不到的：API key 有没有正确进到容器、provider 路由对不对、
agent 会不会真的去调工具。**拿到 0 分不要紧，这一级看的是「跑完了没有」，
不是「答对了没有」。**

通了再跑整批：

```bash
make configs
make run CONFIG=configs/jobs/job-deepseek-x3.yaml    # 3 道题 × 3 遍 = 9 次 trial
make run CONFIG=configs/jobs/job-deepseek-x5.yaml    # 4 道题 × 5 遍 = 20 次 trial
```

## 凭证

凭证放仓库根目录的 `.env`（模板 `.env.example`，`.env` 已被 `.gitignore` 挡住）。
`make` 的目标会自己 `. scripts/load-env.sh`；手敲 `harbor run` 的话自己先 source 一次。

在 shell 层读而不是在适配器里读，是因为凭证有三个去处——harbor 本体、agent 容器、
判分器容器——**只有 shell 层能一次覆盖三个**。

两条规矩：

- **最小权限。** 差分判分意味着一个任意模型拿着你的凭证联网（那些题的
  `network_mode` 必须是 `"public"`）。只读、只给必要的那一个服务。
- **审计日志会脱敏。** `/var/lib/opc/audit.log` 记录完整 argv 且会被当 artifact 收走，
  `opc/agent/opc_internal/audit.py` 把 argv 和异常文本里的 key/secret/token 打码。

凭证怎么从 shell 进到容器里，见[项目结构](project-structure.md#凭证怎么进到容器里)。

## 出错时先看哪儿

| 现象 | 大概率原因 |
|---|---|
| harbor 抛 `RewardFileNotFoundError` | 判分器自己挂了（退 99），**不是 agent 答错**，这次 trial 作废 |
| 想知道哪条断言挂了 | `/logs/verifier/ctrf.json`，pytest 每条断言分开报告 |
| 想知道 agent 到底调没调工具 | 容器里的 `/var/lib/opc/audit.log` |
| 差分判分假阴性 | `/logs/verifier/oracle.json`，判分器当时取到的真值 |
| hermes 报 `can't reach the model provider` | `base_url` 指到了别处。题目现在是 `network_mode = "public"`，适配器不再需要临时放行模型端点；改回 `no-network` 的话，放行失败也会报这个 |
| harbor 抛 `network_mode='no-network' is not supported by EnvironmentType.DOCKER` | 宿主内核没有 `nftables fib inet`，harbor 的出网管控起不来，于是拒绝任何非 public 的策略。它靠跑一个写死的 alpine 容器读 `/proc/config.gz` 来探测，**拉不到那个镜像也会报同样的错**。题目默认已经是 `public`，只有你手动改回 `no-network` 才会撞上 |

## 几个会绊人的点

- **`docker: permission denied`** —— 当前 shell 不在 docker 组。`usermod -aG docker $USER`
  之后必须重新登录（或 `newgrp docker`）：组成员身份在进程创建时就定死了，
  改完 `/etc/group` 对已有的 shell 不生效。别用 `sudo docker` 绕，
  harbor 是在 python 里调 docker 的，`sudo` 救不了它。
- **`HERMES_VERSION` 用日历版本号**（如 `v2026.9.14`），不是语义化版本。
  留空装最新版；正式跑分请钉死，浮动的 hermes 版本等于浮动的结论。
- **`local/` provider 且模型服务在宿主机上时**，Linux 的 Docker 要加
  `--add-host=host.docker.internal:host-gateway`（适配器已经把 URL 改写好了，
  但 host 别名得 Docker 那边给）。
- **跑在远程环境**（`--env daytona/modal/...`）时，两个基础镜像要先推到 registry，
  任务 Dockerfile 的 `ARG *BASE_IMAGE` 默认值换成带仓库前缀的全名，
  并同步改 `[metadata.opc]` 里的声明（`make lint` 会check两边一致）。
