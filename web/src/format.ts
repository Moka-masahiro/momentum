/** 数値の表示。null は「—」。 */

export function num(v: number | null | undefined, digits = 0): string {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v.toLocaleString("ja-JP", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  // 負号は全角のマイナス（−）にそろえる（signed / pct と同じ見た目にする）
  return s.charAt(0) === "-" ? `−${s.slice(1)}` : s;
}

export function signed(v: number | null | undefined, digits = 1, suffix = ""): string {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v > 0 ? "+" : v < 0 ? "−" : "±";
  return `${s}${num(Math.abs(v), digits)}${suffix}`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  return signed(v, digits, "%");
}

/** 株価。1万円以上や整数は小数なし、それ以外は必要な桁だけ。 */
export function yen(v: number | null | undefined): string {
  if (v == null) return "—";
  const digits = Number.isInteger(v) || v >= 10000 ? 0 : v >= 100 ? 1 : 2;
  return `¥${num(v, digits)}`;
}

/** チャートの価格軸。1,000以上は整数・カンマ区切り、それ未満は必要な桁だけ。 */
export function axisPrice(p: number): string {
  const a = Math.abs(p);
  const digits = a >= 1000 ? 0 : a >= 100 ? (Number.isInteger(p) ? 0 : 1) : a >= 10 ? 1 : 2;
  return p.toLocaleString("ja-JP", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** 売買代金などの大きな金額。 */
export function yenLarge(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1e12) return `${num(v / 1e12, 1)}兆円`;
  if (v >= 1e8) return `${num(v / 1e8, v >= 1e10 ? 0 : 1)}億円`;
  if (v >= 1e4) return `${num(v / 1e4, 0)}万円`;
  return `${num(v)}円`;
}

/** 日本式の色分け（上昇=赤 / 下落=青）。 */
export function deltaClass(v: number | null | undefined): string {
  if (v == null || v === 0) return "t-muted";
  return v > 0 ? "t-up" : "t-down";
}

export function mdDate(s: string | null | undefined): string {
  if (!s) return "";
  const [, m, d] = s.split("-");
  return `${Number(m)}/${Number(d)}`;
}

export function slashDate(s: string | null | undefined): string {
  return s ? s.replace(/-/g, "/") : "";
}
