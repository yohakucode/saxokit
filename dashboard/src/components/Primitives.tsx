import type { ReactNode } from "react";
import { pctParts, signParts, type Tone } from "../format";

const toneCls: Record<Tone, string> = {
  up: "text-(--up)",
  down: "text-(--down)",
  flat: "text-(--fg-dim)",
};

/** 符号付き損益(JPY)。利益 = 朱、損失 = 青、常に符号併記。null・非有限は "—"。 */
export function Pnl({ v, className = "" }: { v: number | null | undefined; className?: string }) {
  const p = signParts(v);
  if (!p) return <span className={`num text-(--fg-dim) ${className}`}>—</span>;
  return (
    <span className={`num ${toneCls[p.tone]} ${className}`}>
      {p.sign}
      {p.abs}
    </span>
  );
}

/** 符号付き %。値が無ければ何も描かない。 */
export function Pct({ v, className = "" }: { v: number | null | undefined; className?: string }) {
  const p = pctParts(v);
  if (!p) return null;
  return (
    <span className={`num ${toneCls[p.tone]} ${className}`}>
      {p.sign}
      {p.abs}
    </span>
  );
}

export type ChipKind = "line" | "solid" | "warn" | "warnSolid";

const chipCls: Record<ChipKind, string> = {
  line: "border border-(--line) text-(--fg-mute)",
  solid: "border border-(--fg) bg-(--fg) text-(--bg) font-semibold",
  warn: "border border-(--warn) text-(--warn)",
  warnSolid: "border border-(--warn) bg-(--warn) text-(--panel) font-semibold",
};

export function Chip({ kind = "line", children }: { kind?: ChipKind; children: ReactNode }) {
  return (
    <span
      className={`num inline-block rounded-[4px] px-1.5 py-px text-[10px] leading-[16px] tracking-[0.04em] whitespace-nowrap ${chipCls[kind]}`}
    >
      {children}
    </span>
  );
}

/** 帯の見出し。上段 = 時価、下段 = 記録 という区分そのものを伝える。 */
export function BandLabel({ kanji, text }: { kanji: string; text: string }) {
  return (
    <h2 className="flex flex-wrap items-baseline gap-x-3 text-[11px] font-normal text-(--fg-dim)">
      <span className="text-[12px] font-medium tracking-[0.3em] text-(--fg-mute)">{kanji}</span>
      <span>{text}</span>
    </h2>
  );
}

export function SectionHead({ title, meta, children }: { title: string; meta?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mt-6 mb-3 flex items-center gap-3">
      <h3 className="text-[13px] font-medium tracking-[0.04em]">{title}</h3>
      {meta !== undefined && <span className="num text-[11px] text-(--fg-dim)">{meta}</span>}
      <span className="h-px min-w-4 flex-1 bg-(--line)" aria-hidden="true" />
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-7 text-center text-[12px] leading-[1.7] text-(--fg-dim)">{children}</div>;
}

/** 定義リストの 1 項目(小さな見出し + 値)。 */
export function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] text-(--fg-dim)">{label}</dt>
      <dd className="num mt-0.5 text-[12px]">{children}</dd>
    </div>
  );
}

export interface SegOption<T extends string> {
  key: T;
  label: string;
}

/** セグメント切替。期間・ログ絞り込み・配色で同じ見た目と同じ操作にする。 */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: SegOption<T>[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="flex shrink-0 rounded-md border border-(--line) bg-(--panel)" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          aria-pressed={value === o.key}
          onClick={() => onChange(o.key)}
          className={`num h-[30px] border-r border-(--line) px-2.5 text-[11px] tracking-[0.04em] first:rounded-l-[5px] last:rounded-r-[5px] last:border-r-0 focus-visible:relative focus-visible:z-10 sm:h-[26px] ${
            value === o.key ? "bg-(--fg) font-semibold text-(--bg)" : "text-(--fg-mute) hover:bg-(--panel-2)"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
