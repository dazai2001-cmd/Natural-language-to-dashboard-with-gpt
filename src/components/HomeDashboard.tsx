"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export type MetaDashboard = {
  status: "ok";
  model: string;
  selected_hero: string;
  heroes: string[];
  stats: {
    enriched_matches: number;
    enriched_player_rows: number;
    matchup_rows: number;
    synergy_rows: number;
  };
  coverage: {
    hero_appearances: number;
    matchups: {
      total_rows: number;
      reliable_rows: number;
      max_games: number;
    };
    synergies: {
      total_rows: number;
      reliable_rows: number;
      max_games: number;
    };
    trend_months: number;
    reliable_threshold: number;
    min_hero_appearances: number;
  };
  match_trend: {
    month: string;
    matches: number;
  }[];
  hero_trend: {
    month: string;
    appearances: number;
    win_rate: number;
  }[];
  counters: {
    counter_hero: string;
    matchup_score: number;
    win_rate: number;
    games_played: number;
    reliability: number;
  }[];
  synergies: {
    recommended_ally: string;
    synergy_score: number;
    win_rate: number;
    games_played: number;
    reliability: number;
  }[];
  quick_questions: string[];
  error?: string;
};

type ImportStatus = {
  running: boolean;
  exit_code: number | null;
  started_at: string | null;
  mode: string | null;
  log_tail: string[];
  rate_limit_policy?: {
    delay_seconds_between_successful_calls: number;
    honors_429_retry_after: boolean;
    commits_each_match: boolean;
    skips_existing_matches: boolean;
  };
  error?: string;
};

function formatCompact(value: number | undefined) {
  if (typeof value !== "number") return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return value.toLocaleString();
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function featureStatus({
  rows,
  reliableRows,
  maxGames,
  threshold,
}: {
  rows: number | undefined;
  reliableRows: number | undefined;
  maxGames: number | undefined;
  threshold: number | undefined;
}) {
  if (!rows) return { label: "Needs data", tone: "text-red-200 bg-red-400/10", detail: "No qualifying rows yet" };
  if ((reliableRows ?? 0) > 0) {
    return {
      label: "Reliable",
      tone: "text-emerald-200 bg-emerald-400/10",
      detail: `${reliableRows} rows at ${threshold}+ games`,
    };
  }
  return {
    label: "Exploratory",
    tone: "text-amber-200 bg-amber-400/10",
    detail: `max sample ${maxGames ?? 0}; target ${threshold}+`,
  };
}

export default function HomeDashboard({ initialMeta }: { initialMeta: MetaDashboard | null }) {
  const [question, setQuestion] = useState("");
  const [meta, setMeta] = useState<MetaDashboard | null>(initialMeta);
  const [selectedHero, setSelectedHero] = useState(initialMeta?.selected_hero ?? "Pudge");
  const [metaError, setMetaError] = useState(initialMeta ? "" : "Live meta data is not connected yet.");
  const [metaLoading, setMetaLoading] = useState(false);
  const [importMode, setImportMode] = useState("recent");
  const [importStatus, setImportStatus] = useState<ImportStatus | null>(null);
  const [importError, setImportError] = useState("");
  const [openingCard, setOpeningCard] = useState("");
  const router = useRouter();

  useEffect(() => {
    const controller = new AbortController();
    setMetaLoading(true);
    fetch(`/api/meta-dashboard?hero=${encodeURIComponent(selectedHero)}`, {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = (await response.json()) as MetaDashboard;
        if (!response.ok || payload.error) {
          throw new Error(payload.error ?? "Meta dashboard failed to load.");
        }
        setMeta(payload);
        setMetaError("");
      })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name !== "AbortError") {
          setMetaError(error.message);
        }
      })
      .finally(() => setMetaLoading(false));
    return () => controller.abort();
  }, [selectedHero]);

  useEffect(() => {
    let cancelled = false;

    async function loadStatus() {
      try {
        const response = await fetch("/api/import/status", { cache: "no-store" });
        const payload = (await response.json()) as ImportStatus;
        if (!response.ok || payload.error) {
          throw new Error(payload.error ?? "Import status failed to load.");
        }
        if (!cancelled) {
          setImportStatus(payload);
          setImportError("");
        }
      } catch (error) {
        if (!cancelled && error instanceof Error) setImportError(error.message);
      }
    }

    loadStatus();
    const interval = window.setInterval(loadStatus, importStatus?.running ? 5000 : 15000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [importStatus?.running]);

  function submitQuestion(value: string) {
    const trimmed = value.trim();
    if (trimmed) router.push(`/result?question=${encodeURIComponent(trimmed)}`);
  }

  function resultHref(value: string) {
    return `/result?question=${encodeURIComponent(value)}`;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitQuestion(question);
  }

  async function startImport() {
    setImportError("");
    try {
      const response = await fetch("/api/import/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: importMode }),
      });
      const payload = (await response.json()) as ImportStatus & { error?: string; status?: ImportStatus };
      if (!response.ok || payload.error) {
        setImportStatus(payload.status ?? null);
        throw new Error(payload.error ?? "Import could not be started.");
      }
      setImportStatus(payload);
    } catch (error) {
      if (error instanceof Error) setImportError(error.message);
    }
  }

  const heroName = meta?.selected_hero ?? selectedHero;
  const quickQuestions = meta?.quick_questions ?? [
    `what counters ${heroName} in Dota 2?`,
    `what heroes work best with ${heroName}?`,
  ];
  const featuredStats = [
    { label: "Enriched matches", value: formatCompact(meta?.stats.enriched_matches), tone: "text-cyan-300" },
    { label: "Player rows", value: formatCompact(meta?.stats.enriched_player_rows), tone: "text-emerald-300" },
    { label: "Matchup rows", value: formatCompact(meta?.stats.matchup_rows), tone: "text-violet-300" },
    { label: "Synergy rows", value: formatCompact(meta?.stats.synergy_rows), tone: "text-amber-300" },
  ];
  const cards = [
    {
      title: "Counters",
      eyebrow: "Matchup engine",
      metric: "hero_matchups",
      description: `Find heroes that perform best into ${heroName} using win rate, matchup score, and reliability.`,
      query: `what counters ${heroName} in Dota 2?`,
      preview: (meta?.counters ?? []).slice(0, 3).map((row) => ({
        label: row.counter_hero,
        value: `${row.matchup_score.toFixed(1)} score`,
        sub: `${row.games_played} games`,
      })),
      rows: meta?.coverage.matchups.total_rows,
      status: featureStatus({
        rows: meta?.coverage.matchups.total_rows,
        reliableRows: meta?.coverage.matchups.reliable_rows,
        maxGames: meta?.coverage.matchups.max_games,
        threshold: meta?.coverage.reliable_threshold,
      }),
    },
    {
      title: "Synergies",
      eyebrow: "Draft pairings",
      metric: "hero_synergies",
      description: `Discover allies that win most often alongside ${heroName}, with sample-size context.`,
      query: `what heroes work best with ${heroName}?`,
      preview: (meta?.synergies ?? []).slice(0, 3).map((row) => ({
        label: row.recommended_ally,
        value: `${row.synergy_score.toFixed(1)} score`,
        sub: `${row.games_played} games`,
      })),
      rows: meta?.coverage.synergies.total_rows,
      status: featureStatus({
        rows: meta?.coverage.synergies.total_rows,
        reliableRows: meta?.coverage.synergies.reliable_rows,
        maxGames: meta?.coverage.synergies.max_games,
        threshold: meta?.coverage.reliable_threshold,
      }),
    },
    {
      title: "Meta trends",
      eyebrow: "Time series",
      metric: "hero picks by month",
      description: `Analyze ${heroName}'s monthly appearances and win-rate trend from stored matches.`,
      query: `How often was ${heroName} picked by month?`,
      preview: (meta?.hero_trend ?? []).slice(-3).map((row) => ({
        label: row.month.slice(0, 7),
        value: `${row.appearances} picks`,
        sub: `${formatPercent(row.win_rate)} WR`,
      })),
      rows: meta?.hero_trend.length,
      status: {
        label: (meta?.hero_trend.length ?? 0) >= 8 ? "Usable" : "Sparse",
        tone: (meta?.hero_trend.length ?? 0) >= 8 ? "text-emerald-200 bg-emerald-400/10" : "text-amber-200 bg-amber-400/10",
        detail: `${meta?.hero_trend.length ?? 0} months with ${heroName}`,
      },
    },
  ];

  return (
    <main className="min-h-screen px-4 py-6 text-slate-100 md:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <nav className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-slate-950/70 px-5 py-4 shadow-2xl shadow-black/30 backdrop-blur">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.35em] text-emerald-300">Puppet.GG</p>
            <h1 className="text-2xl font-black tracking-tight text-white">Agentic Meta Analytics</h1>
          </div>
          <div className="flex flex-wrap gap-2 text-xs font-semibold text-slate-300">
            <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-emerald-200">
              {meta?.model ?? metaError}
            </span>
            <span className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1 text-cyan-200">
              {meta ? "Live Postgres data" : "Waiting for backend"}
            </span>
            <span className="rounded-full border border-violet-400/30 bg-violet-400/10 px-3 py-1 text-violet-200">
              Any dataset via SQL agent
            </span>
          </div>
        </nav>

        <section className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-3xl border border-white/10 bg-slate-950/75 p-6 shadow-2xl shadow-black/40 backdrop-blur md:p-8">
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.3em] text-emerald-300">
              Ask. Rank. Counter. Explain.
            </p>
            <h2 className="max-w-3xl text-4xl font-black leading-tight text-white md:text-6xl">
              U.GG-style stats for any selected hero.
            </h2>
            <p className="mt-4 max-w-2xl text-base text-slate-300 md:text-lg">
              Pick a hero, inspect live counters and draft pairings, then ask the local Qwen analyst
              to build a custom dashboard from the same trusted database views.
            </p>

            <div className="mt-6 grid gap-3 rounded-2xl border border-white/10 bg-slate-900/70 p-4 md:grid-cols-[0.45fr_1fr]">
              <label htmlFor="hero" className="text-sm font-bold uppercase tracking-[0.2em] text-slate-400">
                Hero
              </label>
              <select
                id="hero"
                value={selectedHero}
                onChange={(event) => setSelectedHero(event.target.value)}
                className="rounded-xl border border-white/10 bg-slate-950 px-4 py-3 text-white outline-none ring-emerald-400/40 focus:ring-4"
              >
                {(meta?.heroes ?? [selectedHero]).map((hero) => (
                  <option key={hero} value={hero}>{hero}</option>
                ))}
              </select>
            </div>

            <form
              onSubmit={handleSubmit}
              className="mt-5 rounded-2xl border border-emerald-400/30 bg-slate-900/90 p-2 shadow-lg shadow-emerald-950/30"
            >
              <label htmlFor="question" className="sr-only">Ask the analyst</label>
              <div className="flex flex-col gap-2 md:flex-row">
                <input
                  id="question"
                  type="text"
                  className="min-h-14 flex-1 rounded-xl border border-white/10 bg-slate-950 px-4 text-base text-white outline-none ring-emerald-400/40 placeholder:text-slate-500 focus:ring-4"
                  placeholder={`Ask: what counters ${heroName} in Dota 2?`}
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  autoFocus
                />
                <button type="submit" className="rounded-xl bg-emerald-400 px-6 py-3 font-black text-slate-950 transition hover:bg-emerald-300">
                  Analyze
                </button>
              </div>
            </form>

            <div className="mt-4 flex flex-wrap gap-2">
              {quickQuestions.map((sample) => (
                <button
                  key={sample}
                  onClick={() => submitQuestion(sample)}
                  className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300 transition hover:border-emerald-300/50 hover:text-emerald-200"
                >
                  {sample}
                </button>
              ))}
            </div>
          </div>

          <aside className="grid gap-4">
            <LiveTable
              title={`${heroName} counters`}
              eyebrow="Live from hero_matchups"
              loading={metaLoading}
              rows={(meta?.counters ?? []).map((row) => ({
                name: row.counter_hero,
                score: row.matchup_score,
                winRate: row.win_rate,
                games: row.games_played,
              }))}
            />
            <LiveTable
              title={`Best allies for ${heroName}`}
              eyebrow="Live from hero_synergies"
              loading={metaLoading}
              rows={(meta?.synergies ?? []).map((row) => ({
                name: row.recommended_ally,
                score: row.synergy_score,
                winRate: row.win_rate,
                games: row.games_played,
              }))}
            />
          </aside>
        </section>

        <section className="grid gap-4 md:grid-cols-4">
          {featuredStats.map((stat) => (
            <div key={stat.label} className="rounded-2xl border border-white/10 bg-slate-950/70 p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-500">{stat.label}</p>
              <p className={`mt-2 text-3xl font-black ${stat.tone}`}>{stat.value}</p>
            </div>
          ))}
        </section>

        <section className="rounded-3xl border border-white/10 bg-slate-950/70 p-5">
          <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500">
                Data pipeline
              </p>
              <h3 className="text-2xl font-black text-white">Enrich database</h3>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
                Pulls public OpenDota match details with a conservative 1.2s delay, honors 429 Retry-After,
                skips existing matches, and commits every match so a rate-limit or crash does not wipe progress.
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <select
                value={importMode}
                onChange={(event) => setImportMode(event.target.value)}
                disabled={importStatus?.running}
                className="rounded-xl border border-white/10 bg-slate-950 px-4 py-3 text-sm font-bold text-white outline-none disabled:opacity-50"
              >
                <option value="recent">Recent safe refresh</option>
                <option value="enrich-existing">Enrich existing rows</option>
                <option value="backfill">Large yearly backfill</option>
              </select>
              <button
                onClick={startImport}
                disabled={importStatus?.running}
                className="rounded-xl bg-emerald-400 px-5 py-3 text-sm font-black text-slate-950 transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
              >
                {importStatus?.running ? "Import running..." : "Start enrichment"}
              </button>
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <CoverageStat label="Job mode" value={0} detail={importStatus?.mode ?? "No job started"} hideValue />
            <CoverageStat
              label="Status"
              value={0}
              detail={importStatus?.running ? "Running" : importStatus?.exit_code === 0 ? "Last run completed" : "Idle / not completed"}
              hideValue
            />
            <CoverageStat label="Delay" value={0} detail={`${importStatus?.rate_limit_policy?.delay_seconds_between_successful_calls ?? 1.2}s between calls`} hideValue />
            <CoverageStat label="Safety" value={0} detail="Skips existing, commits each match" hideValue />
          </div>

          {importError && (
            <p className="mt-3 rounded-xl border border-red-400/20 bg-red-400/10 p-3 text-sm text-red-100">
              {importError}
            </p>
          )}

          {importStatus?.log_tail?.length ? (
            <details className="mt-4 rounded-2xl border border-white/10 bg-black/30 p-4">
              <summary className="cursor-pointer text-sm font-bold text-slate-200">
                Import log tail
              </summary>
              <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-400">
                {importStatus.log_tail.join("\n")}
              </pre>
            </details>
          ) : null}
        </section>

        <section className="rounded-3xl border border-white/10 bg-slate-950/70 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500">
                Coverage check
              </p>
              <h3 className="text-2xl font-black text-white">{heroName} data quality</h3>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-bold ${
              (meta?.coverage.hero_appearances ?? 0) >= (meta?.coverage.min_hero_appearances ?? 50)
                ? "bg-emerald-400/10 text-emerald-200"
                : "bg-amber-400/10 text-amber-200"
            }`}>
              {meta?.coverage.hero_appearances ?? 0} appearances
            </span>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <CoverageStat
              label="Reliable counter rows"
              value={meta?.coverage.matchups.reliable_rows ?? 0}
              detail={`${meta?.coverage.matchups.total_rows ?? 0} total; max ${meta?.coverage.matchups.max_games ?? 0} games`}
            />
            <CoverageStat
              label="Reliable synergy rows"
              value={meta?.coverage.synergies.reliable_rows ?? 0}
              detail={`${meta?.coverage.synergies.total_rows ?? 0} total; max ${meta?.coverage.synergies.max_games ?? 0} games`}
            />
            <CoverageStat
              label="Trend months"
              value={meta?.coverage.trend_months ?? 0}
              detail={`${meta?.stats.enriched_matches ?? 0} enriched matches`}
            />
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          {cards.map((card) => (
            <a
              key={card.title}
              href={resultHref(card.query)}
              onClick={() => setOpeningCard(card.title)}
              className="group rounded-3xl border border-white/10 bg-slate-950/70 p-6 text-left transition hover:-translate-y-1 hover:border-emerald-300/40 hover:bg-slate-900/90"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-bold uppercase tracking-[0.25em] text-emerald-300">{card.eyebrow}</p>
                <span className="rounded-full bg-slate-800 px-2 py-1 text-[10px] font-bold text-slate-300">
                  {card.metric}
                </span>
              </div>
              <h3 className="mt-3 text-2xl font-black text-white">{card.title}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-400">{card.description}</p>
              <div className="mt-4 space-y-2 rounded-2xl border border-white/10 bg-slate-950/60 p-3">
                {card.preview.length ? card.preview.map((item) => (
                  <div key={`${card.title}-${item.label}`} className="flex items-center justify-between gap-3 text-xs">
                    <span className="font-bold text-slate-200">{item.label}</span>
                    <span className="text-right text-slate-400">
                      <span className="font-bold text-emerald-200">{item.value}</span>
                      <span className="ml-2">{item.sub}</span>
                    </span>
                  </div>
                )) : (
                  <p className="text-xs text-slate-500">No preview rows cleared the sample threshold.</p>
                )}
              </div>
              <div className="mt-5 flex items-center justify-between gap-3">
                {openingCard === card.title && (
                  <span className="text-sm font-bold text-emerald-200">Opening dashboard...</span>
                )}
                <p className="text-sm font-bold text-slate-300 group-hover:text-emerald-200">Run live query →</p>
                <span className={`rounded-full px-2 py-1 text-xs font-bold ${card.status.tone}`}>
                  {card.status.label}
                </span>
              </div>
              <p className="mt-3 text-xs font-semibold text-slate-500">
                {card.rows ?? 0} rows checked · {card.status.detail}
              </p>
            </a>
          ))}
        </section>
      </div>
    </main>
  );
}

function CoverageStat({
  label,
  value,
  detail,
  hideValue = false,
}: {
  label: string;
  value: number;
  detail: string;
  hideValue?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-4">
      <p className="text-xs font-bold uppercase tracking-[0.2em] text-slate-500">{label}</p>
      {!hideValue && <p className="mt-2 text-2xl font-black text-white">{value}</p>}
      <p className="mt-1 text-xs text-slate-400">{detail}</p>
    </div>
  );
}

function LiveTable({
  title,
  eyebrow,
  loading,
  rows,
}: {
  title: string;
  eyebrow: string;
  loading: boolean;
  rows: { name: string; score: number; winRate: number; games: number }[];
}) {
  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/75 p-5 shadow-2xl shadow-black/40 backdrop-blur">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.25em] text-slate-500">{eyebrow}</p>
          <h3 className="text-2xl font-black text-white">{title}</h3>
        </div>
        <span className="rounded-full bg-emerald-400/15 px-3 py-1 text-xs font-bold text-emerald-200">
          {loading ? "Refreshing" : "Ranked"}
        </span>
      </div>

      <div className="mt-5 overflow-hidden rounded-2xl border border-white/10">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-900 text-xs uppercase tracking-wider text-slate-400">
            <tr>
              <th className="px-4 py-3">Hero</th>
              <th className="px-4 py-3">Score</th>
              <th className="px-4 py-3">WR</th>
              <th className="px-4 py-3">Games</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10 bg-slate-950/60">
            {rows.map((row, index) => (
              <tr key={row.name} className="text-slate-200">
                <td className="px-4 py-3 font-bold">
                  <span className="mr-2 text-slate-500">#{index + 1}</span>
                  {row.name}
                </td>
                <td className="px-4 py-3 text-emerald-300">{row.score.toFixed(2)}</td>
                <td className="px-4 py-3 text-cyan-300">{formatPercent(row.winRate)}</td>
                <td className="px-4 py-3 text-slate-400">{row.games}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-slate-400">
                  No rows cleared the minimum sample threshold for this hero.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
