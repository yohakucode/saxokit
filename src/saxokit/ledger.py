"""ペーパートレード台帳(data/trades.csv)。

API のネット建玉から同一銘柄の戦略別内訳は分からない。ネッティング方式は口座で確認する。
そのため paper コマンドが発注ごとに「どの戦略が・なぜ」を追記し、戦略別の保有量は
この台帳の Buy/Sell 累計で求める(API のネット建玉と合計が一致するか paper が毎回照合)。
"""

from __future__ import annotations

import csv
from pathlib import Path

COLS = ("ts", "symbol", "strategy", "side", "amount", "price", "order_id", "reason")


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def append_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerows(rows)


def held_by_strategy(rows: list[dict], symbol: str) -> dict[str, float]:
    """symbol の戦略別保有量(Buy +, Sell −)。"""
    out: dict[str, float] = {}
    for r in rows:
        if r["symbol"] != symbol:
            continue
        sign = 1 if r["side"] == "Buy" else -1
        out[r["strategy"]] = out.get(r["strategy"], 0.0) + sign * float(r["amount"])
    return out
