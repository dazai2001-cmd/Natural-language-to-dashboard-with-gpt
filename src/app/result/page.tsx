"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Bar, Line, Pie, Scatter } from "react-chartjs-2";
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, PointElement, LineElement, ArcElement, Tooltip, Legend } from "chart.js";

// Register Chart.js components
ChartJS.register(CategoryScale, LinearScale, BarElement, PointElement, LineElement, ArcElement, Tooltip, Legend);

export default function Result() {
  const searchParams = useSearchParams();
  const query = searchParams.get("query");
  
  const [sqlQuery, setSqlQuery] = useState<string>("");
  const [results, setResults] = useState<any[]>([]);
  const [chartType, setChartType] = useState<string>("");
  const [chartData, setChartData] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!query) return;

    setLoading(true);
    setError("");

    fetch("/api/sql-query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: query }),
    })
      .then((res) => res.json())
      .then((data) => {
        setSqlQuery(data.sql || "No query generated");
        setResults(data.results || []);
        setChartType(data.chart_type || "");
        setChartData(data.chart_data || null);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Error fetching SQL query:", err);
        setError("Failed to generate SQL query. Please try again.");
        setLoading(false);
      });
  }, [query]);

  const renderChart = () => {
    if (!chartData || !chartType) return null;
  
    // Base chart props that are common across all chart types
    const chartProps = {
      data: chartData,
      options: { responsive: true, plugins: { legend: { position: "top" } } },
    };
  
    switch (chartType) {
      case "bar":
        chartProps.options = {
          ...chartProps.options,
          scales: {
            x: {
              // Customize x-axis for bar chart
              title: {
                display: true,
                text: "Category",
              },
            },
            y: {
              // Customize y-axis for bar chart
              title: {
                display: true,
                text: "Value",
              },
              beginAtZero: true,
            },
          },
        };
        return <Bar {...chartProps} />;
  
      case "line":
        chartProps.options = {
          ...chartProps.options,
          scales: {
            x: {
              // Customize x-axis for line chart
              title: {
                display: true,
                text: "Time",
              },
            },
            y: {
              // Customize y-axis for line chart
              title: {
                display: true,
                text: "Value",
              },
            },
          },
          elements: {
            line: {
              tension: 0.4, // Curvature of line
            },
          },
        };
        return <Line {...chartProps} />;
  
      case "pie":
        chartProps.options = {
          ...chartProps.options,
          plugins: {
            ...chartProps.options.plugins,
            tooltip: {
              callbacks: {
                label: (tooltipItem) => {
                  return `${tooltipItem.label}: ${tooltipItem.raw}%`;
                },
              },
            },
          },
          cutoutPercentage: 50, // Pie chart center hole percentage (can make it a donut chart)
        };
        return <Pie {...chartProps} />;
  
      case "scatter":
        chartProps.options = {
          ...chartProps.options,
          scales: {
            x: {
              // Customize x-axis for scatter chart
              title: {
                display: true,
                text: "X-Axis Label",
              },
            },
            y: {
              // Customize y-axis for scatter chart
              title: {
                display: true,
                text: "Y-Axis Label",
              },
            },
          },
        };
        return <Scatter {...chartProps} />;
  
      default:
        return null;
    }
  };
  

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
                    <tbody className="text-black">
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

            {chartData && chartType && (
              <div className="mt-6 w-full max-w-lg">
                <h2 className="text-xl text-green-500 font-semibold mb-2">Visualization</h2>
                {renderChart()}
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
