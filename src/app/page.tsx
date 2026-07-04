import HomeDashboard, { MetaDashboard } from "@/components/HomeDashboard";

const BACKEND_URLS = process.env.BACKEND_URL
  ? [process.env.BACKEND_URL]
  : ["http://127.0.0.1:5001", "http://127.0.0.1:5000"];

async function loadMetaDashboard(): Promise<MetaDashboard | null> {
  for (const backendUrl of BACKEND_URLS) {
    try {
      const response = await fetch(`${backendUrl}/meta-dashboard`, {
        cache: "no-store",
        signal: AbortSignal.timeout(8_000),
      });
      if (!response.ok) continue;
      return (await response.json()) as MetaDashboard;
    } catch {
      // Try the next configured backend URL.
    }
  }
  return null;
}

export default async function Home() {
  const meta = await loadMetaDashboard();
  return <HomeDashboard initialMeta={meta} />;
}
