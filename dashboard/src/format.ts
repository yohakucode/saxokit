// 表示用フォーマッタ。null / 非有限値は必ず "—" に落とし、0 は有効な値として表示する。

export const DASH = "—";
export type Tone = "up" | "down" | "flat";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

const nf0 = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 });
const nfQty = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 2 });
const nfPrice = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 5 });

/** 絶対値を整形し、丸めた結果が 0 でないときだけ負号を付ける("−0" を出さない)。 */
function signedAbs(v: number, nf: Intl.NumberFormat, prefix = ""): string {
  const s = nf.format(Math.abs(v));
  return (v < 0 && /[1-9]/.test(s) ? "−" : "") + prefix + s;
}

export function yen(v: number | null | undefined): string {
  return isNum(v) ? signedAbs(v, nf0, "¥") : DASH;
}

export function qty(v: number | null | undefined): string {
  return isNum(v) ? signedAbs(v, nfQty) : DASH;
}

export function price(v: number | null | undefined): string {
  return isNum(v) ? signedAbs(v, nfPrice) : DASH;
}

export function count(v: number | null | undefined): string {
  return isNum(v) ? nf0.format(v) : DASH;
}

/** 0〜1 の比率を % 表示にする(勝率用)。 */
export function ratioPct(v: number | null | undefined): string {
  return isNum(v) ? `${Math.round(v * 100)}%` : DASH;
}

export interface SignedParts {
  tone: Tone;
  sign: string;
  abs: string;
}

function parts(v: number, abs: string): SignedParts {
  if (!/[1-9]/.test(abs)) return { tone: "flat", sign: "±", abs };
  return v > 0 ? { tone: "up", sign: "+", abs } : { tone: "down", sign: "−", abs };
}

export function signParts(v: number | null | undefined): SignedParts | null {
  return isNum(v) ? parts(v, nf0.format(Math.abs(v))) : null;
}

/** v はすでに % 単位。 */
export function pctParts(v: number | null | undefined): SignedParts | null {
  return isNum(v) ? parts(v, `${Math.abs(v).toFixed(2)}%`) : null;
}

/** 台帳 CSV の数値列。空文字や数値でない文字列は null。 */
export function parseCsvNumber(s: string): number | null {
  const t = s.replace(/,/g, "").trim();
  if (t === "") return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}

/** ISO 時刻をミリ秒へ。タイムゾーン指定が無ければ UTC とみなす(台帳は UTC 記録)。 */
export function parseTs(s: string): number | null {
  const t = s.trim().replace(/(\.\d{3})\d+/, "$1");
  if (t === "") return null;
  const isoLike = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(t);
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/i.test(t);
  const ms = Date.parse(isoLike && !hasZone ? `${t.replace(" ", "T")}Z` : t);
  return Number.isFinite(ms) ? ms : null;
}

const TZ = "Asia/Tokyo";
const fClock = new Intl.DateTimeFormat("ja-JP", {
  timeZone: TZ,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});
const fDateTime = new Intl.DateTimeFormat("ja-JP", {
  timeZone: TZ,
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const fFull = new Intl.DateTimeFormat("ja-JP", {
  timeZone: TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const fMonthDay = new Intl.DateTimeFormat("ja-JP", { timeZone: TZ, month: "2-digit", day: "2-digit" });

function fmtTime(f: Intl.DateTimeFormat, ms: number | null | undefined): string {
  return isNum(ms) && Math.abs(ms) <= 8.64e15 ? f.format(ms) : DASH;
}

export const jstClock = (ms: number | null | undefined) => fmtTime(fClock, ms);
export const jstDateTime = (ms: number | null | undefined) => fmtTime(fDateTime, ms);
export const jstFull = (ms: number | null | undefined) => fmtTime(fFull, ms);
export const jstMonthDay = (ms: number | null | undefined) => fmtTime(fMonthDay, ms);

/** 経過時間の言い回し("3 分前")。 */
export function ageText(diffMs: number): string {
  if (!isNum(diffMs)) return DASH;
  const s = Math.floor(Math.max(0, diffMs) / 1000);
  if (s < 60) return `${s} 秒前`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} 分前`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} 時間前`;
  return `${Math.floor(h / 24)} 日前`;
}
