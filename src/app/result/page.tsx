"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

export default function Result() {
  const searchParams = useSearchParams();
  const query = searchParams.get("query");
  const [sqlQuery, setSqlQuery] = useState("");

  useEffect(() => {
    if (query) {
      fetch("/api/sql-query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      })
        .then((res) => res.json())
        .then((data) => setSqlQuery(data.sql || "No query generated"))
        .catch((err) => console.error("Error fetching SQL query:", err));
    }
  }, [query]);

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-background">
      <h1 className="text-3xl text-green-500 mb-4">
        Generated query
      </h1>

      <div className="bg-white p-8 rounded-2xl shadow-md w-3/4 max-w-2xl text-center">
        <p className="text-green-500">{query}</p>
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
