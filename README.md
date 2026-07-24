# IPTV HD Sync

> 全自动 IPTV 高清直播源流水线 — 从上游抓取 → ffprobe 识别 ≥1080p 频道 → 格式标准化 → HTTP 服务

## 一键部署

```bash
git clone https://github.com/jobkkk-qqq/IPTV-HD_project.git
cd IPTV-HD_project
docker compose up -d
```

**就这么简单。** 容器启动时会自动：
1. 构建镜像（含 ffmpeg、HTTP 服务器、流水线脚本）
2. 启动 HTTP 服务（`:3568`）
3. 后台自动运行首次同步（下载源 → ffprobe 高清检测 → 格式化）

此后每 2 天自动同步一次（Hermes cronjob）。

访问地址：
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

## 手动同步

如需手动触发同步（不等待 cron）：

```bash
docker exec iptv-hd bash /scripts/sync.sh
```

## 自定义

端口通过环境变量覆盖：
```bash
IPTV_PORT=3568 docker compose up -d
```

修改代码后：
```bash
docker compose build && docker compose up -d
```
