import { useEffect, useState } from "react";

export type ThemePref = "system" | "light" | "dark";
const KEY = "saxokit.theme";
const MQ = "(prefers-color-scheme: dark)";

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function apply(pref: ThemePref): void {
  const dark = pref === "dark" || (pref === "system" && window.matchMedia(MQ).matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

/**
 * 配色の選択。"system" は端末設定に追従し、設定変更にも即時追従する。
 * 選択は localStorage に保存(index.html の先読みスクリプトが描画前に同じ規則で適用する)。
 */
export function useTheme(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(readPref);
  useEffect(() => {
    apply(pref);
    try {
      if (pref === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, pref);
    } catch {
      /* 保存不可の環境では選択をセッション内に留める */
    }
    if (pref !== "system") return;
    const mq = window.matchMedia(MQ);
    const on = () => apply("system");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [pref]);
  return [pref, setPref];
}
