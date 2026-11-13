import * as echarts from "echarts";
import { useEffect, useRef } from "react";

// A thin wrapper: the option is built by the caller from API data only.
export function EChart({
  option,
  height = 280,
  label,
}: {
  option: echarts.EChartsOption;
  height?: number;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    chart.current = echarts.init(ref.current, dark ? "dark" : undefined, { renderer: "canvas" });
    const resize = () => chart.current?.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.current?.dispose();
    };
  }, []);
  useEffect(() => {
    // Times are shown in UTC everywhere in the app, charts included.
    chart.current?.setOption({ backgroundColor: "transparent", useUTC: true, ...option }, true);
  }, [option]);
  return <div ref={ref} role="img" aria-label={label} style={{ height, width: "100%" }} />;
}
