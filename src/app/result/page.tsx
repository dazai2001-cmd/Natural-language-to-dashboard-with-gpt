"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

export default function Result() {
  const searchParams = useSearchParams();
  const query = searchParams.get("query");
  
  const [sqlQuery, setSqlQuery] = useState<string>("");
  const [results, setResults] = useState<any[]>([]); // Store query results
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!query) return;

    setLoading(true);
    setError(""); // Reset error message before new fetch

    fetch("/api/sql-query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: query }), // Make sure this matches the backend format
    })
      .then((res) => res.json())
      .then((data) => {
        setSqlQuery(data.sql || "No query generated");
        setResults(data.results || []); // Store query results
        setLoading(false);
      })
      .catch((err) => {
        console.error("Error fetching SQL query:", err);
        setError("Failed to generate SQL query. Please try again.");
        setLoading(false);
      });
  }, [query]);

  return (
    <div className="flex flex-col items-center justify-center h-[80vh] bg-background w-full px-4">
      <h1 className="text-3xl font-semibold text-green-500 mb-4">Results Dashboard</h1>

      <div className="bg-white p-8 rounded-2xl shadow-md w-full max-w-5xl h-[60vh] overflow-auto text-center">
        {loading ? (
          <p className="text-green-500">loading...</p>
        ) : error ? (
          <p className="text-red-500">{error}</p>
        ) : (
          <>
            <p className="text-xl text-green-500 font-semibold mb-2">Generated SQL:</p>
            <pre className="bg-gray-100 p-4 rounded-md text-sm text-gray-800 overflow-auto">
              {sqlQuery}
            </pre>

            {/* Display Query Results */}
            {results.length > 0 && (
              <div className="mt-6">
                <h2 className="text-xl text-green-500 font-semibold mb-2">Query Results</h2>
                <div className="overflow-x-auto">
                  <table className="w-full border border-gray-300 text-left text-sm">
                    <thead className="bg-green-500 text-white">
                      <tr>
                        {Object.keys(results[0]).map((col) => (
                          <th key={col} className="px-4 py-2 border">{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {results.map((row, index) => (
                        <tr key={index} className="border">
                          {Object.values(row).map((val, idx) => (
                            <td key={idx} className="px-4 py-2 border">{val}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <button
        onClick={() => window.location.href = "/"}
        className="absolute bottom-8 left-1/2 transform -translate-x-1/2 px-6 py-2 bg-green-500 text-white text-lg rounded-full hover:bg-green-600 transition duration-200"
      >
        Start Over
      </button>
    </div>
  );
}
