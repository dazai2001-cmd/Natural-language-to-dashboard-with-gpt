const BACKEND_URLS = process.env.BACKEND_URL
  ? [process.env.BACKEND_URL]
  : ["http://127.0.0.1:5001", "http://127.0.0.1:5000"];

export async function GET() {
  return Response.json({
    status: "ok",
    message: "Analytics API is alive. Send a POST request with JSON like { \"question\": \"what counters Pudge in Dota 2?\" }.",
    backends: BACKEND_URLS,
  });
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { question?: unknown };
    const question = typeof body.question === "string" ? body.question.trim() : "";

    if (!question) {
      return Response.json({ error: "A non-empty question is required." }, { status: 400 });
    }

    let response: Response | null = null;
    let lastConnectionError: unknown = null;

    for (const backendUrl of BACKEND_URLS) {
      try {
        response = await fetch(`${backendUrl}/sql-query`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question }),
          cache: "no-store",
          signal: AbortSignal.timeout(130_000),
        });
        break;
      } catch (connectionError) {
        lastConnectionError = connectionError;
      }
    }

    if (!response) {
      throw lastConnectionError instanceof Error
        ? lastConnectionError
        : new Error("No analytics backend was reachable.");
    }

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const message = data?.error ?? `Analytics backend returned ${response.status}.`;
      return Response.json({ error: message }, { status: response.status });
    }

    if (
      !data ||
      typeof data.sql !== "string" ||
      !Array.isArray(data.results) ||
      typeof data.chart_type !== "string" ||
      !data.chart_data
    ) {
      return Response.json({ error: "The analytics backend returned an invalid response." }, { status: 502 });
    }

    const chartData =
      typeof data.chart_data === "string" ? JSON.parse(data.chart_data) : data.chart_data;

    return Response.json({ ...data, chart_data: chartData });
  } catch (error) {
    console.error("Analytics API error:", error);
    const message = error instanceof Error && error.name === "TimeoutError"
      ? "The analytics request timed out. Please try again."
      : "Could not reach the analytics backend. Is Flask running on port 5001?";
    return Response.json({ error: message }, { status: 502 });
  }
}
