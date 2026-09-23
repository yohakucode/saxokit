// GET /api/status の型と正規化。常時返る契約項目は検査し、API エラー時に省略される値だけ null に落とす。

export interface Strategy {
  spec: string;
  signal: number | null;
  held: number | null;
  entry_price: number | null;
  unreal_jpy: number | null;
  unreal_pct: number | null; // すでに % 単位
  realized_jpy: number | null;
  n: number | null;
  wins: number | null;
  mismatch: boolean;
}

export interface Position {
  symbol: string;
  price: number | null;
  market_open: boolean | null;
  amount: number | null; // API のネット建玉
  ledger_mismatch: boolean;
  strategies: Strategy[];
}

/** 台帳 CSV の 1 行。数値列も文字列のまま届く。 */
export interface Trade {
  ts: string;
  symbol: string;
  strategy: string;
  side: string;
  amount: string;
  price: string;
  order_id: string;
  reason: string;
}

export interface EquityPoint {
  t: number; // エポックミリ秒
  v: number; // 口座評価額(円)
}

export interface Stats {
  realized_jpy: number | null;
  n: number | null;
  win_rate: number | null; // 0〜1 の比率
}

export interface Status {
  now_ms: number;
  env: string | null;
  error: string | null;
  balance: number | null;
  currency: string | null;
  balance_raw: string | null;
  positions: Position[];
  log: string[];
  equity: EquityPoint[];
  equity_issues: string[]; // equity.csv の破損行など。空なら問題なし
  trades: Trade[];
  unrealized_jpy: number | null;
  stats: Stats | null;
}

export class HttpError extends Error {
  status: number;
  constructor(status: number) {
    super(`HTTP ${status}`);
    this.status = status;
  }
}

export class PayloadError extends Error {}

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const text = (v: unknown): string => (typeof v === "string" ? v : v === null || v === undefined ? "" : String(v));
const textOrNull = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v : null);
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);

function requiredList(v: unknown, name: string): unknown[] {
  if (!Array.isArray(v)) throw new PayloadError(`${name} は配列ではありません`);
  return v;
}

function requiredNullableText(v: unknown, name: string): string | null {
  if (v !== null && typeof v !== "string") throw new PayloadError(`${name} は文字列または null ではありません`);
  return textOrNull(v);
}

function requiredBoolean(v: unknown, name: string): boolean {
  if (typeof v !== "boolean") throw new PayloadError(`${name} は boolean ではありません`);
  return v;
}

function toStrategy(v: unknown, name: string): Strategy {
  if (!isRec(v)) throw new PayloadError(`${name} はオブジェクトではありません`);
  return {
    spec: text(v.spec),
    signal: num(v.signal),
    held: num(v.held),
    entry_price: num(v.entry_price),
    unreal_jpy: num(v.unreal_jpy),
    unreal_pct: num(v.unreal_pct),
    realized_jpy: num(v.realized_jpy),
    n: num(v.n),
    wins: num(v.wins),
    mismatch: requiredBoolean(v.mismatch, `${name}.mismatch`),
  };
}

function toPosition(v: unknown, index: number): Position {
  const name = `positions[${index}]`;
  if (!isRec(v)) throw new PayloadError(`${name} はオブジェクトではありません`);
  return {
    symbol: text(v.symbol),
    price: num(v.price),
    market_open: bool(v.market_open),
    amount: num(v.amount),
    ledger_mismatch: requiredBoolean(v.ledger_mismatch, `${name}.ledger_mismatch`),
    strategies: requiredList(v.strategies, `${name}.strategies`).map((s, i) => toStrategy(s, `${name}.strategies[${i}]`)),
  };
}

function toTrade(v: unknown): Trade | null {
  if (!isRec(v)) return null;
  return {
    ts: text(v.ts),
    symbol: text(v.symbol),
    strategy: text(v.strategy),
    side: text(v.side),
    amount: text(v.amount),
    price: text(v.price),
    order_id: text(v.order_id),
    reason: text(v.reason),
  };
}

function toEquity(v: unknown): EquityPoint[] {
  const out: EquityPoint[] = [];
  for (const row of list(v)) {
    if (!Array.isArray(row)) continue;
    const t = num(row[0]);
    const val = num(row[1]);
    if (t !== null && val !== null) out.push({ t, v: val });
  }
  return out.sort((a, b) => a.t - b.t);
}

export function normalizeStatus(raw: unknown): Status {
  if (!isRec(raw)) throw new PayloadError("status はオブジェクトではありません");
  const nowMs = num(raw.now_ms);
  if (nowMs === null) throw new PayloadError("now_ms は有限の数値ではありません");
  const positions = requiredList(raw.positions, "positions");
  const trades = requiredList(raw.trades, "trades");
  const equity = requiredList(raw.equity, "equity");
  // 旧バックエンドとの互換性を保ち、項目がある場合は型を検査する
  const equityIssues = raw.equity_issues === undefined ? [] : requiredList(raw.equity_issues, "equity_issues");
  const log = requiredList(raw.log, "log");
  const stats = isRec(raw.stats)
    ? { realized_jpy: num(raw.stats.realized_jpy), n: num(raw.stats.n), win_rate: num(raw.stats.win_rate) }
    : null;
  return {
    now_ms: nowMs,
    env: requiredNullableText(raw.env, "env"),
    error: requiredNullableText(raw.error, "error"),
    balance: num(raw.balance),
    currency: textOrNull(raw.currency),
    balance_raw: textOrNull(raw.balance_raw),
    positions: positions.map(toPosition),
    log: log.map(text),
    equity: toEquity(equity),
    equity_issues: equityIssues.map(text),
    trades: trades
      .map(toTrade)
      .filter((t): t is Trade => t !== null),
    unrealized_jpy: num(raw.unrealized_jpy),
    stats,
  };
}

export async function fetchStatus(signal: AbortSignal): Promise<Status> {
  const res = await fetch("/api/status", { signal, cache: "no-store", headers: { Accept: "application/json" } });
  if (!res.ok) throw new HttpError(res.status);
  let raw: unknown;
  try {
    raw = await res.json();
  } catch (e) {
    if (signal.aborted) throw e;
    throw new PayloadError("JSON として解釈できません");
  }
  return normalizeStatus(raw);
}
