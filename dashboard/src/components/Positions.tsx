import type { Position, Status, Strategy } from "../api";
import { count, price, qty } from "../format";
import { Chip, Empty, Field, Pct, Pnl, SectionHead } from "./Primitives";

/** 戦略ごとの台帳数量の合計。1 つでも不明なら合計も不明にする。 */
function ledgerSum(p: Position): number | null {
  let sum = 0;
  for (const s of p.strategies) {
    if (s.held === null) return null;
    sum += s.held;
  }
  return sum;
}

function SignalChip({ signal }: { signal: number | null }) {
  if (signal === 1) return <Chip kind="solid">シグナル ロング</Chip>;
  if (signal === 0) return <Chip>シグナル フラット</Chip>;
  return <Chip>シグナル —</Chip>;
}

function StrategyRow({ s }: { s: Strategy }) {
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="num text-[12px] font-semibold tracking-[0.04em]">{s.spec}</span>
        <SignalChip signal={s.signal} />
        {s.mismatch && <Chip kind="warnSolid">シグナルと建玉が不一致</Chip>}
      </div>
      <dl className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-2.5 sm:grid-cols-4">
        <Field label="台帳数量">{qty(s.held)}</Field>
        <Field label="平均建値 台帳">{price(s.entry_price)}</Field>
        <Field label="含み損益 概算">
          <Pnl v={s.unreal_jpy} /> <Pct v={s.unreal_pct} className="text-[11px]" />
        </Field>
        <Field label="実現損益 台帳">
          <Pnl v={s.realized_jpy} />
          <span className="ml-1.5 text-[11px] text-(--fg-mute)">
            {count(s.n)} 決済 {count(s.wins)} 勝
          </span>
        </Field>
      </dl>
    </li>
  );
}

function SymbolCard({ p }: { p: Position }) {
  const sum = ledgerSum(p);
  const diff = sum !== null && p.amount !== null ? sum - p.amount : null;
  const flagged = p.ledger_mismatch || p.strategies.some((s) => s.mismatch);
  return (
    <article aria-label={p.symbol} className={`rounded-lg border bg-(--panel) ${flagged ? "border-(--warn)" : "border-(--line)"}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 border-b border-(--line-soft) px-4 py-2.5">
        <span className="num text-[14px] font-semibold tracking-[0.06em]">{p.symbol}</span>
        <Chip>{p.market_open === null ? "市場 —" : p.market_open ? "市場オープン" : "休場"}</Chip>
        <span className="ml-auto flex items-baseline gap-2">
          <span className="text-[10px] text-(--fg-dim)">{p.market_open === false ? "最終気配" : "現在値"}</span>
          <span className="num text-[22px] leading-none font-medium">{price(p.price)}</span>
        </span>
      </div>
      {/* 照合: API のネット建玉と台帳数量の合計を並べる。判定そのものは API の ledger_mismatch に従う */}
      <dl className={`grid grid-cols-3 gap-x-3 border-b border-(--line-soft) px-4 py-2.5 ${p.ledger_mismatch ? "bg-(--panel-2)" : ""}`}>
        <Field label="API 建玉 ネット">{qty(p.amount)}</Field>
        <Field label="台帳数量の合計">{qty(sum)}</Field>
        <Field label="差 台帳 − API">
          <span className={p.ledger_mismatch ? "font-semibold text-(--warn)" : ""}>{qty(diff)}</span>
          {p.ledger_mismatch && <span className="ml-1.5 font-sans text-[10px] text-(--warn)">要照合</span>}
        </Field>
      </dl>
      {p.strategies.length === 0 ? (
        <Empty>この銘柄に戦略が設定されていません</Empty>
      ) : (
        <ul className="divide-y divide-(--line-soft)">
          {p.strategies.map((s) => (
            <StrategyRow key={s.spec} s={s} />
          ))}
        </ul>
      )}
    </article>
  );
}

export function Positions({ data, failed }: { data: Status | null; failed: boolean }) {
  const n = data ? data.positions.length : 0;
  return (
    <section aria-label="銘柄と建玉">
      <SectionHead title="銘柄と建玉" meta={data ? `${n} 銘柄` : undefined} />
      {n > 0 && data ? (
        <div className="grid gap-3.5">
          {data.error !== null && <p className="text-[11px] text-(--warn)">エラー発生までに取得できた銘柄だけを表示しています。</p>}
          {data.positions.map((p) => (
            <SymbolCard key={p.symbol} p={p} />
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-(--line) bg-(--panel)">
          <Empty>
            {!data
              ? failed
                ? "データを取得できていません"
                : "読み込み中…"
              : data.error !== null
                ? "Saxo API のエラーにより、建玉と現在値を取得できていません"
                : "監視する銘柄が設定されていません。saxokit の web.py にある BOOK を確認してください"}
          </Empty>
        </div>
      )}
    </section>
  );
}
