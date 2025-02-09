import os, re
import logging
import psycopg2
import json
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Fetch API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
POSTGRES_PASS = os.getenv("POSTGRES_PASS")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Flask app setup
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# PostgreSQL connection
conn = psycopg2.connect(
    dbname="puppet_db",
    user="postgres",
    password=POSTGRES_PASS,
    host="localhost",
    port="5432"
)

def generate_sql_query(user_question: str) -> str:
    prompt = f"""
    You are a PostgreSQL expert specialized in Dota 2 analytics. Generate an SQL query based on this schema:

    - **matches** (match_id, start_time, duration, radiant_win)
    - **players** (match_id, account_id, hero_id, kills, deaths, assists, gold_per_min, xp_per_min)
    - **heroes** (hero_id, localized_name, primary_attr, attack_type, roles)
    - **items** (item_id, name, cost, description)
    - **teams** (team_id, name, rating, wins, losses)

    **Question:** {user_question}

    - Use correct **JOINs** between tables.
    - Ensure correct **GROUP BY** and **ORDER BY** when needed.
    - Always **limit results to 10 rows** unless specified otherwise.

    **Return ONLY the SQL query. No explanations.**
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert PostgreSQL database assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        
        sql_query = response.choices[0].message.content.strip()

        # 🚀 Remove markdown-style backticks (` ```sql ` and ` ``` `)
        sql_query = re.sub(r"```sql|```", "", sql_query).strip()

        print(f"🔍 Cleaned SQL Query:\n{sql_query}")

        return sql_query
    except Exception as e:
        print(f"❌ OpenAI Error: {e}")
        return None

def execute_query(query: str):
    """Execute SQL query on PostgreSQL database and return results."""
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            columns = [desc[0] for desc in cur.description]  # Get column names
            rows = cur.fetchall()  # Fetch all results

            # Convert to list of dicts
            results = [dict(zip(columns, row)) for row in rows]
            return results
    except Exception as e:
        logging.error(f"Database query execution error: {str(e)}")
        return {"error": str(e)}

def decide_chart_type(df):
    

    prompt = f"""
    Given the following SQL query result, determine the best chart type.

    **SQL Result:**  
    {df.to_dict(orient="records")}

    Choose one:
    - "bar" (for category-based comparisons, like top heroes by kills)
    - "line" (for trends over time)
    - "pie" (for percentage-based distribution)
    - "scatter" (for numeric relationships, like kills vs GPM)

    **Return only the chart type. No explanations.**
    """
    
    try:
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ OpenAI Error (Chart Type): {e}")
        return "bar"

# OpenAI - Convert Data for Chart.js (Fixed for OpenAI v1.0+)
def transform_data_for_chart(chart_type, sql_result):
    prompt = f"""
    Convert the following SQL result into a JSON format for a `{chart_type}` chart.

    **SQL Result:**  
    {sql_result.to_dict(orient="records")}

    Ensure the response is **valid JSON** matching Chart.js format:
    - **Bar Chart:**
      {{
        "labels": ["Category1", "Category2"],
        "datasets": [{{
          "data": [value1, value2], 
          "label": "Metric"
        }}]
      }}
    - **Line Chart:**
      {{
        "labels": ["Time1", "Time2"],
        "datasets": [{{
          "data": [value1, value2], 
          "label": "Trend"
        }}]
      }}
    - **Pie Chart:**
      {{
        "labels": ["Category1", "Category2"],
        "datasets": [{{
          "data": [value1, value2]
        }}]
      }}

    **Return only valid JSON. No explanations.**
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a Chart.js data formatting assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        json_data = response.choices[0].message.content.strip()

        # Validate JSON
        json.loads(json_data)
        return json_data
    except Exception as e:
        print(f"❌ OpenAI Error (Chart Data): {e}")
        return '{"labels": [], "datasets": []}'

@app.route('/sql-query', methods=['POST'])
def generate_sql():
    """API endpoint to generate and execute SQL query."""
    try:
        logging.info("Received request to /sql-query")
        data = request.get_json()
        logging.debug(f"Request JSON: {data}")

        if not data or "query" not in data:
            logging.warning("No 'query' field in request JSON")
            return jsonify({"error": "No query provided"}), 400

        user_query = data["query"]

        # Define table schema information
        table_info = r"""
            matches:
                match_id (BIGINT, Primary Key), start_time (INTEGER), duration (INTEGER), radiant_win (BOOLEAN).
            players:
                match_id (BIGINT, Foreign Key), account_id (BIGINT), hero_id (INTEGER),
                kills (INTEGER), deaths (INTEGER), assists (INTEGER), gold_per_min (INTEGER), xp_per_min (INTEGER).
            heroes:
                hero_id (INTEGER, Primary Key), localized_name (TEXT), primary_attr (TEXT), attack_type (TEXT).
            roles:
                role_id (SERIAL, Primary Key), role_name (TEXT).
            hero_roles:
                hero_id (INTEGER, Foreign Key), role_id (INTEGER, Foreign Key).
            items:
                item_id (TEXT, Primary Key), name (TEXT), cost (INTEGER).
            teams:
                team_id (INTEGER, Primary Key), name (TEXT), rating (FLOAT), wins (INTEGER), losses (INTEGER).
            """

        # Construct the OpenAI prompt
        base_prompt = f"""
        You are an expert in writing PostgreSQL queries. Given a user question, generate a syntactically correct SQL query. 
        Ensure case-insensitive searches and limit results to 10 rows unless specified otherwise.

        Relevant Table Information:
        {table_info}

        User Query: {user_query}

        Guidelines:
        - Always add 'LIMIT 10' unless counting or aggregating.
        - Include latitude/longitude for address-related queries.
        - Ensure correct joins between tables.

        Return ONLY the SQL query with NO explanations.
        """

        # Generate SQL query using OpenAI
        sql_query = generate_sql_query(base_prompt)
        logging.info(f"Generated SQL Query: {sql_query}")

        # Execute the query on the PostgreSQL database
        query_results = execute_query(sql_query)
        print(query_results)

        df = pd.DataFrame(query_results)
        # Determine Best Chart Type
        chart_type = decide_chart_type(df)

        chart_data = transform_data_for_chart(chart_type, df)

        print(f"📊 Generated Chart.js Data:\n{chart_data}")

        return jsonify({"sql": sql_query, "results": query_results, "chart_type": chart_type, "chart_data": chart_data})

    except Exception as e:
        logging.error(f"Server error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
