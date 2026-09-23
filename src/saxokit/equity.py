"""エクイティ履歴 data/equity.csv の読み書き(ダッシュボードの資産推移用)。

形式は "ts,total_value" のヘッダー行と "エポックミリ秒,円建て評価額" の行で、各行は改行で終わる。
読み込みはファイルを変更せず、不正な行を除いた記録と問題の一覧を返す(破損を黙って隠さない)。
追記は既存内容に問題があれば何も書かずに中止し、切れた末尾へ新しい行を継ぎ足さない。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

HEADER = "ts,total_value"
MIN_INTERVAL_MS = (
    30 * 60_000
)  # cron は毎時 2 銘柄分 paper を実行するため 30 分以内の重複は記録しない
MAX_PROBLEMS = 20  # 画面と応答に載せる問題行の上限。超過分は件数だけ伝える

_TS = re.compile(r"[0-9]+")
_NUMBER = re.compile(r"[-+]?(?:[0-9]+(?:[.][0-9]*)?|[.][0-9]+)(?:[eE][-+]?[0-9]+)?")


class EquityError(ValueError):
    """equity.csv が破損している、または記録できない値。メッセージに対処方法を含める。"""


@dataclass(frozen=True)
class EquityScan:
    points: list[list[float]] = field(default_factory=list)  # [[ts, 評価額], ...]
    problems: list[str] = field(default_factory=list)  # 空なら問題なし
    last_ts: int | None = None  # 最後の有効行の ts


def _show(line: str) -> str:
    return repr(line if len(line) <= 40 else line[:40] + "…")


def _parse_row(line: str) -> tuple[int, float] | str:
    """データ行を (ts, 評価額) に変換する。不正なら理由を返す。"""
    if not line.strip():
        return "空行"
    parts = line.split(",")
    if len(parts) != 2:
        return f"列数が 2 ではない ({len(parts)} 列)"
    ts_raw, value_raw = parts
    if not _TS.fullmatch(ts_raw):
        return "ts がエポックミリ秒の整数ではない"
    if _NUMBER.fullmatch(value_raw):
        value = float(value_raw)
    else:
        try:
            value = float(value_raw)
        except ValueError:
            return "total_value が数値ではない"
        if math.isfinite(value):
            return "total_value の書式が不正"
    if not math.isfinite(value):
        return "total_value が有限の数値ではない"
    if len(ts_raw) > 16 or int(ts_raw) > 2**53 - 1:
        return "ts が扱える整数の範囲を超えている"
    return int(ts_raw), value


def scan_equity(data: bytes) -> EquityScan:
    """equity.csv の中身を検査する。空のバイト列は新規ファイルと同じく問題なしとする。"""
    points: list[list[float]] = []
    problems: list[str] = []
    last_ts: int | None = None
    lines = data.decode("utf-8", errors="replace").split("\n") if data else []
    terminated = not lines or lines[-1] == ""
    if lines and terminated:
        lines.pop()
    for no, raw in enumerate(lines, start=1):
        line = raw.removesuffix("\r")
        if no == len(lines) and not terminated:
            # 値が読めても桁が欠けている可能性があるため採用しない
            problems.append(
                f"{no} 行目: 改行で終わっていない(書き込み途中で切れた可能性): {_show(line)}"
            )
            continue
        row = _parse_row(line)
        if no == 1:
            if line == HEADER:
                continue
            if isinstance(row, str):
                problems.append(
                    f"1 行目: ヘッダーが {HEADER!r} ではない: {_show(line)}"
                )
                continue
            problems.append(f"1 行目: ヘッダー {HEADER!r} がない")
        if isinstance(row, str):
            problems.append(f"{no} 行目: {row}: {_show(line)}")
            continue
        points.append([row[0], row[1]])
        last_ts = row[0]
    if len(problems) > MAX_PROBLEMS:
        extra = len(problems) - MAX_PROBLEMS
        problems = problems[:MAX_PROBLEMS] + [f"ほか {extra} 件"]
    return EquityScan(points, problems, last_ts)


def read_equity(path: Path) -> EquityScan:
    """読み込み専用。無いファイルは空、読めないファイルも例外にせず problems で知らせる。"""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return EquityScan()
    except OSError as e:
        return EquityScan(problems=[f"{path} を読み込めない: {type(e).__name__}: {e}"])
    return scan_equity(data)


def append_equity(path: Path, ts_ms: int, total: float) -> None:
    """エクイティ履歴を追記(ダッシュボード用)。30 分以内の重複行はスキップ。

    cron は毎時 2 銘柄分 paper を実行するため、そのままだと 1 時間に 2 行入る。
    既存ファイルに不正な行や改行で終わらない末尾があれば、何も書かずに EquityError を送出する。
    """
    if type(ts_ms) is not int or not 0 <= ts_ms <= 2**53 - 1:
        raise EquityError(
            f"ts {ts_ms!r} はエポックミリ秒の整数ではないため {path} に記録しません"
        )
    if not math.isfinite(total):
        raise EquityError(
            f"評価額 {total!r} は有限の数値ではないため {path} に記録しません"
        )
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        data = b""
    scan = scan_equity(data)
    if scan.problems:
        raise EquityError(
            f"{path} に不正な行があるため評価額の追記を中止しました({'; '.join(scan.problems)})。"
            "ファイルは変更していません。バックアップを取ってから該当行を修正または削除し、"
            "ファイル末尾を改行で終えてください"
        )
    if ts_ms - (scan.last_ts or 0) < MIN_INTERVAL_MS:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"{ts_ms},{total:.0f}\n"
    if not data:  # 新規・空ファイルはヘッダーから書く
        body = HEADER + "\n" + body
    with open(path, "ab") as f:
        f.write(body.encode())
