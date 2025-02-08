import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Fetch API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Flask app setup
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Configure logging
logging.basicConfig(level=logging.DEBUG)

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

@app.route('/sql-query', methods=['POST'])
def generate_sql():
    """API endpoint to generate SQL query based on user input."""
    try:
        logging.info("Received request to /sql-query")
        data = request.get_json()
        logging.debug(f"Request JSON: {data}")

        if not data or "query" not in data:
            logging.warning("No 'query' field in request JSON")
            return jsonify({"error": "No query provided"}), 400

        user_query = data["query"]

        # Define table schema information
        table_info = """\
                    customer:
                        customer_key (TEXT, Primary Key): Unique identifier for each customer.
                        first_name (TEXT): Customer's first name.
                        last_name (TEXT): Customer's last name.
                        source_system_name (TEXT): Source system of customer data.
                        dob (DATE): Date of birth.
                        gender (TEXT): Gender.
                        create_timestamp (TIMESTAMP): Creation timestamp.

                    address:
                        address_key (TEXT, Primary Key): Unique identifier for each address.
                        full_address (TEXT): Full address (street, city, etc.).
                        state (TEXT): State or province.
                        country (TEXT): Country.
                        latitude (TEXT): Latitude.
                        longitude (TEXT): Longitude.

                    customer_address:
                        customer_key (TEXT, Foreign Key): Links to 'customer' table.
                        address_key (TEXT, Foreign Key): Links to 'address' table.
                        PRIMARY KEY (customer_key, address_key).

                    matches:
                        match_id (BIGINT, Primary Key): Unique identifier for each match.
                        start_time (INTEGER): Match start time.
                        duration (INTEGER): Duration of the match.
                        radiant_win (BOOLEAN): Indicates if the Radiant team won.

                    players:
                        match_id (BIGINT, Foreign Key): Links to 'matches' table.
                        account_id (BIGINT): Player's account identifier.
                        hero_id (INTEGER): Identifier for the hero used.
                        kills (INTEGER): Number of kills.
                        deaths (INTEGER): Number of deaths.
                        assists (INTEGER): Number of assists.
                        gold_per_min (INTEGER): Gold earned per minute.
                        xp_per_min (INTEGER): Experience points earned per minute.
                        PRIMARY KEY (match_id, account_id).

                    heroes:
                        hero_id (INTEGER, Primary Key): Unique identifier for each hero.
                        localized_name (TEXT): Hero's localized name.
                        primary_attr (TEXT): Primary attribute of the hero.
                        attack_type (TEXT): Type of attack (melee/ranged).

                    roles:
                        role_id (SERIAL, Primary Key): Unique identifier for each role.
                        role_name (TEXT): Name of the role (e.g., Carry, Support, etc.).

                    hero_roles:
                        hero_id (INTEGER, Foreign Key): Links to 'heroes' table.
                        role_id (INTEGER, Foreign Key): Links to 'roles' table.
                        PRIMARY KEY (hero_id, role_id).

                    items:
                        item_id (TEXT, Primary Key): Unique identifier for each item.
                        name (TEXT): Item name.
                        cost (INTEGER): Cost of the item.

                    teams:
                        team_id (INTEGER, Primary Key): Unique identifier for each team.
                        name (TEXT): Team name.
                        rating (FLOAT): Team rating.
                        wins (INTEGER): Number of wins.
                        losses (INTEGER): Number of losses.
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

        return jsonify({"sql": sql_query})

    except Exception as e:
        logging.error(f"Server error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
