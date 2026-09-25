---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: b8db4e6c56b458d3d8c3c7fcc601e100_8272ce79b8c011f1b172525400248c00
    ReservedCode1: S7ieaI60qgwSD14Xzkrza75NNbHa7iw6Rax6RJZq4DCjqwYt8B9BxoeXBjAyvwcv03Q7xn9SBIOfpTMkU1A/KHqQ/kOnStMcajXJPMXPHeF2/SOqP3wBKxBTg8du9pXdmlQmt8JQxehunXdUMz/nFZDDy2AdjDoLnjaw92uZudKWgylD+50QEtuTc2U=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: b8db4e6c56b458d3d8c3c7fcc601e100_8272ce79b8c011f1b172525400248c00
    ReservedCode2: S7ieaI60qgwSD14Xzkrza75NNbHa7iw6Rax6RJZq4DCjqwYt8B9BxoeXBjAyvwcv03Q7xn9SBIOfpTMkU1A/KHqQ/kOnStMcajXJPMXPHeF2/SOqP3wBKxBTg8du9pXdmlQmt8JQxehunXdUMz/nFZDDy2AdjDoLnjaw92uZudKWgylD+50QEtuTc2U=
---

# mediahub REST API 文档

- **Base URL**：`http://<主机>:<端口>`，默认 `http://localhost:8000`
- **数据格式**：请求与响应均为 `application/json`（流式播放与封面接口除外）
- **鉴权**：无（设计为内网 / 个人自用；如需暴露公网，请置于反向代理之后并自行加鉴权）
- **交互式文档**：启动服务后访问 `/docs`（Swagger UI）或 `/redoc`

---

## 1. 通用约定

### 1.1 错误响应

| 状态码 | 含义 | 响应体示例 |
| --- | --- | --- |
| 400 | 参数非法（如转码既未给 `media_id` 也未给 `path`） | `{"detail": "必须提供 media_id 或 path"}` |
| 404 | 资源不存在（条目 / 任务 / 源文件） | `{"detail": "媒体条目不存在：id=42"}` |
| 409 | 状态冲突（如删除运行中的任务） | `{"detail": "任务正在运行，请先取消再删除"}` |
| 416 | Range 请求区间不可满足 | 空响应体 + `Content-Range: bytes */<size>` |
| 422 | 请求体校验失败 | `{"detail": [ ... ]}` |

### 1.2 媒体条目对象（MediaItem）

```json
{
  "id": 1,
  "filename": "Interstellar.2014.1080p.mkv",
  "title": "Interstellar",
  "media_type": "video",
  "container": "matroska,webm",
  "size": 5368709120,
  "duration": 10140.5,
  "width": 1920,
  "height": 1080,
  "video_codec": "h264",
  "audio_codec": "aac",
  "bit_rate": 4200000,
  "frame_rate": 23.976,
  "sample_rate": 48000,
  "channels": 6,
  "stream_count": 3,
  "year": 2014,
  "has_thumbnail": true,
  "directory": "/media/movies",
  "mtime": 1700000000.0,
  "created_at": "2025-01-01T10:00:00",
  "updated_at": "2025-01-01T10:00:00",
  "thumbnail_url": "/api/media/1/thumbnail",
  "stream_url": "/api/stream/1",
  "download_url": "/api/media/1/download",
  "path": "/media/movies/Interstellar.2014.1080p.mkv"
}
```

### 1.3 任务对象（Task）

```json
{
  "id": 7,
  "task_type": "transcode",
  "status": "running",
  "progress": 42,
  "source_path": "/media/movies/Interstellar.mkv",
  "output_path": "/app/data/transcoded/transcode/Interstellar.mp4",
  "params": {"vcodec": "libx264", "crf": 23},
  "result": null,
  "error": null,
  "created_at": "2025-01-01T10:00:00",
  "started_at": "2025-01-01T10:00:01",
  "finished_at": null
}
```

`status` 取值：`pending`（排队）→ `running`（执行中）→ `success` / `failed` / `canceled`（终态）。
`progress` 为 0–100 的整数，由 ffmpeg `-progress` 输出实时换算。

---

## 2. 健康检查

### GET /api/health

返回服务整体状态、依赖可用性、媒体数量与任务分布。

```bash
curl http://localhost:8000/api/health
```

```json
{
  "status": "ok",
  "app": "mediahub",
  "version": "1.0.0",
  "server_time": "2025-01-01T10:00:00+00:00",
  "uptime_seconds": 128.4,
  "database": "ok",
  "media_count": 128,
  "tasks": {"pending": 0, "running": 1, "success": 30, "failed": 2, "canceled": 0},
  "task_queue": {"workers": 2, "pending_in_memory": 0},
  "ffmpeg": {"available": true, "version": "ffmpeg version 6.1.1 ...", "path": "/usr/bin/ffmpeg"},
  "ffprobe": {"available": true, "version": "ffprobe version 6.1.1 ...", "path": "/usr/bin/ffprobe"},
  "media_dirs": ["/media"]
}
```

`status` 为 `ok` 表示 **数据库可用且 ffmpeg/ffprobe 均可用**；否则为 `degraded`。

### GET /api/health/ping

轻量探活，用于容器 HEALTHCHECK 与负载均衡探测。

```bash
curl http://localhost:8000/api/health/ping
# {"pong": true, "app": "mediahub"}
```

---

## 3. 媒体库

### POST /api/library/scan

创建**扫描任务**（异步执行，立即返回任务对象；进度通过 `/api/tasks/{id}` 查询）。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `directory` | string | 否 | 只扫描指定目录；留空则扫描 `.env` 中配置的全部 `MEDIA_DIRS` |
| `recursive` | bool | 否 | 是否递归子目录；留空则用 `SCAN_RECURSIVE` |

```bash
curl -X POST http://localhost:8000/api/library/scan \
     -H 'Content-Type: application/json' \
     -d '{"directory": "/media/movies", "recursive": true}'
```

任务成功后的 `result` 字段：

```json
{
  "directories": ["/media/movies"],
  "recursive": true,
  "total": 120, "added": 15, "updated": 3,
  "skipped": 102, "failed": 0, "degraded": 0, "removed": 1, "errors": []
}
```

> `failed` 表示完全无法入库的文件数；`degraded` 表示 ffprobe 探测失败、但已按文件名降级入库的数量（缺失 ffmpeg 时也会计入）。

> 扫描为增量：文件 `mtime` 与 `size` 未变化时跳过；源文件已消失的记录会自动清理（仅限本次扫描覆盖的目录）。

### GET /api/library/stats

媒体库统计。

```bash
curl http://localhost:8000/api/library/stats
```

```json
{
  "total_items": 128,
  "by_type": {"video": 96, "audio": 24, "image": 8, "other": 0},
  "total_size": 107374182400,
  "total_size_human": "100.00 GB",
  "total_duration": 432000.0,
  "total_duration_human": "120h 0m 0s",
  "thumbnail_count": 104,
  "by_year": [{"year": 2024, "count": 30}, {"year": 2023, "count": 22}],
  "by_container": [{"container": "mov,mp4,m4a,3gp,3g2,mj2", "count": 60}],
  "top_directories": [{"directory": "/media/movies", "count": 96, "size": 1073741824}],
  "recent_items": [{"id": 128, "filename": "..."}],
  "media_dirs": ["/media"]
}
```

### GET /api/library/dirs

查看已配置的媒体目录与运行时目录。

```json
{
  "media_dirs": ["/media/movies", "/media/music"],
  "recursive": true,
  "scan_thumbnails": true,
  "transcode_dir": "/app/data/transcoded",
  "cache_dir": "/app/data/cache"
}
```

### POST /api/library/prune

清理源文件已不存在的媒体记录（不会删除任何源文件）。

```json
{"ok": true, "message": "已清理 3 条失效记录"}
```

---

## 4. 媒体条目

### GET /api/media

分页查询媒体条目。

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `q` | string | — | 关键词，匹配标题 / 文件名 / 路径（`LIKE` 模糊匹配，大小写不敏感） |
| `media_type` | string | — | `video` / `audio` / `image` / `other` |
| `year` | int | — | 按年份筛选 |
| `container` | string | — | 按容器格式模糊筛选，如 `mp4` |
| `sort` | string | `created_at` | `created_at` / `updated_at` / `title` / `filename` / `size` / `duration` / `year` |
| `order` | string | `desc` | `asc` / `desc` |
| `page` | int | 1 | 页码（从 1 开始） |
| `page_size` | int | 24 | 每页条数（1–200） |

```bash
curl 'http://localhost:8000/api/media?media_type=video&year=2024&sort=duration&order=desc&page=1&page_size=24'
```

```json
{"total": 96, "page": 1, "page_size": 24, "pages": 4, "items": [ /* MediaItem 数组 */ ]}
```

### GET /api/media/{id}

媒体详情。加 `?probe=true` 会现场重新运行 `ffprobe`，返回完整流信息（`streams`）。

```bash
curl 'http://localhost:8000/api/media/1?probe=true'
```

额外字段：`exists`（源文件当前是否仍存在）、`probe`（ffprobe 原始解析结果）、`probe_error`（探测失败时的原因）。

### DELETE /api/media/{id}

仅从媒体库**移除索引记录**，源文件不受影响；同时清理已生成的封面缓存。

```json
{"ok": true, "message": "已从媒体库移除记录 id=1（源文件未被删除）"}
```

### GET /api/media/{id}/thumbnail

返回该条目的封面（JPEG）。若缓存不存在且源文件可读，会**即时生成**后返回；无法生成时返回 404。

### GET /api/media/{id}/download

以附件形式下载源文件，响应头带 `Accept-Ranges: bytes`。

---

## 5. 流式播放（HTTP Range）

### GET /api/stream/{id}

支持单区间 `Range` 请求，播放器可据此实现拖动进度、断点续播。

| 请求 | 状态码 | 响应头 | 说明 |
| --- | --- | --- | --- |
| 无 `Range` | 200 | `Content-Length` | 返回完整文件流 |
| `Range: bytes=0-99` | 206 | `Content-Range: bytes 0-99/<size>` | 返回前 100 字节 |
| `Range: bytes=-50` | 206 | `Content-Range: bytes <size-50>-<size-1>/<size>` | 返回末尾 50 字节 |
| `Range: bytes=5000-6000`（越界） | 416 | `Content-Range: bytes */<size>` | 区间不可满足 |

```bash
# 播放整段
curl -I http://localhost:8000/api/stream/1

# 取前 1MB
curl -H 'Range: bytes=0-1048575' -o part.bin http://localhost:8000/api/stream/1
```

响应头附带 `Accept-Ranges: bytes`、`Content-Disposition: inline; filename="..."`、`Cache-Control: no-cache`。
响应体的 `Content-Type` 会按扩展名推断（如 `video/x-matroska`、`audio/flac`）。

### HEAD /api/stream/{id}

返回流媒体元信息（不返回文件内容）。

```json
{"id": 1, "filename": "movie.mkv", "size": 5368709120, "mime": "video/x-matroska",
 "duration": 10140.5, "range_supported": true}
```

### GET /api/stream/{id}/cover

返回播放器封面（等同缩略图）。

---

## 6. 搜索

### GET /api/search

关键词搜索，同时返回**类型 / 年份聚合面**，便于前端联动筛选。

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `q` | string | — | 关键词，留空返回全部 |
| `media_type` | string | — | 类型筛选 |
| `year` | int | — | 年份筛选 |
| `limit` | int | 50 | 返回条数上限（1–200） |

```bash
curl 'http://localhost:8000/api/search?q=interstellar&limit=20'
```

```json
{
  "query": "interstellar",
  "total": 3,
  "returned": 3,
  "facets": {
    "by_type": {"video": 3, "audio": 0, "image": 0, "other": 0},
    "by_year": [{"year": 2014, "count": 3}]
  },
  "items": [ /* MediaItem 数组 */ ]
}
```

---

## 7. 后台任务

### POST /api/tasks/transcode

创建转码任务。

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `media_id` | int | — | 媒体库条目 ID（与 `path` 二选一） |
| `path` | string | — | 源文件绝对路径 |
| `vcodec` | string | `libx264` | 视频编码器；`copy` 表示直接复用原视频流 |
| `acodec` | string | `aac` | 音频编码器；`copy` 表示直接复用原音频流 |
| `crf` | int | 23 | 质量参数（0–51，越小越清晰） |
| `preset` | string | `medium` | x264/x265 预设 |
| `scale` | string | — | 缩放，如 `1280:-2` |
| `audio_bitrate` | string | `192k` | 音频码率 |
| `output_name` | string | — | 输出文件名（默认 `<源文件名>.<扩展名>`） |

```bash
curl -X POST http://localhost:8000/api/tasks/transcode \
     -H 'Content-Type: application/json' \
     -d '{"media_id": 1, "vcodec": "libx264", "crf": 20, "preset": "slow", "scale": "1280:-2"}'
```

### POST /api/tasks/extract-audio

从视频中抽取音轨。

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `media_id` / `path` | — | — | 源（二选一） |
| `acodec` | string | `libmp3lame` | `libmp3lame` / `aac` / `libopus` / `flac` / `pcm_s16le` / `copy` |
| `bitrate` | string | `192k` | 音频码率 |
| `output_name` | string | — | 输出文件名（扩展名按编码器自动匹配） |

### POST /api/tasks/screenshot

在指定时间点截图。

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `media_id` / `path` | — | — | 源（二选一） |
| `at` | float | 3.0 | 截取时间点（秒） |
| `width` | int | — | 输出宽度，留空保持原尺寸 |
| `output_name` | string | — | 输出文件名（默认 `.jpg`） |

### POST /api/tasks/scan

等价于 `POST /api/library/scan`，参数改为查询串：`?directory=/media&recursive=true`。

### GET /api/tasks

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `status` | string | — | `pending` / `running` / `success` / `failed` / `canceled` |
| `task_type` | string | — | `scan` / `transcode` / `extract_audio` / `screenshot` |
| `limit` | int | 50 | 返回条数（1–500），按 ID 倒序 |

```json
{"total": 12, "items": [ /* Task 数组 */ ]}
```

### GET /api/tasks/{id}

查询任务详情与实时进度（前端轮询此接口刷新进度条）。

### POST /api/tasks/{id}/cancel

请求取消任务。排队中的任务立即标记为 `canceled`；执行中的任务会在下一次进度检查点终止 ffmpeg 进程。

```json
{"ok": true, "message": "已请求取消任务 7"}
```

终态任务无法取消，返回 `{"ok": false, "message": "任务已处于终态（success），无法取消"}`。

### DELETE /api/tasks/{id}

删除任务记录（运行中的任务返回 409，需先取消）。

---

## 8. 页面与静态资源

| 路径 | 说明 |
| --- | --- |
| `GET /` | 前端单页应用（SPA） |
| `GET /static/css/style.css` | 样式 |
| `GET /static/js/app.js` | 前端脚本 |
| `GET /docs` | Swagger UI |
| `GET /redoc` | ReDoc |
| `GET /openapi.json` | OpenAPI 3.1 描述文件 |

---

## 9. 典型流程

```bash
# 1) 配置媒体目录后扫描
curl -X POST http://localhost:8000/api/library/scan -H 'Content-Type: application/json' -d '{}'
# → {"id": 1, "task_type": "scan", "status": "pending", ...}

# 2) 轮询扫描进度
curl http://localhost:8000/api/tasks/1

# 3) 搜索 / 浏览
curl 'http://localhost:8000/api/search?q=2024&media_type=video'
curl 'http://localhost:8000/api/media?sort=duration&order=desc&page=1&page_size=12'

# 4) 在线播放（先拿到条目 ID）
curl -H 'Range: bytes=0-1048575' -o chunk.bin http://localhost:8000/api/stream/1

# 5) 提交转码并跟踪进度
curl -X POST http://localhost:8000/api/tasks/transcode -H 'Content-Type: application/json' \
     -d '{"media_id": 1, "crf": 21, "scale": "1280:-2"}'
curl http://localhost:8000/api/tasks/13     # progress 字段即为百分比
```
*（内容由AI生成，仅供参考）*
