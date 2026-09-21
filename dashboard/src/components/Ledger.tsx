import { useMemo, useState } from "react";
import type { Trade } from "../api";
import { DASH, jstDateTime, parseCsvNumber, parseTs, price, qty } from "../format";
import { Chip, Empty, SectionHead } from "./Primitives";

type RowKind = "netted" | "reconcile" | null;

/** paper が台帳へ記録する専用の注文 ID で、発注を伴わない行を識別する。 */
function rowKind(t: Trade): RowKind {
  if (t.order_id === "netted") return "netted";
  if (t.order_id === "reconcile") return "reconcile";
  return null;
}

function SideChip({ side }: { side: string }) {
  // 売買の別に損益色は使わない(朱・青は損益専用)
  if (side === "Buy") return <Chip kind="solid">買い</Chip>;
  if (side === "Sell") return <Chip>売り</Chip>;
  return <span>{side || DASH}</span>;
}

function Row({ t }: { t: Trade }) {
  const kind = rowKind(t);
  const px = parseCsvNumber(t.price);
  return (
    <tr className={kind ? "bg-(--panel-2)" : ""}>
      <td className="l text-(--fg-mute)" title={t.ts}>
        {jstDateTime(parseTs(t.ts))}
      </td>
      <td className="l">{t.symbol ? t.symbol.toUpperCase() : DASH}</td>
      <td className="l">{t.strategy || DASH}</td>
      <td className="l">
        <SideChip side={t.side} />
      </td>
      <td>{qty(parseCsvNumber(t.amount))}</td>
      <td>{px !== null ? price(px) : t.price.trim() || DASH}</td>
      <td className="l jp min-w-[240px] whitespace-normal text-(--fg-mute)">
        {kind === "reconcile" && (
          <span className="mr-1.5">
            <Chip kind="warn">照合調整</Chip>
          </span>
        )}
        {kind === "netted" && (
          <span className="mr-1.5">
            <Chip kind="warn">相殺 発注なし</Chip>
          </span>
        )}
        {t.reason || DASH}
      </td>
    </tr>
  );
}

export function Ledger({ trades, ready, failed }: { trades: Trade[]; ready: boolean; failed: boolean }) {
  const [symbol, setSymbol] = useState("");
  const [q, setQ] = useState("");
  const symbols = useMemo(() => [...new Set(trades.map((t) => t.symbol.toUpperCase()).filter(Boolean))].sort(), [trades]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return trades.filter((t) => {
      if (symbol && t.symbol.toUpperCase() !== symbol) return false;
      if (!needle) return true;
      return [t.symbol, t.strategy, t.side, t.reason, t.order_id, t.ts].join(" ").toLowerCase().includes(needle);
    });
  }, [trades, symbol, q]);
  const filtered = symbol !== "" || q.trim() !== "";

  return (
    <section aria-label="台帳">
      <SectionHead title="台帳 直近 50 件" meta={ready ? (filtered ? `${rows.length} / ${trades.length} 件` : `${trades.length} 件`) : undefined} />
      <p className="mb-3 max-w-[80ch] text-[11px] leading-[1.7] text-(--fg-dim)">
        台帳の価格は発注時の気配による概算です。実際の約定結果は saxokit journal または証券会社の取引報告書で確認してください。
      </p>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-[11px] text-(--fg-mute)">
          銘柄
          <select className="ctl" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            <option value="">すべて</option>
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-1 items-center gap-1.5 text-[11px] text-(--fg-mute) sm:flex-none">
          <span className="shrink-0">検索</span>
          <input
            type="search"
            className="ctl w-full min-w-0 sm:w-[260px]"
            placeholder="戦略・理由・注文 ID"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        {filtered && (
          <button
            type="button"
            className="ctl font-sans hover:bg-(--panel-2)"
            onClick={() => {
              setSymbol("");
              setQ("");
            }}
          >
            絞り込みを解除
          </button>
        )}
      </div>
      <div className="max-h-[440px] overflow-auto rounded-lg border border-(--line) bg-(--panel)" tabIndex={0} role="region" aria-label="台帳の表">
        {!ready ? (
          <Empty>{failed ? "データを取得できていません" : "読み込み中…"}</Empty>
        ) : trades.length === 0 ? (
          <Empty>台帳に売買の記録がありません。最初の発注が記録されると、戦略と理由つきで表示します</Empty>
        ) : rows.length === 0 ? (
          <Empty>条件に合う行がありません</Empty>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th className="l">時刻 JST</th>
                <th className="l">銘柄</th>
                <th className="l">戦略</th>
                <th className="l">売買</th>
                <th>数量</th>
                <th>価格 概算</th>
                <th className="l">理由</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t, i) => (
                <Row key={`${i}:${t.ts}:${t.order_id}`} t={t} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
