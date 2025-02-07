import { NextResponse } from "next/server";

export async function POST(req: Request) {
  try {
    const { query } = await req.json();

    const response = await fetch("http://localhost:5000/sql-query", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ query }),
    });

    if (!response.ok) {
      throw new Error(`Flask server error: ${response.statusText}`);
    }

    const data = await response.json();
    return NextResponse.json(data); // Send SQL response back to frontend
  } catch (error) {
    console.error("Error calling Flask server:", error);
    return NextResponse.json(
      { error: "Failed to generate SQL query" },
      { status: 500 }
    );
  }
}
