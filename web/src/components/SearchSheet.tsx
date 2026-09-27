import { useEffect, useRef, useState } from "react";
import { api } from "../data";
import { num } from "../format";
import { go, recentStocks } from "../router";
import type { StockRow } from "../types";
import { Icon, RankBadge, Sheet } from "./ui";

export default function SearchSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<StockRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 60);
  }, [open]);

  useEffect(() => {
    const query = q.trim();
    if (!query) {
      setItems([]);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      setBusy(true);
      setErr(null);
      try {
        const r = await api.search(query);
        if (!cancelled) setItems(r.items);
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      } finally {
        if (!cancelled) setBusy(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q]);

  const open_ = (code: string) => {
    onClose();
    go(`stock/${code}`);
  };
  const recent = open && !q.trim() ? recentStocks() : [];

  return (
    <Sheet open={open} onClose={onClose} title="銘柄検索">
      <div className="flex items-center gap-2 tile !py-2">
        <span className="t-3"><Icon name="search" size={18} /></span>
        <input
          ref={input}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="会社名の一部 または 銘柄コード"
          className="flex-1 bg-transparent outline-none text-[16px] t-1 placeholder:text-[#7b98a6]"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
        />
        {q && (
          <button className="t-3" onClick={() => setQ("")} aria-label="消す"><Icon name="close" size={16} /></button>
        )}
      </div>
      {busy && <div className="loading-bar mt-2" />}
      {err && <p className="t-warn text-[13px] mt-2">{err}</p>}
      <div className="mt-2 min-h-[40vh]">
        {items.map((r) => (
          <button key={r.code} className="list-row" style={{ gridTemplateColumns: "1fr auto 40px" }} onClick={() => open_(r.code)}>
            <span className="list-name"><b>{r.name}</b><small>{r.code} · {r.segment ?? "—"}{r.missing ? " · 日足なし" : ""}</small></span>
            <span className="text-right text-[16px] font-bold num">{r.missing ? "" : num(r.score)}</span>
            <span className="text-center">{!r.missing && <RankBadge rank={r.rank} />}</span>
          </button>
        ))}
        {q.trim() && !busy && items.length === 0 && !err && <p className="note mt-3">見つかりませんでした。</p>}
        {recent.length > 0 && (
          <>
            <div className="note mt-2 mb-1">最近見た銘柄</div>
            {recent.map((r) => (
              <button key={r.code} className="list-row" style={{ gridTemplateColumns: "1fr 20px" }} onClick={() => open_(r.code)}>
                <span className="list-name"><b>{r.name ?? r.code}</b><small>{r.code}</small></span>
                <span className="t-3"><Icon name="chev" size={16} /></span>
              </button>
            ))}
          </>
        )}
      </div>
    </Sheet>
  );
}
