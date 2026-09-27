import { useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import { axisPrice, mdDate } from "../format";
import type { Series } from "../types";
import { RANK_COLOR, rankOf } from "./ui";

export interface LineDef {
  key: string;
  label: string;
  color: string;
  series: Series;
  pane?: number;            // 0=上段 1=下段（単位の違うものは段を分ける。2軸にはしない）
  rankColored?: boolean;    // モメンタム度の線をランクの色で塗る
  width?: 1 | 2 | 3;
  format?: (v: number | null) => string;   // 凡例に出す値の書式（省略時は全体の format）
}

// 既定値は固定しておく（毎回新しいオブジェクトだと、指で触るたびにチャートが作り直される）。
// 呼ぶ側も lines / ranges / baselines は useMemo か定数で渡すこと
const NO_RANGES: Record<number, [number, number]> = {};
const NO_BASELINES: Record<number, number> = {};
const DEFAULT_FORMAT = (v: number | null) => (v == null ? "—" : v.toFixed(1));

interface Props {
  lines: LineDef[];
  height?: number;
  ranges?: Record<number, [number, number]>;   // 段ごとの固定の縦軸範囲
  baselines?: Record<number, number>;          // 段ごとの基準線（0 など）
  format?: (v: number | null) => string;
  paneHeights?: number[];
}

export default function LineChart({ lines, height = 220, ranges = NO_RANGES, baselines = NO_BASELINES, format = DEFAULT_FORMAT, paneHeights }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const [hoverTime, setHoverTime] = useState<string | null>(null);

  const lookup = useMemo(
    () =>
      lines.map((l) => {
        const m = new Map<string, number | null>();
        l.series.dates.forEach((d, i) => m.set(d, l.series.values[i]));
        return m;
      }),
    [lines],
  );
  const lastDate = useMemo(() => {
    let last = "";
    for (const l of lines) {
      const d = l.series.dates[l.series.dates.length - 1];
      if (d && d > last) last = d;
    }
    return last;
  }, [lines]);

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#7b98a6",
        fontSize: 11,
        fontFamily: getComputedStyle(document.body).fontFamily,
        panes: { separatorColor: "#2a4a58", separatorHoverColor: "#2a4a58", enableResize: false },
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: "#1a3440" } },
      rightPriceScale: { borderColor: "#2a4a58", minimumWidth: 52 },
      timeScale: { borderColor: "#2a4a58", fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: CrosshairMode.Magnet },
      localization: { locale: "ja-JP", dateFormat: "yyyy/MM/dd" },
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: { time: true, price: false } },
    });
    const firstInPane: Record<number, ISeriesApi<"Line">> = {};
    for (const l of lines) {
      const pane = l.pane ?? 0;
      const range = ranges[pane];
      const s = c.addSeries(
        LineSeries,
        {
          color: l.color,
          lineWidth: l.width ?? 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerRadius: 3,
          // 軸の目盛りも凡例と同じ書式にする（% や符号つきの IC など）
          priceFormat: { type: "custom", formatter: (v: number) => (l.format ? l.format(v) : axisPrice(v)), minMove: 0.001 },
          autoscaleInfoProvider: range ? () => ({ priceRange: { minValue: range[0], maxValue: range[1] } }) : undefined,
        },
        pane,
      );
      s.setData(
        l.series.dates
          .map((d, i) => {
            const v = l.series.values[i];
            if (v == null) return null;
            return l.rankColored ? { time: d as Time, value: v, color: RANK_COLOR[rankOf(v) ?? "C"] } : { time: d as Time, value: v };
          })
          .filter((p): p is { time: Time; value: number; color?: string } => p != null),
      );
      if (!firstInPane[pane]) {
        firstInPane[pane] = s;
        // 縦軸を固定した段は、既定の上下余白で 0〜125 のように見えるので詰める
        if (range) s.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.04 } });
      }
    }
    for (const [pane, v] of Object.entries(baselines)) {
      firstInPane[Number(pane)]?.createPriceLine({ price: v, color: "#5f7d8b", lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: false, title: "" });
    }
    if (paneHeights) {
      const panes = c.panes();
      paneHeights.forEach((h, i) => panes[i]?.setHeight(h));
    }
    c.timeScale().fitContent();
    const onMove = (p: MouseEventParams<Time>) => setHoverTime(p.time ? String(p.time) : null);
    c.subscribeCrosshairMove(onMove);
    return () => {
      c.unsubscribeCrosshairMove(onMove);
      c.remove();
    };
  }, [lines, ranges, baselines, paneHeights]);

  const at = hoverTime ?? lastDate;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] t-2 mb-1 min-h-[20px]">
        <span className="t-1 font-semibold">{mdDate(at)}</span>
        {lines.map((l, i) => (
          <span key={l.key} className="inline-flex items-center gap-1">
            <span style={{ width: 12, height: 0, borderTop: `2px solid ${l.rankColored ? RANK_COLOR.A : l.color}`, display: "inline-block" }} />
            {l.label} <b className="t-1 num">{(l.format ?? format)(lookup[i].get(at) ?? null)}</b>
          </span>
        ))}
      </div>
      <div ref={el} style={{ height }} className="w-full" />
    </div>
  );
}
