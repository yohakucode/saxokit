"""テクニカル指標(純 Python 実装)。

各関数は入力と同じ長さのリストを返す。
計算に必要な本数に満たない先頭部分は None。
"""

from __future__ import annotations


def sma(values: list[float], period: int) -> list[float | None]:
    """単純移動平均。"""
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    total = sum(values[:period])
    out[period - 1] = total / period
    for i in range(period, len(values)):
        total += values[i] - values[i - period]
        out[i] = total / period
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    """指数移動平均。最初の period 本の SMA をシードにする。"""
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    k = 2.0 / (period + 1)
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def bollinger(
    values: list[float], period: int, num_std: float
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """ボリンジャーバンド。(ミドル, アッパー, ロワー) を返す。

    標準偏差は母標準偏差(ddof=0)。一般的な BB の定義に合わせる。
    """
    n = len(values)
    mid: list[float | None] = [None] * n
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    if period <= 1 or n < period:
        return mid, upper, lower
    total = sum(values[:period])
    total_sq = sum(v * v for v in values[:period])
    for i in range(period - 1, n):
        if i >= period:
            total += values[i] - values[i - period]
            total_sq += values[i] ** 2 - values[i - period] ** 2
        mean = total / period
        var = max(total_sq / period - mean * mean, 0.0)  # 丸め誤差で負になるのを防ぐ
        sd = var**0.5
        mid[i] = mean
        upper[i] = mean + num_std * sd
        lower[i] = mean - num_std * sd
    return mid, upper, lower


def donchian(
    highs: list[float], lows: list[float], period: int
) -> tuple[list[float | None], list[float | None]]:
    """ドンチャンチャネル。(上限, 下限) を返す。

    上限[i] = 直前 period 本(i を含まない)の最高値、下限は同様の最安値。
    「終値が上限を上回ったらブレイク」の判定で自分自身を含めないための規約。
    """
    n = len(highs)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(period, n):
        window_h = highs[i - period : i]
        window_l = lows[i - period : i]
        upper[i] = max(window_h)
        lower[i] = min(window_l)
    return upper, lower


def rsi(values: list[float], period: int) -> list[float | None]:
    """RSI(Wilder 方式)。0-100。"""
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period

    def to_rsi(g: float, l: float) -> float:
        if l == 0:
            return 100.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[period] = to_rsi(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        diff = values[i] - values[i - 1]
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = to_rsi(avg_gain, avg_loss)
    return out


def atr(
    highs: list[float], lows: list[float], closes: list[float], period: int
) -> list[float | None]:
    """ATR(Wilder 方式)。ボラティリティの目安。"""
    n = len(closes)
    out: list[float | None] = [None] * n
    if period <= 0 or n < period:
        return out
    trs: list[float] = []
    for i in range(n):
        if i == 0:
            trs.append(highs[0] - lows[0])
        else:
            trs.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
    prev = sum(trs[:period]) / period
    out[period - 1] = prev
    for i in range(period, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out
