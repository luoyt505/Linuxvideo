"""CLI 工具测试：参数解析与 stats 子命令（不依赖 ffmpeg）。"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from cli import mediahub_cli as cli


@pytest.fixture()
def parser():
    return cli.build_parser()


def test_scan_args(parser):
    args = parser.parse_args(["scan", "--dir", "/media/movies", "--no-recursive", "--json"])
    assert args.command == "scan"
    assert args.dir == "/media/movies"
    assert args.recursive is False
    assert args.json is True
    assert args.func is cli.cmd_scan


def test_list_args_defaults(parser):
    args = parser.parse_args(["list"])
    assert args.type is None
    assert args.limit == 20
    assert args.offset == 0


def test_list_args_filters(parser):
    args = parser.parse_args(["list", "--type", "video", "--year", "2024", "--search", "星际"])
    assert (args.type, args.year, args.search) == ("video", 2024, "星际")


def test_info_args(parser):
    args = parser.parse_args(["info", "12", "--probe"])
    assert args.media_id == 12
    assert args.probe is True


def test_transcode_args(parser):
    args = parser.parse_args(["transcode", "--input", "/tmp/a.mkv", "--crf", "20", "--preset", "slow"])
    assert args.input == "/tmp/a.mkv"
    assert args.crf == 20
    assert args.preset == "slow"


def test_serve_args(parser):
    args = parser.parse_args(["serve", "--port", "9000", "--reload"])
    assert args.port == 9000
    assert args.reload is True


def test_no_command_prints_help(parser):
    args = parser.parse_args([])
    assert getattr(args, "command", None) is None


def test_transcode_requires_source(parser):
    with pytest.raises(SystemExit):
        cli.main(["transcode"])


def test_stats_command_json(db):
    """stats 子命令以 JSON 输出，空库时各计数为 0。"""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(["stats", "--json"])
    assert code == 0
    data = json.loads(buffer.getvalue())
    assert data["total_items"] == 0
    assert set(data["by_type"]) == {"video", "audio", "image", "other"}
