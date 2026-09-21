import { Account } from "./components/Account";
import { EquityChart } from "./components/EquityChart";
import { Alerts, Header } from "./components/Header";
import { Ledger } from "./components/Ledger";
import { LogPane } from "./components/LogPane";
import { Positions } from "./components/Positions";
import { BandLabel } from "./components/Primitives";
import { useStatus } from "./hooks/useStatus";
import { useTheme } from "./hooks/useTheme";

export default function App() {
  const [theme, setTheme] = useTheme();
  // サーバー側キャッシュは 30 秒。15 秒間隔で十分に追従できる
  const { data, receivedAt, failure, loading, slow, refresh } = useStatus(15_000, 15_000);
  // データの時刻はサーバーが組み立てた時刻(now_ms)。無ければ受信時刻で代用する
  const dataAt = data ? (data.now_ms ?? receivedAt) : null;
  const stale = failure !== null && data !== null;
  const failed = failure !== null;
  const ready = data !== null;

  return (
    <div className="min-h-screen bg-(--bg) text-(--fg)">
      <div className="surface-board border-b border-(--line) bg-(--bg-deep)">
        <Header
          env={data?.env ?? null}
          dataAt={dataAt}
          hasData={ready}
          loading={loading}
          failure={failure}
          slow={slow}
          apiError={Boolean(data?.error)}
          theme={theme}
          onTheme={setTheme}
          onRefresh={refresh}
        />
      </div>
      <main>
        <div className="surface-board border-b border-(--line) bg-(--bg-deep)">
          <div className="mx-auto max-w-[1200px] px-4 pt-2 pb-9 sm:px-5">
            <Alerts data={data} failure={failure} slow={slow} dataAt={dataAt} receivedAt={receivedAt} />
            <BandLabel kanji="時価" text="口座評価と建玉。いまの気配による未確定の評価です" />
            <div className="grid items-start gap-x-3.5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
              <Account data={data} stale={stale} failed={failed} />
              <Positions data={data} failed={failed} />
            </div>
          </div>
        </div>
        <div className="mx-auto max-w-[1200px] px-4 pt-7 pb-12 sm:px-5">
          <BandLabel kanji="記録" text="資産推移・台帳・実行ログ。ファイルに残っている記録です" />
          <EquityChart equity={data?.equity ?? []} nowMs={dataAt} ready={ready} failed={failed} />
          <Ledger trades={data?.trades ?? []} ready={ready} failed={failed} />
          <LogPane log={data?.log ?? []} ready={ready} failed={failed} />
          <footer className="mt-8 border-t border-(--line) pt-4 text-[11px] leading-[1.8] text-(--fg-dim)">
            定期実行の状態は、実行ログの時刻と内容を確認してください。
          </footer>
        </div>
      </main>
    </div>
  );
}
