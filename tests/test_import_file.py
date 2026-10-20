"""Parsers for `flow --import` (CSV / m3u / txt) — no network needed.

The interactive panel (questionary select) is not exercised here; imports
resolve online. These tests pin the row normalization the three actions
(playlist download, plain download, play one by one) all build on.
"""

import pathlib

import pytest

from backend import config
from backend import import_file


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_csv_spotify_style_columns(tmp_path):
    path = _write(
        tmp_path,
        "list.csv",
        "Track Name,Artist Name(s),Album Name,Duration(ms)\n"
        "52 Bars,Karan Aujla & Ikky,Four You,215000\n"
        ",, ,\n",
    )
    rows = import_file.parse(path)
    assert len(rows) == 1
    assert rows[0]["title"] == "52 Bars"
    assert rows[0]["artist"] == "Karan Aujla & Ikky"
    assert rows[0]["album"] == "Four You"
    assert rows[0]["duration"] == 215
    assert rows[0]["query"] == "52 Bars Karan Aujla & Ikky"
    assert not rows[0]["url"] and not rows[0]["vid"]


def test_csv_takeout_style_video_id_and_dur(tmp_path):
    path = _write(
        tmp_path,
        "playlist.csv",
        "Video Id,Title,Duration\n6y9_c5Qavhs,52 Bars,215\n",
    )
    rows = import_file.parse(path)
    assert rows[0]["vid"] == "6y9_c5Qavhs"
    assert rows[0]["title"] == "52 Bars"
    assert rows[0]["duration"] == 215


def test_csv_url_column_extracts_video_id(tmp_path):
    path = _write(
        tmp_path,
        "list.csv",
        "url,title\ney: https://youtu.be/6y9_c5Qavhs,52\n",
    )
    rows = import_file.parse(path)
    assert rows[0]["url"].startswith("https://")
    assert rows[0]["vid"] == "6y9_c5Qavhs"
    # the thrown-away label prefix after the url column is not the title
    assert rows[0]["title"] in ("52", "")


def test_m3u_urls_and_meta(tmp_path):
    path = _write(
        tmp_path,
        "list.m3u",
        "#EXTM3U\n#EXTINF:215,52 Bars\n"
        "https://www.youtube.com/watch?v=6y9_c5Qavhs\n"
        "#EXTINF:0,Wavy\nhttps://youtu.be/qlOwSBYKD6g\n",
    )
    rows = import_file.parse(path)
    assert [r["title"] for r in rows] == ["52 Bars", "Wavy"]
    assert [r["duration"] for r in rows] == [215, 0]
    assert rows[1]["vid"] == "qlOwSBYKD6g"


def test_m3u_saved_query_lines(tmp_path):
    path = _write(tmp_path, "list.m3u", "#EXTM3U\n#EXTINF:0,\na r khan o b相 52 bars\n")
    rows = import_file.parse(path)
    assert rows[0]["query"] == "a r khan o b相 52 bars"


def test_m3u8_extension_local_file(tmp_path):
    local = tmp_path / "52 Bars.webm"
    local.write_bytes(b"x")
    path = _write(
        tmp_path,
        "pl.m3u8",
        f"#EXTM3U\n#EXTINF:0,52 Bars\n{local}\n",
    )
    rows = import_file.parse(path)
    assert rows[0]["local"] == str(local)
    assert rows[0]["title"] == "52 Bars"


def test_txt_lines_become_queries_or_urls(tmp_path):
    path = _write(
        tmp_path,
        "list.txt",
        "# a comment\n"
        "arijit singh kesariya\n"
        "52 bars - https://youtu.be/6y9_c5Qavhs\n"
        "\n",
    )
    rows = import_file.parse(path)
    assert rows[0]["query"] == "arijit singh kesariya"
    assert rows[1]["url"] == "https://youtu.be/6y9_c5Qavhs"
    assert rows[1]["title"] == "52 bars"


def test_unknown_extension_sniffs_m3u(tmp_path):
    path = _write(
        tmp_path,
        "list.unknown",
        "#EXTM3U\n#EXTINF:215,52 Bars\nhttps://youtu.be/6y9_c5Qavhs\n",
    )
    rows = import_file.parse(path)
    assert len(rows) == 1 and rows[0]["duration"] == 215


def test_unknown_extension_sniffs_csv_header(tmp_path):
    path = _write(tmp_path, "list.unknown", "title,artist\n52 Bars,Karan Aujla\n")
    rows = import_file.parse(path)
    assert rows[0]["title"] == "52 Bars"


def test_unmatched_extension_is_txt_lines(tmp_path):
    path = _write(tmp_path, "list.unknown", "52 Bars Karan Aujla\nWavy\n")
    rows = import_file.parse(path)
    assert [r["query"] for r in rows] == ["52 Bars Karan Aujla", "Wavy"]


def test_run_offline_guard(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "Mode", "Offline")
    import_file.run([str(tmp_path / "x.csv")])
    out = capsys.readouterr().out
    assert "online" in out.lower()
    monkeypatch.setattr(config, "Mode", "Online")


def test_run_missing_file_reports(capsys, tmp_path):
    import_file.run([str(tmp_path / "nope.csv")])
    assert "Cannot find" in capsys.readouterr().out


def test_run_no_tty_panel_declines(tmp_path, capsys):
    path = _write(tmp_path, "list.txt", "52 bars karan aujla\n")
    import_file.run([str(path)])
    assert "Interactive panel needs a terminal" in capsys.readouterr().out
