"""決済履歴を Saxo の ClosedPosition スキーマから同期する。"""

from types import SimpleNamespace

import pytest

import saxokit.api
import saxokit.cli as cli


def closed_position(
    position_id="open-close",
    position_side="Buy",
    open_price=160.0,
    closing_price=160.16,
    profit_loss=160.0,
):
    return {
        "ClosedPositionUniqueId": position_id,
        "ClosedPosition": {
            "AccountId": "synthetic-account",
            "Amount": 1000.0,
            "AssetType": "FxSpot",
            "BuyOrSell": position_side,
            "ClosedProfitLoss": profit_loss,
            "ClosingPositionId": "close",
            "ClosingPrice": closing_price,
            "ExecutionTimeClose": "2026-09-20T02:00:00Z",
            "ExecutionTimeOpen": "2026-09-20T01:00:00Z",
            "OpeningPositionId": "open",
            "OpenPrice": open_price,
            "Uic": 42,
        },
    }


@pytest.mark.parametrize(
    ("position_side", "closing_price", "expected_amount", "expected_bps"),
    [
        ("Buy", 160.16, "1000.0", "10.0"),
        ("Sell", 159.84, "-1000.0", "10.0"),
    ],
)
def test_journal_line_uses_get_prices_currency_and_position_direction(
    position_side, closing_price, expected_amount, expected_bps
):
    _, line = cli.journal_line(
        closed_position(position_side=position_side, closing_price=closing_price), "JPY"
    )

    cells = line.split(",")
    assert cells[5] == expected_amount
    assert cells[7] == str(closing_price)
    assert cells[8] == expected_bps
    assert cells[9:] == ["160.0", "JPY"]


@pytest.mark.parametrize("missing", ["ClosingPrice", "ClosedProfitLoss"])
def test_journal_line_rejects_incomplete_official_response(missing):
    item = closed_position()
    del item["ClosedPosition"][missing]

    with pytest.raises(ValueError, match=missing):
        cli.journal_line(item, "JPY")


def test_journal_line_rejects_unknown_profit_loss_currency():
    with pytest.raises(ValueError, match="損益通貨"):
        cli.journal_line(closed_position())


def test_journal_resync_creates_directory_and_repairs_existing_row(
    monkeypatch, tmp_path
):
    current = closed_position()

    class Api:
        detail_calls = 0

        def closed_positions(self):
            return [current, closed_position("second")]

        def get(self, path):
            assert path == "ref/v1/instruments/details/42/FxSpot"
            type(self).detail_calls += 1
            return {"CurrencyCode": "JPY"}

    monkeypatch.setattr(saxokit.api, "SaxoApi", Api)
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "missing" / "data")
    cli.cmd_journal(SimpleNamespace(verbose=False))

    path = cli.DATA_DIR / "journal.csv"
    first = path.read_text().splitlines()
    assert first[0] == cli.JOURNAL_COLS
    assert [line.split(",", 1)[0] for line in first[1:]] == ["open-close", "second"]
    assert Api.detail_calls == 1

    historic = "historic,old,row"
    stale = first[1].split(",")
    stale[7:11] = ["0.0", "0.0", "160.0", ""]
    path.write_text("\n".join([cli.JOURNAL_COLS, historic, ",".join(stale), ""]))
    cli.cmd_journal(SimpleNamespace(verbose=False))

    synced = path.read_text().splitlines()
    assert synced[1] == historic
    assert [line.split(",", 1)[0] for line in synced[1:]] == [
        "historic",
        "open-close",
        "second",
    ]
    repaired = synced[2].split(",")
    assert repaired[7:11] == ["160.16", "10.0", "160.0", "JPY"]
    assert Api.detail_calls == 2
