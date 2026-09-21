import { useEffect, useMemo, useRef, useState } from "react";
import { Empty, SectionHead, Segmented, type SegOption } from "./Primitives";

type Mode = "all" | "issues";
const MODES: SegOption<Mode>[] = [
  { key: "all", label: "すべて" },
  { key: "issues", label: "要確認" },
];

// 旧画面と同じ語に警告系を足したもの。行の意味までは解釈しない
const ISSUE = /401|エラー|Error|Traceback|不明|拒否|失敗|警告|WARN/i;

export function LogPane({ log, ready, failed }: { log: string[]; ready: boolean; failed: boolean }) {
  const [mode, setMode] = useState<Mode>("all");
  const box = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => log.map((text) => ({ text, issue: ISSUE.test(text) })), [log]);
  const issues = lines.filter((l) => l.issue).length;
  const shown = mode === "issues" ? lines.filter((l) => l.issue) : lines;
  const tail = log.length > 0 ? log[log.length - 1] : "";

  // 新しい行が届いたら末尾へ送る
  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [tail, log.length, mode]);

  return (
    <section aria-label="実行ログ">
      <SectionHead title="実行ログ" meta={ready ? `${log.length} 行 うち要確認 ${issues} 行` : undefined}>
        <Segmented value={mode} options={MODES} onChange={setMode} label="ログの絞り込み" />
      </SectionHead>
      <div
        ref={box}
        tabIndex={0}
        role="region"
        aria-label="実行ログの本文"
        className="max-h-[320px] overflow-auto rounded-lg border border-(--line) bg-(--panel) py-2"
      >
        {!ready ? (
          <Empty>{failed ? "データを取得できていません" : "読み込み中…"}</Empty>
        ) : log.length === 0 ? (
          <Empty>ログがありません。paper の初回実行後に data/paper_log.txt の末尾を表示します</Empty>
        ) : shown.length === 0 ? (
          <Empty>要確認に当たる行はありません</Empty>
        ) : (
          // 行は React のテキストノードとして描くので、ログ中の HTML は実行されない
          <div className="num w-max min-w-full text-[11px] leading-[1.8]">
            {shown.map((l, i) => (
              <div key={i} className={`flex gap-2 px-3 whitespace-pre ${l.issue ? "bg-(--panel-2) text-(--warn)" : "text-(--fg-mute)"}`}>
                <span className="w-3 shrink-0 text-center font-semibold" aria-hidden="true">
                  {l.issue ? "!" : ""}
                </span>
                {l.issue && <span className="sr-only">要確認</span>}
                <span>{l.text}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
