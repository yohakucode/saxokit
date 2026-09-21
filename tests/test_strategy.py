"""donchian_target / bollinger_reversion_target の信号検証(トイデータ)。"""

from saxokit.data import Candle
from saxokit.strategy import bollinger_reversion_target, donchian_target


def mk(closes: list[float]) -> list[Candle]:
    return [
        Candle(ts=i * 60_000, open=c, high=c, low=c, close=c)
        for i, c in enumerate(closes)
    ]


def test_donchian_breakout_long_then_exit():
    # 横ばい5本 → 上抜け → 下落で exit チャネル割れ
    closes = [100.0] * 5 + [105.0, 106.0, 95.0]
    t = donchian_target(mk(closes), enter=5, exit=3)
    assert t[4] == 0  # ウォームアップ直後、ブレイクなし
    assert t[5] == 1  # 直前5本高値100を上抜け → ロング
    assert t[6] == 1  # 継続
    assert t[7] == -1  # enter 下限も割る大陰線 → ドテンショート


def test_donchian_warmup_is_flat():
    t = donchian_target(mk([100.0] * 4), enter=5, exit=3)
    assert t == [0, 0, 0, 0]


def test_bollinger_reversion_long_and_exit():
    # 100横ばい → 急落で下限割れ → 戻りでミドル回復
    closes = [100.0, 101.0, 99.0, 100.0, 101.0, 99.0, 100.0, 101.0, 99.0, 100.0,
              90.0, 100.5]
    t = bollinger_reversion_target(mk(closes), period=10, num_std=2.0)
    assert t[10] == 1  # 90 は下限割れ → ロング
    assert t[11] == 0  # ミドル回復 → 手仕舞い


def test_bollinger_flat_in_band():
    closes = [100.0, 100.1] * 10
    t = bollinger_reversion_target(mk(closes), period=10, num_std=2.0)
    assert all(x == 0 for x in t)


def test_order_guard_refuses_live(monkeypatch):
    """live 環境での発注は SystemExit(ペーパーフェーズの安全策)。"""
    import pytest
    from saxokit.api import SaxoApi

    monkeypatch.setattr("saxokit.api.load_dotenv", lambda **_kwargs: None)
    monkeypatch.setenv("SAXO_TOKEN", "dummy")
    api = SaxoApi(env="live")
    with pytest.raises(SystemExit):
        api.place_market_order(42, 1000, "Buy")


def test_paper_amount_currency_conversion():
    """建値通貨換算の数量計算(誤ると発注サイズが 160 倍ずれる)。"""
    from saxokit.cli import paper_amount

    # USDJPY: 評価額1000万円 lev2 @160円 → 125,000 USD(1000単位)
    assert paper_amount(2.0, 10_000_000, 160.0, 1.0, 1000) == 125_000
    # XAUUSD: 同条件 @4455USD、USDJPY=160 → 28oz(1単位)
    assert paper_amount(2.0, 10_000_000, 4455.0, 160.0, 1) == 28
    # 評価額ゼロ → 0
    assert paper_amount(2.0, 0, 160.0, 1.0, 1000) == 0


def test_journal_line_conversion():
    """closedpositions → journal.csv 行変換(bps 符号・欠損耐性)。"""
    from saxokit.cli import journal_line

    d = {
        "ClosedPositionUniqueId": "abc123",
        "ClosedPosition": {
            "Uic": 42, "Amount": 125000.0,
            "OpenPrice": 160.0, "ClosePrice": 161.6,
            "ExecutionTimeOpen": "2026-08-31T01:00:00Z",
            "ExecutionTimeClose": "2026-09-02T10:00:00Z",
            "ProfitLossOnTrade": 200000.0, "ProfitLossCurrency": "JPY",
        },
    }
    pid, line = journal_line(d)
    assert pid == "abc123"
    cells = line.split(",")
    assert cells[4] == "USDJPY"
    assert cells[8] == "100.0"  # (161.6/160-1)*1e4 = +100bps ロング
    # ショートは符号反転
    d["ClosedPosition"]["Amount"] = -125000.0
    assert journal_line(d)[1].split(",")[8] == "-100.0"
    # id 欠損は None
    assert journal_line({"ClosedPosition": {}}) is None


def test_reset_guard_refuses_live(monkeypatch):
    import pytest
    from saxokit.api import SaxoApi

    monkeypatch.setattr("saxokit.api.load_dotenv", lambda **_kwargs: None)
    monkeypatch.setenv("SAXO_TOKEN", "dummy")
    with pytest.raises(SystemExit):
        SaxoApi(env="live").reset_account(1000.0)
