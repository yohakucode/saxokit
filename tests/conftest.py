"""テストが実認証情報や外部 API に触れないための共通隔離。"""

import os
from urllib.parse import urlsplit

import pytest
import requests


@pytest.fixture(autouse=True)
def isolate_saxo_environment():
    """SAXO_* を消し、未モックの外部 HTTP 通信を送信前に止める。"""
    patcher = pytest.MonkeyPatch()
    original_saxo_keys = {key for key in os.environ if key.startswith("SAXO_")}
    for key in original_saxo_keys:
        patcher.delenv(key)

    original_request = requests.Session.request

    def local_request(session, method, url, *args, **kwargs):
        parsed = urlsplit(str(url))
        if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}:
            return original_request(session, method, url, *args, **kwargs)
        origin = f"{parsed.scheme}://{parsed.hostname}" if parsed.hostname else "invalid URL"
        pytest.fail(f"テスト中の外部 HTTP 通信を拒否: {method} {origin}", pytrace=False)

    patcher.setattr(requests.Session, "request", local_request)
    try:
        yield
    finally:
        for key in tuple(os.environ):
            if key.startswith("SAXO_") and key not in original_saxo_keys:
                os.environ.pop(key)
        patcher.undo()
