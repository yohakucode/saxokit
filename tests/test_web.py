"""認証なしダッシュボードの API・静的配信契約を検証する。"""

from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest
import requests

from saxokit import web


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


def test_dashboard_serves_index_and_hashed_assets_with_queries(tmp_path, monkeypatch):
    static = tmp_path / "static"
    assets = static / "assets"
    assets.mkdir(parents=True)
    index = "<!doctype html><div id=\"root\"></div>".encode()
    script = "export const ready = true;".encode()
    (static / "index.html").write_bytes(index)
    (assets / "app-a1b2.js").write_bytes(script)
    monkeypatch.setattr(web, "STATIC_DIR", static)

    with dashboard_server() as base:
        page = requests.get(f"{base}/?v=20260921")
        asset = requests.get(f"{base}/assets/app-a1b2.js?v=20260921")

    assert page.status_code == 200
    assert page.content == index
    assert page.headers["Content-Type"] == "text/html; charset=utf-8"
    assert int(page.headers["Content-Length"]) == len(index)
    assert asset.status_code == 200
    assert asset.content == script
    assert asset.headers["Content-Type"] in {
        "application/javascript; charset=utf-8",
        "text/javascript; charset=utf-8",
    }
    assert int(asset.headers["Content-Length"]) == len(script)


@pytest.mark.parametrize(
    "path",
    [
        "/assets/",
        "/assets/%2e%2e/index.html",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/assets/nested/%2e%2e/app.js",
        "/unknown",
    ],
)
def test_dashboard_rejects_directories_traversal_and_unknown_routes(
    path, tmp_path, monkeypatch
):
    static = tmp_path / "static"
    (static / "assets" / "nested").mkdir(parents=True)
    (static / "index.html").write_text("index")
    (static / "assets" / "app.js").write_text("app")
    (tmp_path / "secret.txt").write_text("secret")
    monkeypatch.setattr(web, "STATIC_DIR", static)

    with dashboard_server() as base:
        response = requests.get(base + path)

    assert response.status_code == 404
    assert b"secret" not in response.content


def test_dashboard_rejects_symlinks_outside_static_root(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.html").write_text("outside index")
    (outside / "escape.js").write_text("outside asset")

    index_link_root = tmp_path / "index-link-static"
    index_link_root.mkdir()
    (index_link_root / "index.html").symlink_to(outside / "index.html")
    monkeypatch.setattr(web, "STATIC_DIR", index_link_root)
    with dashboard_server() as base:
        index_response = requests.get(f"{base}/")

    asset_link_root = tmp_path / "asset-link-static"
    (asset_link_root / "assets").mkdir(parents=True)
    (asset_link_root / "index.html").write_text("safe index")
    (asset_link_root / "assets" / "escape.js").symlink_to(outside / "escape.js")
    monkeypatch.setattr(web, "STATIC_DIR", asset_link_root)
    with dashboard_server() as base:
        asset_response = requests.get(f"{base}/assets/escape.js")

    assets_dir_link_root = tmp_path / "assets-dir-link-static"
    assets_dir_link_root.mkdir()
    (assets_dir_link_root / "index.html").write_text("safe index")
    (assets_dir_link_root / "assets").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(web, "STATIC_DIR", assets_dir_link_root)
    with dashboard_server() as base:
        assets_dir_response = requests.get(f"{base}/assets/escape.js")

    assert index_response.status_code == 404
    assert asset_response.status_code == 404
    assert assets_dir_response.status_code == 404
    assert b"outside" not in index_response.content
    assert b"outside" not in asset_response.content
    assert b"outside" not in assets_dir_response.content


def test_status_api_remains_available_when_dashboard_bundle_is_missing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(web, "STATIC_DIR", tmp_path / "not-built")
    monkeypatch.setattr(web, "cached_status", lambda: {"env": "sim", "error": None})

    with dashboard_server() as base:
        missing = requests.get(f"{base}/?cache=1")
        status = requests.get(f"{base}/api/status?cache=1")
        traversal = requests.get(f"{base}/assets/%2e%2e/secret.txt")

    assert missing.status_code == 503
    assert "Dashboard bundle is missing" in missing.text
    assert status.status_code == 200
    assert status.json() == {"env": "sim", "error": None}
    assert status.headers["Content-Type"] == "application/json; charset=utf-8"
    assert int(status.headers["Content-Length"]) == len(status.content)
    assert traversal.status_code == 404
