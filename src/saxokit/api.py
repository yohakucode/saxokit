"""Saxo OpenAPI クライアント。

- 認証: OAuth 等で取得した access token(.env の SAXO_TOKEN)
- 既定は sim(シミュレーション)環境
- 発注とリセットは sim 環境専用。live 環境への書き込みは実装しない
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from saxokit.data import Candle, from_saxo

BASES = {
    "sim": "https://gateway.saxobank.com/sim/openapi",
    "live": "https://gateway.saxobank.com/openapi",
}
MAX_COUNT = 1200  # chart API の 1 リクエスト上限


class SaxoApi:
    def __init__(self, env: str | None = None, token: str | None = None) -> None:
        load_dotenv(dotenv_path=Path(".env"), override=True)  # .env 更新(トークン再発行)を常駐 web が再起動なしで拾う
        env = env or os.environ.get("SAXO_ENV", "sim")
        if env not in BASES:
            raise SystemExit(f"SAXO_ENV は sim / live のみ(現在: {env})")
        self.env = env
        self.base = BASES[env]
        self.token = token or os.environ.get("SAXO_TOKEN", "")
        if not self.token:
            raise SystemExit(
                "SAXO_TOKEN がありません。`saxokit login` で OAuth ログインするか、"
                "有効な access token を .env に設定してください"
            )
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {self.token}"

    def get(self, path: str, **params) -> dict:
        resp = self.session.get(f"{self.base}/{path}", params=params, timeout=30)
        if resp.status_code == 401:
            raise SystemExit(
                "401 Unauthorized: access token が無効または失効。"
                "`saxokit refresh` を実行し、拒否された場合は `saxokit login` をやり直してください"
            )
        resp.raise_for_status()
        return resp.json()

    def me(self) -> dict:
        """トークン疎通確認。UserId / 環境が返れば OK。"""
        return self.get("port/v1/users/me")

    def account_key(self) -> str:
        """既定口座の AccountKey(発注に必要)。"""
        accounts = self.get("port/v1/accounts/me").get("Data", [])
        if not accounts:
            raise SystemExit("口座が見つからない")
        return accounts[0]["AccountKey"]

    def total_value(self) -> tuple[float, str]:
        """口座評価額と通貨。"""
        j = self.get("port/v1/balances/me")
        return float(j["TotalValue"]), j.get("Currency", "")

    def net_position_amount(self, uic: int, asset_type: str = "FxSpot") -> float:
        """指定銘柄のネット建玉数量(なければ 0)。"""
        j = self.get("port/v1/netpositions/me", FieldGroups="NetPositionBase")
        for d in j.get("Data", []):
            base = d.get("NetPositionBase", {})
            if base.get("Uic") == uic and base.get("AssetType") == asset_type:
                return float(base.get("Amount", 0.0))
        return 0.0

    def quote(self, uic: int, asset_type: str = "FxSpot") -> dict:
        """現在気配(Mid/Bid/Ask/MarketState 等)。MarketState は Open/Closed など。"""
        return self.get(
            "trade/v1/infoprices", Uic=uic, AssetType=asset_type, FieldGroups="Quote"
        )["Quote"]

    def net_positions(self) -> list[dict]:
        """全ネット建玉の詳細(数量・平均建値など)。"""
        j = self.get(
            "port/v1/netpositions/me", FieldGroups="NetPositionBase,NetPositionView"
        )
        return j if isinstance(j, list) else j.get("Data", [])

    def closed_positions(self) -> list[dict]:
        """決済済みポジション一覧(実約定価格・損益。journal の元データ)。"""
        j = self.get("port/v1/closedpositions/me", **{"$top": 500})
        # sim は bare list、標準形は {"Data": [...]} の両方が観測される
        return j if isinstance(j, list) else j.get("Data", [])

    def reset_account(self, new_balance: float) -> None:
        """sim 口座を新残高(口座通貨建て)でリセット。建玉・注文も全消去。sim 専用。"""
        if self.env != "sim":
            raise SystemExit("リセットは sim 環境のみ(live には存在しない操作)")
        key = self.account_key()
        resp = self.session.put(
            f"{self.base}/port/v1/accounts/{key}/reset",
            json={"NewBalance": new_balance},
            timeout=30,
        )
        if resp.status_code not in (200, 204):
            raise SystemExit(f"リセット失敗 {resp.status_code}: {resp.text[:300]}")

    def place_market_order(
        self, uic: int, amount: float, buy_sell: str, asset_type: str = "FxSpot"
    ) -> dict:
        """成行発注。Simulation 環境のみ許可し、live 発注は対応しない。"""
        if self.env != "sim":
            raise SystemExit("発注は Simulation 環境のみ許可。live 発注は未対応")
        if buy_sell not in ("Buy", "Sell"):
            raise SystemExit(f"buy_sell は Buy/Sell のみ(現在: {buy_sell})")
        body = {
            "AccountKey": self.account_key(),
            "Uic": uic,
            "AssetType": asset_type,
            "Amount": amount,
            "BuySell": buy_sell,
            "OrderType": "Market",
            "ManualOrder": False,
            "OrderDuration": {"DurationType": "DayOrder"},
        }
        resp = self.session.post(f"{self.base}/trade/v2/orders", json=body, timeout=30)
        if resp.status_code >= 400:
            raise SystemExit(f"発注エラー {resp.status_code}: {resp.text[:300]}")
        result = resp.json()
        error = result.get("ErrorInfo") or {}
        if resp.status_code == 202:
            code = error.get("ErrorCode", "HTTP 202")
            message = error.get("Message", "")
            order_id = result.get("OrderId", "")
            raise SystemExit(
                f"発注結果不明 ({code}, OrderId={order_id or 'なし'}): {message}。"
                "自動再送せず Portfolio の注文・建玉を照会してください。台帳は未更新です"
            )
        if error:
            code = error.get("ErrorCode", "UnknownError")
            message = error.get("Message", "")
            if code == "TradeNotCompleted":
                order_id = result.get("OrderId", "")
                raise SystemExit(
                    f"発注結果不明 ({code}, OrderId={order_id or 'なし'}): {message}。"
                    "自動再送せず Portfolio の注文・建玉を照会してください。台帳は未更新です"
                )
            raise SystemExit(f"発注拒否 {code}: {message}")
        if not result.get("OrderId"):
            raise SystemExit(
                "発注応答に OrderId がないため結果を確定できません。"
                "自動再送せず Portfolio の注文・建玉を照会してください。台帳は未更新です"
            )
        return result

    def instruments(self, keywords: str, asset_types: str = "FxSpot") -> list[dict]:
        """銘柄検索。asset_types はカンマ区切り(FxSpot,CfdOnIndex 等)。"""
        j = self.get(
            "ref/v1/instruments",
            Keywords=keywords,
            AssetTypes=asset_types,
            **{"$top": 100},
        )
        return j.get("Data", [])

    def fetch_candles(
        self,
        uic: int,
        asset_type: str = "FxSpot",
        horizon: int = 60,
        days: float = 365,
    ) -> list[Candle]:
        """ローソク足を過去方向にページングして days 日分取得する。

        horizon は分(1,5,15,30,60,120,240,1440,10080,43200)。
        chart/v3 を試し、404 なら chart/v1 にフォールバック。
        """
        want_from_ms = int((time.time() - days * 86400) * 1000)
        out: dict[int, Candle] = {}
        upto: str | None = None
        path = None
        while True:
            params: dict = {
                "Uic": uic,
                "AssetType": asset_type,
                "Horizon": horizon,
                "Count": MAX_COUNT,
            }
            if upto:
                params.update(Mode="UpTo", Time=upto)
            if path is None:
                for cand in ("chart/v3/charts", "chart/v1/charts"):
                    resp = self.session.get(
                        f"{self.base}/{cand}", params=params, timeout=30
                    )
                    if resp.status_code != 404:
                        path = cand
                        break
                else:
                    raise SystemExit("chart API が v3/v1 とも 404。API 仕様確認を")
            else:
                resp = self.session.get(f"{self.base}/{path}", params=params, timeout=30)
            if resp.status_code == 401:
                raise SystemExit(
                    "401: access token が無効または失効。`saxokit refresh` を実行し、"
                    "拒否された場合は `saxokit login` をやり直してください"
                )
            resp.raise_for_status()
            rows = resp.json().get("Data", [])
            if not rows:
                break
            batch = [from_saxo(r) for r in rows]
            new = {c.ts: c for c in batch if c.ts not in out}
            out.update(new)
            oldest = min(c.ts for c in batch)
            if oldest <= want_from_ms or not new:
                break
            upto = datetime.fromtimestamp(oldest / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            time.sleep(0.3)  # レートリミット保護
        return [out[ts] for ts in sorted(out) if out[ts].ts >= want_from_ms]
