"""Saxo OAuth の認可コードフローで access / refresh token を取得・更新する。

手順:
  1. developer.saxo でアプリを作成(環境 Simulation、Grant type: Code、Redirect URL: http://localhost)。
     .env に SAXO_APP_KEY / SAXO_APP_SECRET を書く
  2. `uv run saxokit login` → 表示された URL をブラウザで開いてログイン →
     リダイレクト先 URL(http://localhost/?code=...&state=...)を丸ごと貼る。access/refresh token を .env に書く
  3. `uv run saxokit refresh` を cron で実行 → token を更新して .env を書き換える。
     有効期間は API 応答値をログへ表示する。SaxoApi は毎回 .env を読み直す
refresh が拒否された場合は 2 をやり直す。cron 10 分毎は運用例で、API 応答に応じた動的間隔ではない。
"""

from __future__ import annotations

import os
import re
import secrets
import tempfile
import time
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import dotenv_values

AUTH_BASES = {
    "sim": "https://sim.logonvalidation.net",
    "live": "https://live.logonvalidation.net",
}
ENV_PATH = Path(".env")


def _cfg(env_path: Path, key: str) -> str:
    return dotenv_values(env_path).get(key) or os.environ.get(key) or ""


def _auth_base(env_path: Path) -> str:
    return _cfg(env_path, "SAXO_AUTH_BASE") or AUTH_BASES[_cfg(env_path, "SAXO_ENV") or "sim"]


def write_env(path: Path, **kv: str) -> None:
    """.env の該当キー行だけ差し替え(無ければ末尾追記)。他行は保持。atomic に置換。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for k, v in kv.items():
        pat = re.compile(rf"^\s*(export\s+)?{k}=")
        hit = [i for i, line in enumerate(lines) if pat.match(line)]
        if hit:
            lines[hit[0]] = f"{k}={v}"
        else:
            lines.append(f"{k}={v}")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if fd >= 0:
            os.close(fd)
        tmp.unlink(missing_ok=True)


@contextmanager
def _token_lock(env_path: Path) -> Iterator[None]:
    lock_path = env_path.with_name(f"{env_path.name}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        flock(fd, LOCK_EX)
        yield
    finally:
        flock(fd, LOCK_UN)
        os.close(fd)


def _exchange_unlocked(env_path: Path, data: dict[str, str]) -> dict[str, Any]:
    key, secret = _cfg(env_path, "SAXO_APP_KEY"), _cfg(env_path, "SAXO_APP_SECRET")
    if not key or not secret:
        raise SystemExit("SAXO_APP_KEY / SAXO_APP_SECRET を .env に書く(developer.saxo でアプリ作成)")
    request_data = {**data, "redirect_uri": _cfg(env_path, "SAXO_REDIRECT_URI") or "http://localhost"}
    resp = requests.post(f"{_auth_base(env_path)}/token", data=request_data, auth=(key, secret), timeout=30)
    if resp.status_code not in (200, 201):  # Saxo は 201 Created を返す
        raise SystemExit(f"token 取得失敗 (HTTP {resp.status_code})")
    j: dict[str, Any] = resp.json()
    access_token, refresh_token = j.get("access_token"), j.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise SystemExit("token 応答に access_token / refresh_token がない")
    write_env(env_path, SAXO_TOKEN=access_token, SAXO_REFRESH_TOKEN=refresh_token)
    return j


def _exchange(env_path: Path, data: dict[str, str]) -> dict[str, Any]:
    with _token_lock(env_path):
        return _exchange_unlocked(env_path, data)


def login(env_path: Path = ENV_PATH) -> None:
    key = _cfg(env_path, "SAXO_APP_KEY")
    if not key:
        raise SystemExit("SAXO_APP_KEY / SAXO_APP_SECRET を .env に書く(developer.saxo でアプリ作成)")
    redirect = _cfg(env_path, "SAXO_REDIRECT_URI") or "http://localhost"
    state = secrets.token_urlsafe(32)
    query = urlencode({
        "response_type": "code",
        "client_id": key,
        "state": state,
        "redirect_uri": redirect,
    })
    print(f"ブラウザで開いてログイン:\n{_auth_base(env_path)}/authorize?{query}")
    raw = input("リダイレクト先 URL を丸ごと貼る: ").strip()
    callback = urlparse(raw)
    if not callback.scheme or not callback.netloc:
        raise SystemExit("リダイレクト先 URL を丸ごと貼る必要がある")
    params = parse_qs(callback.query, keep_blank_values=True)
    callback_states = params.get("state", [])
    if len(callback_states) != 1 or not secrets.compare_digest(callback_states[0], state):
        raise SystemExit("OAuth state が一致しないため中止")
    errors = params.get("error", [])
    if errors:
        raise SystemExit(f"OAuth 認可失敗: {errors[0] or 'unknown_error'}")
    codes = params.get("code", [])
    if len(codes) != 1 or not codes[0]:
        raise SystemExit("リダイレクト先 URL に認可 code がない")
    code = codes[0]
    j = _exchange(env_path, {"grant_type": "authorization_code", "code": code})
    print(f"OK access {j.get('expires_in')}s / refresh {j.get('refresh_token_expires_in')}s → .env 更新")


def refresh(env_path: Path = ENV_PATH) -> bool:
    """refresh token があれば更新して True。未 login なら何もせず False(cron ログを汚さない)。"""
    with _token_lock(env_path):
        rt = _cfg(env_path, "SAXO_REFRESH_TOKEN")
        if not rt:
            return False
        j = _exchange_unlocked(env_path, {"grant_type": "refresh_token", "refresh_token": rt})
    print(
        f"{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())} refresh OK "
        f"access {j.get('expires_in')}s / refresh {j.get('refresh_token_expires_in')}s"
    )
    return True
