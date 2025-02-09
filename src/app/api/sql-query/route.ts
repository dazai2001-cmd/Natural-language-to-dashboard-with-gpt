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

        // Check if the response contains required fields
        if (
            !data.sql ||
            !data.results ||
            !data.chart_type ||
            !data.chart_data ||
            typeof data.chart_data !== "string"
        ) {
            throw new Error("Invalid response format from Flask");
        }

        // Parse chart_data (which is a JSON string) into an object
        let chartData;
        try {
            chartData = JSON.parse(data.chart_data);
        } catch (e) {
            throw new Error("Failed to parse chart_data JSON");
        }

        // Return the SQL query, the query results, and chart data in a structured format
        return new Response(
            JSON.stringify({
                sql: data.sql,
                results: data.results,
                chart_type: data.chart_type,
                chart_data: chartData, // Include parsed chart_data
            }),
            {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }
        );
    } catch (error) {
        console.error("Error calling Flask server:", error);
        return new Response(
            JSON.stringify({ error: "Failed to fetch results from the database." }),
            {
                status: 500,
                headers: { "Content-Type": "application/json" },
            }
        );
    }
}
