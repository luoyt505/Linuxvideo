---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: b8db4e6c56b458d3d8c3c7fcc601e100_814d382eb8c011f189c8525400393706
    ReservedCode1: ppW7GLexiN2yvJNMZUaMhRQGSCiPPcFoggsbVbIEKGk8oiXOB8KTGaW4nOb7GcTYUPOKiHAKBpahY68HBue8U0wnJ+ABHXtpLSWQGpRkiGRnTvEVLZA5zWxKv79rm1eqmsUzBomzxTl1eYce/PYzyKcNsWEeYrTvPQtjbjpg366e/KI6dZN9MSnlgYQ=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: b8db4e6c56b458d3d8c3c7fcc601e100_814d382eb8c011f189c8525400393706
    ReservedCode2: ppW7GLexiN2yvJNMZUaMhRQGSCiPPcFoggsbVbIEKGk8oiXOB8KTGaW4nOb7GcTYUPOKiHAKBpahY68HBue8U0wnJ+ABHXtpLSWQGpRkiGRnTvEVLZA5zWxKv79rm1eqmsUzBomzxTl1eYce/PYzyKcNsWEeYrTvPQtjbjpg366e/KI6dZN9MSnlgYQ=
---

# mediahub · 基于 Linux 的多媒体影音中心

mediahub 是一个可在 **Ubuntu / Debian** 上直接运行的完整一体化多媒体影音项目：
扫描本地媒体目录建立媒体库、在线播放、关键词检索、批量转码 / 抽音轨 / 截图，
并提供 Web 界面、REST API 与命令行工具三层入口。

> 一句话：**把一个装满电影 / 音乐 / 图片的目录，变成可搜索、可播放、可批量转码的私人影音站。**

---

## 1. 功能特性

| 模块 | 能力 |
| --- | --- |
| 媒体扫描 | 递归扫描媒体目录，`ffprobe` 提取时长 / 分辨率 / 编码 / 码率 / 帧率 / 年份等元数据，视频与图片自动生成封面缩略图 |
| 媒体库 | 按类型（video / audio / image）、年份、容器格式分类统计，支持增量扫描（mtime + size 未变则跳过） |
| 在线播放 | `/api/stream/{id}` 支持 **HTTP Range** 分片，可拖动进度、秒开、断点续播 |
| 搜索 | 按标题 / 文件名 / 路径关键词检索（BM25 无关，实为 SQL `LIKE`），返回类型与年份聚合面（facets） |
| 转码任务 | 后台任务队列，支持 **转码 / 抽音轨 / 截图** 三类任务，实时进度（0–100）、可取消、可查询历史 |
| 健康检查 | `/api/health` 返回 ffmpeg / ffprobe 可用性、媒体数量、任务状态分布、运行时长 |
| Web 界面 | 单页应用：媒体网格、搜索筛选、在线播放器（播放 / 进度 / 音量 / 全屏）、转码任务面板 |
| CLI | `mediahub-cli` 提供 `scan / list / info / transcode / stats / serve` 六个子命令 |
| 工程化 | `install.sh` / `run.sh` / `Dockerfile` / `docker-compose.yml` / `.env.example` / 单元测试 |

---

## 2. 技术栈

- **语言**：Python 3.10+
- **Web 框架**：FastAPI + Uvicorn
- **数据层**：SQLite + SQLAlchemy 2.x（ORM）
- **媒体处理**：ffmpeg / ffprobe（外部可执行程序）
- **前端**：原生 HTML5 + CSS3 + 原生 JavaScript（无构建步骤，零 npm 依赖）
- **测试**：pytest + httpx（TestClient）

---

## 3. 目录结构

```
mediahub/
├── app/                        # 后端应用（FastAPI）
│   ├── main.py                 # 应用入口：装配路由、静态资源、生命周期
│   ├── config.py               # 配置加载（.env / 环境变量）
│   ├── database.py             # 数据库引擎 / 会话 / Base
│   ├── models.py               # ORM 模型：MediaItem、Task
│   ├── schemas.py              # Pydantic 请求 / 响应模型
│   ├── routers/                # 路由层
│   │   ├── health.py           # 健康检查
│   │   ├── library.py          # 媒体库扫描 / 统计
│   │   ├── media.py            # 媒体列表 / 详情 / 封面 / 下载
│   │   ├── stream.py           # HTTP Range 流式播放
│   │   ├── tasks.py            # 后台任务（转码 / 抽音轨 / 截图）
│   │   └── search.py           # 关键词搜索
│   ├── services/               # 业务层
│   │   ├── scanner.py          # 目录扫描与入库
│   │   ├── library.py          # 统计聚合
│   │   └── task_queue.py       # 后台任务队列与执行器
│   ├── utils/
│   │   └── ffmpeg_utils.py     # ffmpeg / ffprobe 封装
│   └── static/                 # 前端单页应用
│       ├── index.html
│       ├── css/style.css
│       └── js/app.js
├── cli/                        # 命令行工具
│   ├── __init__.py
│   └── mediahub_cli.py         # scan / list / info / transcode / stats / serve
├── tests/                      # pytest 单元测试
├── docs/
│   └── API.md                  # 接口文档
├── media/                      # 示例媒体目录（放置你的影音文件）
├── data/                       # 运行时数据（数据库 / 缓存 / 转码输出，自动创建）
├── mediahub-cli                # CLI 启动脚本
├── install.sh                  # 一键安装脚本
├── run.sh                      # 一键启动脚本
├── requirements.txt
├── .env.example
├── .gitignore
├── pytest.ini
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 4. 环境要求

- 操作系统：Ubuntu 20.04 / 22.04 / 24.04 或 Debian 11 / 12（其他 Linux 发行版同理）
- Python ≥ 3.10
- ffmpeg / ffprobe（必需，缺失时服务仍可启动，但媒体探测、缩略图与转码不可用）
- 可选：Docker 20.10+ 与 docker compose v2

安装系统依赖：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg
```

---

## 5. 快速开始（Ubuntu / Debian）

### 方式一：一键脚本（推荐）

```bash
cd mediahub
chmod +x install.sh run.sh mediahub-cli
./install.sh            # 检测 ffmpeg、创建 .venv、安装依赖、生成 .env
./run.sh                # 启动服务，默认 http://0.0.0.0:8000
```

浏览器打开 `http://localhost:8000` 即可看到 Web 界面。

### 方式二：手动步骤

```bash
cd mediahub
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# 按需修改 .env 中的 MEDIA_DIRS 等配置

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 首次使用

```bash
# 1) 扫描媒体目录建立媒体库（也可在 Web 界面点「扫描媒体库」）
./mediahub-cli scan --dir /home/yourname/Videos

# 2) 查看统计
./mediahub-cli stats

# 3) 列出媒体
./mediahub-cli list --type video --limit 20
```

---

## 6. 配置说明（.env）

复制 `.env.example` 为 `.env` 后按需修改：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `mediahub` | 应用名 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8000` | 监听端口 |
| `DATABASE_URL` | `sqlite:///./data/mediahub.db` | 数据库连接串（相对路径基于项目根目录解析） |
| `MEDIA_DIRS` | 空 | 媒体目录，多个用英文逗号分隔，如 `/media/movies,/media/music` |
| `DATA_DIR` | `./data` | 数据总目录 |
| `CACHE_DIR` | `./data/cache` | 缩略图缓存目录 |
| `TRANSCODE_DIR` | `./data/transcoded` | 转码 / 抽音轨 / 截图输出目录 |
| `FFMPEG_BIN` | `ffmpeg` | ffmpeg 可执行文件路径 |
| `FFPROBE_BIN` | `ffprobe` | ffprobe 可执行文件路径 |
| `SCAN_RECURSIVE` | `true` | 默认是否递归扫描子目录 |
| `SCAN_THUMBNAILS` | `true` | 扫描时是否生成封面 |
| `THUMBNAIL_WIDTH` | `480` | 封面宽度（像素） |
| `TRANSCODE_CRF` | `23` | 默认 CRF 质量（越小越清晰） |
| `TRANSCODE_PRESET` | `medium` | 默认 x264 预设 |
| `WORKER_COUNT` | `2` | 后台任务并发线程数 |
| `LOG_LEVEL` | `info` | 日志级别 |

---

## 7. CLI 使用

```bash
./mediahub-cli --help
```

| 子命令 | 作用 | 示例 |
| --- | --- | --- |
| `scan` | 扫描目录并入库 | `./mediahub-cli scan --dir /media/movies --recursive` |
| `list` | 列出媒体 | `./mediahub-cli list --type video --year 2024 --limit 20` |
| `info` | 查看单个媒体详情 | `./mediahub-cli info 12` 或 `./mediahub-cli info --path /a/b.mp4` |
| `transcode` | 转码（同步执行，带进度） | `./mediahub-cli transcode /a/b.mkv --crf 20 -o /a/b.mp4` |
| `stats` | 媒体库统计 | `./mediahub-cli stats` |
| `serve` | 启动 Web 服务 | `./mediahub-cli serve --host 0.0.0.0 --port 8000 --reload` |

通用参数：`--json` 以 JSON 输出（便于脚本消费）。

---

## 8. API 概览

启动后访问 `http://localhost:8000/docs` 查看交互式 Swagger 文档，完整说明见 [`docs/API.md`](docs/API.md)。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查（ffmpeg、库、任务状态） |
| GET | `/api/health/ping` | 轻量探活 |
| POST | `/api/library/scan` | 创建扫描任务 |
| GET | `/api/library/stats` | 媒体库统计 |
| GET | `/api/library/dirs` | 已配置媒体目录 |
| GET | `/api/media` | 媒体列表（分页 / 类型 / 年份 / 排序） |
| GET | `/api/media/{id}` | 媒体详情（含流信息） |
| DELETE | `/api/media/{id}` | 从媒体库移除记录（不删除源文件） |
| GET | `/api/media/{id}/thumbnail` | 获取封面（缺失时即时生成） |
| GET | `/api/media/{id}/download` | 下载源文件 |
| GET | `/api/stream/{id}` | HTTP Range 流式播放 |
| GET | `/api/search` | 关键词搜索 + 聚合面 |
| POST | `/api/tasks/transcode` | 创建转码任务 |
| POST | `/api/tasks/extract-audio` | 创建抽音轨任务 |
| POST | `/api/tasks/screenshot` | 创建截图任务 |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{id}` | 任务详情 / 进度 |
| POST | `/api/tasks/{id}/cancel` | 取消任务 |
| DELETE | `/api/tasks/{id}` | 删除任务记录 |

示例：

```bash
curl -X POST http://localhost:8000/api/library/scan -H 'Content-Type: application/json' \
     -d '{"directory":"/media/movies","recursive":true}'

curl http://localhost:8000/api/media?media_type=video&page=1&page_size=24

curl -X POST http://localhost:8000/api/tasks/transcode -H 'Content-Type: application/json' \
     -d '{"media_id":12,"vcodec":"libx264","acodec":"aac","crf":23,"scale":"1280:-2"}'
```

---

## 9. Docker 部署

```bash
docker compose up -d --build
# 浏览器访问 http://localhost:8000
```

`docker-compose.yml` 会把宿主机的 `${MEDIA_HOST_DIR}`（默认 `./media`）只读挂载到容器 `/media`，
并把 `./data` 持久化出来。

```bash
MEDIA_HOST_DIR=/srv/movies docker compose up -d --build
```

---

## 10. 测试

```bash
source .venv/bin/activate
pytest -q
```

测试覆盖：健康检查、媒体列表 / 详情 / 搜索接口、ffprobe 解析工具、CLI 子命令。

---

## 11. 常见问题（FAQ）

**Q1：`ffmpeg 不可用` 怎么办？**
执行 `sudo apt install -y ffmpeg`，或把 `FFMPEG_BIN` / `FFPROBE_BIN` 指向自定义路径。服务在缺少 ffmpeg 时仍可启动，`/api/health` 会返回 `degraded`。

**Q2：播放时不能拖动进度？**
确认请求走的是 `/api/stream/{id}`（前端默认使用），该接口实现了 HTTP Range；若用 `/download` 则不支持分片。

**Q3：扫描很慢？**
缩略图生成耗时明显，可在 `.env` 中设 `SCAN_THUMBNAILS=false`，封面会在首次访问缩略图接口时即时生成。

**Q4：数据库在哪？**
默认 `data/mediahub.db`（SQLite）。修改 `DATABASE_URL` 可切换数据库位置。

**Q5：如何彻底重置媒体库？**
停止服务后删除 `data/mediahub.db` 与 `data/cache/`，重新扫描即可。**注意：这只影响索引与封面，不会动你的源文件。**

---

## 12. 许可

MIT License。仅供学习与个人使用。
*（内容由AI生成，仅供参考）*
