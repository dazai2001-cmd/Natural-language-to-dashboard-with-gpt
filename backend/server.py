import os
import re
import logging
import psycopg2
import json
import pandas as pd
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Fetch API keys
OR_API_KEY = os.getenv("OR_API_KEY")
POSTGRES_PASS = os.getenv("POSTGRES_PASS")

# OpenRouter API URL
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Flask app setup
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# PostgreSQL connection
conn = psycopg2.connect(
    dbname="mydatabase",
    user="postgres",
    password=POSTGRES_PASS,
    host="localhost",
    port="5432"
)

def generate_sql_query(user_question: str) -> str:
    """Generate an SQL query using OpenRouter Mistral 24B."""
    
    prompt = f"""
    You are a PostgreSQL expert specialized in Dota 2 analytics. Generate an SQL query based on this schema:

    - **matches** (match_id, start_time, duration, radiant_win)
    - **players** (match_id, account_id, hero_id, kills, deaths, assists, gold_per_min, xp_per_min)
    - **heroes** (hero_id, localized_name, primary_attr, attack_type, roles ARRAY)
    - **items** (item_id, name, cost, description)
    - **teams** (team_id, name, rating, wins, losses)

    **Question:** {user_question}

    ### SQL Query Guidelines:
    - **For date-related queries**, use `TO_CHAR(start_time, 'YYYY-MM')` for **monthly grouping** or `TO_CHAR(start_time, 'YYYY-MM-DD')` for **daily grouping** (no need to use `TO_TIMESTAMP` if `start_time` is already a timestamp).
    - **DO NOT use `UNNEST(h.roles)` in `JOIN`.** Instead, select it separately.
    - **Always ensure valid SQL syntax with `GROUP BY`.**
    - **Use `SUM(kills)` instead of `COUNT(hero_id)` for ranking.**
    - **DO NOT add extra unnecessary joins.**
    - **Return ONLY the SQL query. No explanations.**
    """


    headers = {
        "Authorization": f"Bearer {OR_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "mistralai/mistral-small-24b-instruct-2501:free",  # ✅ Ensure correct model name
        "messages": [
            {"role": "system", "content": "You are an expert PostgreSQL database assistant."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 300
    }

    try:
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=data)
        response.raise_for_status()  # Raises an exception for HTTP errors

        # 🚀 Log the full API response
        logging.debug(f"🔍 OpenRouter Raw Response: {response.text}")

        if not response.text.strip():
            logging.error("❌ OpenRouter returned an empty response.")
            return None

        json_response = response.json()

        # 🚀 Check if the response contains 'choices'
        if "choices" not in json_response or not json_response["choices"]:
            logging.error(f"❌ OpenRouter response missing 'choices': {json_response}")
            return None

        sql_query = json_response["choices"][0]["message"]["content"].strip()

        # Remove markdown-style backticks (` ```sql ` and ` ``` `)
        sql_query = re.sub(r"```sql|```", "", sql_query).strip()

        logging.info(f"✅ Generated SQL Query:\n{sql_query}")

        return sql_query
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ OpenRouter API Error: {e}")
        return None
    except json.JSONDecodeError:
        logging.error(f"❌ OpenRouter returned invalid JSON: {response.text}")
        return None


def execute_query(query: str):
    """Execute SQL query on PostgreSQL database and return results."""
    try:
        if not query:
            return {"error": "Generated SQL query is empty."}

        if conn.closed:
            logging.warning("🔄 Reconnecting to the database...")
            conn.reset()

        with conn.cursor() as cur:
            cur.execute(query)
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            
            results = [dict(zip(columns, row)) for row in rows]
            return results

    except psycopg2.OperationalError as e:
        logging.error(f"🚨 Database connection error: {str(e)}")
        return {"error": "Database connection issue. Please try again."}

    except psycopg2.ProgrammingError as e:
        logging.error(f"❌ SQL Execution Error: {str(e)}")
        return {"error": "Invalid SQL query. Please check your syntax."}

    except Exception as e:
        logging.error(f"💥 Unexpected error during query execution: {str(e)}")
        return {"error": str(e)}
    
def decide_chart_type(df):
    """Determine the best chart type based on the given DataFrame."""
    print("🔍 DataFrame for Chart Type Decision:\n", df.to_dict(orient="records"))

    # Detect column names and data types
    columns = df.columns.tolist()
    numeric_columns = [col for col in columns if pd.api.types.is_numeric_dtype(df[col])]
    categorical_columns = [col for col in columns if df[col].dtype == object]

    print(f"📊 Columns: {columns}")
    print(f"🔢 Numeric Columns: {numeric_columns}")
    print(f"🔠 Categorical Columns: {categorical_columns}")

    # 🔥 Use Scatter Plot if Exactly Two Numeric Columns Exist (for relationships)
    if len(numeric_columns) == 2:
        print("🔬 Numeric Relationship Detected → Using Scatter Chart")
        return "scatter"

    # 🔥 Use Line Chart if There’s a Time-Based Column
    time_keywords = ["date", "time", "month", "week", "year"]
    if any(any(keyword in col.lower() for keyword in time_keywords) for col in columns):
        print("📈 Detected Time-Based Data → Using Line Chart")
        return "line"

    # 🔥 Use Pie Chart ONLY IF the numeric values **sum to 100 or represent proportions**
    if len(categorical_columns) == 1 and len(numeric_columns) == 1:
        numeric_col = numeric_columns[0]

        # ✅ Ensure Pie Chart is only used when total sum ≈ 100 (percentage-based)
        total_value = df[numeric_col].sum()
        if 90 <= total_value <= 110:  # Allow a small margin of error
            print("🥧 Percentage-Based Data → Using Pie Chart")
            return "pie"

        # Otherwise, default to Bar Chart
        print("📊 Category Data → Using Bar Chart")
        return "bar"

    # 🔥 Default to Bar Chart
    print("📊 Defaulting to Bar Chart")
    return "bar"


def transform_data_for_chart(chart_type, sql_result):
    """Convert SQL result into a Chart.js JSON format based on chart type."""

    if sql_result.empty:
        print("⚠️ Empty DataFrame → Returning default empty chart data.")
        return '{"labels": [], "datasets": []}'

    labels = sql_result.iloc[:, 0].tolist()  # First column as labels (categories)
    data_values = sql_result.iloc[:, 1].tolist()  # Second column as values

    chart_data = {}

    if chart_type == "bar":
        chart_data = {
            "labels": labels,
            "datasets": [
                {
                    "label": "Total Kills",
                    "data": data_values
                }
            ]
        }

    elif chart_type == "line":
        chart_data = {
            "labels": labels,
            "datasets": [
                {
                    "label": "Trend Over Time",
                    "data": data_values,
                    "fill": False,
                    "borderColor": "blue",
                    "tension": 0.1
                }
            ]
        }

    elif chart_type == "pie":
        chart_data = {
            "labels": labels,
            "datasets": [
                {
                    "data": data_values,
                    "backgroundColor": ["red", "blue", "green", "yellow", "orange"]
                }
            ]
        }

    elif chart_type == "scatter":
        if sql_result.shape[1] < 3:  # Ensure at least 2 numeric columns
            return '{"error": "Scatter plot requires two numeric columns"}'

        x_values = sql_result.iloc[:, 1].tolist()  # Second column as X values
        y_values = sql_result.iloc[:, 2].tolist()  # Third column as Y values
        chart_data = {
            "datasets": [
                {
                    "label": "Scatter Plot Data",
                    "data": [{"x": x, "y": y} for x, y in zip(x_values, y_values)],
                    "backgroundColor": "blue"
                }
            ]
        }

    else:
        print(f"⚠️ Unknown chart type '{chart_type}', defaulting to bar chart.")
        chart_data = {
            "labels": labels,
            "datasets": [
                {
                    "label": "Data",
                    "data": data_values
                }
            ]
        }

    return json.dumps(chart_data)


@app.route('/sql-query', methods=['POST'])
def generate_sql():
    """API endpoint to generate and execute SQL query."""
    try:
        logging.info("📩 Received request to /sql-query")
        data = request.get_json()
        logging.debug(f"🔍 Request JSON: {data}")

        if not data or "query" not in data:
            logging.warning("⚠️ No 'query' field in request JSON")
            return jsonify({"error": "No query provided"}), 400

        user_query = data["query"]

        # Generate SQL query using OpenRouter
        sql_query = generate_sql_query(user_query)
        
        if not sql_query:
            logging.error("❌ Failed to generate SQL query.")
            return jsonify({"error": "SQL generation failed."}), 500

        logging.info(f"✅ Generated SQL Query:\n{sql_query}")

        # Execute the query on the PostgreSQL database
        query_results = execute_query(sql_query)
        
        if "error" in query_results:
            logging.error(f"❌ SQL Execution Error: {query_results['error']}")
            return jsonify({"error": query_results["error"]}), 500

        # Convert results to a DataFrame
        df = pd.DataFrame(query_results)

        # Determine Best Chart Type
        chart_type = decide_chart_type(df)

        logging.info(f"📊 Decided Chart Type: {chart_type}")

        return jsonify({
            "sql": sql_query,
            "results": query_results,
            "chart_type": chart_type  # ✅ Include chart type in the response
        })

    except Exception as e:
        logging.error(f"💥 Server error: {str(e)}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
