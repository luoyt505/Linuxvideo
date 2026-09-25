#!/usr/bin/env python3
"""mediahub-cli —— 命令行管理工具。

子命令：
    scan       扫描媒体目录并入库
    list       列出媒体条目（支持搜索 / 筛选 / 排序）
    info       查看单个媒体条目的详细信息
    transcode  转码文件（本机进程内执行，带进度条）
    stats      查看媒体库统计
    serve      启动 Web 服务

用法示例：
    python -m cli.mediahub_cli stats
    python -m cli.mediahub_cli scan --dir ~/Videos --recursive
    python -m cli.mediahub_cli list --type video --limit 20
    python -m cli.mediahub_cli info 3
    python -m cli.mediahub_cli transcode 3 --crf 20 --preset slow
    python -m cli.mediahub_cli serve --port 8000 --reload
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# 允许直接以脚本方式运行（python cli/mediahub_cli.py）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings          # noqa: E402
from app.database import SessionLocal, init_db   # noqa: E402
from app.services import library, scanner         # noqa: E402
from app.utils import ffmpeg_utils                # noqa: E402

try:  # 优先使用 SQLAlchemy 模型查询
    from app import models
except Exception:  # pragma: no cover
    models = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# 输出辅助
# --------------------------------------------------------------------------- #
def _fmt_size(num: float) -> str:
    return library.human_size(num)


def _fmt_duration(seconds: float) -> str:
    return library.human_duration(seconds)


def _use_color() -> bool:
    return sys.stdout.isatty()


def _color(text: str, code: str) -> str:
    if not _use_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def _ok(text: str) -> str:
    return _color(text, "32")


def _warn(text: str) -> str:
    return _color(text, "33")


def _err(text: str) -> str:
    return _color(text, "31")


def _bold(text: str) -> str:
    return _color(text, "1")


def _truncate(text: str, width: int) -> str:
    """按显示宽度截断（中文按 2 列计）。"""
    text = str(text)
    if len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "…"


def print_table(headers, rows) -> None:
    """打印对齐的文本表格。"""
    if not rows:
        print(_warn("（无数据）"))
        return
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))

    line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(_bold(line))
    print("-" * len(line))
    for row in rows:
        print("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))


def progress_bar(label: str, percent: int) -> None:
    """渲染单行进度条。"""
    percent = max(0, min(100, int(percent)))
    filled = int(percent / 100 * 30)
    bar = "#" * filled + "-" * (30 - filled)
    sys.stdout.write(f"\r{label} [{bar}] {percent:3d}%")
    sys.stdout.flush()
    if percent >= 100:
        sys.stdout.write("\n")


# --------------------------------------------------------------------------- #
# 子命令实现
# --------------------------------------------------------------------------- #
def cmd_scan(args) -> int:
    init_db()
    db = SessionLocal()
    try:
        if args.dir:
            target = Path(args.dir).expanduser()
            if not target.exists():
                print(_err(f"[错误] 目录不存在：{target}"))
                return 1
            directories = [str(target)]
        else:
            directories = settings.media_dirs
            if not directories:
                print(_err("[错误] 未配置媒体目录：请在 .env 中设置 MEDIA_DIRS，或使用 --dir 指定"))
                return 1

        recursive = settings.scan_recursive if args.recursive is None else args.recursive
        if not ffmpeg_utils.ffprobe_available():
            print(_warn("[警告] 未检测到 ffprobe，将只入库基础信息（无法提取时长/编码等元数据）"))

        print(f"开始扫描：{', '.join(directories)}（递归={recursive}）")
        last = {"value": -1}

        def on_progress(value: int) -> None:
            if value != last["value"]:
                last["value"] = value
                progress_bar("扫描进度", value)

        def cancel_check() -> bool:
            return False

        stats = scanner.scan_directory(
            db,
            directory=directories[0] if len(directories) == 1 else None,
            recursive=recursive,
            on_progress=on_progress,
            cancel_check=cancel_check,
        )

        if len(directories) > 1:
            # 多目录时逐个扫描，合并统计
            merged = dict(stats)
            merged["added"] = 0
            merged["updated"] = 0
            merged["skipped"] = 0
            merged["failed"] = 0
            merged["degraded"] = 0
            merged["removed"] = 0
            merged["total"] = 0
            for directory in directories:
                part = scanner.scan_directory(db, directory=directory, recursive=recursive)
                for key in ("added", "updated", "skipped", "failed", "degraded", "removed", "total"):
                    merged[key] = int(merged[key]) + int(part[key])
            stats = merged

        print()
        print(_ok("扫描完成"))
        print(f"  扫描目录 : {', '.join(str(d) for d in stats['directories'])}")
        print(f"  文件总数 : {stats['total']}")
        print(f"  新增     : {stats['added']}")
        print(f"  更新     : {stats['updated']}")
        print(f"  跳过     : {stats['skipped']}")
        print(f"  失败     : {stats['failed']}")
        print(f"  降级入库 : {stats.get('degraded', 0)}")
        print(f"  移除失效 : {stats['removed']}")
        if args.json:
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def cmd_list(args) -> int:
    init_db()
    db = SessionLocal()
    try:
        query = db.query(models.MediaItem)
        if args.type:
            query = query.filter(models.MediaItem.media_type == args.type)
        if args.year:
            query = query.filter(models.MediaItem.year == args.year)
        if args.search:
            pattern = f"%{args.search}%"
            query = query.filter(models.MediaItem.title.ilike(pattern))

        total = query.count()
        rows = query.order_by(models.MediaItem.id.asc()).offset(args.offset).limit(args.limit).all()

        if args.json:
            print(json.dumps([item.to_dict() for item in rows], ensure_ascii=False, indent=2))
            return 0

        table_rows = []
        for item in rows:
            resolution = f"{item.width}x{item.height}" if item.width and item.height else "-"
            table_rows.append([
                item.id,
                item.media_type or "-",
                _truncate(item.filename, 40),
                resolution,
                _fmt_duration(item.duration),
                _fmt_size(item.size),
                item.year or "-",
            ])
        print(f"共 {total} 条，显示 {len(rows)} 条（offset={args.offset}, limit={args.limit}）")
        print_table(["ID", "类型", "文件名", "分辨率", "时长", "大小", "年份"], table_rows)
        return 0
    finally:
        db.close()


def cmd_info(args) -> int:
    init_db()
    db = SessionLocal()
    try:
        target = None
        if args.media_id:
            target = db.query(models.MediaItem).filter(models.MediaItem.id == args.media_id).first()
        elif args.path:
            target = db.query(models.MediaItem).filter(
                models.MediaItem.path == str(Path(args.path).expanduser())
            ).first()

        if target is None and args.path:
            path = Path(args.path).expanduser()
            if path.exists() and ffmpeg_utils.is_media(path):
                data = ffmpeg_utils.probe_info(path)
                data["path"] = str(path)
                data["filename"] = path.name
                print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else _render_info(data))
                return 0

        if target is None:
            print(_err("[错误] 未找到对应的媒体条目"))
            return 1

        data = target.to_dict()
        if args.probe and Path(target.path).exists():
            try:
                data["probe"] = ffmpeg_utils.probe_info(target.path)
            except Exception as exc:  # noqa: BLE001
                data["probe_error"] = str(exc)

        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            _render_info(data)
        return 0
    finally:
        db.close()


def _render_info(data: dict) -> None:
    print(_bold("=" * 64))
    print(_bold(f" {data.get('title') or data.get('filename') or '（未命名）'}"))
    print(_bold("=" * 64))
    fields = [
        ("ID", data.get("id", "-")),
        ("类型", data.get("media_type", "-")),
        ("容器", data.get("container") or "-"),
        ("路径", data.get("path") or "-"),
        ("大小", _fmt_size(data.get("size", 0))),
        ("时长", _fmt_duration(data.get("duration", 0))),
        ("分辨率", f"{data.get('width') or 0}x{data.get('height') or 0}"),
        ("视频编码", data.get("video_codec") or "-"),
        ("音频编码", data.get("audio_codec") or "-"),
        ("帧率", f"{data.get('frame_rate') or 0} fps"),
        ("采样率", f"{data.get('sample_rate') or 0} Hz"),
        ("声道", data.get("channels") or 0),
        ("流数量", data.get("stream_count") or 0),
        ("年份", data.get("year") or "-"),
        ("封面", "有" if data.get("has_thumbnail") else "无"),
    ]
    for label, value in fields:
        print(f"  {label:<8}: {value}")

    streams = (data.get("probe") or {}).get("streams")
    if streams:
        print()
        print(_bold("  流信息:"))
        for stream in streams:
            desc = f"#{stream.get('index')} {stream.get('codec_type')} / {stream.get('codec_name')}"
            if stream.get("width"):
                desc += f" / {stream.get('width')}x{stream.get('height')}"
            if stream.get("sample_rate"):
                desc += f" / {stream.get('sample_rate')}Hz"
            print(f"    - {desc}")


def cmd_transcode(args) -> int:
    init_db()
    db = SessionLocal()
    try:
        source = None
        if args.media_id:
            item = db.query(models.MediaItem).filter(models.MediaItem.id == args.media_id).first()
            if item is None:
                print(_err(f"[错误] 媒体条目不存在：id={args.media_id}"))
                return 1
            source = Path(item.path)
            duration = float(item.duration or 0.0)
        else:
            source = Path(args.input).expanduser()
            duration = 0.0

        if not source.exists():
            print(_err(f"[错误] 源文件不存在：{source}"))
            return 1

        suffix = Path(source).suffix.lower() or ".mp4"
        output = Path(args.output).expanduser() if args.output else (
            settings.transcode_dir / "transcode" / f"{source.stem}_transcoded{suffix}"
        )

        if not ffmpeg_utils.ffmpeg_available():
            print(_err("[错误] 未检测到 ffmpeg，请先安装：sudo apt install -y ffmpeg"))
            return 1

        print(f"源文件 : {source}")
        print(f"输出   : {output}")
        print(f"编码   : v={args.vcodec} a={args.acodec} crf={args.crf} preset={args.preset}")
        print()

        def on_progress(value: int) -> None:
            progress_bar("转码进度", value)

        try:
            ffmpeg_utils.transcode(
                source,
                output,
                vcodec=args.vcodec,
                acodec=args.acodec,
                crf=args.crf,
                preset=args.preset,
                scale=args.scale,
                audio_bitrate=args.audio_bitrate,
                duration=duration or float(args.duration or 0.0),
                on_progress=on_progress,
            )
        except Exception as exc:  # noqa: BLE001
            print()
            print(_err(f"[失败] 转码出错：{exc}"))
            return 1

        print(_ok("[完成]") + f" 输出文件：{output}")
        return 0
    finally:
        db.close()


def cmd_stats(args) -> int:
    init_db()
    db = SessionLocal()
    try:
        data = library.library_stats(db)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0

        print(_bold("=" * 64))
        print(_bold(" mediahub 媒体库统计"))
        print(_bold("=" * 64))
        print(f"  条目总数   : {data['total_items']}")
        print(f"  视频       : {data['by_type'].get('video', 0)}")
        print(f"  音频       : {data['by_type'].get('audio', 0)}")
        print(f"  图片       : {data['by_type'].get('image', 0)}")
        print(f"  其它       : {data['by_type'].get('other', 0)}")
        print(f"  总大小     : {data['total_size_human']}")
        print(f"  总时长     : {data['total_duration_human']}")
        print(f"  已生成封面 : {data['thumbnail_count']}")

        if data["by_container"]:
            print()
            print(_bold("  容器格式分布:"))
            for row in data["by_container"]:
                print(f"    - {row['container']:<10} {row['count']}")

        if data["by_year"]:
            print()
            print(_bold("  年份分布:"))
            for row in data["by_year"][:10]:
                print(f"    - {row['year']:<6} {row['count']}")

        if data["top_directories"]:
            print()
            print(_bold("  目录 TOP: "))
            for row in data["top_directories"]:
                print(f"    - {_truncate(row['directory'], 48):<50} {row['count']} 个 / {_fmt_size(row['size'])}")
        return 0
    finally:
        db.close()


def cmd_serve(args) -> int:
    import uvicorn

    host = args.host or settings.host
    port = int(args.port or settings.port)
    print(f"启动 mediahub 服务：http://{host}:{port}  （API 文档 /docs）")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=bool(args.reload),
        log_level=settings.log_level,
    )
    return 0


# --------------------------------------------------------------------------- #
# 参数解析
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mediahub-cli",
        description="mediahub 命令行管理工具（媒体库扫描 / 查询 / 转码 / 统计 / 服务）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"mediahub-cli {settings.version}")
    sub = parser.add_subparsers(dest="command", metavar="<子命令>")

    # scan
    p_scan = sub.add_parser("scan", help="扫描媒体目录并入库")
    p_scan.add_argument("--dir", "-d", help="指定媒体目录（缺省使用 .env 的 MEDIA_DIRS）")
    p_scan.add_argument("--recursive", action="store_true", default=None, help="递归子目录")
    p_scan.add_argument("--no-recursive", dest="recursive", action="store_false", help="仅扫描顶层")
    p_scan.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_scan.set_defaults(func=cmd_scan)

    # list
    p_list = sub.add_parser("list", help="列出媒体条目")
    p_list.add_argument("--type", "-t", choices=["video", "audio", "image", "other"], help="按类型筛选")
    p_list.add_argument("--year", "-y", type=int, help="按年份筛选")
    p_list.add_argument("--search", "-s", help="按标题关键词搜索")
    p_list.add_argument("--limit", "-n", type=int, default=20, help="显示条数（默认 20）")
    p_list.add_argument("--offset", type=int, default=0, help="起始偏移（默认 0）")
    p_list.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_list.set_defaults(func=cmd_list)

    # info
    p_info = sub.add_parser("info", help="查看媒体条目详情")
    p_info.add_argument("media_id", nargs="?", type=int, help="媒体条目 ID")
    p_info.add_argument("--path", "-p", help="或直接指定文件路径")
    p_info.add_argument("--probe", action="store_true", help="重新运行 ffprobe 获取实时信息")
    p_info.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_info.set_defaults(func=cmd_info)

    # transcode
    p_tc = sub.add_parser("transcode", help="转码媒体文件")
    p_tc.add_argument("media_id", nargs="?", type=int, help="媒体条目 ID")
    p_tc.add_argument("--input", "-i", help="或直接指定源文件路径")
    p_tc.add_argument("--output", "-o", help="输出文件路径")
    p_tc.add_argument("--vcodec", default="libx264", help="视频编码器（默认 libx264）")
    p_tc.add_argument("--acodec", default="aac", help="音频编码器（默认 aac）")
    p_tc.add_argument("--crf", type=int, default=23, help="质量参数（默认 23）")
    p_tc.add_argument("--preset", default="medium", help="编码预设（默认 medium）")
    p_tc.add_argument("--scale", help="缩放，如 1280:-2")
    p_tc.add_argument("--audio-bitrate", default="192k", help="音频码率（默认 192k）")
    p_tc.add_argument("--duration", type=float, default=0.0, help="源时长（秒），用于进度计算")
    p_tc.set_defaults(func=cmd_transcode)

    # stats
    p_stats = sub.add_parser("stats", help="查看媒体库统计")
    p_stats.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_stats.set_defaults(func=cmd_stats)

    # serve
    p_serve = sub.add_parser("serve", help="启动 Web 服务")
    p_serve.add_argument("--host", help=f"监听地址（默认 {settings.host}）")
    p_serve.add_argument("--port", type=int, help=f"监听端口（默认 {settings.port}）")
    p_serve.add_argument("--reload", action="store_true", help="开发模式自动重载")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv=None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    if args.command == "transcode" and not (args.media_id or args.input):
        parser.error("transcode 需要提供 media_id 或 --input")
    if args.command == "info" and not (args.media_id or args.path):
        parser.error("info 需要提供 media_id 或 --path")

    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\n" + _warn("已中断"))
        return 130


if __name__ == "__main__":
    sys.exit(main())
