"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const [inputText, setInputText] = useState("");
  const router = useRouter();

  const handleKeyDown = async (e) => {
    if (e.key === "Enter") {
      // Send the input question to the API and get the generated SQL query
      const response = await fetch("/api/sql-query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ question: inputText }),
      });
      
      const data = await response.json();

      // Pass the generated SQL query as a query param to the results page
      if (data.sqlQuery) {
        router.push(`/result?query=${encodeURIComponent(data.sqlQuery)}`);
      } else {
        console.error("Failed to generate SQL query.");
      }
    }
  };

  return (
    <div className="flex items-center justify-center h-screen">
      <input
        type="text"
        className="block mx-auto my-5 p-2 border rounded w-full max-w-4xl h-20 text-center text-3xl text-green-500"
        placeholder="What do you want to see plotted?"
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
        onKeyDown={handleKeyDown}
      />
    </div>
  );
}
