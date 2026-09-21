# saxokit

サクソバンク証券 OpenAPI の FX スポットを Simulation 環境でペーパートレード・監視し、
FX / CFD のデータ取得・バックテストを行うための最小キット。

- **OAuth トークン更新** — 認可コードで取得した access / refresh token を更新して `.env` に保存
- **バックテスト** — スプレッド・スワップ・レバレッジを設定でき、IS/OOS 70/30 の結果を併記
- **FX スポットのペーパートレード** — 1 銘柄に複数戦略を同時運用し、差分をネットして成行 1 本。台帳と口座を毎回照合
- **監視ダッシュボード** — 標準ライブラリだけの読み取り専用 Web UI

実行時の依存は `requests` と `python-dotenv` のみ。Python 3.12 以上、Linux を対象とする。
トークン更新の排他に `fcntl.flock` を使う。

## セットアップ

```bash
uv sync --locked
uv run pytest -q
mkdir -p data
if [ ! -e .env ]; then
  (umask 077; printf '%s\n' 'SAXO_ENV=sim' 'SAXO_APP_KEY=' 'SAXO_APP_SECRET=' > .env)
fi
chmod 600 .env
```

1. [developer.saxo](https://www.developer.saxo/) で Simulation 用アプリを作成する。
   Grant type は `Code`、Redirect URL は `http://localhost` にする。
   AppKey / AppSecret を `.env` の `SAXO_APP_KEY` / `SAXO_APP_SECRET` に設定する
2. コードを置いた環境で `uv run saxokit login` を実行し、表示された URL をブラウザで開く。
   ログインして Approve を押し、戻り先の URL (`http://localhost/?code=...&state=...`) 全体を
   CLI の入力待ちへ貼る。接続エラーが表示されても、URL に code と state があれば使える
3. `uv run saxokit token` で `OK (sim) UserId=...` が出れば疎通完了

手元の Linux PC でもサーバーでも実行できる。常時稼働が必要になったら VPS へ置く。

## 使い方

```bash
uv run saxokit instruments --keywords USDJPY                 # Uic を調べる
uv run saxokit fetch --uic 42 --symbol usdjpy --horizon 60 --days 365
uv run saxokit backtest --symbol usdjpy --strategy donchian --enter 55 --exit 20 --long-only
uv run saxokit paper --uic 42 --symbol usdjpy --strategies ema9/26 --lot 1000 --leverage 1 --dry-run   # ペーパー 1 サイクル
uv run saxokit web                                           # http://127.0.0.1:8787
uv run pytest -q
```

`backtest` と `paper` は、開始時刻に足の長さを加えた時刻が現在以前の確定足だけを使う。
fetch は取得開始時点で確定した足だけを保存する。バックテストの執行コストは当足の始値
spread_open、旧形式なら前足の終値 spread、それも無ければ設定値の順に使う。
始値の bid/ask はローソク足の集約値で、同一 tick や実約定コストを保証しない。

`paper --dry-run` は口座・市場データを読み取って計画を表示し、発注やファイル更新をしない。
`--symbol` は台帳のキーであり、取引銘柄は `--uic` で指定する。
Web の対象は `src/saxokit/web.py` の `BOOK` を paper の銘柄・戦略と一致させる。

VPS 上のダッシュボードを見る場合は、手元の PC から SSH ポート転送する。

```bash
ssh -L 8787:127.0.0.1:8787 user@example-vps
```

接続後に手元のブラウザで <http://127.0.0.1:8787> を開く。ダッシュボードに認証機能はないため、
既定では VPS の外部インターフェースへ公開しない。LAN などへ意図して公開する場合だけ
`uv run saxokit web --host 0.0.0.0` を指定し、ファイアウォールで接続元を制限する。

## cron による定期実行

```cron
*/10 * * * * cd "$HOME/saxokit" && "$HOME/.local/bin/uv" run saxokit refresh >> data/refresh_log.txt 2>&1
2 * * * *    cd "$HOME/saxokit" && flock -n data/paper.lock "$HOME/.local/bin/uv" run saxokit paper --uic 42 --symbol usdjpy --strategies ema9/26 --lot 1000 --leverage 1 >> data/paper_log.txt 2>&1
4 * * * *    cd "$HOME/saxokit" && flock -n data/paper.lock "$HOME/.local/bin/uv" run saxokit journal >> data/paper_log.txt 2>&1
```

cron の引数は dry-run で確認したものと同じにする。`--leverage` を省略すると既定の 5 倍で新規数量を計算する。
`crontab -e` で上の行を登録する。先に `mkdir -p data` を実行し、各コマンドを手動で確認する。
`command -v flock` でコマンドの存在を確認する。上の paper / journal は同じロックを使い、前の処理が動いていればその回をスキップする。ロックを使わない手動実行は先に cron を止め、処理終了を確認してから行う。
`uv` を別の場所へ導入した場合は実行パスを変更する。停止時は `crontab -e` で対象行をコメントアウトする。

`refresh` は refresh token で新しいトークンを取得し `.env` を書き換える。有効期間は API 応答値を
ログへ表示する。上の 10 分間隔は運用例であり、refresh が拒否された場合は `login` をやり直す。
ダッシュボードの常駐は `deploy/` の systemd unit を参照。

## 注意

- このキットの発注と口座リセットは Simulation 環境専用。live 環境への書き込みには対応しない
- `reset` の利用可否は Simulation 口座と認証情報の権限による。拒否された場合はアプリ設定と権限を確認する
- 収益を保証するものではない。同梱の戦略は教科書的なもので、パラメータ・銘柄の検証は利用者の責任
- `.env` と `data/` はコミットしない(`.gitignore` 済み)

## ライセンス

MIT
