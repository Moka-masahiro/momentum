import { useEffect, type ReactNode } from "react";
import { deltaClass, num, pct, signed } from "../format";
import type { Rank, Session, Why } from "../types";

/* ---------- アイコン（線画。currentColor で色を継ぐ） ---------- */

const P = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const s = { width: size, height: size, viewBox: "0 0 24 24", "aria-hidden": true } as const;
  switch (name) {
    case "home":
      return <svg {...s}><path {...P} d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z" /></svg>;
    case "search":
      return <svg {...s}><circle {...P} cx="11" cy="11" r="6.5" /><path {...P} d="M16 16l4.5 4.5" /></svg>;
    case "back":
      return <svg {...s}><path {...P} d="M15 5l-7 7 7 7" /></svg>;
    case "chev":
      return <svg {...s}><path {...P} d="M9 6l6 6-6 6" /></svg>;
    case "star":
      return <svg {...s}><path {...P} d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" /></svg>;
    case "star-fill":
      return <svg {...s}><path fill="currentColor" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" /></svg>;
    case "info":
      return <svg {...s}><circle {...P} cx="12" cy="12" r="8.5" /><path {...P} d="M12 11v5M12 7.6v.2" /></svg>;
    case "bars":
      return <svg {...s}><path {...P} d="M5 20V11M10 20V6M15 20v-7M20 20V9" /></svg>;
    case "trend":
      return <svg {...s}><path {...P} d="M3 17l6-6 4 4 8-8" /><path {...P} d="M15 7h6v6" /></svg>;
    case "bolt":
      return <svg {...s}><path {...P} d="M13 3L5 13.5h6L10 21l8-10.5h-6z" /></svg>;
    case "eye":
      return <svg {...s}><path {...P} d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle {...P} cx="12" cy="12" r="3" /></svg>;
    case "gear":
      return <svg {...s}><circle {...P} cx="12" cy="12" r="3" /><path {...P} d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>;
    case "guide":
      return <svg {...s}><circle {...P} cx="12" cy="12" r="8.5" /><path {...P} d="M15.5 8.5l-2 5-5 2 2-5z" /></svg>;
    case "warn":
      return <svg {...s}><path {...P} d="M12 4l9 16H3z" /><path {...P} d="M12 10v4M12 17v.2" /></svg>;
    case "check":
      return <svg {...s}><path {...P} d="M5 12.5l4.5 4.5L19 7.5" /></svg>;
    case "close":
      return <svg {...s}><path {...P} d="M6 6l12 12M18 6L6 18" /></svg>;
    case "flask":
      return <svg {...s}><path {...P} d="M9 3h6M10 3v6l-5.5 9.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3" /><path {...P} d="M7.5 15h9" /></svg>;
    case "pulse":
      return <svg {...s}><path {...P} d="M3 12h4l2.5-6 5 12 2.5-6h4" /></svg>;
    default:
      return null;
  }
}

/* ---------- ランク ---------- */

export function RankBadge({ rank, large = false }: { rank: Rank | null | undefined; large?: boolean }) {
  return (
    <span className={`rank ${large ? "rank-lg" : ""} ${rank ? `rank-${rank}` : "rank-none"}`} aria-label={rank ? `ランク${rank}` : "ランクなし"}>
      {rank ?? "—"}
    </span>
  );
}

export const RANK_COLOR: Record<string, string> = {
  S: "#ffab8c",
  A: "#ff8968",
  B: "#e77052",
  C: "#bd5d45",
  D: "#934c3a",
};

export function rankOf(score: number | null | undefined): Rank | null {
  if (score == null) return null;
  if (score >= 85) return "S";
  if (score >= 70) return "A";
  if (score >= 55) return "B";
  if (score >= 40) return "C";
  return "D";
}

/* ---------- 値動きの理由 ---------- */

export const WHY_LABEL: Record<Why, string> = {
  news: "ニュース",
  supply: "需給",
  market: "地合い",
  unknown: "材料不明",
};

/** 値動きの理由のラベル。理由の無い日（目立った動きが無い）は何も出さない */
export function WhyChip({ why, className = "" }: { why: Why | null | undefined; className?: string }) {
  if (!why || !WHY_LABEL[why]) return null;
  return <span className={`why why-${why} ${className}`}>{WHY_LABEL[why]}</span>;
}

/** 一覧の2行目に添える理由（ラベルと短い文言。文言は長ければ省略） */
export function WhyNote({ row, text = true }: { row: { why?: Why | null; why_text?: string | null }; text?: boolean }) {
  if (!row.why) return null;
  return (
    <>
      <WhyChip why={row.why} />
      {text && row.why_text && <span className="why-text">{row.why_text}</span>}
    </>
  );
}

/* ---------- データの時点（昼の実行） ---------- */

export const SESSION_LABEL: Record<Session, string> = { close: "", am: "前場", intraday: "取引中" };

/** 昼の実行のデータなら「前場」などの印を出す（大引け後のデータは何も出さない） */
export function SessionBadge({ session }: { session: Session | undefined }) {
  if (!session || session === "close") return null;
  return <span className="chip chip-warn !text-[11px] !py-0.5 !px-2">{SESSION_LABEL[session]}</span>;
}

/** 途中経過のデータであることの案内 */
export function SessionNote({ session, className = "" }: { session: Session | undefined; className?: string }) {
  if (!session || session === "close") return null;
  return (
    <p className={`note t-warn ${className}`}>
      {session === "am"
        ? "前場（11:30）までの途中経過です。当日の株価は前場の終値、出来高は前場の分だけ（ふだん1日の約半分）。17時過ぎに大引けのデータに置き換わります。"
        : "取引時間中の途中経過です。当日の株価と出来高は途中の値で、17時過ぎに大引けのデータに置き換わります。"}
    </p>
  );
}

/* ---------- 数値 ---------- */

export function Delta({ v, digits = 1, suffix = "%" }: { v: number | null | undefined; digits?: number; suffix?: string }) {
  return <span className={`${deltaClass(v)} num`}>{suffix === "%" ? pct(v, digits) : signed(v, digits, suffix)}</span>;
}

export function Score({ score, rank }: { score: number | null | undefined; rank: Rank | null | undefined }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="text-[18px] font-bold num">{num(score)}</span>
      <RankBadge rank={rank} />
    </span>
  );
}

/* ---------- カード ---------- */

export function Card({
  title,
  icon,
  link,
  onLink,
  aside,
  sub,
  guide,
  children,
  className = "",
}: {
  title?: ReactNode;
  icon?: string;
  link?: string;
  onLink?: () => void;
  aside?: ReactNode;       // 見出しの右に置く、押せない補足（件数など）
  sub?: ReactNode;
  guide?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`} data-guide={guide}>
      {(title || link || aside) && (
        <div className="card-head">
          <div className="card-title">
            {icon && <Icon name={icon} size={20} />}
            {title}
          </div>
          {link && (
            <button className="card-link" onClick={onLink}>
              {link}
              <Icon name="chev" size={16} />
            </button>
          )}
          {aside && <span className="text-[13px] t-2 font-semibold whitespace-nowrap">{aside}</span>}
        </div>
      )}
      {sub && <div className="card-sub">{sub}</div>}
      {children}
    </section>
  );
}

export function Loading({ label = "読み込み中…", slow = false }: { label?: string; slow?: boolean }) {
  return (
    <div className="card">
      <div className="loading-bar mb-3" />
      <div className="t-2 text-sm">{label}</div>
      {slow && (
        <div className="note mt-2">
          初めて開くときは、全銘柄（約3,700）の最新値の読み込みと復号に数秒かかります。
        </div>
      )}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card" role="alert">
      <div className="flex items-center gap-2 t-warn font-bold">
        <Icon name="warn" size={18} />
        読み込めませんでした
      </div>
      <div className="t-2 text-sm mt-2 break-all">{message}</div>
      <div className="note mt-2">
        電波の状態を確認してください。データは平日の夕方に GitHub で作り直しており、その直後の数分はつながらないことがあります。
      </div>
      {onRetry && (
        <button className="btn-ghost mt-3" onClick={onRetry}>
          もう一度読み込む
        </button>
      )}
    </div>
  );
}

/* ---------- シート ---------- */

export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title?: ReactNode; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className="sheet-backdrop" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true">
        <div className="sheet-grip" />
        <div className="flex items-center justify-between mb-2">
          <div className="text-[16px] font-bold">{title}</div>
          <button className="btn-ghost !h-9 !px-3 text-sm" onClick={onClose}>
            閉じる
          </button>
        </div>
        {children}
      </div>
    </>
  );
}

export function Seg<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="seg" role="tablist">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={o.value === value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Disclaimer() {
  return (
    <p className="note mt-4 px-1">
      価格は yfinance（無料・非公式）の日足で、リアルタイムではありません。指標とシグナルは決まったルールで機械的に計算した参考情報で、売買の推奨ではありません。実績の数字は過去約2年分の日足による検証結果で、将来も同じになるとは限りません。値動きの理由は、会社の適時開示（やのしん TDnet WEB-API 経由）と JPX の公表データから機械的に付けた手がかりで、原因の証明ではありません。データは平日の夕方に GitHub Actions が自動で作り直しています。
      チャート: <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer" className="underline">TradingView Lightweight Charts™</a>
    </p>
  );
}
