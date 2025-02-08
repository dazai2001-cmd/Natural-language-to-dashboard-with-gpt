from sqlalchemy import create_engine, MetaData, Table
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path='../.env')
POSTGRES_PASS = os.getenv("POSTGRES_PASS")

# PostgreSQL connection string
DATABASE_URL = f"postgresql://postgres:{POSTGRES_PASS}@localhost:5432/puppet_db"

# Create engine and metadata
engine = create_engine(DATABASE_URL)
metadata = MetaData()

# Reflect the heroes table
heroes_table = Table('heroes', metadata, autoload_with=engine)

# Drop the heroes table
heroes_table.drop(engine)

print("Heroes table has been dropped.")
