"use server";

export async function POST(req: Request) {
    try {
        const body = await req.json(); // Parse JSON request
        console.log("Sending request to Flask:", body);

        const response = await fetch("http://127.0.0.1:5000/sql-query", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ query: body.question }),
        });

        console.log("Flask response status:", response.status);

        if (!response.ok) {
            throw new Error(`Flask server error: ${response.statusText}`);
        }

        const data = await response.json();
        console.log("Flask response data:", data);

        // Check if the response contains results
        if (!data.sql || !data.results) {
            throw new Error("Invalid response format from Flask");
        }

        // Return the SQL query and the query results in a structured format
        return new Response(JSON.stringify({
            sql: data.sql,
            results: data.results
        }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });

    } catch (error) {
        console.error("Error calling Flask server:", error);
        return new Response(JSON.stringify({ error: "Failed to fetch results from the database." }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
        });
    }
}
