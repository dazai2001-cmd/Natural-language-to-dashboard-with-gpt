"use server";

export async function POST(req: Request) {
    try {
        const body = await req.json(); // Ensure we get JSON data
        console.log("Sending request to Flask:", body);
        console.log("Received request body:", body); // Log the incoming request body

        const response = await fetch("http://127.0.0.1:5000/sql-query", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ query: body.question }), // Use body.question instead of query
        });

        console.log("Flask response status:", response.status); // Log the response status

        if (!response.ok) {
            throw new Error(`Flask server error: ${response.statusText}`);
        }

        const data = await response.json();
        console.log("Flask response data:", data); // Log the response data
        return new Response(JSON.stringify(data), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });

    } catch (error) {
        console.error("Error calling Flask server:", error);
        return new Response(JSON.stringify({ error: "Failed to generate SQL query." }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
        });
    }
}
