import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fetch API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Flask app setup
app = Flask(__name__)
CORS(app)  # Enable Cross-Origin Resource Sharing (CORS) for frontend access

def generate_sql_query(prompt: str) -> str:
    """Generate SQL query using OpenAI."""
    try:
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content.strip("```sql\n").strip("\n```")
    except Exception as e:
        return f"Error generating SQL query: {str(e)}"

@app.route('/sql-query', methods=['POST'])
def generate_sql():
    """API endpoint to generate SQL query based on user input."""
    try:
        data = request.get_json()
        user_query = data.get("query")

        if not user_query:
            return jsonify({"error": "No query provided"}), 400

        # Define table schema information
        table_info = """
        1. customer:
        - customer_key (TEXT, Primary Key): Unique identifier for each customer.
        - first_name (TEXT): Customer's first name.
        - last_name (TEXT): Customer's last name.
        - source_system_name (TEXT): Source system of customer data.
        - dob (DATE): Date of birth.
        - gender (TEXT): Gender.
        - create_timestamp (TIMESTAMP): Creation timestamp.

        2. address:
        - address_key (TEXT, Primary Key): Unique identifier for each address.
        - full_address (TEXT): Full address (street, city, etc.).
        - state (TEXT): State or province.
        - country (TEXT): Country.
        - latitude (TEXT): Latitude.
        - longitude (TEXT): Longitude.

        3. customer_address:
        - customer_key (TEXT, Foreign Key): Links to 'customer' table.
        - address_key (TEXT, Foreign Key): Links to 'address' table.
        - PRIMARY KEY (customer_key, address_key).
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

        return jsonify({"sql": sql_query})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
