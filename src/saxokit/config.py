"""config.toml をコスト・バックテスト設定(frozen dataclass)に読み込む。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    # 片道の取引コスト(bps)。FX はスプレッドのみなので通常 0
    fee_bps: float = 0.0
    # bid/ask の無い商品(spread=0 のローソク)に使う想定スプレッド(bps)
    spread_bps_fallback: float = 2.0
    # 建玉保有コスト(bps/日)。負 = 支払い。FX スワップ / CFD 金利調整の近似
    swap_long_bps_per_day: float = -1.0
    swap_short_bps_per_day: float = -1.0
    # バックテスト
    leverage: float = 1.0
    is_ratio: float = 0.7  # IS/OOS 分割


def load_config(path: str | Path = "config.toml") -> Config:
    path = Path(path)
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    flat = {**raw.get("costs", {}), **raw.get("backtest", {})}
    known = {k: v for k, v in flat.items() if k in Config.__dataclass_fields__}
    return Config(**known)
