import os
import sys
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path='.env')

# Fetch API keys and database credentials from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
POSTGRES_PASS = os.getenv("POSTGRES_PASS")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


def generate_sql_query(prompt: str) -> str:
    """Use OpenAI to generate SQL query based on prompt."""
    completion = client.chat.completions.create(
        model="gpt-4", 
        store=True,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    return completion.choices[0].message.content


def main():
    # Get input question from the command-line argument
    input_question = sys.argv[1] if len(sys.argv) > 1 else "Please enter your question: "

    # Define the table information for OpenAI to reference
    table_info = """
    Relevant Table Information:
    1. customer:
    - customer_key (TEXT, Primary Key): Unique identifier for each customer.
    - first_name (TEXT): Customer's first name.
    - last_name (TEXT): Customer's last name.
    - source_system_name (TEXT): The system from which the customer data originates.
    - dob (DATE): Customer's date of birth.
    - gender (TEXT): Customer's gender.
    - create_timestamp (TIMESTAMP): The timestamp when the customer was created in the system.

    2. address:
    - address_key (TEXT, Primary Key): Unique identifier for each address.
    - full_address (TEXT): The full address, including street, city, etc.
    - state (TEXT): The state or province of the address.
    - country (TEXT): The country of the address.
    - latitude (TEXT): The latitude of the address.
    - longitude (TEXT): The longitude of the address.

    3. customer_address:
    - customer_key (TEXT, Foreign Key): Refers to the unique identifier of a customer in the 'customer' table.
    - address_key (TEXT, Foreign Key): Refers to the unique identifier of an address in the 'address' table.
    - PRIMARY KEY (customer_key, address_key): Composite primary key.
    """
    
    # Define the prompt to be sent to OpenAI
    top_k = 10  # Limit results to 10 rows unless stated otherwise
    base_prompt = f"""
    You are a SQL expert with access to a BigQuery dataset containing customers and customer addresses.
    Given an input question, generate a syntactically correct SQL query to answer it. Unless explicitly requested otherwise, limit the results to {top_k} rows.

    Relevant Table Information:
    {table_info}

    Question: {input_question}

    Guidelines:
    1. Ensure that all attribute searches are case-insensitive.
    2. ALWAYS add 'LIMIT {top_k}' at the end of the query unless:
      - The question explicitly asks for all records
      - The query uses GROUP BY and needs to show all groups
      - The query is counting records (using COUNT)
      - The query calculates aggregates that need all data

    Address and Location Queries:
    1. For questions about addresses, locations, or properties, always include latitude and longitude columns in the SELECT clause.

    Double check the user's PostgreSQL query for common mistakes, including:
    - Using NOT IN with NULL values
    - Using UNION when UNION ALL should have been used
    - Using BETWEEN for exclusive ranges
    - Data type mismatch in predicates
    - Properly quoting identifiers
    - Using the correct number of arguments for functions
    - Casting to the correct data type
    - Using the proper columns for joins
    - Missing LIMIT clause when returning raw records

    If there are any of the above mistakes, rewrite the query.
    If there are no mistakes, just reproduce the original query with no further commentary.

    Provide only the final SQL query as plain text without any formatting.
    If the question is not about customers or addresses, respond with "I don't know"
    """

    # Generate SQL query from OpenAI
    sql_non_parsed = generate_sql_query(base_prompt)
    sql_query = sql_non_parsed.strip('```sql\n').strip('\n```')
    
    # Print the final SQL query (will be captured by the Next.js API route)
    print(sql_query)


if __name__ == "__main__":
    main()
