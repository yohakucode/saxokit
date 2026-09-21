"""CLI のファイル副作用と確定足の保存を合成データで検証する。"""

from types import SimpleNamespace

import pytest

import saxokit.api
import saxokit.cli as cli
from saxokit.data import Candle, load_candles_csv, save_candles_csv
from saxokit.ledger import append_ledger

H1 = 3_600_000


def paper_stub(monkeypatch, tmp_path, position=1000.0):
    class Api:
        env = "sim"

        def fetch_candles(self, **kwargs):
            return [Candle(i * H1, 100, 100, 100, 100) for i in range(80)]

        def quote(self, _uic):
            return {"MarketState": "Open", "Mid": 100, "Bid": 99, "Ask": 101}

        def net_position_amount(self, _uic):
            return position

        def total_value(self):
            return 200_000, "JPY"

        def get(self, _path):
            return {"CurrencyCode": "JPY"}

        def place_market_order(self, *_args):
            raise AssertionError("dry-run must never submit an order")

    monkeypatch.setattr(saxokit.api, "SaxoApi", Api)
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(cli.time, "time", lambda: 100 * 3600)
    monkeypatch.setattr(
        cli, "strategy_target", lambda spec, cs: [int(spec.startswith("donchian"))] * len(cs)
    )
    return SimpleNamespace(
        strategies="ema9/26,donchian30/15", symbol="sample", uic=42,
        horizon=60, leverage=1, lot=1000, dry_run=True,
    )


def seed_ledger(path, strategy):
    append_ledger(path, [{
        "ts": "2026-01-01T00:00:00Z", "symbol": "sample", "strategy": strategy,
        "side": "Buy", "amount": 1000, "price": 100,
        "order_id": "synthetic", "reason": "test",
    }])


@pytest.mark.parametrize("position", [0.0, 1000.0])
def test_paper_dry_run_leaves_all_files_unchanged(monkeypatch, tmp_path, capsys, position):
    args = paper_stub(monkeypatch, tmp_path, position)
    seed_ledger(cli.DATA_DIR / "trades.csv", "ema9/26")
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    cli.cmd_paper(args)

    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before
    log = capsys.readouterr().out
    assert "[dry-run]" in log
    assert ("相殺 0" if position else "Buy 1000") in log


def test_paper_dry_run_does_not_create_data_directory(monkeypatch, tmp_path):
    args = paper_stub(monkeypatch, tmp_path, position=0)
    cli.cmd_paper(args)
    assert not cli.DATA_DIR.exists()


def test_equity_creates_parent_directory(tmp_path):
    path = tmp_path / "new" / "equity.csv"
    cli.append_equity(path, 2 * H1, 1000)
    assert path.read_text() == "ts,total_value\n7200000,1000\n"


def test_fetch_never_promotes_a_partial_candle_by_waiting(monkeypatch, tmp_path):
    candles = [Candle(i * H1, 100, 100, 100, 100 + i) for i in range(3)]

    class Api:
        def fetch_candles(self, **kwargs):
            return candles

    monkeypatch.setattr(saxokit.api, "SaxoApi", Api)
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli.time, "time", lambda: 2.5 * 3600)
    path = cli.cache_path("sample", 60)
    save_candles_csv(path, candles)  # 旧版の未確定行が残っている場合も検証
    cli.cmd_fetch(SimpleNamespace(uic=42, symbol="sample", asset_type="FxSpot", horizon=60, days=10))
    saved = load_candles_csv(path)
    assert [c.ts for c in saved] == [0, H1]
    assert cli.completed_candles(saved, 60, 4 * H1) == saved


def test_history_window_expands_for_daily_strategy():
    assert cli.history_days(["donchian55/20"], 1440) >= 84
    assert cli.history_days(["ema9/26"], 60) >= 10
