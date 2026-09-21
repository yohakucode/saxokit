"""ポジション列バックテスト。

- 足 i 確定でシグナル → 足 i+1 の始値で執行
- 執行ごとに半スプレッド + fee_bps を片道コストとして課す
- 保有中は UTC 日跨ぎごとにスワップ(bps/日)を課す
- エクイティは複利(レバレッジは損益とコストの両方に掛かる)
- エクイティが 0 以下になる損失は 0 で打ち切り、以後の取引を行わない
- spread は執行足の始値時点を使う。旧キャッシュで欠測なら前足終値、設定値の順で補う
"""

from __future__ import annotations

from dataclasses import dataclass

from saxokit.config import Config
from saxokit.data import Candle, utc_midnights_crossed


@dataclass
class Trade:
    side: int  # +1 ロング / -1 ショート
    entry_ts: int
    exit_ts: int
    ret_bps: float  # コスト・スワップ込み、レバレッジ抜きの 1 往復リターン


@dataclass
class Result:
    total_return_pct: float  # レバレッジ込み・複利
    max_drawdown_pct: float
    n_trades: int
    win_rate: float
    avg_trade_bps: float
    swap_cost_bps: float  # 期間合計のスワップ負担(レバ抜き)
    ruined: bool

    def line(self) -> str:
        return (
            f"return {self.total_return_pct:+.2f}%  DD {self.max_drawdown_pct:.2f}%  "
            f"trades {self.n_trades}  win {self.win_rate * 100:.0f}%  "
            f"avg {self.avg_trade_bps:+.1f}bps  swap {self.swap_cost_bps:+.1f}bps"
            f"{'  RUIN' if self.ruined else ''}"
        )


def _half_spread_frac(c: Candle, previous: Candle, cfg: Config) -> float:
    """執行時の半スプレッド。当足始値、前足終値、config の順で使う。"""
    if c.spread_open is not None:
        return c.spread_open / 2 / c.open
    if previous.spread > 0:
        return previous.spread / 2 / c.open
    return cfg.spread_bps_fallback / 2 / 1e4


def _compound(equity: float, return_fraction: float) -> float:
    """区間リターンを複利計上し、資本を下回る損失は 0 で打ち切る。"""
    return max(equity * (1 + return_fraction), 0.0)


def run_position_backtest(
    candles: list[Candle], target: list[int], cfg: Config
) -> Result:
    """target[i] ∈ {-1, 0, +1}(足 i 確定時の望みポジション)を i+1 始値で執行する。"""
    assert len(candles) == len(target)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    pos = 0
    entry_price = 0.0
    entry_ts = 0
    entry_cost_bps = 0.0
    trade_swap_bps = 0.0
    total_swap_bps = 0.0
    trades: list[Trade] = []
    lev = cfg.leverage

    for i in range(1, len(candles)):
        c = candles[i]
        # 当足始値で持ち替える前は、旧ポジションに前足終値→当足始値のギャップだけを計上する。
        if pos != 0:
            r = (c.open - candles[i - 1].close) / candles[i - 1].close
            equity = _compound(equity, lev * pos * r)
            days = utc_midnights_crossed(candles[i - 1].ts, c.ts)
            if days:
                swap_bps = (
                    cfg.swap_long_bps_per_day
                    if pos > 0
                    else cfg.swap_short_bps_per_day
                )
                cost = -swap_bps * days  # 正 = 負担
                equity = _compound(equity, -lev * cost / 1e4)
                trade_swap_bps += cost
                total_swap_bps += cost

        want = target[i - 1]  # 足 i-1 確定のシグナルを足 i 始値で執行
        if want != pos:
            exec_cost = _half_spread_frac(c, candles[i - 1], cfg) + cfg.fee_bps / 1e4
            if pos != 0:  # 決済
                equity = _compound(equity, -lev * exec_cost)
                gross = pos * (c.open - entry_price) / entry_price * 1e4
                net = gross - (entry_cost_bps + exec_cost * 1e4) - trade_swap_bps
                trades.append(Trade(pos, entry_ts, c.ts, net))
            if want != 0:  # 新規(ドテン含む)
                equity = _compound(equity, -lev * exec_cost)
                entry_price = c.open
                entry_ts = c.ts
                entry_cost_bps = exec_cost * 1e4
                trade_swap_bps = 0.0
            pos = want

        # 持ち替え後は、新ポジションに当足始値→終値の値動きを計上する。
        if pos != 0:
            r = (c.close - c.open) / c.open
            equity = _compound(equity, lev * pos * r)

        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        if equity == 0:
            break

    wins = sum(1 for t in trades if t.ret_bps > 0)
    return Result(
        total_return_pct=(equity - 1) * 100,
        max_drawdown_pct=max_dd * 100,
        n_trades=len(trades),
        win_rate=wins / len(trades) if trades else 0.0,
        avg_trade_bps=(
            sum(t.ret_bps for t in trades) / len(trades) if trades else 0.0
        ),
        swap_cost_bps=total_swap_bps,
        ruined=equity == 0,
    )


def split_is_oos(candles: list[Candle], cfg: Config) -> tuple[list[Candle], list[Candle]]:
    """IS 70% / OOS 30% 分割。target は各区間で再計算する(先読み防止)。"""
    k = int(len(candles) * cfg.is_ratio)
    return candles[:k], candles[k:]
