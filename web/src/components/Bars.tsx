import { pct } from "../format";

interface Bar {
  label: string;
  value: number | null;
}

/**
 * 0を境に上下へ伸びる棒（プラス=赤、マイナス=青。上昇・下落の色と同じ向き）。
 * 数字は最大と最小の棒にだけ付ける（全部に付けると読めない）。全値は表で見られる。
 */
export default function Bars({ bars, height = 120, domain }: { bars: Bar[]; height?: number; domain?: number }) {
  const w = 300;
  const top = 16;
  const bottom = 18;
  const vals = bars.map((b) => b.value ?? 0);
  const m = domain ?? Math.max(0.5, ...vals.map((v) => Math.abs(v)));
  const mid = top + (height - top - bottom) / 2;
  const scale = (height - top - bottom) / 2 / m;
  const bw = w / bars.length;
  const maxI = vals.indexOf(Math.max(...vals));
  const minI = vals.indexOf(Math.min(...vals));
  return (
    <svg viewBox={`0 0 ${w} ${height}`} width="100%" role="img" aria-label={bars.map((b) => `${b.label}: ${pct(b.value, 2)}`).join("、")}>
      <line x1={0} x2={w} y1={mid} y2={mid} stroke="#5f7d8b" strokeWidth={1} />
      {bars.map((b, i) => {
        const v = b.value ?? 0;
        const h = Math.abs(v) * scale;
        const x = i * bw + 3;
        const y = v >= 0 ? mid - h : mid;
        const showLabel = i === maxI || i === minI;
        return (
          <g key={b.label}>
            <rect x={x} y={y} width={bw - 6} height={Math.max(h, 1)} rx={3} fill={v >= 0 ? "#e5534b" : "#4a8fe8"}>
              <title>{`${b.label}: ${pct(b.value, 2)}`}</title>
            </rect>
            {showLabel && (
              <text x={x + (bw - 6) / 2} y={v >= 0 ? y - 4 : y + h + 11} textAnchor="middle" fontSize={10} fill="#eaf4f8">
                {pct(b.value, 1)}
              </text>
            )}
            <text x={x + (bw - 6) / 2} y={height - 4} textAnchor="middle" fontSize={10} fill="#7b98a6">
              {b.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
