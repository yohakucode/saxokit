import { useCallback, useEffect, useRef, useState } from "react";
import { fetchStatus, HttpError, PayloadError, type Status } from "../api";

export type Failure =
  | { kind: "http"; status: number }
  | { kind: "network" }
  | { kind: "payload" };

export interface StatusState {
  /** 最後に取得できたスナップショット。取得失敗では消さない */
  data: Status | null;
  /** data を受け取ったブラウザ側の時刻 */
  receivedAt: number | null;
  /** 直近の取得が失敗していればその理由。成功で null に戻る */
  failure: Failure | null;
  loading: boolean;
  /** 同じリクエストの応答を 15 秒以上待っている */
  slow: boolean;
}

function toFailure(e: unknown): Failure {
  if (e instanceof HttpError) return { kind: "http", status: e.status };
  if (e instanceof PayloadError) return { kind: "payload" };
  return { kind: "network" };
}

/**
 * /api/status の定期取得。前回の完了を待ってから次を予約するので取得は重ならない。
 * タブが隠れている間は取得せず、表示に戻った時点で取り直す。
 */
export function useStatus(intervalMs = 15_000, slowMs = 15_000): StatusState & { refresh: () => void } {
  const [state, setState] = useState<StatusState>({ data: null, receivedAt: null, failure: null, loading: true, slow: false });
  const runRef = useRef<() => void>(() => {});

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    let slowTimer: number | undefined;
    let inflight: AbortController | null = null;

    const schedule = () => {
      window.clearTimeout(timer);
      if (!disposed) timer = window.setTimeout(() => void run(), intervalMs);
    };

    const run = async (): Promise<void> => {
      if (disposed || inflight) return; // 多重取得しない
      if (document.visibilityState === "hidden") {
        schedule();
        return;
      }
      window.clearTimeout(timer);
      const ac = new AbortController();
      inflight = ac;
      slowTimer = window.setTimeout(() => {
        if (!disposed && inflight === ac) setState((s) => ({ ...s, slow: true }));
      }, slowMs);
      setState((s) => ({ ...s, loading: true, slow: false }));
      try {
        const data = await fetchStatus(ac.signal);
        if (!disposed) setState({ data, receivedAt: Date.now(), failure: null, loading: false, slow: false });
      } catch (e) {
        // 最後に取得できたスナップショットは残し、失敗理由だけを更新する
        if (!disposed) setState((s) => ({ ...s, failure: toFailure(e), loading: false, slow: false }));
      } finally {
        window.clearTimeout(slowTimer);
        inflight = null;
        schedule();
      }
    };

    runRef.current = () => void run();
    const onVisible = () => {
      if (document.visibilityState === "visible") void run();
    };
    document.addEventListener("visibilitychange", onVisible);
    void run();

    return () => {
      disposed = true;
      window.clearTimeout(timer);
      window.clearTimeout(slowTimer);
      document.removeEventListener("visibilitychange", onVisible);
      const ac = inflight as AbortController | null;
      if (ac) ac.abort();
    };
  }, [intervalMs, slowMs]);

  const refresh = useCallback(() => runRef.current(), []);
  return { ...state, refresh };
}
