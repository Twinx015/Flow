"""JSON-logger formatter tests — Path-bearing payloads must not crash.

Regression for the download logging error: `outdir` arrived as a
`pathlib.Path` and `json.dumps` raised, dropping the log line and
spamming stderr. The formatter now passes `default=str`.
"""

import json
import logging
import pathlib

from backend import logger as flog


def _record(data):
    record = logging.LogRecord(
        name="flow.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="downloading %s",
        args=("https://example.com/watch?v=abc",),
        exc_info=None,
    )
    record.component = "yt_dlp"
    record.event = "download_start"
    record.data = data
    return record


def test_path_payload_serializes():
    fmtr = flog._make_json_formatter()
    out = fmtr.format(_record({"outdir": pathlib.Path("/home/x/.flow/downloads")}))
    entry = json.loads(out)
    assert entry["data"]["outdir"] == "/home/x/.flow/downloads"
    assert entry["event"] == "download_start"


def test_plain_payloads_still_valid_json():
    fmtr = flog._make_json_formatter()
    out = fmtr.format(_record({"url": "u", "fmt": None, "ms": 30_000}))
    entry = json.loads(out)
    assert entry["data"] == {"url": "u", "fmt": None, "ms": 30_000}
    assert entry["message"] == "downloading https://example.com/watch?v=abc"


def test_unexpected_objects_degrade_not_raise():
    fmtr = flog._make_json_formatter()
    out = fmtr.format(_record({"when": pathlib.Path("/a/b"), "blob": object()}))
    entry = json.loads(out)
    assert entry["data"]["when"] == "/a/b"
    assert isinstance(entry["data"]["blob"], str)
