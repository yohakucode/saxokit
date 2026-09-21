"""ペーパートレード監視ダッシュボード(読み取り専用・stdlib http.server)。

data/paper_log.txt / data/equity.csv と Saxo API(口座・建玉・現値)を集約して
dashboard.html に表示する。発注系コードは含まない。

起動: uv run saxokit web  →  http://127.0.0.1:8787 (loopback バインド)。
VPS から見る場合は SSH ポート転送を使う。認証機能は持たない。
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from saxokit.cli import history_days
from saxokit.ledger import read_ledger
from saxokit.strategy import strategy_target

# ペーパー運用中の銘柄(cron の paper 引数と揃えること)。symbol は台帳のキー(paper --symbol)、
# quote は建値通貨(含み損益の換算用)
BOOK = [  # cron の paper 引数と手動で揃える(例)
    {"uic": 42, "symbol": "usdjpy", "strategies": ["ema9/26"], "quote": "JPY"},
]
HORIZON = 60  # 分
DATA_DIR = Path("data")
CACHE_TTL = 30.0  # 秒。ブラウザ複数タブでも Saxo API を叩きすぎない


def signal_of(spec: str, candles) -> int:
    t = strategy_target(spec, candles)
    return max(t[-1], 0) if t else 0  # long-only


def ledger_books(rows: list[dict], rates: dict[str, float]) -> dict[tuple[str, str], dict]:
    """台帳を (symbol, strategy) ごとに集計: 保有量・平均建値・実現損益(JPY)・決済数・勝数。

    long-only 前提で Buy は平均建値に加重、Sell は平均建値との差を実現損益に計上。
    """
    quote = {b["symbol"]: b["quote"] for b in BOOK}
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["symbol"], r["strategy"])
        s = out.setdefault(key, {"held": 0.0, "cost": 0.0, "realized_jpy": 0.0, "n": 0, "wins": 0})
        amt, px = float(r["amount"]), float(r["price"] or 0)
        if r["side"] == "Buy":
            s["cost"] += amt * px
            s["held"] += amt
        else:
            avg = s["cost"] / s["held"] if s["held"] else px
            pl = amt * (px - avg) * rates.get(quote.get(r["symbol"], "JPY"), 1.0)
            s["realized_jpy"] += pl
            s["n"] += 1
            s["wins"] += pl > 0
            s["cost"] -= amt * avg
            s["held"] -= amt
    for s in out.values():
        s["avg"] = s["cost"] / s["held"] if s["held"] > 0 else None
    return out


def tail_lines(path: Path, n: int = 60) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]


def read_equity(path: Path) -> list[list[float]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines()[1:]:
        ts, val = line.split(",", 1)
        out.append([int(ts), float(val)])
    return out


def build_status() -> dict:
    """Saxo API + ローカルファイルからダッシュボード 1 画面分の JSON を組む。"""
    from saxokit.api import SaxoApi

    out: dict = {
        "now_ms": int(time.time() * 1000),
        "env": None,
        "error": None,
        "balance": None,
        "currency": None,
        "positions": [],
        "log": tail_lines(DATA_DIR / "paper_log.txt"),
        "equity": read_equity(DATA_DIR / "equity.csv"),
        "trades": [],
    }
    ledger = read_ledger(DATA_DIR / "trades.csv")
    out["trades"] = ledger[::-1][:50]  # 新しい順・直近 50 件(エントリー理由付き)
    try:
        api = SaxoApi()
        out["env"] = api.env

        def mid_of(uic: int) -> float:
            return api.quote(uic)["Mid"]

        total, ccy = api.total_value()
        rate_uics = {"JPY": None, "USD": 42, "EUR": 18}
        if ccy not in rate_uics:
            raise SystemExit(f"口座通貨 {ccy} は JPY 換算未対応")
        quote_ccys = {row["quote"] for row in BOOK}
        unsupported_quotes = quote_ccys - rate_uics.keys()
        if unsupported_quotes:
            names = ", ".join(sorted(unsupported_quotes))
            raise SystemExit(f"BOOK の建値通貨 {names} は JPY 換算未対応")
        # 換算レート(JPY 建て表示用)
        needed_ccys = quote_ccys | {ccy}
        rates = {"JPY": 1.0}
        for needed in ("USD", "EUR"):
            if needed in needed_ccys:
                uic = rate_uics[needed]
                assert uic is not None
                rates[needed] = mid_of(uic)
        total_jpy = total * rates[ccy]
        out["balance"] = total_jpy
        out["currency"] = "円"
        out["balance_raw"] = f"{total:,.2f} {ccy}"

        # API のネット建玉(台帳合計との照合用)
        netpos = {}
        for d in api.net_positions():
            base = d.get("NetPositionBase", {})
            if base.get("Uic"):
                netpos[base["Uic"]] = float(base.get("Amount", 0.0) or 0.0)

        books = ledger_books(ledger, rates)
        now_ms = out["now_ms"]
        unreal_total = 0.0
        for row in BOOK:
            candles = api.fetch_candles(
                uic=row["uic"],
                horizon=HORIZON,
                days=history_days(row["strategies"], HORIZON),
            )
            closed = [c for c in candles if c.ts + HORIZON * 60_000 <= now_ms]
            q = api.quote(row["uic"])
            market_open = q.get("MarketState") == "Open"
            price = q.get("Mid") or (closed[-1].close if closed else None)  # 現値(閉場中は最終気配)
            strategies = []
            for spec in row["strategies"]:
                b = books.get((row["symbol"], spec), {})
                held, avg = b.get("held", 0.0), b.get("avg")
                sig = signal_of(spec, closed) if closed else 0
                unreal_jpy = pct = None
                if held and avg and price:
                    # 含み損益 = 数量×(現値-平均建値) を建値通貨→JPY 換算
                    unreal_jpy = held * (price - avg) * rates[row["quote"]]
                    pct = (price / avg - 1) * 100
                    unreal_total += unreal_jpy
                strategies.append(
                    {
                        "spec": spec,
                        "signal": sig,
                        "held": held,
                        "entry_price": avg,
                        "unreal_jpy": unreal_jpy,
                        "unreal_pct": pct,
                        "realized_jpy": b.get("realized_jpy", 0.0),
                        "n": b.get("n", 0),
                        "wins": b.get("wins", 0),
                        # シグナルと建玉の不整合(発注失敗・トークン失効中の取り残し検知)
                        "mismatch": market_open and ((sig == 1) != (held > 0)),
                    }
                )
            ledger_amount = sum(x["held"] for x in strategies)
            api_amount = netpos.get(row["uic"], 0.0)
            out["positions"].append(
                {
                    "symbol": row["symbol"].upper(),
                    "price": price,
                    "market_open": market_open,
                    "amount": api_amount,
                    "strategies": strategies,
                    # 台帳と API 建玉のズレ(次の paper 実行で自動同期される)
                    "ledger_mismatch": abs(ledger_amount - api_amount) > 0.5,
                }
            )
        out["unrealized_jpy"] = unreal_total
        n = sum(b["n"] for b in books.values())
        out["stats"] = {
            "realized_jpy": sum(b["realized_jpy"] for b in books.values()),
            "n": n,
            "win_rate": sum(b["wins"] for b in books.values()) / n if n else None,
        }
    except SystemExit as e:  # SaxoApi は 401/設定不備を SystemExit で報告する
        out["error"] = str(e)
    except Exception as e:  # ネットワーク断等でもログとエクイティは表示し続ける
        out["error"] = f"{type(e).__name__}: {e}"
    return out


_cache: dict = {"ts": 0.0, "data": None}


def cached_status() -> dict:
    now = time.time()
    if _cache["data"] is None or now - _cache["ts"] > CACHE_TTL:
        _cache["data"] = build_status()
        _cache["ts"] = now
    return _cache["data"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (http.server の規約)
        if self.path.startswith("/api/status"):
            body = json.dumps(cached_status()).encode()
            ctype = "application/json; charset=utf-8"
        elif self.path == "/":
            body = (Path(__file__).parent / "dashboard.html").read_bytes()
            ctype = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # アクセスログは抑制
        pass


def serve(port: int = 8787, host: str = "127.0.0.1") -> None:
    # 認証機能がないため既定は loopback。外部バインドは CLI で明示した場合だけ行う
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"http://{host}:{port} (Ctrl+C で終了)")
    httpd.serve_forever()
