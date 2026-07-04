const BACKEND_URLS = process.env.BACKEND_URL
  ? [process.env.BACKEND_URL]
  : ["http://127.0.0.1:5001", "http://127.0.0.1:5000"];

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));

  for (const backendUrl of BACKEND_URLS) {
    try {
      const response = await fetch(`${backendUrl}/import/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
        signal: AbortSignal.timeout(15_000),
      });
      const data = await response.json().catch(() => null);
      return Response.json(data, { status: response.status });
    } catch {
      // Try the next backend URL.
    }
  }

  return Response.json({ error: "No analytics backend was reachable." }, { status: 502 });
}
