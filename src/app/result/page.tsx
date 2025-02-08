"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

export default function Result() {
  const searchParams = useSearchParams();
  const query = searchParams.get("query");
  const [sqlQuery, setSqlQuery] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!query) return;

    setLoading(true);
    setError(""); // Reset error message before new fetch

    fetch("/api/sql-query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    })
      .then((res) => res.json())
      .then((data) => {
        setSqlQuery(data.sql || "No query generated");
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
      <h1 className="text-3xl text-green-500 mb-4">Generated SQL Query</h1>

      <div className="bg-white p-8 rounded-2xl shadow-md w-full max-w-5xl h-[60vh] overflow-auto text-center">
        {loading ? (
          <p className="text-green-500">Generating SQL query...</p>
        ) : error ? (
          <p className="text-red-500">{error}</p>
        ) : (
          <>
            <p className="text-green-500 font-semibold mb-4">Your Question:</p>
            <p className="text-gray-700 mb-6">{query}</p>
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
