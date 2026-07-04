"""Import a reproducible year-scale sample of high-skill OpenDota public matches.

The default target is 12 matches per week across the trailing 385 days. The
extra edge coverage ensures the stored observations span at least 365 days.
That is roughly 6,000-6,500 player rows: large enough for this dashboard while
remaining practical for a local PostgreSQL database and a rate-limited API.
"""

import argparse
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import requests
from dotenv import load_dotenv


API_BASE = "https://api.opendota.com/api"


SCHEMA_MIGRATION_SQL = """
ALTER TABLE matches
    ADD COLUMN IF NOT EXISTS patch integer,
    ADD COLUMN IF NOT EXISTS radiant_score integer,
    ADD COLUMN IF NOT EXISTS dire_score integer,
    ADD COLUMN IF NOT EXISTS avg_rank_tier integer,
    ADD COLUMN IF NOT EXISTS game_mode integer,
    ADD COLUMN IF NOT EXISTS lobby_type integer;

ALTER TABLE players
    ADD COLUMN IF NOT EXISTS player_slot integer,
    ADD COLUMN IF NOT EXISTS is_radiant boolean,
    ADD COLUMN IF NOT EXISTS is_winner boolean,
    ADD COLUMN IF NOT EXISTS win integer,
    ADD COLUMN IF NOT EXISTS lose integer,
    ADD COLUMN IF NOT EXISTS lane integer,
    ADD COLUMN IF NOT EXISTS lane_role integer,
    ADD COLUMN IF NOT EXISTS is_roaming boolean,
    ADD COLUMN IF NOT EXISTS item_0 integer,
    ADD COLUMN IF NOT EXISTS item_1 integer,
    ADD COLUMN IF NOT EXISTS item_2 integer,
    ADD COLUMN IF NOT EXISTS item_3 integer,
    ADD COLUMN IF NOT EXISTS item_4 integer,
    ADD COLUMN IF NOT EXISTS item_5 integer,
    ADD COLUMN IF NOT EXISTS backpack_0 integer,
    ADD COLUMN IF NOT EXISTS backpack_1 integer,
    ADD COLUMN IF NOT EXISTS backpack_2 integer,
    ADD COLUMN IF NOT EXISTS item_neutral integer,
    ADD COLUMN IF NOT EXISTS ability_upgrades_arr integer[];

CREATE INDEX IF NOT EXISTS idx_players_match_id ON players(match_id);
CREATE INDEX IF NOT EXISTS idx_players_hero_id ON players(hero_id);
CREATE INDEX IF NOT EXISTS idx_players_match_side ON players(match_id, is_radiant);
CREATE INDEX IF NOT EXISTS idx_matches_start_time ON matches(start_time);
CREATE INDEX IF NOT EXISTS idx_matches_patch ON matches(patch);
"""


class OpenDotaClient:
    def __init__(self, delay: float, max_calls: int):
        self.delay = delay
        self.max_calls = max_calls
        self.calls = 0
        self.api_key = os.getenv("OPENDOTA_API_KEY")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "puppet-dashboard-yearly-import/1.0"

    def get(self, endpoint: str, params: dict | None = None):
        if self.calls >= self.max_calls:
            raise RuntimeError(f"Stopped at the configured API-call ceiling ({self.max_calls}).")

        request_params = dict(params or {})
        if self.api_key:
            request_params["api_key"] = self.api_key

        for attempt in range(5):
            self.calls += 1
            response = self.session.get(
                f"{API_BASE}/{endpoint}", params=request_params, timeout=45
            )
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 5 * (attempt + 1)))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            time.sleep(self.delay)
            return response.json()
        raise RuntimeError(f"OpenDota continued to rate-limit {endpoint} after retries.")


def database_connection():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "mydatabase"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASS"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
    )


def collect_weekly_sample(
    client: OpenDotaClient, cutoff: datetime, per_week: int
) -> list[dict]:
    selected = []
    now = datetime.now(timezone.utc)
    week_start = cutoff
    week_number = 1
    while week_start < now:
        week_end = min(now, week_start + timedelta(days=7))
        sql = f"""
            SELECT match_id, start_time
            FROM public_matches
            WHERE start_time >= {int(week_start.timestamp())}
              AND start_time < {int(week_end.timestamp())}
              AND avg_rank_tier >= 70
            ORDER BY start_time
            LIMIT {int(per_week)}
        """
        payload = client.get("explorer", {"sql": sql})
        rows = payload.get("rows", [])
        selected.extend(rows)
        print(
            f"Sample week {week_number:02d} ({week_start.date()}): {len(rows)} matches",
            flush=True,
        )
        week_start = week_end
        week_number += 1
    return sorted(selected, key=lambda match: match["start_time"])


def existing_match_ids(connection, match_ids: list[int]) -> set[int]:
    if not match_ids:
        return set()
    with connection.cursor() as cursor:
        cursor.execute("SELECT match_id FROM matches WHERE match_id = ANY(%s)", (match_ids,))
        return {row[0] for row in cursor.fetchall()}


def matches_needing_enrichment(connection, match_ids: list[int]) -> set[int]:
    if not match_ids:
        return set()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT match_id
            FROM players
            WHERE match_id = ANY(%s)
              AND (player_slot IS NULL OR is_radiant IS NULL OR is_winner IS NULL)
            """,
            (match_ids,),
        )
        return {row[0] for row in cursor.fetchall()}


def all_existing_matches_needing_enrichment(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT m.match_id, EXTRACT(EPOCH FROM m.start_time)::bigint AS start_time
            FROM matches m
            WHERE EXISTS (
                SELECT 1
                FROM players p
                WHERE p.match_id = m.match_id
                  AND (p.player_slot IS NULL OR p.is_radiant IS NULL OR p.is_winner IS NULL)
            )
            ORDER BY m.start_time, m.match_id
            """
        )
        return [
            {"match_id": row[0], "start_time": row[1]}
            for row in cursor.fetchall()
        ]


def player_is_radiant(player: dict) -> bool | None:
    if "isRadiant" in player:
        return bool(player["isRadiant"])
    player_slot = player.get("player_slot")
    if player_slot is None:
        return None
    return int(player_slot) < 128


def player_is_winner(player: dict, radiant_win: bool | None) -> bool | None:
    if "win" in player:
        return bool(player.get("win"))
    is_radiant = player_is_radiant(player)
    if is_radiant is None or radiant_win is None:
        return None
    return is_radiant == bool(radiant_win)


def store_match(connection, details: dict):
    match_id = details["match_id"]
    start_time = datetime.fromtimestamp(details["start_time"], timezone.utc).replace(tzinfo=None)
    radiant_win = details.get("radiant_win")
    players = [player for player in details.get("players", []) if player.get("hero_id")]
    if len(players) < 10:
        raise ValueError(f"Match {match_id} has only {len(players)} usable player rows.")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO matches (
                match_id, start_time, duration, radiant_win, patch, radiant_score,
                dire_score, avg_rank_tier, game_mode, lobby_type
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_id) DO UPDATE SET
                start_time = EXCLUDED.start_time,
                duration = EXCLUDED.duration,
                radiant_win = EXCLUDED.radiant_win,
                patch = EXCLUDED.patch,
                radiant_score = EXCLUDED.radiant_score,
                dire_score = EXCLUDED.dire_score,
                avg_rank_tier = EXCLUDED.avg_rank_tier,
                game_mode = EXCLUDED.game_mode,
                lobby_type = EXCLUDED.lobby_type
            """,
            (
                match_id,
                start_time,
                details.get("duration"),
                radiant_win,
                details.get("patch"),
                details.get("radiant_score"),
                details.get("dire_score"),
                details.get("avg_rank_tier"),
                details.get("game_mode"),
                details.get("lobby_type"),
            ),
        )
        cursor.execute("DELETE FROM players WHERE match_id = %s", (match_id,))
        cursor.executemany(
            """
            INSERT INTO players (
                match_id, account_id, hero_id, kills, deaths, assists, gold_per_min, xp_per_min,
                player_slot, is_radiant, is_winner, win, lose, lane, lane_role, is_roaming,
                item_0, item_1, item_2, item_3, item_4, item_5, backpack_0, backpack_1,
                backpack_2, item_neutral, ability_upgrades_arr
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            [
                (
                    match_id,
                    player.get("account_id"),
                    player.get("hero_id"),
                    player.get("kills", 0),
                    player.get("deaths", 0),
                    player.get("assists", 0),
                    player.get("gold_per_min", 0),
                    player.get("xp_per_min", 0),
                    player.get("player_slot"),
                    player_is_radiant(player),
                    player_is_winner(player, radiant_win),
                    player.get("win"),
                    player.get("lose"),
                    player.get("lane"),
                    player.get("lane_role"),
                    player.get("is_roaming"),
                    player.get("item_0"),
                    player.get("item_1"),
                    player.get("item_2"),
                    player.get("item_3"),
                    player.get("item_4"),
                    player.get("item_5"),
                    player.get("backpack_0"),
                    player.get("backpack_1"),
                    player.get("backpack_2"),
                    player.get("item_neutral"),
                    player.get("ability_upgrades_arr"),
                )
                for player in players
            ],
        )


def apply_schema_migration(connection):
    with connection.cursor() as cursor:
        cursor.execute(SCHEMA_MIGRATION_SQL)


def apply_analytics_view(connection):
    sql_path = Path(__file__).with_name("analytics.sql")
    with connection.cursor() as cursor:
        cursor.execute(sql_path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=385)
    parser.add_argument("--matches-per-week", type=int, default=12)
    parser.add_argument("--delay", type=float, default=1.1)
    parser.add_argument("--max-api-calls", type=int, default=1500)
    parser.add_argument(
        "--enrich-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Re-fetch selected matches whose stored player rows are missing side/win fields.",
    )
    parser.add_argument(
        "--enrich-db-existing-only",
        action="store_true",
        help="Skip OpenDota Explorer sampling and only enrich matches already stored in PostgreSQL.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    client = OpenDotaClient(args.delay, args.max_api_calls)

    with database_connection() as connection:
        apply_schema_migration(connection)
        connection.commit()

        if args.enrich_db_existing_only:
            selected = all_existing_matches_needing_enrichment(connection)
            pending = selected
            print(f"Enriching {len(pending)} existing matches already stored in PostgreSQL.")
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
            selected = collect_weekly_sample(client, cutoff, args.matches_per_week)
            if not selected:
                raise RuntimeError("OpenDota returned no professional matches in the requested period.")

            first = datetime.fromtimestamp(selected[0]["start_time"], timezone.utc).date()
            last = datetime.fromtimestamp(selected[-1]["start_time"], timezone.utc).date()
            print(f"Selected {len(selected)} matches covering {first} through {last}.")
            already_loaded = existing_match_ids(connection, [match["match_id"] for match in selected])
            needs_enrichment = (
                matches_needing_enrichment(connection, [match["match_id"] for match in selected])
                if args.enrich_existing
                else set()
            )
            pending = [
                match
                for match in selected
                if match["match_id"] not in already_loaded or match["match_id"] in needs_enrichment
            ]
            print(
                f"Importing/enriching {len(pending)} matches; {len(already_loaded)} already exist, "
                f"{len(needs_enrichment)} need enrichment."
            )

        if args.dry_run:
            print(f"Dry run complete after {client.calls} API calls; database was not changed.")
            return

        imported = 0
        for index, match in enumerate(pending, start=1):
            try:
                details = client.get(f"matches/{match['match_id']}")
                store_match(connection, details)
                connection.commit()
                imported += 1
            except Exception as exc:
                connection.rollback()
                print(f"Skipped match {match['match_id']}: {exc}")
            if index % 25 == 0 or index == len(pending):
                print(f"Progress: {index}/{len(pending)} attempted, {imported} imported")
        apply_analytics_view(connection)
        connection.commit()

    print(f"Done. Imported {imported} matches using {client.calls} API calls.")


if __name__ == "__main__":
    main()
