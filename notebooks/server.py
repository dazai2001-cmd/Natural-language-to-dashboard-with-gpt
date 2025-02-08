import os
import logging
import psycopg2
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

def generate_sql_query(prompt: str) -> str:
    """Generate SQL query using OpenAI."""
    try:
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content.strip("```sql\n").strip("\n```")
    except Exception as e:
        logging.error(f"Error generating SQL query: {str(e)}")
        return f"Error generating SQL query: {str(e)}"

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

        return jsonify({"sql": sql_query, "results": query_results})

    except Exception as e:
        logging.error(f"Server error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
