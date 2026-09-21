"""認証なしダッシュボードの安全な待受既定を検証する。"""

from pathlib import Path

import pytest
import requests

from saxokit import web


def test_serve_defaults_to_loopback(monkeypatch):
    seen = {}

    class StubServer:
        def __init__(self, address, handler):
            seen["address"] = address
            seen["handler"] = handler

        def serve_forever(self):
            seen["served"] = True

    monkeypatch.setattr(web, "ThreadingHTTPServer", StubServer)
    web.serve()

    assert seen == {
        "address": ("127.0.0.1", 8787),
        "handler": web.Handler,
        "served": True,
    }


def test_build_status_rejects_unsupported_account_currency(tmp_path, monkeypatch):
    class StubApi:
        env = "sim"

        def quote(self, uic):
            raise AssertionError(f"未対応通貨で換算レートを取得しようとした: {uic}")

        def total_value(self):
            return 1000.0, "CHF"

    import saxokit.api

    monkeypatch.setattr(saxokit.api, "SaxoApi", StubApi)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path)

    status = web.build_status()

    assert status["balance"] is None
    assert status["error"] == "口座通貨 CHF は JPY 換算未対応"


def test_build_status_uses_strategy_warmup_history_days(tmp_path, monkeypatch):
    calls = []

    class StubApi:
        env = "sim"

        def quote(self, uic):
            return {"Mid": 150.0, "MarketState": "Open"}

        def total_value(self):
            return 1000.0, "JPY"

        def net_positions(self):
            return []

        def fetch_candles(self, **kwargs):
            calls.append(kwargs)
            return []

    import saxokit.api

    book = [{"uic": 42, "symbol": "usdjpy", "strategies": ["ema9/26"], "quote": "JPY"}]
    monkeypatch.setattr(saxokit.api, "SaxoApi", StubApi)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web, "BOOK", book)
    monkeypatch.setattr(web, "HORIZON", 240)
    monkeypatch.setattr(web, "history_days", lambda specs, horizon: 37)

    status = web.build_status()

    assert status["error"] is None
    assert calls == [{"uic": 42, "horizon": 240, "days": 37}]


def test_build_status_avoids_unused_conversion_quotes(tmp_path, monkeypatch):
    quote_uics = []

    class StubApi:
        env = "sim"

        def quote(self, uic):
            quote_uics.append(uic)
            return {"Mid": 150.0, "MarketState": "Open"}

        def total_value(self):
            return 1000.0, "JPY"

        def net_positions(self):
            return []

        def fetch_candles(self, **_kwargs):
            return []

    import saxokit.api

    monkeypatch.setattr(saxokit.api, "SaxoApi", StubApi)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path)

    status = web.build_status()

    assert status["error"] is None
    assert quote_uics == [42]  # BOOK の USDJPY 気配だけ。USD/EUR の換算気配は不要


def test_external_requests_are_blocked_before_sending():
    with pytest.raises(pytest.fail.Exception, match="外部 HTTP 通信を拒否"):
        requests.get("https://gateway.saxobank.com/sim/openapi/port/v1/users/me")


def test_dashboard_labels_estimates_and_routes_error_help():
    html = (Path(web.__file__).parent / "dashboard.html").read_text(encoding="utf-8")

    assert '<div class="brand">saxokit ' in html
    assert "台帳・概算" in html
    assert "saxokit journal" in html
    assert "証券会社の取引報告" in html
    assert "照合" in html
    assert "const authHelp = /401|SAXO_TOKEN/.test(d.error)" in html
    assert "/401|エラー|Error|Traceback|不明|拒否|失敗/.test(l)" in html
