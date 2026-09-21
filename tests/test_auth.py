"""OAuth token の取得・安全な保存を確認。"""

import json
import os
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest

import saxokit.auth as auth
from saxokit.auth import login, refresh, write_env

seen = {}


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        seen["path"] = self.path
        seen["auth"] = self.headers.get("Authorization", "")
        seen["body"] = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        self.send_response(201)  # 過去の観測を模した成功応答
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "access_token": "NEW_ACCESS", "expires_in": 1200,
            "refresh_token": "NEW_REFRESH", "refresh_token_expires_in": 3600,
        }).encode())

    def log_message(self, *_):
        pass


def test_refresh_rewrites_only_token_lines(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = tmp_path / ".env"
    env.write_text(
        "# コメントは残る\nSAXO_TOKEN=OLD\nSAXO_ENV=sim\n"
        f"SAXO_AUTH_BASE=http://127.0.0.1:{srv.server_port}\n"
        "SAXO_APP_KEY=k\nSAXO_APP_SECRET=s\nSAXO_REFRESH_TOKEN=OLD_R\n"
    )
    try:
        assert refresh(env) is True
    finally:
        srv.shutdown()
    text = env.read_text()
    assert "# コメントは残る" in text and "SAXO_ENV=sim" in text
    assert "SAXO_TOKEN=NEW_ACCESS\n" in text and "SAXO_REFRESH_TOKEN=NEW_REFRESH\n" in text
    assert "OLD" not in text
    assert seen["path"] == "/token" and seen["auth"].startswith("Basic ")
    assert seen["body"]["grant_type"] == ["refresh_token"]
    assert seen["body"]["refresh_token"] == ["OLD_R"]
    assert seen["body"]["redirect_uri"] == ["http://localhost"]


def test_refresh_is_noop_without_refresh_token(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SAXO_TOKEN=DEV24H\n")
    assert refresh(env) is False
    assert env.read_text() == "SAXO_TOKEN=DEV24H\n"


def test_write_env_appends_missing_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    write_env(env, A="2", B="3")
    assert env.read_text() == "A=2\nB=3\n"


def test_write_env_keeps_secret_permissions_with_common_umask(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    env.chmod(0o600)
    old_umask = os.umask(0o022)
    try:
        write_env(env, A="2")
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_write_env_cleans_up_temp_file_when_replace_fails(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("A=1\n")

    def fail_replace(_src, _dst):
        raise OSError("replace failed")

    monkeypatch.setattr(auth.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        write_env(env, A="2")

    assert env.read_text() == "A=1\n"
    assert list(tmp_path.iterdir()) == [env]


def test_concurrent_refresh_uses_rotated_refresh_token(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "SAXO_AUTH_BASE=https://auth.invalid\n"
        "SAXO_APP_KEY=k\nSAXO_APP_SECRET=s\nSAXO_REFRESH_TOKEN=OLD\n"
    )
    first_started = threading.Event()
    release_first = threading.Event()
    calls = []

    def fake_post(_url, *, data, auth, timeout):
        del auth, timeout
        calls.append(data["refresh_token"])
        if data["refresh_token"] == "OLD":
            first_started.set()
            assert release_first.wait(timeout=2)
            suffix = "FIRST"
        else:
            suffix = "SECOND"
        return SimpleNamespace(
            status_code=201,
            json=lambda: {
                "access_token": f"ACCESS_{suffix}",
                "refresh_token": suffix,
            },
        )

    monkeypatch.setattr(auth.requests, "post", fake_post)
    first = threading.Thread(target=refresh, args=(env,))
    second = threading.Thread(target=refresh, args=(env,))
    first.start()
    assert first_started.wait(timeout=2)
    second.start()
    time.sleep(0.05)
    assert calls == ["OLD"]
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive() and not second.is_alive()
    assert calls == ["OLD", "FIRST"]
    assert "SAXO_REFRESH_TOKEN=SECOND\n" in env.read_text()


def test_login_validates_state_and_exchanges_code(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("SAXO_APP_KEY=k\nSAXO_APP_SECRET=s\n")
    exchanged = {}
    monkeypatch.setattr(auth.secrets, "token_urlsafe", lambda _size: "one-time-state")
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "http://localhost/?code=AUTH_CODE&state=one-time-state",
    )

    def fake_exchange(_env_path, data):
        exchanged.update(data)
        return {}

    monkeypatch.setattr(auth, "_exchange", fake_exchange)
    login(env)

    assert exchanged == {"grant_type": "authorization_code", "code": "AUTH_CODE"}
    assert "state=one-time-state" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("callback", "message"),
    [
        ("AUTH_CODE", "URL を丸ごと"),
        ("http://localhost/?code=AUTH_CODE&state=wrong", "state が一致しない"),
        ("http://localhost/?error=access_denied&state=one-time-state", "access_denied"),
    ],
)
def test_login_rejects_unverifiable_or_error_callback(tmp_path, monkeypatch, callback, message):
    env = tmp_path / ".env"
    env.write_text("SAXO_APP_KEY=k\nSAXO_APP_SECRET=s\n")
    monkeypatch.setattr(auth.secrets, "token_urlsafe", lambda _size: "one-time-state")
    monkeypatch.setattr("builtins.input", lambda _prompt: callback)
    monkeypatch.setattr(auth, "_exchange", lambda *_args, **_kwargs: pytest.fail("must not exchange"))

    with pytest.raises(SystemExit, match=message):
        login(env)


def test_token_error_does_not_include_response_body(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "SAXO_AUTH_BASE=https://auth.invalid\n"
        "SAXO_APP_KEY=k\nSAXO_APP_SECRET=s\nSAXO_REFRESH_TOKEN=OLD\n"
    )
    monkeypatch.setattr(
        auth.requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=400, text="SECRET_RESPONSE_BODY"),
    )

    with pytest.raises(SystemExit) as exc_info:
        refresh(env)

    assert "HTTP 400" in str(exc_info.value)
    assert "SECRET_RESPONSE_BODY" not in str(exc_info.value)
