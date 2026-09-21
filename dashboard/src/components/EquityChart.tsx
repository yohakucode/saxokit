import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import type { EquityPoint } from "../api";
import { jstDateTime, jstFull, jstMonthDay, signParts, yen } from "../format";
import { Empty, SectionHead, Segmented, type SegOption } from "./Primitives";

type RangeKey = "7d" | "30d" | "all";
const RANGES: SegOption<RangeKey>[] = [
  { key: "7d", label: "7日" },
  { key: "30d", label: "30日" },
  { key: "all", label: "全期間" },
];
const DAY = 86_400_000;
const H = 250;
const M = { l: 72, r: 18, t: 24, b: 28 };
const TIP_W = 200;
const TICK_CHAR_W = 7;
const TICK_GAP = 18;

function niceStep(span: number, n: number): number {
  const raw = span / n;
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
}

/** 値が一定・負・1 点だけでも有限な軸になるよう余白を取る。 */
function buildScale(pts: EquityPoint[]) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of pts) {
    if (p.v < lo) lo = p.v;
    if (p.v > hi) hi = p.v;
  }
  const pad = (hi - lo) * 0.1 || Math.max(Math.abs(hi) * 0.001, 1);
  const step = niceStep(hi - lo + pad * 2, 4);
  const y0 = Math.floor((lo - pad) / step) * step;
  let y1 = Math.ceil((hi + pad) / step) * step;
  if (!(y1 > y0)) y1 = y0 + step;
  const n = Math.min(12, Math.max(1, Math.round((y1 - y0) / step)));
  const ticks = Array.from({ length: n + 1 }, (_, i) => {
    const v = y0 + i * step;
    return Math.abs(v) < step * 1e-6 ? 0 : v;
  });
  return { x0: pts[0].t, x1: pts[pts.length - 1].t, y0, y1, step, ticks };
}

function Plot({ pts, w }: { pts: EquityPoint[]; w: number }) {
  const [hi, setHi] = useState<number | null>(null);
  const sc = useMemo(() => buildScale(pts), [pts]);
  const last = pts.length - 1;
  const idx = hi !== null && hi <= last ? hi : null;
  const digits = sc.step >= 1 ? 0 : Math.min(4, Math.ceil(-Math.log10(sc.step)));
  const tickNf = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const tickLabel = (v: number) => (v < 0 ? "−" : "") + tickNf.format(Math.abs(v));
  // 等幅フォントの最大目盛り幅を確保し、大きな評価額でも先頭桁を SVG 外へ出さない
  const left = Math.max(M.l, ...sc.ticks.map((v) => [...tickLabel(v)].length * TICK_CHAR_W + TICK_GAP));
  const plotW = w - left - M.r;
  const plotH = H - M.t - M.b;
  // 記録時刻が 1 種類しかなければ中央に置く
  const X = (t: number) => (sc.x1 > sc.x0 ? left + ((t - sc.x0) / (sc.x1 - sc.x0)) * plotW : left + plotW / 2);
  const Y = (v: number) => H - M.b - ((v - sc.y0) / (sc.y1 - sc.y0)) * plotH;

  const xTicks = sc.x1 > sc.x0 ? [sc.x0, (sc.x0 + sc.x1) / 2, sc.x1] : [sc.x0];
  const xLabel = sc.x1 - sc.x0 < 3 * DAY ? jstDateTime : jstMonthDay;

  const line = pts.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)} ${Y(p.v).toFixed(1)}`).join(" ");
  const first = pts[0];
  const end = pts[last];
  const endRight = X(end.t) > w - 120;

  const pick = (e: ReactPointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0) return;
    const mx = ((e.clientX - r.left) / r.width) * w;
    let best = 0;
    let bd = Infinity;
    pts.forEach((p, i) => {
      const d = Math.abs(X(p.t) - mx);
      if (d < bd) {
        bd = d;
        best = i;
      }
    });
    setHi(best);
  };
  const onKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowLeft") setHi((h) => Math.max(0, (h ?? last) - 1));
    else if (e.key === "ArrowRight") setHi((h) => Math.min(last, (h ?? -1) + 1));
    else if (e.key === "Home") setHi(0);
    else if (e.key === "End") setHi(last);
    else if (e.key === "Escape") setHi(null);
    else return;
    e.preventDefault();
  };

  const sel = idx !== null ? pts[idx] : null;
  let tipLeft = 0;
  if (sel) {
    const hx = X(sel.t);
    tipLeft = hx + 12 + TIP_W > w ? hx - 12 - TIP_W : hx + 12;
    tipLeft = Math.max(4, tipLeft);
  }
  const delta = sel ? signParts(sel.v - first.v) : null;

  return (
    <div
      className="relative rounded-lg"
      role="group"
      tabIndex={0}
      aria-label="口座評価額の推移グラフ。左右の矢印キーで記録点を移動し、Esc で閉じます"
      onKeyDown={onKey}
      onFocus={() => setHi((h) => h ?? last)}
      onBlur={() => setHi(null)}
    >
      <p className="sr-only">
        記録 {pts.length} 点。最初は {jstFull(first.t)} の {yen(first.v)}、最新は {jstFull(end.t)} の {yen(end.v)}。
      </p>
      <svg
        viewBox={`0 0 ${w} ${H}`}
        width={w}
        height={H}
        aria-hidden="true"
        className="block w-full touch-pan-y select-none"
        onPointerMove={pick}
        onPointerDown={pick}
        onPointerLeave={(e) => {
          if (e.pointerType === "mouse") setHi(null);
        }}
      >
        {sc.ticks.map((v) => (
          <g key={v}>
            <line x1={left} x2={w - M.r} y1={Y(v)} y2={Y(v)} stroke={v === 0 ? "var(--fg-dim)" : "var(--line-soft)"} strokeWidth={1} />
            <text x={left - 10} y={Y(v) + 3.5} textAnchor="end" fontSize={10} fill="var(--fg-dim)" className="num">
              {tickLabel(v)}
            </text>
          </g>
        ))}
        {xTicks.map((t, i) => (
          <text
            key={i}
            className={`num ${w < 480 && i === 1 ? "hidden" : ""}`}
            x={X(t)}
            y={H - 8}
            textAnchor={xTicks.length === 1 ? "middle" : i === 0 ? "start" : i === 2 ? "end" : "middle"}
            fontSize={10}
            fill="var(--fg-dim)"
          >
            {xLabel(t)}
          </text>
        ))}
        {pts.length > 1 && <path d={line} fill="none" stroke="var(--ink-line)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
        {sel && (
          <>
            <line x1={X(sel.t)} x2={X(sel.t)} y1={M.t} y2={H - M.b} stroke="var(--fg-mute)" strokeWidth={1} />
            <circle cx={X(sel.t)} cy={Y(sel.v)} r={4.5} fill="var(--fg)" stroke="var(--panel)" strokeWidth={2} />
          </>
        )}
        <circle cx={X(end.t)} cy={Y(end.v)} r={4.5} fill="var(--ink-line)" stroke="var(--panel)" strokeWidth={2} />
        <text
          x={endRight ? X(end.t) - 9 : X(end.t) + 9}
          y={Y(end.v) - 11}
          textAnchor={endRight ? "end" : "start"}
          fontSize={12}
          fontWeight={600}
          fill="var(--fg)"
          stroke="var(--panel)"
          strokeWidth={3}
          paintOrder="stroke"
          className="num"
        >
          {yen(end.v)}
        </text>
      </svg>
      {sel && (
        <div
          role="status"
          className="num pointer-events-none absolute top-2 z-10 rounded-md border border-(--line) bg-(--panel) px-2.5 py-1.5 text-[11px] leading-[1.7]"
          style={{ left: tipLeft, width: TIP_W }}
        >
          <div className="text-(--fg-mute)">{jstFull(sel.t)} JST</div>
          <div className="text-[12px] font-semibold">{yen(sel.v)}</div>
          {/* 入出金も含む評価額の増減なので、損益色は付けない */}
          <div className="text-(--fg-mute)">
            <span className="font-sans">表示期間の始点比</span> {delta ? `${delta.sign}${delta.abs}` : "—"}
          </div>
        </div>
      )}
    </div>
  );
}

/** 口座全体の評価額を、記録された時刻どおりに描く。戦略の損益ではない。 */
export function EquityChart({ equity, nowMs, ready, failed }: { equity: EquityPoint[]; nowMs: number | null; ready: boolean; failed: boolean }) {
  const [range, setRange] = useState<RangeKey>("30d");
  const [w, setW] = useState(720);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const box = entries[0];
      if (box) setW(Math.max(280, Math.floor(box.contentRect.width)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pts = useMemo(() => {
    if (range === "all" || equity.length === 0) return equity;
    const anchor = nowMs ?? equity[equity.length - 1].t;
    const from = anchor - (range === "7d" ? 7 : 30) * DAY;
    return equity.filter((p) => p.t >= from);
  }, [equity, range, nowMs]);

  return (
    <section aria-label="口座評価額の推移">
      <SectionHead title="口座評価額の推移" meta={ready ? `${pts.length} 点` : undefined}>
        <Segmented value={range} options={RANGES} onChange={setRange} label="表示期間" />
      </SectionHead>
      <div className="rounded-lg border border-(--line) bg-(--panel)">
        <div ref={wrap}>
          {!ready ? (
            <Empty>{failed ? "データを取得できていません" : "読み込み中…"}</Empty>
          ) : equity.length === 0 ? (
            <Empty>評価額の記録がまだありません。data/equity.csv に記録がたまると表示します</Empty>
          ) : pts.length === 0 ? (
            <Empty>この期間の記録はありません。「全期間」に切り替えると過去の記録を確認できます</Empty>
          ) : (
            <Plot key={range} pts={pts} w={w} />
          )}
        </div>
        {ready && pts.length > 0 && (
          <p className="border-t border-(--line-soft) px-4 py-2.5 text-[11px] leading-[1.7] text-(--fg-dim)">
            {pts.length === 1 ? "記録は 1 点だけです。" : `${jstDateTime(pts[0].t)} から ${jstDateTime(pts[pts.length - 1].t)} までの記録です。`}
            口座全体の評価額で、入出金も増減に含まれます。戦略ごとの損益ではありません。
          </p>
        )}
      </div>
    </section>
  );
}
