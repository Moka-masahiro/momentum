import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { axisPrice, mdDate, num, pct, yen } from "../format";
import type { Level, StockDetail, StockSignal } from "../types";
import { RANK_COLOR, RankBadge, Seg, rankOf } from "./ui";

type Period = "3M" | "6M" | "1Y";
// 既定値の空配列は固定しておく（毎回新しい配列だと、指で触るたびにチャートが作り直される）
const NO_SIGNALS: StockSignal[] = [];
const NO_LEVELS: Level[] = [];
const BARS: Record<Period, number> = { "3M": 63, "6M": 126, "1Y": 250 };

const C = {
  text: "#7b98a6",
  grid: "#1a3440",
  axis: "#2a4a58",
  up: "#e5534b",
  down: "#4a8fe8",
  ma25: "#d8d3c4",
  ma75: "#8aa4b0",
  level: "#a9c3cf",
  signalUp: "#4fc8ee",
  signalWarn: "#f0b44c",
  threshold: "rgba(169, 195, 207, 0.32)",
};

interface Props {
  chart: StockDetail["chart"];
  signals?: StockSignal[];
  levels?: Level[];
  showScore?: boolean;
  defaultPeriod?: Period;
  height?: number;
}

/**
 * 上段: ローソク足＋25日線・75日線（＋節目の水平線）、下段: モメンタム度（0〜100）。
 *
 * 紹介動画のアプリは株価とモメンタム度を左右2本の縦軸で1枚に重ねていたが、2軸の図は
 * 軸の合わせ方しだいで「連動しているように」見せられてしまうので、上下2段に分けて
 * 時間軸だけを共有する。
 */
export default function StockChart({ chart, signals = NO_SIGNALS, levels = NO_LEVELS, showScore = true, defaultPeriod = "3M", height = 340 }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const api = useRef<IChartApi | null>(null);
  const [period, setPeriod] = useState<Period>(defaultPeriod);
  const [hover, setHover] = useState<number | null>(null);

  const n = chart.dates.length;
  const idx = useMemo(() => {
    const m = new Map<string, number>();
    chart.dates.forEach((d, i) => m.set(d, i));
    return m;
  }, [chart.dates]);

  useEffect(() => {
    if (!el.current || n === 0) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: C.text,
        fontSize: 11,
        fontFamily: getComputedStyle(document.body).fontFamily,
        panes: { separatorColor: C.axis, separatorHoverColor: C.axis, enableResize: false },
        // TradingView のロゴは小さな下段に重なるので消し、ライセンスが求める表記は画面下の注記に出す
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: C.grid } },
      rightPriceScale: { borderColor: C.axis, minimumWidth: 58 },
      timeScale: { borderColor: C.axis, rightOffset: 2, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: CrosshairMode.Magnet },
      localization: { locale: "ja-JP", dateFormat: "yyyy/MM/dd" },
      // 縦のスワイプはページのスクロールに回す（チャートが指を奪わないように）
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: { time: true, price: false } },
    });
    api.current = c;

    const candles = c.addSeries(CandlestickSeries, {
      upColor: C.up,
      downColor: C.down,
      borderUpColor: C.up,
      borderDownColor: C.down,
      wickUpColor: C.up,
      wickDownColor: C.down,
      priceLineVisible: false,
      // 軸の書式は系列ごとに決める（全体で決めると下段のモメンタム度まで円の書式になる）
      priceFormat: { type: "custom", formatter: axisPrice, minMove: 0.01 },
    });
    const bars = chart.dates
      .map((d, i) => ({ time: d as Time, open: chart.open[i], high: chart.high[i], low: chart.low[i], close: chart.close[i] }))
      .filter((b): b is { time: Time; open: number; high: number; low: number; close: number } =>
        b.open != null && b.high != null && b.low != null && b.close != null);
    candles.setData(bars);

    const line = (values: (number | null)[], color: string) => {
      const s = c.addSeries(LineSeries, {
        color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        priceFormat: { type: "custom", formatter: axisPrice, minMove: 0.01 },
      });
      s.setData(chart.dates.map((d, i) => ({ time: d as Time, value: values[i] })).filter((p): p is { time: Time; value: number } => p.value != null));
      return s;
    };
    line(chart.ma25, C.ma25);
    line(chart.ma75, C.ma75);

    for (const lv of levels) {
      candles.createPriceLine({
        price: lv.price,
        color: C.level,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: lv.label,
      });
    }

    const markers: SeriesMarker<Time>[] = signals
      .filter((s) => idx.has(s.date))
      .map((s) => ({
        time: s.date as Time,
        position: s.tone === "warn" ? "aboveBar" : "belowBar",
        shape: s.tone === "warn" ? "arrowDown" : "arrowUp",
        color: s.tone === "warn" ? C.signalWarn : C.signalUp,
        size: 1,
      }));
    markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
    if (markers.length) createSeriesMarkers(candles, markers);

    if (showScore) {
      const score = c.addSeries(
        LineSeries,
        {
          lineWidth: 2,
          color: RANK_COLOR.B,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerRadius: 4,
          autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
          priceFormat: { type: "custom", formatter: (v: number) => v.toFixed(0), minMove: 1 },
        },
        1,
      );
      score.setData(
        chart.dates
          .map((d, i) => {
            const v = chart.score[i];
            return v == null ? null : { time: d as Time, value: v, color: RANK_COLOR[rankOf(v) ?? "C"] };
          })
          .filter((p): p is { time: Time; value: number; color: string } => p != null),
      );
      // ランクの境界（S/A/B/C の下限）を点線で示す。これが帯の凡例も兼ねる
      for (const [label, v] of [["S", 85], ["A", 70], ["B", 55], ["C", 40]] as const) {
        score.createPriceLine({ price: v, color: C.threshold, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: label });
      }
      // 既定の上下余白だと縦軸が 0〜120 まで伸びて見えるので詰める
      score.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.04 } });
      const panes = c.panes();
      if (panes[1]) panes[1].setHeight(Math.round(height * 0.3));
    }

    const onMove = (p: MouseEventParams<Time>) => {
      if (!p.time) return setHover(null);
      const i = idx.get(String(p.time));
      setHover(i ?? null);
    };
    c.subscribeCrosshairMove(onMove);
    return () => {
      c.unsubscribeCrosshairMove(onMove);
      c.remove();
      api.current = null;
    };
  }, [chart, signals, levels, showScore, height, idx, n]);

  useEffect(() => {
    const c = api.current;
    if (!c || n === 0) return;
    const k = Math.min(BARS[period], n);
    c.timeScale().setVisibleLogicalRange({ from: n - k - 0.5, to: n - 1 + 2 });
  }, [period, n, chart]);

  const i = hover ?? n - 1;
  const close = chart.close[i];
  const prev = i > 0 ? chart.close[i - 1] : null;
  const chg = close != null && prev ? (close / prev - 1) * 100 : null;
  const sc = chart.score[i];

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-2">
        <Seg<Period>
          value={period}
          onChange={setPeriod}
          options={[
            { value: "3M", label: "3か月" },
            { value: "6M", label: "6か月" },
            { value: "1Y", label: "1年" },
          ]}
        />
      </div>
      {/* 指で触れた日の値（触れていなければ最新日） */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] t-2 mb-1 min-h-[20px]">
        <span className="t-1 font-semibold">{mdDate(chart.dates[i])}</span>
        <span>
          終値 <b className="t-1 num">{yen(close)}</b>{" "}
          <span className={chg == null ? "t-3" : chg >= 0 ? "t-up" : "t-down"}>{pct(chg, 1)}</span>
        </span>
        {showScore && (
          <span className="inline-flex items-center gap-1">
            モメンタム度 <b className="t-1 num">{num(sc)}</b> <RankBadge rank={rankOf(sc)} />
          </span>
        )}
      </div>
      <div ref={el} style={{ height }} className="w-full" />
      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 text-[11px] t-2">
        <Legend color={C.up} label="陽線" box />
        <Legend color={C.down} label="陰線" box />
        <Legend color={C.ma25} label="25日線" />
        <Legend color={C.ma75} label="75日線" />
        {signals.length > 0 && <span><span style={{ color: C.signalUp }}>▲</span> シグナル <span style={{ color: C.signalWarn }}>▼</span> 警戒</span>}
        {levels.length > 0 && <Legend color={C.level} label="節目（点線）" dashed />}
        {showScore && <span>下段: モメンタム度（色はランク。点線は上から S・A・B・C の下限）</span>}
      </div>
    </div>
  );
}

function Legend({ color, label, box = false, dashed = false }: { color: string; label: string; box?: boolean; dashed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1">
      {box ? (
        <span style={{ width: 9, height: 9, borderRadius: 2, background: color, display: "inline-block" }} />
      ) : (
        <span style={{ width: 14, height: 0, borderTop: `2px ${dashed ? "dashed" : "solid"} ${color}`, display: "inline-block" }} />
      )}
      {label}
    </span>
  );
}
