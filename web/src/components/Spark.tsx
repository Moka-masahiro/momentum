import type { Series } from "../types";

/** 小さな推移線（ホームの地合いカード用）。最新の点だけ強調する。 */
export default function Spark({ series, width = 120, height = 34, color = "#4fc8ee", domain }: { series: Series; width?: number; height?: number; color?: string; domain?: [number, number] }) {
  const vals = series.values.filter((v): v is number => v != null);
  if (vals.length < 2) return null;
  const lo = domain ? domain[0] : Math.min(...vals);
  const hi = domain ? domain[1] : Math.max(...vals);
  const span = hi - lo || 1;
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * (width - 6) + 3, height - 3 - ((v - lo) / span) * (height - 6)]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" opacity={0.85} />
      <circle cx={last[0]} cy={last[1]} r={3} fill={color} stroke="#0f2530" strokeWidth={1.5} />
    </svg>
  );
}
