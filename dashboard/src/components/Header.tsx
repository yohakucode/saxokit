import { useEffect, useState, type ReactNode } from "react";
import type { Status } from "../api";
import { ageText, jstClock, qty } from "../format";
import type { Failure } from "../hooks/useStatus";
import type { ThemePref } from "../hooks/useTheme";
import { Chip, Segmented, type SegOption } from "./Primitives";

const THEMES: SegOption<ThemePref>[] = [
  { key: "system", label: "自動" },
  { key: "light", label: "ライト" },
  { key: "dark", label: "ダーク" },
];

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

function Clock() {
  const now = useNow(1000);
  return <span>{jstClock(now)} JST</span>;
}

function EnvChip({ env }: { env: string | null }) {
  if (env === null) return <Chip>環境 —</Chip>;
  const name = env.toUpperCase();
  // SIM 以外(実口座)は塗りつぶして目立たせる
  return <Chip kind={name === "SIM" ? "line" : "solid"}>{name} 環境</Chip>;
}

export function Header({
  env,
  dataAt,
  hasData,
  loading,
  failure,
  slow,
  apiError,
  theme,
  onTheme,
  onRefresh,
}: {
  env: string | null;
  dataAt: number | null;
  hasData: boolean;
  loading: boolean;
  failure: Failure | null;
  slow: boolean;
  apiError: boolean;
  theme: ThemePref;
  onTheme: (t: ThemePref) => void;
  onRefresh: () => void;
}) {
  // HTTP が成功しただけではボットの稼働は分からないので、ここでは「データ更新」だけを伝える
  let status: ReactNode;
  if (slow) {
    status = <span className="text-(--warn)">{hasData ? `応答待ち 最終データ ${jstClock(dataAt)}` : "応答待ち データ未取得"}</span>;
  } else if (failure) {
    status = (
      <span className="text-(--warn)">{hasData ? `接続エラー 最終データ ${jstClock(dataAt)}` : "接続エラー データ未取得"}</span>
    );
  } else if (!hasData) {
    status = "初回読み込み中…";
  } else {
    status = (
      <>
        データ更新 {jstClock(dataAt)}
        {apiError && <span className="ml-2 text-(--warn)">API エラーあり</span>}
      </>
    );
  }
  return (
    <header className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-4 pb-3 sm:px-5">
      <h1 className="num text-[15px] font-semibold tracking-[0.16em]">saxokit</h1>
      <div className="text-[13px] text-(--fg-mute)">運用モニター</div>
      <EnvChip env={env} />
      <div className="num ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-(--fg-mute)">
        <Clock />
        <span role="status">{status}</span>
      </div>
      <button
        type="button"
        className="ctl inline-flex items-center gap-1.5 hover:bg-(--panel-2) aria-disabled:opacity-60"
        aria-disabled={loading}
        onClick={() => {
          if (!loading) onRefresh();
        }}
      >
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" />
          <path d="M13.5 2.5v3h-3" />
        </svg>
        <span className="font-sans">{loading ? "更新中…" : "今すぐ更新"}</span>
      </button>
      <Segmented value={theme} options={THEMES} onChange={onTheme} label="配色" />
    </header>
  );
}

function Alert({ title, tag, live, children }: { title: string; tag: string; live: "alert" | "status"; children: ReactNode }) {
  return (
    <section role={live} className="rounded-lg border border-(--warn) bg-(--panel) px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--warn)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M8 1.8 15 14H1L8 1.8Z" />
          <path d="M8 6.5v3.5M8 12.1v.1" />
        </svg>
        <h2 className="text-[13px] font-medium">{title}</h2>
        <Chip kind="warnSolid">{tag}</Chip>
      </div>
      <div className="mt-1.5 max-w-[78ch] text-[12px] leading-[1.8] text-(--fg-mute)">{children}</div>
    </section>
  );
}

function failureReason(f: Failure): string {
  switch (f.kind) {
    case "http":
      return `サーバーが HTTP ${f.status} を返しました。saxokit web を起動した端末の出力を確認してください。`;
    case "payload":
      return "応答を解釈できませんでした。saxokit 本体とダッシュボードのビルドが同じ版か確認してください。";
    default:
      return "saxokit web に接続できません。プロセスが起動しているか、SSH ポート転送が切れていないか確認してください。";
  }
}

function Age({ since }: { since: number | null }) {
  const now = useNow(5000);
  return <>{since === null ? "—" : ageText(now - since)}</>;
}

const Code = ({ children }: { children: ReactNode }) => (
  <code className="num rounded-[4px] border border-(--line) bg-(--panel-2) px-1 text-[11px] text-(--fg)">{children}</code>
);

/** 取得失敗・API エラー・照合差を画面の最上部にまとめて出す。 */
export function Alerts({
  data,
  failure,
  slow,
  dataAt,
  receivedAt,
}: {
  data: Status | null;
  failure: Failure | null;
  slow: boolean;
  dataAt: number | null;
  receivedAt: number | null;
}) {
  const ledgerDiffs = data ? data.positions.filter((p) => p.ledger_mismatch) : [];
  const signalDiffs = data
    ? data.positions.flatMap((p) => p.strategies.filter((s) => s.mismatch).map((s) => ({ symbol: p.symbol, spec: s.spec })))
    : [];
  // 401 / SAXO_TOKEN のときだけ再認証を案内する
  const auth = data?.error ? /401|SAXO_TOKEN/.test(data.error) : false;
  if (!failure && !slow && !data?.error && ledgerDiffs.length === 0 && signalDiffs.length === 0) return null;

  return (
    <div className="mb-5 grid gap-2.5">
      {slow && (
        <Alert live="status" tag="取得中" title="取得に時間がかかっています">
          <p>応答を待っています。</p>
          {data && <p>表示中の内容は前回取得分です。新しい応答を受け取るまで更新しません。</p>}
        </Alert>
      )}
      {failure && (
        <Alert live="alert" tag="取得失敗" title={data ? "新しいデータを取得できません" : "データを取得できません"}>
          <p>{failureReason(failure)}</p>
          <p>
            {data ? (
              <>
                表示中の内容は <span className="num text-(--fg)">{jstClock(dataAt)}</span> 時点の最終取得データです(
                <Age since={receivedAt} />
                に取得)。最新の状況ではありません。
              </>
            ) : (
              "取得できるまで数値は表示しません。"
            )}
            15 秒ごとに自動で再試行します。
          </p>
        </Alert>
      )}
      {data?.error && (
        <Alert live="alert" tag={auth ? "認証エラー" : "API エラー"} title={auth ? "Saxo API の認証に失敗しています" : "Saxo API からの取得でエラーが発生しています"}>
          <p className="num text-[11px] break-words text-(--fg)">{data.error}</p>
          {auth ? (
            <p>
              <Code>saxokit refresh</Code> を実行してください。拒否された場合は <Code>saxokit login</Code> で認証をやり直します。
            </p>
          ) : (
            <p>エラー内容と saxokit の設定、ネットワークを確認してください。次回の取得で自動的に再試行されます。</p>
          )}
          <p>口座評価額・建玉・損益の集計は取得できた分だけを表示します。資産推移・台帳・実行ログはローカルの記録から表示しています。</p>
        </Alert>
      )}
      {(ledgerDiffs.length > 0 || signalDiffs.length > 0) && (
        <Alert live="status" tag="照合差" title="台帳と建玉に差があります">
          <ul className="grid gap-0.5">
            {ledgerDiffs.map((p) => (
              <li key={`l:${p.symbol}`}>
                <span className="num text-(--fg)">{p.symbol}</span> 台帳数量の合計と API 建玉(
                <span className="num">{qty(p.amount)}</span>)が一致しません。口座の注文・建玉と実行ログを確認してください。
              </li>
            ))}
            {signalDiffs.map((s) => (
              <li key={`s:${s.symbol}:${s.spec}`}>
                <span className="num text-(--fg)">
                  {s.symbol} {s.spec}
                </span>{" "}
                シグナルと台帳の建玉が一致しません。発注の失敗や、トークン失効中の取り残しがないか実行ログを確認してください。
              </li>
            ))}
          </ul>
        </Alert>
      )}
    </div>
  );
}
