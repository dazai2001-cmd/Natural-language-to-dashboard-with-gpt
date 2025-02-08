import os
import psycopg2
import pandas as pd
import openai
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# PostgreSQL Connection Config
DB_CONFIG = {
    'dbname': os.getenv('DB_NAME', 'mydatabase'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', ''),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432')
}

# Initialize Flask App
app = Flask(__name__)
CORS(app)  # Allow Cross-Origin Requests for Next.js

# Function to Connect to PostgreSQL and Execute Query
def execute_query(query):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except Exception as e:
        print(f"❌ Database Error: {e}")
        return pd.DataFrame()

# OpenAI - Generate SQL Query
def generate_sql(user_question):
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
        response = openai.Completion.create(
            model="gpt-4",
            prompt=prompt,
            max_tokens=150
        )
        sql_query = response['choices'][0]['text'].strip()
        print(f"🔍 Generated SQL Query:\n{sql_query}")
        return sql_query
    except Exception as e:
        print(f"❌ OpenAI Error: {e}")
        return None

# OpenAI - Decide Best Chart Type
def decide_chart_type(sql_result):
    prompt = f"""
    Given the following SQL query result, determine the best chart type.

    **SQL Result:**  
    {sql_result.to_dict(orient="records")}

    Choose one:
    - "bar" (for category-based comparisons, like top heroes by kills)
    - "line" (for trends over time)
    - "pie" (for percentage-based distribution)
    - "scatter" (for numeric relationships, like kills vs GPM)

    **Return only the chart type. No explanations.**
    """
    
    try:
        response = openai.Completion.create(
            model="gpt-4",
            prompt=prompt,
            max_tokens=20
        )
        return response['choices'][0]['text'].strip()
    except Exception as e:
        print(f"❌ OpenAI Error (Chart Type): {e}")
        return "bar"

# OpenAI - Convert Data for Chart.js
def transform_data_for_chart(chart_type, sql_result):
    prompt = f"""
    Convert the following SQL result into a JSON format for a `{chart_type}` chart.

    **SQL Result:**  
    {sql_result.to_dict(orient="records")}

    Ensure the response is **valid JSON** matching Chart.js format:
    - **Bar Chart:**
      ```json
      {{"labels": ["Category1", "Category2"], "datasets": [{{"data": [value1, value2], "label": "Metric"}}]}}
      ```
    - **Line Chart:**
      ```json
      {{"labels": ["Time1", "Time2"], "datasets": [{{"data": [value1, value2], "label": "Trend"}}]}}
      ```
    - **Pie Chart:**
      ```json
      {{"labels": ["Category1", "Category2"], "datasets": [{{"data": [value1, value2]}}]}}
      ```

    **Return only valid JSON. No explanations.**
    """
    
    try:
        response = openai.Completion.create(
            model="gpt-4",
            prompt=prompt,
            max_tokens=200
        )
        json_data = response['choices'][0]['text'].strip()

        # Validate JSON
        json.loads(json_data)
        return json_data
    except Exception as e:
        print(f"❌ OpenAI Error (Chart Data): {e}")
        return '{"labels": [], "datasets": []}'

# API: Handle User Input
@app.route('/api/generate-chart', methods=['POST'])
def generate_chart():
    user_question = request.json.get('question')

    # Generate SQL Query
    sql_query = generate_sql(user_question)
    if not sql_query:
        return jsonify({"error": "Failed to generate SQL query."}), 500

    # Execute Query
    df = execute_query(sql_query)

    if df.empty:
        return jsonify({"error": "No data found."}), 400

    # Determine Best Chart Type
    chart_type = decide_chart_type(df)

    # Convert Data to Chart.js Format
    chart_data = transform_data_for_chart(chart_type, df)

    return jsonify({"chart_type": chart_type, "chart_data": chart_data})

# Run Flask Server
if __name__ == '__main__':
    app.run(debug=True, port=5000)