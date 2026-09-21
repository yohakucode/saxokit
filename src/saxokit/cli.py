"""CLI: token / login / refresh / instruments / fetch / backtest / paper。

例:
    uv run saxokit token
    uv run saxokit instruments --keywords USDJPY --asset-types FxSpot
    uv run saxokit fetch --uic 42 --symbol usdjpy --horizon 60 --days 365
    uv run saxokit backtest --symbol usdjpy --horizon 60 --fast 9 --slow 26
    uv run saxokit paper --uic 42 --symbol usdjpy --strategies ema9/26,donchian30/15
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

from saxokit.backtest import run_position_backtest, split_is_oos
from saxokit.config import load_config
from saxokit.data import Candle, load_candles_csv, save_candles_csv
from saxokit.ledger import append_ledger, held_by_strategy, read_ledger
from saxokit.strategy import strategy_target, trade_reason, warmup

DATA_DIR = Path("data")


def cache_path(symbol: str, horizon: int) -> Path:
    return DATA_DIR / f"candles_{symbol}_{horizon}min.csv"


def cmd_token(_args) -> None:
    from saxokit.api import SaxoApi

    api = SaxoApi()
    me = api.me()
    print(f"OK ({api.env}) UserId={me.get('UserId')} Culture={me.get('Culture')}")


def cmd_instruments(args) -> None:
    from saxokit.api import SaxoApi

    rows = SaxoApi().instruments(args.keywords, args.asset_types)
    if not rows:
        print("該当なし")
        return
    for r in rows:
        print(
            f"{r.get('Identifier'):>10}  {r.get('AssetType'):<14} "
            f"{r.get('Symbol'):<12} {r.get('Description', '')}"
        )


def cmd_fetch(args) -> None:
    from saxokit.api import SaxoApi

    fetch_started_ms = time.time() * 1000
    candles = SaxoApi().fetch_candles(
        uic=args.uic, asset_type=args.asset_type, horizon=args.horizon, days=args.days
    )
    if not candles:
        print("0 本。Uic / AssetType / Horizon を確認")
        return
    path = cache_path(args.symbol or str(args.uic), args.horizon)
    closed = completed_candles(candles, args.horizon, fetch_started_ms)
    save_candles_csv(
        path, closed, max_ts=int(fetch_started_ms) - args.horizon * 60_000
    )
    print(f"確定足 {len(closed)} 本 → {path} (取得時に未確定 {len(candles) - len(closed)} 本を除外)")


def spec_of(args) -> str:
    """backtest の --strategy/--fast... を "ema9/26" 形式の戦略指定に畳む。"""
    return {
        "ema": f"ema{args.fast}/{args.slow}",
        "donchian": f"donchian{args.enter}/{args.exit}",
        "bb": f"bb{args.period}x{args.std}",
    }[args.strategy]


def build_target(args, cs) -> list[int]:
    t = strategy_target(spec_of(args), cs)
    return [max(x, 0) for x in t] if args.long_only else t


def paper_plan(
    sigs: dict[str, int], held: dict[str, float], size: int
) -> list[tuple[str, str, int]]:
    """戦略ごとの変更 (spec, side, amount)。sig=1 で未保有なら size 買い、sig=0 で保有中なら全量売り。

    保有中の再サイジングはしない(評価額変動で毎時売買が発生しコスト漏れするため)。
    """
    out = []
    for spec, sig in sigs.items():
        h = held.get(spec, 0.0)
        if sig == 1 and h <= 0 and size > 0:
            out.append((spec, "Buy", size))
        elif sig == 0 and h > 0:
            out.append((spec, "Sell", int(h)))
    return out


def reconcile(
    held: dict[str, float], specs: list[str], api_pos: float
) -> list[tuple[str, str, int]]:
    """台帳合計と API ネット建玉のズレを台帳側で吸収する調整行。

    超過分は先頭戦略に付け、不足分は保有中の戦略から順に減らす(口座リセット・手動決済・
    発注失敗後の取り残し対策。ゼロなら空)。
    """
    diff = api_pos - sum(held.values())
    rows: list[tuple[str, str, int]] = []
    if diff > 0.5:
        return [(specs[0], "Buy", int(round(diff)))]
    for spec in specs:
        if diff < -0.5 and held.get(spec, 0) > 0:
            cut = min(held[spec], -diff)
            rows.append((spec, "Sell", int(round(cut))))
            diff += cut
    return rows


def paper_amount(
    leverage: float, total_jpy: float, price: float, jpy_per_quote: float, lot: int
) -> int:
    """発注数量 = レバ×口座評価額(JPY)を建値通貨換算して価格で割り、lot 単位に切り捨て。"""
    raw = leverage * total_jpy / jpy_per_quote / price
    return int(raw // lot * lot)


def append_equity(path: Path, ts_ms: int, total: float) -> None:
    """エクイティ履歴を追記(ダッシュボード用)。30 分以内の重複行はスキップ。

    cron は毎時 2 銘柄分 paper を実行するため、そのままだと 1 時間に 2 行入る。
    """
    last_ts = 0
    if path.exists():
        line = ""
        with open(path) as f:
            for line in f:
                pass
        head = line.split(",", 1)[0]
        if head.isdigit():
            last_ts = int(head)
    if ts_ms - last_ts < 30 * 60_000:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a") as f:
        if new:
            f.write("ts,total_value\n")
        f.write(f"{ts_ms},{total:.0f}\n")


def completed_candles(
    candles: list[Candle], horizon: int, now_ms: float | None = None
) -> list[Candle]:
    """開始時刻 + horizon が現在以前の確定足だけを返す。"""
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    duration_ms = horizon * 60_000
    return [c for c in candles if c.ts + duration_ms <= now_ms]


def history_days(specs: list[str], horizon: int) -> int:
    """必要足数を週末と取得境界の余裕込みで日数に換算する。休場による不足は別判定。"""
    bars = max(warmup(spec) for spec in specs) + 5
    return max(10, math.ceil(bars * horizon / 1440 * 7 / 5) + 7)


def cmd_backtest(args) -> None:
    cfg = load_config()
    path = cache_path(args.symbol, args.horizon)
    if not path.exists():
        raise SystemExit(f"{path} が無い。先に fetch を実行")
    loaded = load_candles_csv(path)
    candles = completed_candles(loaded, args.horizon)
    excluded = len(loaded) - len(candles)
    if not candles:
        raise SystemExit(f"{path} に確定足が無い")
    if args.leverage:
        cfg = type(cfg)(**{**cfg.__dict__, "leverage": args.leverage})

    def make_target(cs):
        return build_target(args, cs)

    def run(cs, label):
        res = run_position_backtest(cs, make_target(cs), cfg)
        print(f"{label:<5} {res.line()}")

    print(
        f"{args.symbol} {args.horizon}min {spec_of(args)}"
        f"{' long-only' if args.long_only else ''} lev={cfg.leverage} "
        f"({len(candles)} 本"
        f"{f', 未確定 {excluded} 本除外' if excluded else ''})"
    )
    run(candles, "FULL")
    is_c, oos_c = split_is_oos(candles, cfg)
    run(is_c, "IS")
    run(oos_c, "OOS")


JOURNAL_COLS = (
    "id,closed,opened,uic,symbol,amount,open_price,close_price,pl_bps,pl,pl_ccy"
)
SYMBOL_BY_UIC = {42: "USDJPY", 8176: "XAUUSD"}


def journal_line(d: dict, currency_code: str = "") -> tuple[str, str] | None:
    """closedpositions の 1 要素を journal.csv の 1 行に変換。(id, 行) を返す。

    ClosingPrice を正規形とし、旧 ClosePrice も読み取る。ClosedProfitLoss は銘柄通貨建て。
    GET の BuyOrSell は建玉方向として扱い、方向付き数量と値幅損益率を記録する。
    """
    cp = d.get("ClosedPosition", {})
    pid = str(d.get("ClosedPositionUniqueId") or cp.get("ClosingPositionId") or "")
    if not pid:
        return None

    def required(*names: str):
        for name in names:
            value = cp.get(name)
            if value is not None and value != "":
                return value
        raise ValueError(f"closed position {pid}: {names[0]} がない")

    amount = float(required("Amount"))
    open_price = float(required("OpenPrice"))
    close_price = float(required("ClosingPrice", "ClosePrice"))
    if amount == 0 or open_price == 0:
        raise ValueError(f"closed position {pid}: Amount/OpenPrice が 0")

    position_side = cp.get("BuyOrSell")
    if position_side in ("Buy", "Sell"):
        # GET の公式例は Buy・価格上昇・正の損益であり、実 SIM の Buy 建玉も Buy を返す。
        # datatype の "Closing direction" という説明ではなく GET の応答意味に合わせる。
        position_sign = 1 if position_side == "Buy" else -1
        amount = abs(amount) * position_sign
    elif position_side in (None, ""):
        position_sign = 1 if amount > 0 else -1
    else:
        raise ValueError(f"closed position {pid}: BuyOrSell={position_side} は不正")
    bps = position_sign * (close_price / open_price - 1) * 1e4
    pl = required("ClosedProfitLoss", "ProfitLossOnTrade")
    pl_ccy = currency_code or cp.get("ProfitLossCurrency", "")
    if not pl_ccy:
        raise ValueError(f"closed position {pid}: 損益通貨がない")
    uic = required("Uic")
    vals = [
        pid,
        cp.get("ExecutionTimeClose", ""),
        cp.get("ExecutionTimeOpen", ""),
        uic,
        SYMBOL_BY_UIC.get(uic, str(uic)),
        amount,
        open_price,
        close_price,
        f"{bps:.1f}",
        pl,
        pl_ccy,
    ]
    return pid, ",".join(str(v) for v in vals)


def cmd_journal(args) -> None:
    """サクソの決済履歴を data/journal.csv へ upsert(cron 毎時実行を想定)。"""
    from saxokit.api import SaxoApi

    path = DATA_DIR / "journal.csv"
    rows: list[str] = []
    if path.exists():
        rows = [line for line in path.read_text().splitlines()[1:] if line]
    row_index = {line.split(",", 1)[0]: i for i, line in enumerate(rows)}
    api = SaxoApi()
    currencies: dict[tuple[int, str], str] = {}
    added = updated = 0
    for d in api.closed_positions():
        cp = d.get("ClosedPosition", {})
        uic = cp.get("Uic")
        asset_type = cp.get("AssetType")
        if uic is None or not asset_type:
            pid = d.get("ClosedPositionUniqueId", "不明")
            raise ValueError(f"closed position {pid}: Uic/AssetType がない")
        key = (int(uic), str(asset_type))
        if key not in currencies:
            currencies[key] = api.get(
                f"ref/v1/instruments/details/{key[0]}/{key[1]}"
            ).get("CurrencyCode", "")
        pid, line = journal_line(d, currencies[key]) or ("", "")
        if not pid:
            continue
        if pid in row_index:
            index = row_index[pid]
            if rows[index] != line:
                rows[index] = line
                updated += 1
        else:
            row_index[pid] = len(rows)
            rows.append(line)
            added += 1
    if added or updated:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        try:
            tmp.write_text(JOURNAL_COLS + "\n" + "\n".join(rows) + "\n")
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()
        print(f"journal: {added} 件追加・{updated} 件更新(累計 {len(rows)})")
    elif args.verbose:
        print(f"journal: 変更なし(累計 {len(rows)})")


def cmd_reset(args) -> None:
    """sim 口座を JPY 指定額(口座通貨換算)でリセット。建玉・注文も全消去される。"""
    from saxokit.api import SaxoApi

    # --token は .env を書き換えず、このリセット要求だけに指定した access token を使う
    api = SaxoApi(token=args.token)
    _, ccy = api.total_value()
    ccy_jpy_uic = {"JPY": None, "EUR": 18, "USD": 42}
    if ccy not in ccy_jpy_uic:
        raise SystemExit(f"口座通貨 {ccy} 未対応")
    balance = args.balance_jpy
    if ccy_jpy_uic[ccy]:
        mid = api.quote(ccy_jpy_uic[ccy])["Mid"]
        balance = round(args.balance_jpy / mid, 2)
    api.reset_account(balance)
    total, _ = api.total_value()
    print(f"リセット完了: {total} {ccy} (≈{args.balance_jpy:.0f} JPY 指定)")


def cmd_paper(args) -> None:
    """ペーパートレード 1 サイクル(cron から銘柄ごとに毎時実行する想定)。

    直近の確定足でシグナル判定 → 実行時の市場価格で成行注文。
    バックテストの次足始値と同じ価格での執行は保証しない。
    1 銘柄で複数戦略を同時運用し、戦略別の保有量は data/trades.csv(台帳)で管理する
    (API のネット建玉から戦略別内訳は分からない)。API のネット建玉は
    台帳合計との照合に使い、ズレは台帳側で調整する。発注は戦略の差分を合算して 1 本。
    """
    from datetime import datetime, timezone

    from saxokit.api import SaxoApi

    def log(msg: str) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{now}Z {msg}")

    specs = [x.strip() for x in args.strategies.split(",") if x.strip()]
    if not specs or len(set(specs)) != len(specs):
        raise SystemExit("--strategies は空欄・重複のない戦略一覧を指定してください")
    tag = args.symbol or str(args.uic)
    api = SaxoApi()
    if api.env != "sim":
        raise SystemExit("paper は Simulation 環境のみ許可。SAXO_ENV=sim を指定してください")
    candles = api.fetch_candles(
        uic=args.uic, horizon=args.horizon, days=history_days(specs, args.horizon)
    )
    now_ms = time.time() * 1000
    closed = completed_candles(candles, args.horizon, now_ms)
    if len(closed) < max(warmup(x) for x in specs) + 5:
        log(f"{tag} 確定足 {len(closed)} 本で不足 → スキップ")
        return
    # 閉場中(週末・XAUUSD の毎日 21-22 UTC 休憩等)は API の MarketState で判定。
    # 足の鮮度で判定すると休憩明けの 1 本欠落を誤って閉場扱いする
    q = api.quote(args.uic)
    if q.get("MarketState") != "Open":
        log(f"{tag} 市場クローズ(MarketState={q.get('MarketState')}) → スキップ")
        return

    # ペーパーは long-only 構成のみ運用
    sigs = {x: max(strategy_target(x, closed)[-1], 0) for x in specs}
    pos = api.net_position_amount(args.uic)
    price = closed[-1].close
    ledger_path = DATA_DIR / "trades.csv"
    held = held_by_strategy(read_ledger(ledger_path), tag)

    total, ccy = api.total_value()
    # API が返す口座通貨を JPY 換算。対応通貨を増やす場合は {ccy}JPY の Uic を足す
    ccy_jpy_uic = {"JPY": None, "EUR": 18, "USD": 42}
    if ccy not in ccy_jpy_uic:
        log(f"口座通貨 {ccy} 未対応 → スキップ")
        return
    total_jpy = total
    if ccy_jpy_uic[ccy]:
        mid = api.quote(ccy_jpy_uic[ccy])["Mid"]
        total_jpy = total * mid
    if not args.dry_run:
        append_equity(DATA_DIR / "equity.csv", int(now_ms), total_jpy)  # JPY 建てで記録

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def rows_of(changes, order_id, reason=None):
        return [
            {
                "ts": ts,
                "symbol": tag,
                "strategy": spec,
                "side": side,
                "amount": amt,
                "price": q.get("Ask" if side == "Buy" else "Bid") or price,
                "order_id": order_id,
                "reason": reason or trade_reason(spec, side),
            }
            for spec, side, amt in changes
        ]

    fix = reconcile(held, specs, pos)
    if fix:
        action = "[dry-run] 台帳の同期予定(未書込)" if args.dry_run else "台帳を同期"
        log(f"{tag} 台帳 {sum(held.values()):.0f} ≠ API 建玉 {pos:.0f} → {action} {fix}")
        if not args.dry_run:
            append_ledger(ledger_path, rows_of(fix, "reconcile", "台帳を API 建玉に同期"))
        # dry-run でも、調整後の保有量に基づいて同じ注文計画を計算する。
        for spec, side, amount in fix:
            held[spec] = held.get(spec, 0.0) + (amount if side == "Buy" else -amount)

    # 建値通貨が JPY 以外(XAUUSD 等)は USDJPY で JPY 換算してから数量計算
    quote_ccy = api.get(f"ref/v1/instruments/details/{args.uic}/FxSpot").get(
        "CurrencyCode", ""
    )
    jpy_per_quote = {"JPY": 1.0, "USD": None}.get(quote_ccy, 0.0)
    if jpy_per_quote is None:
        jpy_per_quote = api.quote(42)["Mid"]
    if not jpy_per_quote:
        log(f"{tag} 建値通貨 {quote_ccy} は未対応 → スキップ")
        return
    # 新規数量計算のレバレッジは戦略数で等分。保有後や複数銘柄全体の上限は制御しない
    size = paper_amount(
        args.leverage / len(specs), total_jpy, price, jpy_per_quote, args.lot
    )
    changes = paper_plan(sigs, held, size)
    state = " ".join(f"{x} sig={sigs[x]} held={held.get(x, 0):.0f}" for x in specs)
    if not changes:
        if size <= 0 and any(sigs.values()):
            log(f"{tag} 数量 0(評価額 {total_jpy:,.0f} 円) → スキップ ({state})")
        else:
            log(f"{tag} 変化なし ({state} @~{price})")
        return
    delta = sum(amt if side == "Buy" else -amt for _, side, amt in changes)
    why = "; ".join(trade_reason(spec, side) for spec, side, _ in changes)
    order_id = "netted"  # 戦略間で相殺され発注不要
    if args.dry_run:
        action = "Buy" if delta > 0 else "Sell" if delta < 0 else "相殺"
        log(f"[dry-run] {tag} {action} {abs(delta)} @~{price} [{why}]")
        return
    if delta:
        r = api.place_market_order(args.uic, abs(delta), "Buy" if delta > 0 else "Sell")
        order_id = str(r.get("OrderId", ""))
    append_ledger(ledger_path, rows_of(changes, order_id))
    log(
        f"{tag} {'Buy' if delta > 0 else 'Sell' if delta < 0 else '相殺'} {abs(delta)} "
        f"@~{price} → OrderId={order_id} [{why}]"
    )


def main() -> None:
    p = argparse.ArgumentParser(prog="saxokit")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("token", help="トークン疎通確認").set_defaults(fn=cmd_token)
    sub.add_parser("login", help="OAuth 初回ログイン(access/refresh token を .env へ)").set_defaults(
        fn=lambda a: __import__("saxokit.auth", fromlist=["login"]).login()
    )
    sub.add_parser("refresh", help="refresh token で SAXO_TOKEN を更新(cron 10 分毎)").set_defaults(
        fn=lambda a: __import__("saxokit.auth", fromlist=["refresh"]).refresh()
    )

    pi = sub.add_parser("instruments", help="銘柄検索(Uic を調べる)")
    pi.add_argument("--keywords", required=True)
    pi.add_argument("--asset-types", default="FxSpot")
    pi.set_defaults(fn=cmd_instruments)

    pf = sub.add_parser("fetch", help="ローソク足を data/ にキャッシュ")
    pf.add_argument("--uic", type=int, required=True)
    pf.add_argument("--symbol", help="キャッシュファイル名(省略時は uic)")
    pf.add_argument("--asset-type", default="FxSpot")
    pf.add_argument("--horizon", type=int, default=60, help="足の分数(既定 60)")
    pf.add_argument("--days", type=float, default=365)
    pf.set_defaults(fn=cmd_fetch)

    pb = sub.add_parser("backtest", help="キャッシュ済みデータで EMA / donchian / bb を検証")
    pb.add_argument("--symbol", required=True)
    pb.add_argument("--horizon", type=int, default=60)
    pb.add_argument(
        "--strategy", choices=("ema", "donchian", "bb"), default="ema"
    )
    pb.add_argument("--fast", type=int, default=9)
    pb.add_argument("--slow", type=int, default=26)
    pb.add_argument("--enter", type=int, default=55, help="donchian: エントリー本数")
    pb.add_argument("--exit", type=int, default=20, help="donchian: 手仕舞い本数")
    pb.add_argument("--period", type=int, default=20, help="bb: 期間")
    pb.add_argument("--std", type=float, default=2.0, help="bb: σ倍率")
    pb.add_argument("--long-only", action="store_true")
    pb.add_argument("--leverage", type=float, default=0, help="config を一時上書き")
    pb.set_defaults(fn=cmd_backtest)

    pp = sub.add_parser("paper", help="ペーパートレード 1 サイクル(sim 限定・long-only)")
    pp.add_argument("--uic", type=int, default=42, help="売買する銘柄ID。symbolから検索しない(既定42)")
    pp.add_argument("--symbol", help="台帳・ダッシュボードの銘柄キー。売買する銘柄は --uic で指定")
    pp.add_argument("--horizon", type=int, default=60)
    pp.add_argument(
        "--strategies",
        default="ema9/26",
        help="カンマ区切りで複数可(例: ema9/26,donchian30/15)。レバは戦略数で等分",
    )
    pp.add_argument("--leverage", type=float, default=5.0, help="新規数量計算のレバレッジ(戦略数で等分。保有後の上限制御なし)")
    pp.add_argument("--lot", type=int, default=1000, help="数量の切り捨て単位(金は 1)")
    pp.add_argument("--dry-run", action="store_true")
    pp.set_defaults(fn=cmd_paper)

    pr = sub.add_parser("reset", help="sim 口座残高リセット(JPY 指定→口座通貨換算)")
    pr.add_argument("--balance-jpy", type=float, required=True)
    pr.add_argument(
        "--token",
        help="リセット権限を持つ Simulation access token(.env は書き換えない)",
    )
    pr.set_defaults(fn=cmd_reset)

    pj = sub.add_parser("journal", help="決済履歴を data/journal.csv へ同期")
    pj.add_argument("--verbose", action="store_true", help="追加 0 件でも表示")
    pj.set_defaults(fn=cmd_journal)

    pw = sub.add_parser("web", help="監視ダッシュボード(既定 127.0.0.1:8787)")
    pw.add_argument("--port", type=int, default=8787)
    pw.add_argument(
        "--host",
        default="127.0.0.1",
        help="待受アドレス(既定 127.0.0.1。外部公開は認証がない点に注意)",
    )
    pw.set_defaults(
        fn=lambda a: __import__("saxokit.web", fromlist=["serve"]).serve(
            a.port, a.host
        )
    )

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
