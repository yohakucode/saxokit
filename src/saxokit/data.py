"""ローソク足の CSV 保存 / 読み込み(リサーチ用キャッシュ)。

data.py の規約(ts で併合・新データ優先)。
FX は bid/ask 中値(mid)を OHLC に持ち、spread_open / spread 列に始値 / 終値時点の
ask-bid(価格単位)を持つ。bid/ask の無い商品(指数 CFD 等)は spread_open=None、
spread=0 で保存し、バックテスト側が config のフォールバック値を使う。
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HEADER = ["ts", "open", "high", "low", "close", "spread", "spread_open"]


@dataclass(frozen=True)
class Candle:
    ts: int  # unix ms
    open: float
    high: float
    low: float
    close: float
    spread: float = 0.0  # 終値時点の ask-bid(価格単位)。0 = 不明
    spread_open: float | None = None  # 始値時点の ask-bid。None = 不明、0 = 実測ゼロ

    def __post_init__(self) -> None:
        if not math.isfinite(self.spread) or self.spread < 0:
            raise ValueError(
                f"spread must be finite and non-negative: {self.spread!r}"
            )
        if self.spread_open is not None and (
            not math.isfinite(self.spread_open) or self.spread_open < 0
        ):
            raise ValueError(
                "spread_open must be finite and non-negative: "
                f"{self.spread_open!r}"
            )


def _optional_spread(value: object) -> float | None:
    """CSV / API の欠測を None とし、実測ゼロと区別する。"""
    if value is None or value == "":
        return None
    spread = float(value)
    if not math.isfinite(spread) or spread < 0:
        raise ValueError(f"spread_open must be finite and non-negative: {value!r}")
    return spread


def from_saxo(row: dict) -> Candle:
    """Saxo chart API の 1 要素を Candle に変換。

    FxSpot 系は OpenBid/OpenAsk... の bid/ask OHLC → mid に潰して spread を保持。
    それ以外(CfdOnIndex 等)は Open/High/Low/Close をそのまま使う。
    """
    ts = int(
        datetime.fromisoformat(row["Time"].replace("Z", "+00:00")).timestamp() * 1000
    )
    if "CloseBid" in row:
        mid = lambda a, b: (row[a] + row[b]) / 2  # noqa: E731
        return Candle(
            ts=ts,
            open=mid("OpenBid", "OpenAsk"),
            high=mid("HighBid", "HighAsk"),
            low=mid("LowBid", "LowAsk"),
            close=mid("CloseBid", "CloseAsk"),
            spread=row["CloseAsk"] - row["CloseBid"],
            spread_open=_optional_spread(row["OpenAsk"] - row["OpenBid"]),
        )
    return Candle(
        ts=ts,
        open=row["Open"],
        high=row["High"],
        low=row["Low"],
        close=row["Close"],
        spread=0.0,
        spread_open=None,
    )


def save_candles_csv(
    path: str | Path,
    candles: list[Candle],
    *,
    max_ts: int | None = None,
) -> None:
    """既存キャッシュと ts で併合し、開始時刻が max_ts 以前の足を保存する。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        merged = {c.ts: c for c in load_candles_csv(path)}
        merged.update({c.ts: c for c in candles})
        candles = [merged[ts] for ts in sorted(merged)]
    if max_ts is not None:
        candles = [c for c in candles if c.ts <= max_ts]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for c in candles:
            w.writerow(
                [
                    c.ts,
                    c.open,
                    c.high,
                    c.low,
                    c.close,
                    c.spread,
                    "" if c.spread_open is None else c.spread_open,
                ]
            )


def load_candles_csv(path: str | Path) -> list[Candle]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            Candle(
                ts=int(row["ts"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                spread=float(row.get("spread") or 0.0),
                spread_open=_optional_spread(row.get("spread_open")),
            )
            for row in reader
        ]


def utc_midnights_crossed(ts_a_ms: int, ts_b_ms: int) -> int:
    """ts_a → ts_b の間に UTC 0 時を何回跨いだか(スワップ日数の計算用)。

    ponytail: FX 実務は NY17時ロールオーバー + 水曜3日分だが、検証目的では
    UTC 日跨ぎ近似で十分。実弾前に per-instrument のロール仕様に置き換える。
    """
    a = datetime.fromtimestamp(ts_a_ms / 1000, tz=timezone.utc).date()
    b = datetime.fromtimestamp(ts_b_ms / 1000, tz=timezone.utc).date()
    return max((b - a).days, 0)
