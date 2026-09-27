/**
 * データの読み込み。サーバーは無く、GitHub Actions が毎日書き出した暗号化済みの
 * ファイル（data/*.bin）を読んで、ブラウザの中で復号する。
 *
 *   鍵   = PBKDF2-HMAC-SHA256(合言葉, salt, meta.iterations 回) → AES-256-GCM
 *   ファイル = [IV 12バイト][暗号文＋認証タグ]。復号すると gzip した JSON
 *
 * 合言葉から鍵を作るのはスマホで1〜2秒かかるので、作った鍵は（希望すれば）端末に保存し、
 * 次からは合言葉なしで開く。合言葉を変えたら保存済みの鍵では開けなくなり、入力画面に戻る。
 *
 * ランキングの絞り込み・検索・ウォッチリストは、全銘柄の最新値（latest）から画面側で作る。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  Home,
  MarketResponse,
  RankingResponse,
  SignalGroup,
  SignalStats,
  SignalsResponse,
  StockDetail,
  StockRow,
  VerifyResponse,
} from "./types";
import { watchlist } from "./watch";

const DATA = "./data/";
const KEY_STORE = "m_key_v1";

interface Meta {
  v: number;
  built: string;
  salt: string;
  iterations: number;
  check: string;
}

/** 合言葉が必要（まだ入れていない・保存した鍵が合わない）。画面は入力欄を出す */
export class LockedError extends Error {}

const lockListeners = new Set<() => void>();
/** どこかの読み込みで合言葉が必要になったら呼ばれる（App が入力画面に切り替える） */
export function onLocked(f: () => void): () => void {
  lockListeners.add(f);
  return () => lockListeners.delete(f);
}
/** その銘柄のデータが無い */
export class NotFoundError extends Error {}

export function cryptoAvailable(): boolean {
  return typeof crypto !== "undefined" && !!crypto.subtle && typeof DecompressionStream !== "undefined";
}

/* ---------------- 復号 ---------------- */

function fromB64(s: string): Uint8Array<ArrayBuffer> {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function toB64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

async function openBlob(buf: ArrayBuffer, key: CryptoKey): Promise<unknown> {
  const iv = new Uint8Array(buf.slice(0, 12));
  const packed = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, buf.slice(12));
  const stream = new Blob([packed]).stream().pipeThrough(new DecompressionStream("gzip"));
  return JSON.parse(await new Response(stream).text());
}

let metaPromise: Promise<Meta> | null = null;
let keyPromise: Promise<CryptoKey> | null = null;

function loadMeta(): Promise<Meta> {
  if (!metaPromise) {
    metaPromise = fetch(`${DATA}meta.json`, { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(`データの目次を読めませんでした（HTTP ${r.status}）`);
      return r.json() as Promise<Meta>;
    });
    metaPromise.catch(() => (metaPromise = null));
  }
  return metaPromise;
}

async function keyFromRaw(raw: ArrayBuffer, meta: Meta): Promise<CryptoKey> {
  const key = await crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["decrypt"]);
  await openBlob(fromB64(meta.check).buffer as ArrayBuffer, key); // 違う鍵ならここで失敗する
  return key;
}

async function savedKey(meta: Meta): Promise<CryptoKey> {
  let saved: { salt: string; iter: number; key: string } | null = null;
  try {
    saved = JSON.parse(localStorage.getItem(KEY_STORE) || "null");
  } catch {
    saved = null;
  }
  if (!saved || saved.salt !== meta.salt || saved.iter !== meta.iterations) throw new LockedError();
  try {
    return await keyFromRaw(fromB64(saved.key).buffer as ArrayBuffer, meta);
  } catch {
    throw new LockedError("保存していた鍵では開けませんでした（合言葉が変わった可能性）");
  }
}

function getKey(): Promise<CryptoKey> {
  if (!keyPromise) {
    keyPromise = loadMeta().then(savedKey);
    keyPromise.catch(() => (keyPromise = null));
  }
  return keyPromise;
}

/** 保存済みの鍵で開けるか（起動時）。 */
export async function isUnlocked(): Promise<boolean> {
  try {
    await getKey();
    return true;
  } catch (e) {
    if (e instanceof LockedError) return false;
    throw e;
  }
}

/** 合言葉で開く。remember なら作った鍵を端末に保存する。 */
export async function unlock(passphrase: string, remember: boolean): Promise<void> {
  const meta = await loadMeta();
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(passphrase), "PBKDF2", false, ["deriveBits"]);
  const raw = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: fromB64(meta.salt), iterations: meta.iterations },
    base,
    256,
  );
  let key: CryptoKey;
  try {
    key = await keyFromRaw(raw, meta);
  } catch {
    throw new LockedError("合言葉が違います");
  }
  if (remember) {
    try {
      localStorage.setItem(KEY_STORE, JSON.stringify({ salt: meta.salt, iter: meta.iterations, key: toB64(raw) }));
    } catch {
      /* 保存できなくても今回は開ける */
    }
  }
  keyPromise = Promise.resolve(key);
}

/** この端末から鍵を消す（次回は合言葉が必要） */
export function forgetKey() {
  try {
    localStorage.removeItem(KEY_STORE);
  } catch {
    /* 無視 */
  }
  keyPromise = null;
  invalidate();
}

/* ---------------- 読み込みとキャッシュ ---------------- */

const pending = new Map<string, Promise<unknown>>();
const resolved = new Map<string, unknown>();

/** 画面の切り替えのたびに読み直さないよう、同じ版のデータは使い回す。 */
async function load<T>(name: string): Promise<T> {
  const meta = await loadMeta();
  const k = `${meta.built}|${name}`;
  let p = pending.get(k);
  if (!p) {
    p = (async () => {
      const key = await getKey();
      const r = await fetch(`${DATA}${name}.bin`, { cache: "no-cache" });
      if (r.status === 404) throw new NotFoundError(`${name} のデータがありません`);
      if (!r.ok) throw new Error(`データを読めませんでした（HTTP ${r.status}）`);
      const buf = await r.arrayBuffer();
      try {
        return await openBlob(buf, key);
      } catch {
        throw new LockedError("データを開けませんでした（合言葉が変わった可能性）");
      }
    })();
    pending.set(k, p);
    p.catch(() => pending.delete(k));
  }
  return p as Promise<T>;
}

export function invalidate(prefix = "") {
  if (!prefix) {
    pending.clear();
    resolved.clear();
    metaPromise = null;
    return;
  }
  for (const k of resolved.keys()) if (k.startsWith(prefix)) resolved.delete(k);
}

export function peek<T>(key: string): T | undefined {
  return resolved.get(key) as T | undefined;
}

/* ---------------- 全銘柄の最新値 ---------------- */

interface LatestDoc {
  as_of: string;
  universe: number;
  columns: string[];
  rows: unknown[][];
  missing: [string, string | null, string | null][];
}

interface Latest {
  as_of: string;
  universe: number;
  rows: StockRow[];
  byCode: Map<string, StockRow>;
  missing: StockRow[];
}

let latestCache: { built: string; value: Promise<Latest> } | null = null;

async function latest(): Promise<Latest> {
  const meta = await loadMeta();
  if (!latestCache || latestCache.built !== meta.built) {
    const value = load<LatestDoc>("latest").then((doc) => {
      const rows = doc.rows.map((a) => {
        const o: Record<string, unknown> = { universe: doc.universe };
        doc.columns.forEach((c, i) => (o[c] = a[i]));
        return o as unknown as StockRow;
      });
      const missing = doc.missing.map(
        ([code, name, segment]) => ({ code, name, segment, missing: true }) as unknown as StockRow,
      );
      return { as_of: doc.as_of, universe: doc.universe, rows, byCode: new Map(rows.map((r) => [r.code, r])), missing };
    });
    latestCache = { built: meta.built, value };
    value.catch(() => (latestCache = null));
  }
  return latestCache.value;
}

function watchRows(l: Latest): StockRow[] {
  return watchlist().map(
    (code) => l.byCode.get(code) ?? ({ code, name: null, missing: true } as unknown as StockRow),
  );
}

/** 全角英数を半角にそろえて比べる（銘柄名は「ＮＴＴ」「ＪＸ金属」のように全角が多い） */
function norm(s: string): string {
  return s.normalize("NFKC").toLowerCase();
}

/* ---------------- 画面ごとの問い合わせ ---------------- */

type HomeDoc = Omit<Home, "watchlist">;

interface SignalsDoc {
  as_of: string;
  dates: string[];
  events: Record<string, [string, string, boolean][]>;
  stats: Record<string, SignalStats>;
  defs: { key: string; label: string; tone: "up" | "warn"; rule: string }[];
}

export const paths = {
  home: "home",
  ranking: (segment: string, minTurnover: number, limit: number) => `ranking|${segment}|${minTurnover}|${limit}`,
  stock: (code: string) => `stock|${code}`,
  signals: (date?: string) => `signals|${date ?? ""}`,
  market: "market",
  verify: "verify",
};

export const api = {
  async home(): Promise<Home> {
    const [h, l] = await Promise.all([load<HomeDoc>("home"), latest()]);
    return { ...h, watchlist: watchRows(l) };
  },

  async ranking(segment: string, minTurnover: number, limit: number): Promise<RankingResponse> {
    const l = await latest();
    const hits = l.rows
      .filter((r) => r.base && r.score != null && (r.turnover20 ?? 0) >= minTurnover && (!segment || r.segment === segment))
      .sort((a, b) => (b.t ?? -1e9) - (a.t ?? -1e9));
    return { as_of: l.as_of, count: hits.length, items: hits.slice(0, limit) };
  },

  async stock(code: string): Promise<StockDetail> {
    const d = await load<StockDetail>(`stocks/${code}`);
    return { ...d, watched: watchlist().includes(code) };
  },

  async signals(date?: string): Promise<SignalsResponse> {
    const [s, l] = await Promise.all([load<SignalsDoc>("signals"), latest()]);
    const target = date && s.events[date] ? date : s.dates[0];
    const today = s.events[target] ?? [];
    const groups: SignalGroup[] = s.defs.map((d) => {
      const items = today
        .filter(([, key]) => key === d.key)
        .map(([code]) => l.byCode.get(code))
        .filter((r): r is StockRow => !!r)
        .sort((a, b) => Number(!a.liquid) - Number(!b.liquid) || (b.score ?? 0) - (a.score ?? 0));
      return { ...d, count: items.length, items, stats: s.stats[d.key] ?? null };
    });
    return { as_of: s.as_of, date: target, dates: s.dates, total: today.length, groups };
  },

  market: () => load<MarketResponse>("market"),
  verify: () => load<VerifyResponse>("verify"),

  async search(q: string): Promise<{ items: StockRow[] }> {
    const l = await latest();
    const query = norm(q.trim());
    if (!query) return { items: [] };
    const scoreOf = (r: StockRow) => {
      const code = norm(r.code);
      if (code === query) return 0;
      if (code.startsWith(query)) return 1;
      return norm(r.name ?? "").includes(query) ? 2 : 9;
    };
    const items = [...l.rows, ...l.missing]
      .map((r) => [scoreOf(r), r] as const)
      .filter(([s]) => s < 9)
      .sort((a, b) => a[0] - b[0] || a[1].code.localeCompare(b[1].code))
      .slice(0, 20)
      .map(([, r]) => r);
    return { items };
  },

  /** 設定画面用: いま見ているデータの版 */
  async status(): Promise<{ built: string; as_of: string; universe: number; stocks: number }> {
    const [meta, l] = await Promise.all([loadMeta(), latest()]);
    return { built: meta.built, as_of: l.as_of, universe: l.universe, stocks: l.rows.length };
  },
};

/** 取得中は前回の表示を残す（画面がちらつかないように）。 */
export function useData<T>(key: string, fetcher: () => Promise<T>) {
  const [data, setData] = useState<T | undefined>(() => peek<T>(key));
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const reload = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcherRef
      .current()
      .then((d) => {
        resolved.set(key, d);
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (e instanceof LockedError) lockListeners.forEach((f) => f());
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [key]);

  useEffect(() => {
    setData(peek<T>(key));
    return reload();
  }, [key, reload]);

  return { data, error, loading, reload };
}
