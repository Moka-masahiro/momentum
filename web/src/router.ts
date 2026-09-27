import { useEffect, useState } from "react";

/**
 * URL の # 以降で画面を切り替える（#/ ・ #/stock/5801 ・ #/signals/2026-09-24 …）。
 * サーバー側の設定が要らず、スマホの「戻る」でそのまま前の画面に戻れる。
 *
 * 戻ったときは、前にいたスクロール位置へ戻す（一覧 → 詳細 → 戻る、で先頭に飛ばないように）。
 */
const positions = new Map<string, number>();
let pushing = false;

function current(): string {
  return window.location.hash.replace(/^#\/?/, "");
}

export function go(path: string) {
  pushing = true;
  window.location.hash = `/${path}`;
}

export function back() {
  if (window.history.length > 1) window.history.back();
  else go("");
}

export function useRoute(): string[] {
  const [path, setPath] = useState(current);
  useEffect(() => {
    const onChange = (e: HashChangeEvent) => {
      const oldHash = new URL(e.oldURL).hash.replace(/^#\/?/, "");
      positions.set(oldHash, window.scrollY);
      setPath(current());
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  useEffect(() => {
    const target = pushing ? 0 : positions.get(path) ?? 0;
    pushing = false;
    // 描画が終わってから動かす（データはキャッシュから即座に出るので、ほぼ元の高さになる）
    requestAnimationFrame(() => window.scrollTo(0, target));
  }, [path]);
  return path.split("/").filter(Boolean).map(decodeURIComponent);
}

/** 最近見た銘柄（検索シートに出す）。端末のブラウザにだけ保存する。 */
const RECENT_KEY = "m_recent_stocks";

export function rememberStock(code: string, name: string | null) {
  try {
    const list: { code: string; name: string | null }[] = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    const next = [{ code, name }, ...list.filter((x) => x.code !== code)].slice(0, 8);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* プライベートブラウズ等で保存できなくても動作には影響しない */
  }
}

export function recentStocks(): { code: string; name: string | null }[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
  } catch {
    return [];
  }
}

export function flag(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

export function setFlag(key: string, on = true) {
  try {
    if (on) localStorage.setItem(key, "1");
    else localStorage.removeItem(key);
  } catch {
    /* 同上 */
  }
}
