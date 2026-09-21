"""ポジション列(target)を生成する戦略関数群。

各関数は candles と同じ長さの list[int](-1/0/+1)を返す。
バックテストは backtest.run_position_backtest がこの列を i+1 始値で執行する。
"""

from __future__ import annotations

import re

from saxokit.data import Candle
from saxokit.indicators import bollinger, donchian, ema


def ema_cross_target(
    candles: list[Candle], fast: int = 9, slow: int = 26, allow_short: bool = True
) -> list[int]:
    """EMA クロスのドテン。"""
    closes = [c.close for c in candles]
    f = ema(closes, fast)
    s = ema(closes, slow)
    out = [0] * len(candles)
    for i in range(len(candles)):
        if f[i] is None or s[i] is None:
            continue
        if f[i] > s[i]:
            out[i] = 1
        elif f[i] < s[i]:
            out[i] = -1 if allow_short else 0
    return out


def donchian_target(
    candles: list[Candle], enter: int = 55, exit: int = 20
) -> list[int]:
    """ドンチャンブレイクアウト(タートル型)。

    enter 本チャネル上抜けでロング、exit 本チャネル下抜けで手仕舞い。
    保有中に逆側の enter チャネルを抜けたらドテン。ショートは対称。
    """
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    ent_u, ent_l = donchian(highs, lows, enter)
    ex_u, ex_l = donchian(highs, lows, exit)
    out = [0] * len(candles)
    pos = 0
    for i in range(len(candles)):
        if ent_u[i] is None or ex_u[i] is None:
            continue
        if pos == 1 and closes[i] < ex_l[i]:
            pos = 0
        elif pos == -1 and closes[i] > ex_u[i]:
            pos = 0
        if closes[i] > ent_u[i]:
            pos = 1
        elif closes[i] < ent_l[i]:
            pos = -1
        out[i] = pos
    return out


def bollinger_reversion_target(
    candles: list[Candle], period: int = 20, num_std: float = 2.0
) -> list[int]:
    """ボリンジャー平均回帰。下限割れでロング、ミドル回復で手仕舞い。上限は対称ショート。"""
    closes = [c.close for c in candles]
    mid, upper, lower = bollinger(closes, period, num_std)
    out = [0] * len(candles)
    pos = 0
    for i in range(len(candles)):
        if mid[i] is None:
            continue
        if pos == 1 and closes[i] >= mid[i]:
            pos = 0
        elif pos == -1 and closes[i] <= mid[i]:
            pos = 0
        if pos == 0:
            if closes[i] < lower[i]:
                pos = 1
            elif closes[i] > upper[i]:
                pos = -1
        out[i] = pos
    return out


# 戦略指定文字列: "ema9/26" / "donchian30/15" / "bb20x2.0"(大文字小文字不問)
_SPEC = re.compile(r"(ema|donchian|bb)(\d+)[/x](\d+(?:\.\d+)?)", re.I)


def parse_spec(spec: str) -> tuple[str, int, float]:
    m = _SPEC.fullmatch(spec.strip())
    if not m:
        raise SystemExit(f"戦略指定 {spec!r} が不正(例: ema9/26, donchian30/15, bb20x2)")
    return m[1].lower(), int(m[2]), float(m[3])


def strategy_target(spec: str, candles: list[Candle]) -> list[int]:
    """指定文字列から target 列を作る(backtest / paper / web 共用)。"""
    kind, a, b = parse_spec(spec)
    if kind == "ema":
        return ema_cross_target(candles, a, int(b))
    if kind == "donchian":
        return donchian_target(candles, a, int(b))
    return bollinger_reversion_target(candles, a, b)


def warmup(spec: str) -> int:
    """シグナル判定に最低限必要な足数。"""
    _, a, b = parse_spec(spec)
    return int(max(a, b))


def trade_reason(spec: str, side: str) -> str:
    """台帳・ログ用のエントリー/手仕舞い理由(long-only 前提)。"""
    kind, a, b = parse_spec(spec)
    b = int(b) if kind != "bb" else b
    text = {
        "ema": (f"EMA{a} が EMA{b} を上抜け", f"EMA{a} が EMA{b} を下抜け"),
        "donchian": (f"{a}本高値ブレイク", f"{b}本安値割れ"),
        "bb": (f"BB{a} -{b}σ 割れ", f"BB{a} ミドル回復"),
    }[kind]
    return f"{spec}: {text[side == 'Sell']}"
