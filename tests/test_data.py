import csv

import pytest

from saxokit.data import Candle, from_saxo, load_candles_csv, save_candles_csv


def test_new_csv_round_trip_preserves_missing_and_zero_open_spread(tmp_path):
    path = tmp_path / "candles.csv"
    candles = [
        Candle(1, 100, 101, 99, 100, spread=0.2, spread_open=None),
        Candle(2, 100, 101, 99, 100, spread=0.3, spread_open=0.0),
    ]

    save_candles_csv(path, candles)

    assert load_candles_csv(path) == candles
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["spread_open"] == ""
    assert rows[1]["spread_open"] == "0.0"


def test_legacy_six_column_csv_loads_and_resaves(tmp_path):
    path = tmp_path / "legacy.csv"
    path.write_text(
        "ts,open,high,low,close,spread\n"
        "1,100,101,99,100,0.2\n",
        encoding="utf-8",
    )

    loaded = load_candles_csv(path)

    assert loaded == [Candle(1, 100, 101, 99, 100, spread=0.2)]
    save_candles_csv(path, [])
    assert load_candles_csv(path) == loaded


def test_save_filters_old_cache_rows_after_merge(tmp_path):
    path = tmp_path / "candles.csv"
    save_candles_csv(
        path,
        [
            Candle(1, 100, 100, 100, 100),
            Candle(3, 100, 100, 100, 100),
        ],
    )

    save_candles_csv(
        path,
        [Candle(2, 100, 100, 100, 100)],
        max_ts=2,
    )

    assert [c.ts for c in load_candles_csv(path)] == [1, 2]


def test_from_saxo_keeps_open_and_close_spreads():
    candle = from_saxo(
        {
            "Time": "2026-09-21T00:00:00Z",
            "OpenBid": 100.0,
            "OpenAsk": 100.4,
            "HighBid": 101.0,
            "HighAsk": 101.6,
            "LowBid": 99.0,
            "LowAsk": 99.2,
            "CloseBid": 100.1,
            "CloseAsk": 100.3,
        }
    )

    assert candle.open == pytest.approx(100.2)
    assert candle.spread_open == pytest.approx(0.4)
    assert candle.spread == pytest.approx(0.2)


@pytest.mark.parametrize("spread_open", ["nan", "-0.1"])
def test_invalid_open_spread_is_rejected_on_load(tmp_path, spread_open):
    path = tmp_path / "invalid.csv"
    path.write_text(
        "ts,open,high,low,close,spread,spread_open\n"
        f"1,100,101,99,100,0.2,{spread_open}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="spread_open"):
        load_candles_csv(path)
