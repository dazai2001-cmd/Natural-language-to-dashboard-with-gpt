const BACKEND_URLS = process.env.BACKEND_URL
  ? [process.env.BACKEND_URL]
  : ["http://127.0.0.1:5001", "http://127.0.0.1:5000"];

export async function GET(request: Request) {
  const hero = new URL(request.url).searchParams.get("hero");
  let response: Response | null = null;
  let lastConnectionError: unknown = null;

  for (const backendUrl of BACKEND_URLS) {
    try {
      const url = new URL(`${backendUrl}/meta-dashboard`);
      if (hero) url.searchParams.set("hero", hero);
      response = await fetch(url, {
        cache: "no-store",
        signal: AbortSignal.timeout(20_000),
      });
      break;
    } catch (connectionError) {
      lastConnectionError = connectionError;
    }
  }

  if (!response) {
    const message = lastConnectionError instanceof Error
      ? lastConnectionError.message
      : "No analytics backend was reachable.";
    return Response.json({ error: message }, { status: 502 });
  }

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    return Response.json(
      { error: data?.error ?? `Analytics backend returned ${response.status}.` },
      { status: response.status },
    );
  }

  return Response.json(data);
}
