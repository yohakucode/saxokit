"""equity.csv 破損時の読み込み・追記・ダッシュボード API の回帰テスト(合成データのみ)。"""

import math
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest
import requests
import saxokit.api
from saxokit import cli, web
from saxokit.data import Candle
from saxokit.equity import EquityError, append_equity, read_equity

H1 = 3_600_000


def csv_bytes(*rows: str, tail: str = "") -> bytes:
    return ("".join(row + "\n" for row in rows) + tail).encode()


@contextmanager
def dashboard_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class StubApi:
    env = "sim"

    def quote(self, uic):
        return {"Mid": 150.0, "MarketState": "Open"}

    def total_value(self):
        return 1000.0, "JPY"

    def net_positions(self):
        return []

    def fetch_candles(self, **_kwargs):
        return []


def test_status_serves_valid_equity_and_warning_for_malformed_csv(
    tmp_path, monkeypatch
):
    path = tmp_path / "equity.csv"
    path.write_bytes(
        csv_bytes(
            "ts,total_value",
            "3600000,1000",
            "",
            "7200000,1001",
            "10800000,nan",
            "14400000,inf",
            "garbage",
            "18000000,-Infinity",
            "21600000,1e999",
            "25200000,1002",
            tail="2880",
        )
    )
    before = path.read_bytes()
    monkeypatch.setattr(saxokit.api, "SaxoApi", StubApi)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web, "_cache", {"ts": 0.0, "data": None})

    with dashboard_server() as base:
        response = requests.get(f"{base}/api/status")

    assert response.status_code == 200
    status = response.json()
    assert status["error"] is None  # 記録の破損は API エラーと別枠で伝える
    assert status["balance"] == 1000.0
    assert status["equity"] == [[3600000, 1000], [7200000, 1001], [25200000, 1002]]
    issues = status["equity_issues"]
    assert [issue.split(" ", 1)[0] for issue in issues] == [
        "3",
        "5",
        "6",
        "7",
        "8",
        "9",
        "11",
    ]
    assert "改行で終わっていない" in issues[-1]
    assert path.read_bytes() == before


def test_status_reports_no_issue_for_clean_equity(tmp_path, monkeypatch):
    (tmp_path / "equity.csv").write_bytes(csv_bytes("ts,total_value", "3600000,1000"))
    monkeypatch.setattr(saxokit.api, "SaxoApi", StubApi)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path)

    status = web.build_status()

    assert status["equity"] == [[3600000, 1000.0]]
    assert status["equity_issues"] == []


@pytest.mark.parametrize(
    "value", ["nan", "NaN", "-nan", "inf", "+inf", "-Infinity", "1e999"]
)
def test_read_equity_rejects_nonfinite_values(tmp_path, value):
    path = tmp_path / "equity.csv"
    path.write_bytes(
        csv_bytes("ts,total_value", "3600000,1000", f"7200000,{value}", "10800000,1002")
    )

    scan = read_equity(path)

    assert scan.points == [[3600000, 1000.0], [10800000, 1002.0]]
    assert all(math.isfinite(v) for _, v in scan.points)
    assert len(scan.problems) == 1
    assert scan.problems[0].startswith("3 行目: total_value が有限の数値ではない")


def test_read_equity_excludes_parseable_but_truncated_tail(tmp_path):
    path = tmp_path / "equity.csv"
    path.write_bytes(csv_bytes("ts,total_value", "3600000,1000", tail="7200000,10"))

    scan = read_equity(path)

    assert scan.points == [[3600000, 1000.0]]
    assert len(scan.problems) == 1
    assert scan.problems[0].startswith("3 行目: 改行で終わっていない")


def test_read_equity_missing_empty_and_header_only_are_clean(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    header_only = tmp_path / "header.csv"
    header_only.write_bytes(csv_bytes("ts,total_value"))

    for path in (tmp_path / "missing.csv", empty, header_only):
        scan = read_equity(path)
        assert scan.points == []
        assert scan.problems == []


def test_read_equity_reports_unreadable_path(tmp_path):
    path = tmp_path / "equity.csv"
    path.mkdir()

    scan = read_equity(path)

    assert scan.points == []
    assert len(scan.problems) == 1
    assert "読み込めない" in scan.problems[0]


@pytest.mark.parametrize(
    "content",
    [
        csv_bytes("ts,total_value", "3600000,1000", tail="72000"),
        csv_bytes("ts,total_value", "3600000,1000", tail="7200000,1001"),
        csv_bytes("ts,total_value", "3600000,1000", ""),
        csv_bytes("ts,total_value", "3600000,nan"),
        csv_bytes("ts,total_value", "3600000,1000", "x,y,z"),
        csv_bytes("timestamp,value", "3600000,1000"),
        b"ts,total_value",
    ],
)
def test_append_refuses_corrupt_file_and_leaves_bytes_unchanged(tmp_path, content):
    path = tmp_path / "equity.csv"
    path.write_bytes(content)

    with pytest.raises(EquityError, match="追記を中止"):
        append_equity(path, 10 * H1, 2000)

    assert path.read_bytes() == content


@pytest.mark.parametrize("total", [math.nan, math.inf, -math.inf])
def test_append_rejects_nonfinite_total(tmp_path, total):
    path = tmp_path / "equity.csv"
    content = csv_bytes("ts,total_value", "3600000,1000")
    path.write_bytes(content)
    missing = tmp_path / "new" / "equity.csv"

    with pytest.raises(EquityError, match="有限"):
        append_equity(path, 10 * H1, total)
    with pytest.raises(EquityError, match="有限"):
        append_equity(missing, 10 * H1, total)

    assert path.read_bytes() == content
    assert not missing.parent.exists()


def test_append_keeps_clean_cadence(tmp_path):
    path = tmp_path / "equity.csv"

    append_equity(path, H1, 1000)
    append_equity(path, H1 + 10 * 60_000, 1001)  # 30 分以内は記録しない
    append_equity(path, H1 + 31 * 60_000, 1002.4)

    assert path.read_text() == "ts,total_value\n3600000,1000\n5460000,1002\n"


def test_append_writes_header_to_empty_file_and_rows_after_header_only(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    header_only = tmp_path / "header.csv"
    header_only.write_bytes(csv_bytes("ts,total_value"))

    append_equity(empty, 2 * H1, 1000)
    append_equity(header_only, 2 * H1, 1000)

    assert empty.read_text() == "ts,total_value\n7200000,1000\n"
    assert header_only.read_text() == "ts,total_value\n7200000,1000\n"


def test_paper_stops_before_order_when_equity_is_corrupt(monkeypatch, tmp_path):
    class Api:
        env = "sim"

        def fetch_candles(self, **kwargs):
            return [Candle(i * H1, 100, 100, 100, 100) for i in range(80)]

        def quote(self, _uic):
            return {"MarketState": "Open", "Mid": 100, "Bid": 99, "Ask": 101}

        def net_position_amount(self, _uic):
            return 0.0

        def total_value(self):
            return 200_000, "JPY"

        def get(self, _path):
            return {"CurrencyCode": "JPY"}

        def place_market_order(self, *_args):
            raise AssertionError("破損を検知した後に発注しようとした")

    monkeypatch.setattr(saxokit.api, "SaxoApi", Api)
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli.time, "time", lambda: 100 * 3600)
    monkeypatch.setattr(cli, "strategy_target", lambda spec, cs: [1] * len(cs))
    path = tmp_path / "equity.csv"
    path.write_bytes(csv_bytes("ts,total_value", "3600000,1000", tail="36000"))
    before = path.read_bytes()

    with pytest.raises(EquityError, match="追記を中止"):
        cli.cmd_paper(
            SimpleNamespace(
                strategies="ema9/26",
                symbol="sample",
                uic=42,
                horizon=60,
                leverage=1,
                lot=1000,
                dry_run=False,
            )
        )

    assert path.read_bytes() == before


def test_oversized_timestamp_is_reported_without_crashing(tmp_path):
    path = tmp_path / "equity.csv"
    path.write_text("ts,total_value\n" + "9" * 5000 + ",1000\n3600000,1001\n")
    scan = read_equity(path)
    assert scan.points == [[3600000, 1001.0]]
    assert len(scan.problems) == 1


def test_api_error_and_csv_warning_are_preserved_together(tmp_path, monkeypatch):
    class FailedApi:
        def __init__(self):
            raise SystemExit("401 simulated")

    (tmp_path / "equity.csv").write_text("ts,total_value\n3600000,nan\n")
    monkeypatch.setattr(saxokit.api, "SaxoApi", FailedApi)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path)
    status = web.build_status()
    assert status["error"] == "401 simulated"
    assert status["equity_issues"]


@pytest.mark.parametrize("ts", [True, -1, 2**53, 3.5])
def test_append_rejects_unrepresentable_timestamp(tmp_path, ts):
    path = tmp_path / "equity.csv"
    with pytest.raises(EquityError):
        append_equity(path, ts, 1000)
    assert not path.exists()
