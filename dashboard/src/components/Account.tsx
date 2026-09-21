import type { Status } from "../api";
import { count, DASH, ratioPct, yen } from "../format";
import { Chip, Empty, Field, Pnl, SectionHead } from "./Primitives";

function AccountBody({ data, stale }: { data: Status; stale: boolean }) {
  const partial = data.error !== null;
  return (
    <div className="px-4 pt-3.5 pb-4">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-(--fg-dim)">
        <span>口座評価額 円換算</span>
        {stale && <Chip kind="warn">前回取得分</Chip>}
        {partial && data.balance !== null && <Chip kind="warn">エラー発生時の部分データ</Chip>}
      </div>
      <div className="num mt-1.5 text-[30px] leading-none font-medium sm:text-[40px]">{yen(data.balance)}</div>
      <div className="num mt-2 text-[11px] text-(--fg-mute)">
        {data.balance === null ? (
          <span className="font-sans">{partial ? "Saxo API のエラーにより取得できていません" : "口座評価額は未取得です"}</span>
        ) : (
          <>
            <span className="font-sans">口座通貨建て</span> <span className="text-(--fg)">{data.balance_raw ?? DASH}</span>
          </>
        )}
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-3 border-t border-(--line-soft) pt-3.5 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
        <Field label="含み損益 概算">
          <Pnl v={data.unrealized_jpy} className="text-[14px] font-medium" />
        </Field>
        <Field label="実現損益 台帳">
          <Pnl v={data.stats?.realized_jpy} className="text-[14px] font-medium" />
        </Field>
        <Field label="決済数 台帳">
          <span className="text-[14px]">{count(data.stats?.n)}</span>
        </Field>
        <Field label="勝率 台帳">
          <span className="text-[14px]">{ratioPct(data.stats?.win_rate)}</span>
        </Field>
      </dl>
      <p className="mt-3.5 text-[11px] leading-[1.7] text-(--fg-dim)">
        損益は円換算の概算です。台帳の記録価格と現在の気配から計算し、入出金を含む口座評価額の増減とは一致しません。
      </p>
    </div>
  );
}

export function Account({ data, stale, failed }: { data: Status | null; stale: boolean; failed: boolean }) {
  return (
    <section aria-label="口座評価">
      <SectionHead title="口座評価" />
      <div className="rounded-lg border border-(--line) bg-(--panel)">
        {data ? (
          <AccountBody data={data} stale={stale} />
        ) : (
          <Empty>{failed ? "データを取得できていません。取得できるまで数値は表示しません" : "読み込み中…"}</Empty>
        )}
      </div>
    </section>
  );
}
