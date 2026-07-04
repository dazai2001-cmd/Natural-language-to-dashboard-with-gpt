const BACKEND_URLS = process.env.BACKEND_URL
  ? [process.env.BACKEND_URL]
  : ["http://127.0.0.1:5001", "http://127.0.0.1:5000"];

export async function GET() {
  for (const backendUrl of BACKEND_URLS) {
    try {
      const response = await fetch(`${backendUrl}/import/status`, {
        cache: "no-store",
        signal: AbortSignal.timeout(10_000),
      });
      const data = await response.json().catch(() => null);
      if (response.ok) return Response.json(data);
    } catch {
      // Try the next backend URL.
    }
  }

  return Response.json({ error: "No analytics backend was reachable." }, { status: 502 });
}
