"""バックテストの最小チェック: 執行規約・コスト・スワップが壊れたら落ちる。"""

from types import SimpleNamespace

import pytest

from saxokit.backtest import run_position_backtest
from saxokit.cli import cmd_backtest
from saxokit.config import Config
from saxokit.data import Candle, utc_midnights_crossed

DAY = 86_400_000
H1 = 3_600_000


def mk(ts, price, spread=0.0, spread_open=None):
    return Candle(
        ts=ts,
        open=price,
        high=price,
        low=price,
        close=price,
        spread=spread,
        spread_open=spread_open,
    )


def test_long_uptrend_profits_and_costs_reduce_it():
    candles = [mk(i * H1, 100 + i) for i in range(10)]
    target = [1] * 10
    free = run_position_backtest(candles, target, Config(spread_bps_fallback=0))
    costly = run_position_backtest(candles, target, Config(spread_bps_fallback=20))
    assert free.total_return_pct > 0
    assert costly.total_return_pct < free.total_return_pct


def test_short_downtrend_profits():
    candles = [mk(i * H1, 100 - i * 0.5) for i in range(10)]
    res = run_position_backtest(
        candles, [-1] * 10, Config(spread_bps_fallback=0)
    )
    assert res.total_return_pct > 0


def test_signal_executes_next_bar_and_counts_trade():
    # 足 2 確定で +1 → 足 3 始値で執行、足 4 確定で 0 → 足 5 始値で決済
    candles = [mk(i * H1, 100) for i in range(7)]
    target = [0, 0, 1, 1, 0, 0, 0]
    res = run_position_backtest(candles, target, Config(spread_bps_fallback=0))
    assert res.n_trades == 1


def test_execution_uses_open_spread_not_future_close_spread():
    target = [1, 0, 0]
    base = [
        mk(0, 100),
        mk(H1, 100, spread=0.2, spread_open=0.1),
        mk(2 * H1, 100, spread_open=0.1),
    ]
    changed_future_close = [
        base[0],
        mk(H1, 100, spread=50.0, spread_open=0.1),
        base[2],
    ]

    expected = run_position_backtest(
        base, target, Config(spread_bps_fallback=200)
    )
    actual = run_position_backtest(
        changed_future_close, target, Config(spread_bps_fallback=200)
    )

    assert actual.total_return_pct == pytest.approx(expected.total_return_pct)
    assert actual.avg_trade_bps == pytest.approx(expected.avg_trade_bps)


def test_legacy_cache_uses_previous_close_spread_before_config_fallback():
    candles = [
        mk(0, 100, spread=0.2),
        mk(H1, 100),
        mk(2 * H1, 100),
    ]

    res = run_position_backtest(
        candles,
        [1, 0, 0],
        Config(spread_bps_fallback=200),
    )

    # Entry uses the previous close's 0.2 spread (10bps); exit falls back to 200bps/2.
    assert res.avg_trade_bps == pytest.approx(-110.0)


def test_explicit_zero_open_spread_does_not_fall_back():
    candles = [
        mk(0, 100, spread=10.0),
        mk(H1, 100, spread_open=0.0),
        mk(2 * H1, 100, spread_open=0.0),
    ]

    res = run_position_backtest(
        candles,
        [1, 0, 0],
        Config(spread_bps_fallback=200),
    )

    assert res.avg_trade_bps == 0.0


def test_cmd_backtest_excludes_current_incomplete_bar(
    monkeypatch, tmp_path, capsys
):
    import saxokit.cli

    candles = [mk(i * H1, 100 + i) for i in range(4)]
    path = tmp_path / "candles_test_60min.csv"
    path.touch()
    monkeypatch.setattr(saxokit.cli, "cache_path", lambda *_args: path)
    monkeypatch.setattr(saxokit.cli, "load_candles_csv", lambda _path: candles)
    monkeypatch.setattr(saxokit.cli.time, "time", lambda: 3 * 3600)
    args = SimpleNamespace(
        symbol="test",
        horizon=60,
        strategy="ema",
        fast=2,
        slow=3,
        enter=5,
        exit=3,
        period=3,
        std=2.0,
        long_only=False,
        leverage=0,
    )

    # 3:00 時点では 0:00, 1:00, 2:00 開始の各1時間足が確定し、3:00 足は未確定。
    cmd_backtest(args)

    assert "(3 本, 未確定 1 本除外)" in capsys.readouterr().out


def test_next_open_execution_counts_only_the_held_price_segments():
    """入口前のギャップと出口後の日中値動きを除き、保有中の値動きだけを数える。"""
    candles = [
        Candle(ts=0 * H1, open=100, high=100, low=100, close=100),
        Candle(ts=1 * H1, open=100, high=100, low=90, close=90),
        # 足1確定で買い。90→120 の入口ギャップは未保有、120→132 は保有中。
        Candle(ts=2 * H1, open=120, high=132, low=120, close=132),
        # 足2確定で決済。132→99 の出口ギャップは保有中、99→49.5 は決済後。
        Candle(ts=3 * H1, open=99, high=99, low=49.5, close=49.5),
    ]
    res = run_position_backtest(
        candles,
        [0, 1, 0, 0],
        Config(spread_bps_fallback=0),
    )

    assert res.n_trades == 1
    assert res.total_return_pct == pytest.approx(-17.5)
    assert res.avg_trade_bps == pytest.approx(-1750.0)


def test_swap_charged_on_midnight_cross():
    assert utc_midnights_crossed(0, DAY) == 1
    # 値動きゼロ。エントリーは足1始値(執行規約)なので保有中の日跨ぎは3回
    candles = [mk(i * DAY, 100) for i in range(5)]
    res = run_position_backtest(
        candles,
        [1] * 5,
        Config(spread_bps_fallback=0, swap_long_bps_per_day=-10),
    )
    assert res.swap_cost_bps == 30  # 10bps × 3 日
    assert res.total_return_pct < 0


def test_leverage_scales_pnl():
    candles = [mk(i * H1, 100 + i) for i in range(10)]
    r1 = run_position_backtest(candles, [1] * 10, Config(spread_bps_fallback=0))
    r5 = run_position_backtest(
        candles, [1] * 10, Config(spread_bps_fallback=0, leverage=5)
    )
    assert r5.total_return_pct > r1.total_return_pct * 4  # 複利で 5 倍弱〜超


def test_equity_stops_at_zero_after_leveraged_ruin():
    candles = [
        Candle(ts=0 * H1, open=100, high=100, low=100, close=100),
        # 足0の買いシグナルを 100 で執行後、50% 下落。レバ3なら資本を超える損失。
        Candle(ts=1 * H1, open=100, high=100, low=50, close=50),
        # 破綻後に価格が戻っても、負の資本で計算を継続してはならない。
        Candle(ts=2 * H1, open=100, high=100, low=100, close=100),
    ]
    res = run_position_backtest(
        candles,
        [1, 1, 1],
        Config(spread_bps_fallback=0, leverage=3),
    )

    assert res.ruined is True
    assert res.total_return_pct == -100.0
    assert res.max_drawdown_pct == 100.0
