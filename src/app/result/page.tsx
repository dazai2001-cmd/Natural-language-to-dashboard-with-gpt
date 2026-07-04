"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Bar, Line, Pie, Scatter } from "react-chartjs-2";
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  ChartData,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";

ChartJS.register(
  ArcElement,
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
);

type ResultRow = Record<string, string | number | boolean | null>;

type VisualizationSpec = {
  type: "bar" | "line" | "pie" | "scatter" | "table";
  title: string;
  x_column: string | null;
  y_column: string | null;
  rationale: string;
};

type Visualization = {
  chart_type: VisualizationSpec["type"];
  chart_data: ChartData;
  chart_spec: VisualizationSpec;
};

type ApiResponse = {
  status?: "ok" | "insufficient_data";
  message?: string;
  answer?: string | null;
  answer_fallback?: boolean;
  sql?: string;
  results?: ResultRow[];
  chart_type?: "bar" | "line" | "pie" | "scatter" | "table";
  chart_data?: ChartData;
  chart_spec?: VisualizationSpec;
  visualizations?: Visualization[];
  chart_fallback?: boolean;
  model?: string;
  data_quality?: {
    match_count: number;
    player_rows: number;
    first_match: string | null;
    last_match: string | null;
    coverage_days: number;
    covered_weeks: number;
    max_hero_appearances: number;
    eligible_hero_count: number;
    sufficient_for_best_hero: boolean;
    enriched_player_rows?: number;
    enriched_match_count?: number;
    sufficient_for_matchups?: boolean;
  };
  data_profile?: {
    table_count: number;
    tables: {
      name: string;
      type: string;
      column_count: number;
      row_count: number | null;
    }[];
  };
  metric?: {
    name: string;
    scale: string;
    formula: string;
    reliability: string;
    eligibility: string;
    limitation: string;
  };
  error?: string;
};

function formatCell(value: ResultRow[string]) {
  if (value === null) return "—";
  if (typeof value === "number") {
    if (Math.abs(value) < 1 && value !== 0) return `${(value * 100).toFixed(2)}%`;
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  }
  return String(value);
}

const chartPalette = [
  "#34d399",
  "#22d3ee",
  "#a78bfa",
  "#fbbf24",
  "#fb7185",
  "#60a5fa",
  "#f472b6",
  "#bef264",
  "#2dd4bf",
  "#f97316",
];

function themeChartData(chartData: ChartData, chartType: VisualizationSpec["type"]): ChartData {
  const datasets = (chartData.datasets ?? []).map((dataset, index) => {
    const color = chartPalette[index % chartPalette.length];
    const itemCount = Array.isArray(dataset.data) ? dataset.data.length : 0;
    return {
      ...dataset,
      backgroundColor: chartType === "pie"
        ? chartPalette.slice(0, Math.max(itemCount, 1))
        : color,
      borderColor: color,
      borderWidth: chartType === "line" ? 3 : 1,
      pointBackgroundColor: color,
      pointBorderColor: "#020617",
      pointRadius: chartType === "line" || chartType === "scatter" ? 4 : undefined,
      hoverBackgroundColor: color,
    };
  });

  return { ...chartData, datasets };
}

function ResultsContent() {
  const searchParams = useSearchParams();
  const question = searchParams.get("question");
  const [data, setData] = useState<ApiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!question) {
      setError("No analytics question was provided.");
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setError("");

    fetch("/api/sql-query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = (await response.json()) as ApiResponse;
        if (!response.ok || payload.error) {
          throw new Error(payload.error ?? "The analytics request failed.");
        }
        setData(payload);
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof Error && requestError.name !== "AbortError") {
          setError(requestError.message);
        }
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, [question]);

  function renderChart(visualization: Visualization) {
    const { chart_data: chartData, chart_type: chartType, chart_spec: chartSpec } = visualization;
    const themedChartData = themeChartData(chartData, chartType);
    const gridColor = "rgba(148, 163, 184, 0.18)";
    const textColor = "#cbd5e1";
    const options = {
      responsive: true,
      plugins: {
        legend: { labels: { color: textColor } },
        title: { display: false },
      },
      scales: {
        x: {
          ticks: { color: textColor },
          grid: { color: gridColor },
          title: { display: true, text: chartSpec.x_column ?? "", color: textColor },
        },
        y: {
          ticks: { color: textColor },
          grid: { color: gridColor },
          title: { display: true, text: chartSpec.y_column ?? "", color: textColor },
          beginAtZero: true,
        },
      },
    };

    if (chartType === "table") return null;
    if (chartType === "pie") {
      return <Pie data={themedChartData as ChartData<"pie">} options={{ responsive: true, plugins: options.plugins }} />;
    }
    if (chartType === "line") return <Line data={themedChartData as ChartData<"line">} options={options} />;
    if (chartType === "scatter") return <Scatter data={themedChartData as ChartData<"scatter">} options={options} />;
    return <Bar data={themedChartData as ChartData<"bar">} options={options} />;
  }

  const results = data?.results ?? [];
  const visualizations = data?.visualizations ?? (
    data?.chart_spec && data.chart_data && data.chart_type
      ? [{ chart_spec: data.chart_spec, chart_data: data.chart_data, chart_type: data.chart_type }]
      : []
  );
  const analystSummary = data?.answer ?? data?.message;
  const firstRow = results[0];
  const columns = firstRow ? Object.keys(firstRow) : [];

  return (
    <main className="min-h-screen px-4 py-6 text-slate-100 md:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="rounded-2xl border border-white/10 bg-slate-950/75 p-5 shadow-2xl shadow-black/30 backdrop-blur">
          <button
            onClick={() => window.location.assign("/")}
            className="mb-4 text-sm font-bold text-emerald-300 hover:text-emerald-200"
          >
            ← Back to meta hub
          </button>
          <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
                Analyst query
              </p>
              <h1 className="mt-2 text-3xl font-black text-white md:text-5xl">
                {question}
              </h1>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-bold text-emerald-200">
                {data?.model ?? "loading model"}
              </span>
              {data?.chart_fallback && (
                <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-3 py-1 text-xs font-bold text-amber-200">
                  safe chart fallback
                </span>
              )}
            </div>
          </div>
        </header>

        {loading ? (
          <section className="rounded-3xl border border-white/10 bg-slate-950/75 p-10 text-center">
            <div className="mx-auto mb-4 h-12 w-12 animate-spin rounded-full border-4 border-emerald-400 border-t-transparent" />
            <p className="text-lg font-bold text-emerald-200">
              Asking the analytics engine and local Qwen analyst...
            </p>
          </section>
        ) : error ? (
          <section className="rounded-3xl border border-red-400/30 bg-red-950/40 p-6 text-red-100">
            <h2 className="text-2xl font-black">Request failed</h2>
            <p className="mt-2">{error}</p>
          </section>
        ) : (
          <>
            {data?.status === "insufficient_data" && (
              <section className="rounded-3xl border border-amber-400/30 bg-amber-950/30 p-6 text-amber-50">
                <h2 className="text-2xl font-black">Not enough evidence</h2>
                <p className="mt-2 text-amber-100">{data.message}</p>
              </section>
            )}

            {analystSummary && data?.status !== "insufficient_data" && (
              <section className="rounded-3xl border border-emerald-400/20 bg-emerald-400/10 p-6 shadow-xl shadow-emerald-950/20">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-2xl font-black text-white">AI analyst readout</h2>
                  {data?.answer_fallback && (
                    <span className="rounded-full bg-amber-400/15 px-3 py-1 text-xs font-bold text-amber-200">
                      fallback
                    </span>
                  )}
                </div>
                <p className="mt-3 max-w-5xl text-lg leading-8 text-emerald-50">
                  {analystSummary}
                </p>
              </section>
            )}

            <section className="grid gap-4 md:grid-cols-4">
              <div className="rounded-2xl border border-white/10 bg-slate-950/75 p-5">
                <p className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500">Rows</p>
                <p className="mt-2 text-3xl font-black text-emerald-300">{results.length}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-slate-950/75 p-5">
                <p className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500">Charts</p>
                <p className="mt-2 text-3xl font-black text-cyan-300">{visualizations.length}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-slate-950/75 p-5">
                <p className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500">Tables checked</p>
                <p className="mt-2 text-3xl font-black text-violet-300">{data?.data_profile?.table_count ?? "—"}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-slate-950/75 p-5">
                <p className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500">Enriched matches</p>
                <p className="mt-2 text-3xl font-black text-amber-300">{data?.data_quality?.enriched_match_count ?? "—"}</p>
              </div>
            </section>

            {visualizations.length > 0 && (
              <section className="grid gap-5 xl:grid-cols-2">
                {visualizations.map((visualization, index) => (
                  <article
                    key={`${visualization.chart_spec.type}-${visualization.chart_spec.x_column}-${visualization.chart_spec.y_column}-${index}`}
                    className="rounded-3xl border border-white/10 bg-slate-950/75 p-5 shadow-xl shadow-black/20"
                  >
                    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-xs font-bold uppercase tracking-[0.25em] text-emerald-300">
                          {visualization.chart_spec.type}
                        </p>
                        <h2 className="mt-1 text-xl font-black text-white">
                          {visualization.chart_spec.title}
                        </h2>
                      </div>
                      <span className="rounded-full bg-slate-800 px-3 py-1 text-xs font-bold text-slate-300">
                        {visualization.chart_spec.y_column ?? "table"}
                      </span>
                    </div>
                    <p className="mb-4 text-sm leading-6 text-slate-400">
                      {visualization.chart_spec.rationale}
                    </p>
                    <div className="rounded-2xl bg-slate-900/70 p-4">{renderChart(visualization)}</div>
                  </article>
                ))}
              </section>
            )}

            {results.length > 0 && (
              <section className="overflow-hidden rounded-3xl border border-white/10 bg-slate-950/75 shadow-xl shadow-black/20">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-4">
                  <div>
                    <p className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500">
                      Ranking table
                    </p>
                    <h2 className="text-2xl font-black text-white">Query results</h2>
                  </div>
                  <span className="rounded-full bg-slate-800 px-3 py-1 text-xs font-bold text-slate-300">
                    {columns.length} columns
                  </span>
                </div>
                <div className="max-h-[34rem] overflow-auto">
                  <table className="w-full min-w-[720px] text-left text-sm">
                    <thead className="sticky top-0 bg-slate-900 text-xs uppercase tracking-wider text-slate-400">
                      <tr>
                        <th className="px-4 py-3">#</th>
                        {columns.map((column) => (
                          <th key={column} className="px-4 py-3">{column.replaceAll("_", " ")}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/10">
                      {results.map((row, rowIndex) => (
                        <tr key={rowIndex} className="text-slate-200 hover:bg-white/[0.03]">
                          <td className="px-4 py-3 font-bold text-slate-500">{rowIndex + 1}</td>
                          {columns.map((column, columnIndex) => (
                            <td
                              key={column}
                              className={`px-4 py-3 ${columnIndex === 0 ? "font-bold text-white" : "text-slate-300"}`}
                            >
                              {formatCell(row[column])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            <details className="rounded-3xl border border-white/10 bg-slate-950/75 p-5">
              <summary className="cursor-pointer text-lg font-black text-white">
                SQL and dataset debug
              </summary>
              <pre className="mt-4 overflow-auto rounded-2xl bg-black/50 p-4 text-sm text-slate-300">
                {data?.sql}
              </pre>
              {data?.data_profile && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {data.data_profile.tables.slice(0, 12).map((table) => (
                    <span key={table.name} className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
                      {table.name}: {table.row_count ?? "?"} rows
                    </span>
                  ))}
                </div>
              )}
            </details>
          </>
        )}
      </div>
    </main>
  );
}

export default function ResultPage() {
  return (
    <Suspense fallback={<p className="p-8 text-center text-emerald-300">Loading...</p>}>
      <ResultsContent />
    </Suspense>
  );
}
