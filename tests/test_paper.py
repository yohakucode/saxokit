"""paper の純粋ロジック(戦略別台帳・発注計画・API 照合)の最小チェック。"""

from types import SimpleNamespace

import pytest

from saxokit.cli import cmd_paper, paper_plan, reconcile
from saxokit.ledger import held_by_strategy
from saxokit.strategy import strategy_target, trade_reason, warmup
from test_strategy import mk


def test_spec_parser_matches_direct_call():
    from saxokit.strategy import donchian_target

    cs = mk([100.0] * 5 + [105.0, 106.0, 95.0])
    assert strategy_target("Donchian5/3", cs) == donchian_target(cs, 5, 3)
    assert warmup("ema9/26") == 26
    assert trade_reason("donchian30/15", "Sell") == "donchian30/15: 15本安値割れ"


def test_held_by_strategy_sums_buy_minus_sell():
    rows = [
        {"symbol": "usdjpy", "strategy": "ema9/26", "side": "Buy", "amount": "2000"},
        {"symbol": "usdjpy", "strategy": "ema9/26", "side": "Sell", "amount": "1000"},
        {"symbol": "usdjpy", "strategy": "donchian30/15", "side": "Buy", "amount": "1000"},
        {"symbol": "xauusd", "strategy": "donchian30/15", "side": "Buy", "amount": "1"},
    ]
    assert held_by_strategy(rows, "usdjpy") == {"ema9/26": 1000.0, "donchian30/15": 1000.0}


def test_paper_plan_enters_exits_and_nets():
    sigs = {"ema9/26": 0, "donchian30/15": 1}
    held = {"ema9/26": 1000.0}
    changes = paper_plan(sigs, held, size=1000)
    assert changes == [("ema9/26", "Sell", 1000), ("donchian30/15", "Buy", 1000)]
    assert sum(a if s == "Buy" else -a for _, s, a in changes) == 0  # 相殺 → 発注なし
    # 保有中はサイズが変わっても再サイジングしない
    assert paper_plan({"ema9/26": 1}, {"ema9/26": 1000.0}, size=3000) == []
    # 最小ロット未満(size 0)はエントリーしないが手仕舞いはする
    assert paper_plan({"a": 1, "b": 0}, {"b": 1.0}, size=0) == [("b", "Sell", 1)]


def test_reconcile_absorbs_api_difference():
    specs = ["ema9/26", "donchian30/15"]
    # 口座リセット等で API 建玉ゼロ → 保有中の戦略から順に減らす
    assert reconcile({"ema9/26": 1000.0, "donchian30/15": 1000.0}, specs, 0) == [
        ("ema9/26", "Sell", 1000),
        ("donchian30/15", "Sell", 1000),
    ]
    # 台帳より API が多い → 先頭戦略に付ける
    assert reconcile({}, specs, 3000) == [("ema9/26", "Buy", 3000)]
    assert reconcile({"ema9/26": 1000.0}, specs, 1000) == []


def test_paper_refuses_live_before_reading_account(monkeypatch):
    class LiveApi:
        env = "live"

        def __getattr__(self, name):
            raise AssertionError(f"live 口座へアクセスしようとした: {name}")

    import saxokit.api

    monkeypatch.setattr(saxokit.api, "SaxoApi", LiveApi)
    args = SimpleNamespace(strategies="ema9/26", symbol="usdjpy", uic=42)

    with pytest.raises(SystemExit, match="Simulation 環境のみ"):
        cmd_paper(args)
