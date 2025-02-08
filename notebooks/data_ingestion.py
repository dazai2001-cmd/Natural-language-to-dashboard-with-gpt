import requests
import pandas as pd
import psycopg2
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Load environment variables from .env file
load_dotenv(dotenv_path='../.env')
POSTGRES_PASS = os.getenv("POSTGRES_PASS")

# PostgreSQL connection string for SQLAlchemy
DATABASE_URL = f"postgresql://postgres:{POSTGRES_PASS}@localhost:5432/puppet_db"

# Create SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Connect to PostgreSQL using psycopg2 (you can keep this if needed for other operations)
conn = psycopg2.connect(
    dbname="puppet_db",
    user="postgres",
    password=POSTGRES_PASS,
    host="localhost",
    port="5432"
)

# OpenDota API Base URL
OPENDOTA_API_BASE = "https://api.opendota.com/api"

# Fetch Data from OpenDota API
def fetch_data(endpoint):
    """Fetches data from OpenDota API."""
    url = f"{OPENDOTA_API_BASE}/{endpoint}"
    response = requests.get(url)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"❌ Error fetching {endpoint}: {response.status_code}")
        return None

def fetch_public_matches_data(endpoint):
    params = {
        "min_rank": 50,  # Legend Rank minimum
        "max_rank": 65,  # Ancient Rank maximum
        "mmr_descending": 1  # Order by highest MMR first
    }
    API_URL = f"{OPENDOTA_API_BASE}/{endpoint}"
    response = requests.get(API_URL, params=params)

    if response.status_code == 200:
        print("resp 200 for pubmatches")
        return response.json()
    else:
        print(f"❌ Error fetching {endpoint}: {response.status_code}")
        return None

# Store Data in PostgreSQL using pandas with SQLAlchemy engine
def save_to_postgres(df, table_name):
    """Saves data to PostgreSQL using pandas and SQLAlchemy."""
    try:
        df.to_sql(table_name, engine, if_exists='replace', index=False)
        print(f"✅ Inserted {len(df)} records into {table_name}")
    except Exception as e:
        print(f"❌ Error inserting data into {table_name}: {e}")

# Fetch and Store Heroes with Roles (Split roles into a separate table)
def fetch_and_store_heroes():
    heroes = fetch_data("heroes")
    if heroes:
        hero_data = []
        role_data = set()  # Using set to avoid duplicate roles
        hero_role_data = []

        for h in heroes:
            hero_data.append({
                "hero_id": h["id"],
                "localized_name": h["localized_name"],
                "primary_attr": h["primary_attr"],
                "attack_type": h["attack_type"]
            })

            for role in h["roles"]:
                role_data.add(role)  # Add role to set (unique)
                hero_role_data.append({
                    "hero_id": h["id"],
                    "role_name": role
                })

        # Insert roles into the database
        df_roles = pd.DataFrame(list(role_data), columns=["role_name"])
        save_to_postgres(df_roles, "roles")

        # Insert heroes into the database
        df_heroes = pd.DataFrame(hero_data)
        save_to_postgres(df_heroes, "heroes")

        # Insert hero_roles into the database
        hero_role_df = pd.DataFrame(hero_role_data)
        save_to_postgres(hero_role_df, "hero_roles")

# Fetch and Store Items (Remove description column)
def fetch_and_store_items():
    items = fetch_data("constants/items")
    if items:
        item_data = [
            {
                "item_id": key,
                "name": val.get("dname", key),
                "cost": val.get("cost", 0)
            }
            for key, val in items.items()
        ]
        df_items = pd.DataFrame(item_data)
        save_to_postgres(df_items, "items")

# Fetch and Store Teams
def fetch_and_store_teams():
    teams = fetch_data("teams")
    if teams:
        team_data = [
            {
                "team_id": t["team_id"],
                "name": t["name"],
                "rating": t["rating"],
                "wins": t["wins"],
                "losses": t["losses"]
            }
            for t in teams
        ]
        df_teams = pd.DataFrame(team_data)
        save_to_postgres(df_teams, "teams")


# Fetch and Store Matches
def fetch_and_store_matches():
    matches = fetch_public_matches_data("publicMatches")
    print("public match data fetched")
    if matches:
        match_data = []
        players_data = []
        for match in matches:
            match_id = match["match_id"]
            match_details = fetch_data(f"matches/{match_id}")

            if match_details:
                match_info = {
                    "match_id": match_details["match_id"],
                    "start_time": match_details["start_time"],
                    "duration": match_details["duration"],
                    "radiant_win": bool(match_details["radiant_win"])
                }
                match_data.append(match_info)

                for player in match_details["players"]:
                    player_info = {
                        "match_id": match_details["match_id"],
                        "account_id": player.get("account_id", 0),
                        "hero_id": player.get("hero_id", 0),
                        "kills": player.get("kills", 0),
                        "deaths": player.get("deaths", 0),
                        "assists": player.get("assists", 0),
                        "gold_per_min": player.get("gold_per_min", 0),
                        "xp_per_min": player.get("xp_per_min", 0)
                    }
                    players_data.append(player_info)

        df_matches = pd.DataFrame(match_data)
        df_players = pd.DataFrame(players_data)

        save_to_postgres(df_matches, "matches")
        save_to_postgres(df_players, "players")

# Main Execution
if __name__ == "__main__":
    print("🚀 Fetching and storing Dota 2 data...")

    # fetch_and_store_heroes()
    # fetch_and_store_items()
    # fetch_and_store_teams()
    fetch_and_store_matches()

    # Close the psycopg2 connection when done
    conn.close()
    print("✅ Data fetching and storage completed.")
