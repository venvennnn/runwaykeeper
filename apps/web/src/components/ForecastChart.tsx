"use client";

import React, { useEffect, useRef } from "react";

interface ForecastChartProps {
  days: Array<{
    day: string;
    p10_minor: number;
    p50_minor: number;
    p90_minor: number;
  }>;
  bufferMinor: number;
  namedPaths?: {
    optimistic?: number[];
    base?: number[];
    delayed?: number[];
  };
  sharedDelayPath?: number[];
  onSelectDay?: (dayStr: string) => void;
}

export function ForecastChart({
  days,
  bufferMinor,
  namedPaths,
  sharedDelayPath,
  onSelectDay,
}: ForecastChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let unmounted = false;

    async function renderChart() {
      if (!containerRef.current || days.length === 0) return;
      const Plotly = (await import("plotly.js-dist-min")).default;
      if (unmounted || !containerRef.current) return;

      const x = days.map((d) => d.day);
      const p10 = days.map((d) => d.p10_minor / 100);
      const p50 = days.map((d) => d.p50_minor / 100);
      const p90 = days.map((d) => d.p90_minor / 100);
      const buffer = days.map(() => bufferMinor / 100);

      const traces: any[] = [
        // P90 upper bound
        {
          x,
          y: p90,
          type: "scatter",
          mode: "lines",
          line: { width: 0 },
          showlegend: false,
          hoverinfo: "skip",
        },
        // P10 lower bound with fill to P90
        {
          x,
          y: p10,
          type: "scatter",
          mode: "lines",
          fill: "tonexty",
          fillcolor: "rgba(13, 148, 136, 0.08)",
          line: { width: 0 },
          name: "P10 - P90 Band",
          hoverinfo: "skip",
        },
        // P50 Median line
        {
          x,
          y: p50,
          type: "scatter",
          mode: "lines",
          line: { color: "#0f172a", width: 2 },
          name: "Median (P50)",
          hovertemplate: "%{x}<br>Median: $%{y:,.0f}<extra></extra>",
        },
        // Required buffer line
        {
          x,
          y: buffer,
          type: "scatter",
          mode: "lines",
          line: { color: "#dc2626", width: 1.5, dash: "dot" },
          name: "Buffer requirement",
          hovertemplate: "Buffer: $%{y:,.0f}<extra></extra>",
        },
      ];

      // Correlated delay stress path
      if (sharedDelayPath && sharedDelayPath.length === days.length) {
        traces.push({
          x,
          y: sharedDelayPath.map((v) => v / 100),
          type: "scatter",
          mode: "lines",
          line: { color: "#ea580c", width: 1.2, dash: "dash" },
          name: "Shared-delay stress",
          hovertemplate: "Shared late: $%{y:,.0f}<extra></extra>",
        });
      }

      const layout: any = {
        margin: { l: 45, r: 20, t: 15, b: 35 },
        autosize: true,
        height: 280,
        showlegend: true,
        legend: {
          orientation: "h",
          y: -0.2,
          x: 0,
          font: { size: 10, color: "#64748b" },
        },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        xaxis: {
          showgrid: false,
          zeroline: false,
          tickfont: { size: 10, color: "#64748b" },
          tickformat: "%b %d",
        },
        yaxis: {
          showgrid: false,
          zeroline: false,
          tickfont: { size: 10, color: "#64748b" },
          tickprefix: "$",
        },
        hovermode: "x unified",
      };

      const config: any = {
        responsive: true,
        displayModeBar: false,
      };

      Plotly.newPlot(containerRef.current, traces, layout, config);

      (containerRef.current as any).on("plotly_click", (data: any) => {
        if (data.points && data.points.length > 0 && onSelectDay) {
          onSelectDay(data.points[0].x);
        }
      });
    }

    renderChart();

    return () => {
      unmounted = true;
    };
  }, [days, bufferMinor, namedPaths, sharedDelayPath, onSelectDay]);

  return <div ref={containerRef} className="w-full h-[280px]" />;
}
