"""発注応答を成功として扱う条件を検証する。外部 API へは接続しない。"""

import pytest

from saxokit.api import SaxoApi


class StubResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self.payload


class StubSession:
    def __init__(self, response):
        self.response = response

    def post(self, *_args, **_kwargs):
        return self.response


def api_with_response(payload, status_code=200):
    api = object.__new__(SaxoApi)
    api.env = "sim"
    api.base = "https://example.invalid"
    api.session = StubSession(StubResponse(payload, status_code))
    api.account_key = lambda: "account-key"
    return api


@pytest.mark.parametrize(
    ("payload", "status_code", "message"),
    [
        (
            {
                "OrderId": "55024416",
                "ErrorInfo": {
                    "ErrorCode": "TradeNotCompleted",
                    "Message": "status unknown",
                },
            },
            202,
            "発注結果不明",
        ),
        ({"OrderId": "55024416"}, 202, "発注結果不明"),
        ({}, 200, "OrderId がない"),
    ],
)
def test_ambiguous_order_response_is_not_success(payload, status_code, message):
    api = api_with_response(payload, status_code=status_code)

    with pytest.raises(SystemExit, match=message):
        api.place_market_order(42, 1000, "Buy")


def test_order_response_with_order_id_is_success():
    api = api_with_response({"OrderId": "12345"})

    assert api.place_market_order(42, 1000, "Buy") == {"OrderId": "12345"}


def test_api_reads_environment_from_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAXO_TOKEN", "old-synthetic-token")
    (tmp_path / ".env").write_text("SAXO_ENV=sim\nSAXO_TOKEN=local-synthetic-token\n")
    api = SaxoApi()
    assert api.env == "sim"
    assert api.token == "local-synthetic-token"
