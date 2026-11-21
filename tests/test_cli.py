import pytest

from goveehome.cli import build_parser


def test_parser_commands():
    p = build_parser()
    args = p.parse_args(["color", "desk", "255", "0", "0"])
    assert args.color == ["255", "0", "0"]
    args = p.parse_args(["--host", "10.0.0.9", "sync", "--backend", "pattern", "tv"])
    assert args.host == ["10.0.0.9"] and args.targets == ["tv"]


def test_parser_requires_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
