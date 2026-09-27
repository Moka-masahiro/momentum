/**
 * ウォッチリスト。サーバーが無いので、この端末（ブラウザ）の中にだけ保存する。
 * 外には送らないので他人には見えないが、PCとスマホでは別々のリストになる。
 */
const KEY = "m_watchlist_v1";
const listeners = new Set<() => void>();

export function watchlist(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function save(codes: string[]) {
  const uniq = Array.from(new Set(codes)).sort();
  try {
    localStorage.setItem(KEY, JSON.stringify(uniq));
  } catch {
    /* プライベートブラウズ等で保存できない場合 */
  }
  listeners.forEach((f) => f());
}

export function setWatched(code: string, on: boolean) {
  const list = watchlist().filter((c) => c !== code);
  save(on ? [...list, code] : list);
}

/** まとめて追加（設定画面）。銘柄コードらしいもの（4桁の英数字）だけ拾う。戻り値は追加した数 */
export function addMany(text: string): number {
  const found = (text.normalize("NFKC").toUpperCase().match(/\b[0-9][0-9A-Z]{3}\b/g) ?? []);
  const before = new Set(watchlist());
  const added = found.filter((c) => !before.has(c));
  save([...before, ...added]);
  return new Set(added).size;
}

export function onWatchChange(f: () => void): () => void {
  listeners.add(f);
  return () => listeners.delete(f);
}
