import { num } from "../format";

interface Axis {
  key: string;
  label: string;
  value: number | null;
}

/** 5角形（0〜100、外側ほど強い）。値の無い軸は中心に置き、ラベルに「—」を出す。 */
export default function Radar({ axes, size = 240 }: { axes: Axis[]; size?: number }) {
  const cx = size / 2;
  const cy = size / 2 + 6;
  const r = size * 0.33;
  const n = axes.length;
  const pt = (i: number, v: number) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return [cx + Math.cos(a) * r * (v / 100), cy + Math.sin(a) * r * (v / 100)] as const;
  };
  const ring = (v: number) => axes.map((_, i) => pt(i, v).join(",")).join(" ");
  const poly = axes.map((a, i) => pt(i, Math.max(0, Math.min(100, a.value ?? 0))).join(",")).join(" ");

  const pad = 34; // 左右のラベル（「安定度」など）が切れないための余白
  return (
    <svg viewBox={`${-pad} 0 ${size + pad * 2} ${size + 8}`} width="100%" style={{ maxWidth: size + pad * 2 }} role="img" aria-label={axes.map((a) => `${a.label} ${num(a.value)}`).join("、")}>
      {[25, 50, 75, 100].map((v) => (
        <polygon key={v} points={ring(v)} fill="none" stroke={v === 50 ? "#3b6070" : "#1f3d4a"} strokeWidth={1} />
      ))}
      {axes.map((_, i) => {
        const [x, y] = pt(i, 100);
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#1f3d4a" strokeWidth={1} />;
      })}
      <polygon points={poly} fill="rgba(79, 200, 238, 0.18)" stroke="#4fc8ee" strokeWidth={2} strokeLinejoin="round" />
      {axes.map((a, i) => {
        const [x, y] = pt(i, Math.max(0, Math.min(100, a.value ?? 0)));
        return (
          <circle key={a.key} cx={x} cy={y} r={4} fill="#4fc8ee" stroke="#0f2530" strokeWidth={2}>
            <title>{`${a.label}: ${num(a.value)}`}</title>
          </circle>
        );
      })}
      {axes.map((a, i) => {
        const [x, y] = pt(i, 128);
        const anchor = Math.abs(x - cx) < 4 ? "middle" : x > cx ? "start" : "end";
        return (
          <text key={a.key} x={x} y={y} textAnchor={anchor} dominantBaseline="middle" fontSize={11} fill="#a9c3cf">
            <tspan fontWeight={600}>{a.label}</tspan>
            <tspan x={x} dy={13} fill="#eaf4f8" fontWeight={700}>{num(a.value)}</tspan>
          </text>
        );
      })}
      <text x={cx + 3} y={cy - r * 0.5 - 3} fontSize={9} fill="#7b98a6">50</text>
    </svg>
  );
}
