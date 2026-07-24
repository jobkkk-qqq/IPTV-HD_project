# IPTV HD Sync

> 全自动 IPTV 高清直播源流水线 — 从上游抓取 → ffprobe 识别 ≥1080p 频道 → 格式标准化 → HTTP 服务

## 一键部署

```bash
git clone https://github.com/jobkkk-qqq/IPTV-HD_project.git
cd IPTV-HD_project
docker compose up -d                     # 自动构建镜像 + 启动服务
docker exec iptv-hd bash /scripts/sync.sh  # 首次同步
```

容器启动后访问：
- M3U: `http://<服务器IP>:3568/m3u` （PotPlayer / VLC）
- TXT: `http://<服务器IP>:3568/txt` （Diyp / 百川）
- 状态: `http://<服务器IP>:3568/status`

## 架构

```
上游 Guovin/iptv-api  ──▶  ffprobe ≥1080p  ──▶  格式标准化  ──▶  HTTP :3568
   原始 M3U (全部保留)       8 并发 + 15s 超时        去 emoji          PotPlayer
                            结果持久化缓存            去重 + 双输出     Diyp/百川
```

## 流水线

| 步骤 | 脚本 | 说明 |
|------|------|------|
| 1. 下载 | `sync.sh` | Python urllib 从 Guovin 获取最新源，全部保留不做预筛选 |
| 2. 高清检测 | `probe_hd.py` | 8 并发 ffprobe，15s 超时，只保留 height ≥ 1080 频道，失败链接缓存不重试 |
| 3. 格式标准化 | `iptv_format.py` | 分组去 emoji、同名去重、统一头部参数、输出 M3U + TXT |

## 配置

编辑同步间隔（Hermes cronjob）：
```bash
cronjob action=create schedule="0 3 */2 * *" script="docker exec iptv-hd bash /scripts/sync.sh"
```

端口和服务器 IP 通过环境变量覆盖：
```bash
IPTV_PORT=3568 IPTV_SERVER_IP=192.168.1.111 docker compose up -d
```

## 自定义镜像

项目使用自定义 Dockerfile 构建镜像，内含：
- `python:3.11-slim` 基础镜像
- ffmpeg (ffprobe)
- HTTP 服务器 + 流水线脚本

如需修改代码，编辑后 `docker compose build && docker compose up -d` 即可。

## 依赖

- Docker + Docker Compose（宿主机唯一依赖）
- 网络访问 `raw.githubusercontent.com`（上游源）和 `raw.githubusercontent.com`（apt mirror）
