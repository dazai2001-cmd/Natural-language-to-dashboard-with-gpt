import json
import logging
import os
import re
import subprocess
import sys
import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2 import sql as pg_sql
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS


load_dotenv()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OR_API_KEY")
# The free router survives individual free-model retirements and rate limits.
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").lower()

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMPORT_LOG_PATH = PROJECT_ROOT / "backend" / "import-job.log"
IMPORT_JOB_LOCK = threading.Lock()
IMPORT_JOB: dict = {
    "process": None,
    "started_at": None,
    "mode": None,
    "command": None,
}

HERO_SCORE_DESCRIPTION = {
    "name": "Reliability-Adjusted Hero Performance Score",
    "scale": "Centred on 50; higher is better.",
    "formula": (
        "50 + 10 × reliability × (25% kills z-score + 20% assists z-score "
        "− 20% deaths z-score + 20% GPM z-score + 15% XPM z-score)"
    ),
    "reliability": "matches_played / (matches_played + 30)",
    "eligibility": "At least 30 appearances in a dataset spanning 365 days with observations in at least 52 weeks.",
    "limitation": "This measures observed performance in the imported high-skill match sample, not intrinsic patch balance or win rate.",
}

FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|truncate|create|replace|grant|revoke|"
    r"copy|call|execute|do|set|reset|vacuum|analyze|refresh|comment)\b",
    re.IGNORECASE,
)


class QueryExecutionError(Exception):
    pass


def active_model_label() -> str:
    openrouter_label = (
        OPENROUTER_MODEL
        if OPENROUTER_MODEL.startswith("openrouter/")
        else f"openrouter/{OPENROUTER_MODEL}"
    )
    if LLM_PROVIDER == "ollama":
        return f"ollama/{OLLAMA_MODEL}"
    if LLM_PROVIDER == "openrouter":
        return openrouter_label
    return f"auto(ollama/{OLLAMA_MODEL}, {openrouter_label})"


def ollama_is_available() -> bool:
    try:
        response = requests.get(OLLAMA_API_URL.replace("/api/chat", "/api/tags"), timeout=2)
        return response.ok
    except requests.RequestException:
        return False


def strip_thinking(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content, flags=re.IGNORECASE | re.DOTALL).strip()


def ollama_messages(messages: list[dict]) -> list[dict]:
    copied = [dict(message) for message in messages]
    for message in reversed(copied):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            if not message["content"].lstrip().startswith("/no_think"):
                message["content"] = f"/no_think\n{message['content']}"
            break
    return copied


def chat_completion(messages: list[dict], *, temperature: float = 0, max_tokens: int = 1200) -> str:
    providers = [LLM_PROVIDER]
    if LLM_PROVIDER == "auto":
        providers = ["ollama", "openrouter"] if ollama_is_available() else ["openrouter"]

    last_error: Exception | None = None
    for provider in providers:
        try:
            if provider == "ollama":
                response = requests.post(
                    OLLAMA_API_URL,
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": ollama_messages(messages),
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens,
                        },
                    },
                    timeout=120,
                )
                if not response.ok:
                    raise RuntimeError(f"Ollama returned {response.status_code}: {response.text}")
                content = strip_thinking(response.json().get("message", {}).get("content", ""))
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("Ollama returned an empty response.")
                return content.strip()

            if provider == "openrouter":
                if not OPENROUTER_API_KEY:
                    raise RuntimeError("OR_API_KEY is not configured.")
                response = requests.post(
                    OPENROUTER_API_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://localhost:3000",
                        "X-Title": "Puppet Dashboard",
                    },
                    json={
                        "model": OPENROUTER_MODEL,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "reasoning": {"effort": "low", "exclude": True},
                    },
                    timeout=90,
                )
                if not response.ok:
                    try:
                        detail = response.json().get("error", {}).get("message", response.text)
                    except ValueError:
                        detail = response.text
                    raise RuntimeError(f"OpenRouter returned {response.status_code}: {detail}")
                choices = response.json().get("choices") or []
                if not choices:
                    raise RuntimeError("OpenRouter returned no completion choices.")
                content = choices[0].get("message", {}).get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("OpenRouter returned an empty response.")
                return content.strip()

            raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")
        except (RuntimeError, requests.RequestException) as exc:
            last_error = exc
            logging.warning("%s LLM call failed: %s", provider, exc)

    raise RuntimeError(str(last_error or "No LLM provider was available."))


def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "mydatabase"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASS"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        connect_timeout=5,
    )


def get_database_schema() -> dict:
    with get_db_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                c.table_name,
                t.table_type,
                c.column_name,
                c.data_type,
                c.ordinal_position,
                c.is_nullable
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema
             AND t.table_name = c.table_name
            WHERE c.table_schema = 'public'
              AND t.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY c.table_name, c.ordinal_position
            """
        )
        tables: dict[str, dict] = {}
        for table_name, table_type, column_name, data_type, _, is_nullable in cursor.fetchall():
            table = tables.setdefault(
                table_name,
                {"name": table_name, "type": table_type, "columns": []},
            )
            table["columns"].append(
                {
                    "name": column_name,
                    "type": data_type,
                    "nullable": is_nullable == "YES",
                }
            )
    return {"tables": list(tables.values())}


def format_schema_context(schema: dict) -> str:
    if not schema["tables"]:
        return "No public tables or views were found."
    lines = []
    for table in schema["tables"]:
        columns = ", ".join(
            f"{column['name']} {column['type']}{' nullable' if column['nullable'] else ''}"
            for column in table["columns"]
        )
        lines.append(f"{table['name']} ({table['type']}): {columns}")
    return "\n".join(lines)


def schema_has_tables(schema: dict, required_tables: set[str]) -> bool:
    available_tables = {table["name"] for table in schema["tables"]}
    return required_tables.issubset(available_tables)


def get_domain_hints(schema: dict, question: str) -> str:
    table_names = {table["name"] for table in schema["tables"]}
    hints = [
        "Infer the business/domain meaning from table and column names; do not assume hidden columns.",
        "Prefer transparent aggregate metrics with visible denominators and sample sizes.",
        "When a question asks for 'best', 'top', or 'performance', define the ranking metric in SQL from relevant available columns.",
        "If time columns exist and the user asks about trends, group by an appropriate date grain.",
        "For month/week/day trends, prefer DATE_TRUNC so different years are not merged together.",
    ]

    if {"matches", "players", "heroes"}.issubset(table_names):
        hints.extend(
            [
                "This database contains Dota 2 data. Dota playable characters are heroes; treat 'agent' or 'champion' as 'hero'.",
                "For Dota 'best hero' or overall-performance questions, query hero_performance_scores and rank by performance_score.",
                "Never define Dota 'best hero' using one raw stat such as kills or an unadjusted one-match average.",
                "Keep matches_played, reliability, and performance_score visible in best-hero results.",
            ]
        )
        if "hero_matchups" in table_names:
            hints.extend(
                [
                    "For 'counter', 'counters', 'against', or matchup questions, use hero_matchups.",
                    "A counter to hero X is a row where opponent_hero_name = X; rank candidate hero_name by matchup_score or win_rate, and keep games_played/reliability visible.",
                    "Require meaningful samples for matchup claims; prefer games_played >= 20 when enough rows exist.",
                ]
            )
        if "hero_synergies" in table_names:
            hints.extend(
                [
                    "For 'works with', 'synergy', 'combo', or ally questions, use hero_synergies.",
                    "Rank synergies by synergy_score or win_rate, and keep games_played/reliability visible.",
                ]
            )
        if "team_comps" in table_names:
            hints.extend(
                [
                    "For full composition questions, use team_comps and hero_matchups where possible.",
                    "Exact five-hero comp samples are usually sparse, so explain sample size through selected columns.",
                ]
            )

    if re.search(r"\b(finance|financial|revenue|sales|profit|expense|cash|transaction)\b", question, re.I):
        hints.extend(
            [
                "For financial data, distinguish amounts, dates, entities, categories, and accounts before aggregating.",
                "Use SUM for additive money-like measures and AVG only for rates, prices, or per-period comparisons.",
                "For financial rankings, include period coverage and transaction or row counts when possible.",
            ]
        )

    return "\n".join(f"- {hint}" for hint in hints)


def get_database_profile(schema: dict) -> dict:
    profile = {"table_count": len(schema["tables"]), "tables": []}
    with get_db_connection() as connection:
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '2s'")
            for table in schema["tables"]:
                entry = {
                    "name": table["name"],
                    "type": table["type"],
                    "column_count": len(table["columns"]),
                    "row_count": None,
                }
                if table["type"] == "BASE TABLE":
                    try:
                        cursor.execute(
                            pg_sql.SQL("SELECT COUNT(*) FROM {}").format(
                                pg_sql.Identifier(table["name"])
                            )
                        )
                        entry["row_count"] = cursor.fetchone()[0]
                    except psycopg2.Error:
                        connection.rollback()
                profile["tables"].append(entry)
    return profile


def get_dota_data_quality(schema: dict) -> dict | None:
    if not schema_has_tables(schema, {"matches", "players", "heroes"}):
        return None
    with get_db_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            WITH hero_samples AS (
                SELECT hero_id, COUNT(DISTINCT match_id) AS appearances
                FROM players
                WHERE hero_id IS NOT NULL
                GROUP BY hero_id
            )
            SELECT
                COUNT(DISTINCT m.match_id) AS match_count,
                COUNT(p.match_id) AS player_rows,
                MIN(m.start_time) AS first_match,
                MAX(m.start_time) AS last_match,
                COALESCE(EXTRACT(DAY FROM MAX(m.start_time) - MIN(m.start_time)), 0)::integer AS coverage_days,
                COUNT(DISTINCT DATE_TRUNC('week', m.start_time))::integer AS covered_weeks,
                COALESCE((SELECT MAX(appearances) FROM hero_samples), 0) AS max_hero_appearances,
                COALESCE((SELECT COUNT(*) FROM hero_samples WHERE appearances >= 30), 0) AS eligible_hero_count,
                COUNT(p.match_id) FILTER (
                    WHERE p.player_slot IS NOT NULL
                      AND p.is_radiant IS NOT NULL
                      AND p.is_winner IS NOT NULL
                ) AS enriched_player_rows,
                COUNT(DISTINCT m.match_id) FILTER (
                    WHERE p.player_slot IS NOT NULL
                      AND p.is_radiant IS NOT NULL
                      AND p.is_winner IS NOT NULL
                ) AS enriched_match_count
            FROM matches m
            LEFT JOIN players p ON p.match_id = m.match_id
            """
        )
        row = cursor.fetchone()
        columns = [description[0] for description in cursor.description]
        quality = normalize_results([dict(zip(columns, row))])[0]

    quality["sufficient_for_best_hero"] = bool(
        quality["match_count"] >= 500
        and quality["coverage_days"] >= 365
        and quality["covered_weeks"] >= 52
        and quality["eligible_hero_count"] >= 20
    )
    quality["sufficient_for_matchups"] = bool(
        quality["enriched_match_count"] >= 100
        and quality["enriched_player_rows"] >= 1000
    )
    return quality


def asks_for_best_hero(question: str) -> bool:
    ranking_intent = re.search(
        r"\b(best|strongest|most effective|highest[- ]performing|top overall|meta)\b",
        question,
        re.IGNORECASE,
    )
    hero_context = re.search(r"\b(hero|heroes|agent|agents|champion|dota)\b", question, re.IGNORECASE)
    return bool(ranking_intent and hero_context)


def asks_for_dota_matchups(question: str) -> bool:
    matchup_intent = re.search(
        r"\b(counter|counters|countered|against|matchup|matchups|synergy|synergies|"
        r"works with|work best with|work with|combo|composition|comp|draft)\b",
        question,
        re.IGNORECASE,
    )
    hero_context = re.search(r"\b(hero|heroes|agent|agents|champion|dota|lineup)\b", question, re.IGNORECASE)
    return bool(matchup_intent and hero_context)


def insufficient_best_hero_response(quality: dict):
    diagnostic_sql = (
        "SELECT COUNT(*) AS match_count, MIN(start_time) AS first_match, "
        "MAX(start_time) AS last_match, "
        "EXTRACT(DAY FROM MAX(start_time) - MIN(start_time))::integer AS coverage_days "
        "FROM matches;"
    )
    results = [{key: value for key, value in quality.items() if key != "sufficient_for_best_hero"}]
    chart_spec = {
        "type": "table",
        "title": "Dataset evidence check",
        "x_column": None,
        "y_column": None,
        "rationale": "A ranking would be misleading until the minimum coverage and sample thresholds are met.",
    }
    visualization = {
        "chart_type": "table",
        "chart_spec": chart_spec,
        "chart_data": {"labels": [], "datasets": []},
    }
    return jsonify(
        {
            "status": "insufficient_data",
            "message": (
                "There is not enough evidence to name a best Dota 2 hero. "
                f"The database currently has {quality['match_count']} matches across "
                f"{quality['coverage_days']} calendar days but only {quality['covered_weeks']} "
                "observed weeks; the ranking requires at least 500 matches, "
                "365 days of coverage across at least 52 distinct weeks, and 20 heroes with "
                "30 or more appearances."
            ),
            "metric": HERO_SCORE_DESCRIPTION,
            "data_quality": quality,
            "sql": diagnostic_sql,
            "results": results,
            "visualizations": [visualization],
            "chart_type": "table",
            "chart_spec": chart_spec,
            "chart_data": visualization["chart_data"],
            "chart_agent_attempts": 0,
            "chart_fallback": False,
            "model": active_model_label(),
            "attempts": 0,
        }
    )


def insufficient_matchup_response(quality: dict):
    diagnostic_sql = (
        "SELECT COUNT(*) FILTER (WHERE player_slot IS NOT NULL AND is_radiant IS NOT NULL "
        "AND is_winner IS NOT NULL) AS enriched_player_rows, "
        "COUNT(DISTINCT match_id) FILTER (WHERE player_slot IS NOT NULL AND is_radiant IS NOT NULL "
        "AND is_winner IS NOT NULL) AS enriched_match_count FROM players;"
    )
    results = [{
        "enriched_match_count": quality["enriched_match_count"],
        "enriched_player_rows": quality["enriched_player_rows"],
        "required_enriched_matches": 100,
        "required_enriched_player_rows": 1000,
    }]
    chart_spec = {
        "type": "table",
        "title": "Matchup evidence check",
        "x_column": None,
        "y_column": None,
        "rationale": "Counter and composition answers require player side and win/loss fields from enriched match details.",
    }
    visualization = {
        "chart_type": "table",
        "chart_spec": chart_spec,
        "chart_data": {"labels": [], "datasets": []},
    }
    return jsonify(
        {
            "status": "insufficient_data",
            "message": (
                "There is not enough enriched matchup data to answer counter or composition questions yet. "
                f"The database currently has {quality['enriched_match_count']} enriched matches and "
                f"{quality['enriched_player_rows']} enriched player rows; matchup answers require at least "
                "100 enriched matches and 1,000 enriched player rows."
            ),
            "data_quality": quality,
            "sql": diagnostic_sql,
            "results": results,
            "visualizations": [visualization],
            "chart_type": "table",
            "chart_spec": chart_spec,
            "chart_data": visualization["chart_data"],
            "chart_agent_attempts": 0,
            "chart_fallback": False,
            "model": active_model_label(),
            "attempts": 0,
        }
    )


def find_hero_name_in_question(question: str) -> str | None:
    with get_db_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT localized_name FROM heroes WHERE localized_name IS NOT NULL")
        hero_names = sorted((row[0] for row in cursor.fetchall()), key=len, reverse=True)
    normalized_question = question.lower()
    return next((name for name in hero_names if name.lower() in normalized_question), None)


def execute_query_params(sql: str, params: tuple) -> list[dict]:
    try:
        with get_db_connection() as connection:
            connection.set_session(readonly=True)
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '10s'")
                cursor.execute(sql, params)
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except psycopg2.Error as exc:
        message = exc.diag.message_primary if exc.diag else str(exc)
        raise QueryExecutionError(message) from exc


def deterministic_dota_matchup_response(question: str, quality: dict):
    hero_name = find_hero_name_in_question(question)
    if not hero_name:
        return None

    is_synergy_question = re.search(
        r"\b(works with|work best with|work with|synergy|synergies|combo|ally|allies|with)\b",
        question,
        re.IGNORECASE,
    )
    if is_synergy_question:
        sql = """
        SELECT
          ally_hero_name AS recommended_ally,
          hero_name AS for_hero,
          games_played,
          wins,
          win_rate,
          reliability,
          synergy_score
        FROM hero_synergies
        WHERE LOWER(hero_name) = LOWER(%s)
          AND games_played >= 5
        ORDER BY synergy_score DESC, games_played DESC
        LIMIT 10;
        """
        title = f"Best observed allies for {hero_name}"
    else:
        sql = """
        SELECT
          hero_name AS counter_hero,
          opponent_hero_name AS against_hero,
          games_played,
          wins,
          win_rate,
          reliability,
          matchup_score
        FROM hero_matchups
        WHERE LOWER(opponent_hero_name) = LOWER(%s)
          AND games_played >= 5
        ORDER BY matchup_score DESC, games_played DESC
        LIMIT 10;
        """
        title = f"Best observed counters to {hero_name}"

    results = normalize_results(execute_query_params(sql, (hero_name,)))
    chart_specs = fallback_visualization_plans(question, results)
    rendered_sql = clean_and_validate_sql(sql % ("'" + hero_name.replace("'", "''") + "'",))
    answer, answer_fallback = generate_answer_summary(question, rendered_sql, results, chart_specs)
    visualizations = [
        {
            "chart_type": chart_spec["type"],
            "chart_spec": chart_spec,
            "chart_data": build_chart(chart_spec, results),
        }
        for chart_spec in chart_specs
    ]
    primary_visualization = visualizations[0] if visualizations else {
        "chart_type": "table",
        "chart_spec": {
            "type": "table",
            "title": title,
            "x_column": None,
            "y_column": None,
            "rationale": "No matchup rows cleared the minimum sample threshold.",
        },
        "chart_data": {"labels": [], "datasets": []},
    }

    return jsonify(
        {
            "status": "ok",
            "message": (
                f"{title}. Results are based on enriched OpenDota match rows and should be read "
                "with the visible games_played and reliability columns."
            ),
            "answer": answer,
            "answer_fallback": answer_fallback,
            "sql": rendered_sql,
            "results": results,
            "visualizations": visualizations or [primary_visualization],
            "chart_type": primary_visualization["chart_type"],
            "chart_data": primary_visualization["chart_data"],
            "chart_spec": primary_visualization["chart_spec"],
            "chart_agent_attempts": 0,
            "chart_fallback": True,
            "data_quality": quality,
            "model": f"deterministic-dota-matchup + {active_model_label()}",
            "attempts": 0,
        }
    )


def asks_for_dota_hero_trend(question: str) -> bool:
    trend_intent = re.search(
        r"\b(trend|trends|over time|by month|by week|picked|pick rate|appearances|played)\b",
        question,
        re.IGNORECASE,
    )
    hero_name = find_hero_name_in_question(question)
    return bool(trend_intent and hero_name)


def deterministic_dota_hero_trend_response(question: str, quality: dict):
    hero_name = find_hero_name_in_question(question)
    if not hero_name:
        return None

    sql = """
    SELECT
      DATE_TRUNC('month', m.start_time)::date AS month,
      COUNT(DISTINCT p.match_id) AS appearances,
      ROUND(AVG(CASE WHEN p.is_winner THEN 1.0 ELSE 0.0 END)::numeric, 4) AS win_rate
    FROM players p
    JOIN matches m ON m.match_id = p.match_id
    JOIN heroes h ON h.hero_id = p.hero_id
    WHERE LOWER(h.localized_name) = LOWER(%s)
    GROUP BY 1
    ORDER BY 1
    LIMIT 36;
    """
    rendered_sql = clean_and_validate_sql(sql % ("'" + hero_name.replace("'", "''") + "'",))
    results = normalize_results(execute_query_params(sql, (hero_name,)))
    chart_specs = fallback_visualization_plans(question, results)
    answer, answer_fallback = generate_answer_summary(question, rendered_sql, results, chart_specs)
    visualizations = [
        {
            "chart_type": chart_spec["type"],
            "chart_spec": chart_spec,
            "chart_data": build_chart(chart_spec, results),
        }
        for chart_spec in chart_specs
    ]
    primary_visualization = visualizations[0] if visualizations else {
        "chart_type": "table",
        "chart_spec": {
            "type": "table",
            "title": f"{hero_name} trend",
            "x_column": None,
            "y_column": None,
            "rationale": "No rows were found for this hero trend.",
        },
        "chart_data": {"labels": [], "datasets": []},
    }

    return jsonify(
        {
            "status": "ok",
            "message": f"Monthly appearance trend for {hero_name}.",
            "answer": answer,
            "answer_fallback": answer_fallback,
            "sql": rendered_sql,
            "results": results,
            "visualizations": visualizations or [primary_visualization],
            "chart_type": primary_visualization["chart_type"],
            "chart_data": primary_visualization["chart_data"],
            "chart_spec": primary_visualization["chart_spec"],
            "chart_agent_attempts": 0,
            "chart_fallback": True,
            "data_quality": quality,
            "model": f"deterministic-dota-trend + {active_model_label()}",
            "attempts": 0,
        }
    )


def clean_and_validate_sql(raw_sql: str) -> str:
    sql = re.sub(r"```(?:sql)?|```", "", raw_sql, flags=re.IGNORECASE).strip()
    sql = sql.rstrip(";").strip()

    if not re.match(r"^(select|with)\b", sql, re.IGNORECASE):
        raise ValueError("The generated query was not a SELECT statement.")
    if ";" in sql or FORBIDDEN_SQL.search(sql):
        raise ValueError("The generated query contained an unsafe SQL operation.")

    return f"{sql};"


def generate_sql_query(
    user_question: str,
    schema_context: str,
    domain_hints: str,
    previous_sql: str | None = None,
    error: str | None = None,
) -> str:
    repair_context = ""
    if previous_sql and error:
        repair_context = f"""
The previous query failed:
{previous_sql}

PostgreSQL error:
{error}

Correct the query while preserving the user's intent.
"""

    prompt = f"""
Generate one read-only PostgreSQL query for this analytics database.

Live public schema:
{schema_context}

Domain and metric guidance:
{domain_hints}

User question: {user_question}
{repair_context}

Rules:
- Return only SQL, with no Markdown or explanation.
- Only SELECT or WITH ... SELECT is allowed.
- Use valid PostgreSQL GROUP BY syntax.
- Join only tables needed to answer the question.
- Use the exact table and column names shown in the live schema.
- For invented metrics, make the metric explainable by selecting its component columns and sample size.
- Do not use one-row averages or one raw stat as a proxy for "best" if richer evidence is available.
- For non-aggregate detail queries, return at most 100 rows.
- For time-series month/week/day questions, select the truncated timestamp as a date-like column and order by it.
""".strip()

    content = chat_completion(
        [
            {
                "role": "system",
                "content": "You are a careful PostgreSQL analytics agent for arbitrary business datasets. Produce safe, read-only SQL.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=1200,
    )
    return clean_and_validate_sql(content)


def execute_query(sql: str) -> list[dict]:
    try:
        with get_db_connection() as connection:
            connection.set_session(readonly=True)
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '10s'")
                cursor.execute(sql)
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except psycopg2.Error as exc:
        message = exc.diag.message_primary if exc.diag else str(exc)
        raise QueryExecutionError(message) from exc


def json_value(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def normalize_results(results: list[dict]) -> list[dict]:
    return [{key: json_value(value) for key, value in row.items()} for row in results]


def result_metadata(results: list[dict]) -> dict:
    if not results:
        return {"row_count": 0, "columns": [], "sample": []}

    frame = pd.DataFrame(results)
    return {
        "row_count": len(results),
        "columns": [
            {
                "name": column,
                "type": str(frame[column].dtype),
                "numeric": bool(
                    pd.api.types.is_numeric_dtype(frame[column])
                    and not pd.api.types.is_bool_dtype(frame[column])
                ),
            }
            for column in frame.columns
        ],
        "sample": results[:8],
    }


def parse_json_object(content: str) -> dict:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("The visualization agent returned empty content.")
    cleaned = re.sub(r"```(?:json)?|```", "", content, flags=re.IGNORECASE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("The visualization agent did not return a JSON object.")
    parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("The visualization plan must be a JSON object.")
    return parsed


def request_visualization_plan(
    question: str,
    sql: str,
    metadata: dict,
    previous_plan: dict | None = None,
    validation_error: str | None = None,
) -> dict:
    correction = ""
    if previous_plan and validation_error:
        correction = f"""
Your previous plan was rejected:
{json.dumps(previous_plan)}
Validation error: {validation_error}
Return a corrected plan.
"""

    prompt = f"""
You are a visualization agent. Choose the clearest display for the user's question and actual SQL results.

Question: {question}
SQL: {sql}
Result metadata and sample:
{json.dumps(metadata, default=str)}
{correction}

Choose the smallest useful set of non-redundant displays. Usually this is one chart. Use two or more
only when different measures or relationships in the result answer distinct parts of the question.
Return no more than four displays. Each display type must be bar, line, pie, scatter, or table.
- bar: comparing numeric values across categories.
- line: ordered time series or a meaningful continuous sequence.
- pie: parts of a whole with few non-negative categories; never use for rankings.
- scatter: relationship between two numeric measures.
- table: no honest chart is possible.

Return only this JSON shape:
{{
  "visualizations": [
    {{
      "type": "bar|line|pie|scatter|table",
      "title": "concise chart title",
      "x_column": "exact column name or null",
      "y_column": "exact column name or null",
      "rationale": "one concise sentence explaining why this display adds a distinct insight"
    }}
  ]
}}
""".strip()

    content = chat_completion(
        [
            {
                "role": "system",
                "content": "You are an autonomous data-visualization planner. Return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=1200,
    )
    return parse_json_object(content)


def validate_single_visualization(plan: dict, results: list[dict]) -> dict:
    chart_type = plan.get("type")
    if chart_type not in {"bar", "line", "pie", "scatter", "table"}:
        raise ValueError("type must be bar, line, pie, scatter, or table")

    title = plan.get("title")
    rationale = plan.get("rationale")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("rationale must be a non-empty string")

    normalized = {
        "type": chart_type,
        "title": title.strip()[:120],
        "x_column": plan.get("x_column"),
        "y_column": plan.get("y_column"),
        "rationale": rationale.strip()[:300],
    }
    if chart_type == "table":
        if results:
            table_frame = pd.DataFrame(results)
            has_numeric_measure = any(
                pd.api.types.is_numeric_dtype(table_frame[column])
                and not pd.api.types.is_bool_dtype(table_frame[column])
                for column in table_frame.columns
            )
            if len(table_frame.columns) >= 2 and has_numeric_measure:
                raise ValueError("table is not allowed when the result contains chartable numeric measures")
        normalized["x_column"] = None
        normalized["y_column"] = None
        return normalized

    if not results:
        raise ValueError("empty results must use table")

    frame = pd.DataFrame(results)
    x_column, y_column = normalized["x_column"], normalized["y_column"]
    if x_column not in frame.columns or y_column not in frame.columns:
        raise ValueError("x_column and y_column must exactly match result columns")
    if x_column == y_column:
        raise ValueError("x_column and y_column must be different")
    if not pd.api.types.is_numeric_dtype(frame[y_column]):
        raise ValueError("y_column must be numeric")
    if chart_type == "scatter" and not pd.api.types.is_numeric_dtype(frame[x_column]):
        raise ValueError("scatter x_column must be numeric")
    if chart_type == "pie":
        if len(results) > 12:
            raise ValueError("pie charts may contain at most 12 categories")
        if any(value is not None and value < 0 for value in frame[y_column]):
            raise ValueError("pie chart values cannot be negative")
    return normalized


def validate_visualization_plans(payload: dict, results: list[dict]) -> list[dict]:
    plans = payload.get("visualizations")
    if not isinstance(plans, list) or not 1 <= len(plans) <= 4:
        raise ValueError("visualizations must contain between one and four plans")

    validated = [validate_single_visualization(plan, results) for plan in plans]
    signatures = [
        (plan["type"], plan["x_column"], plan["y_column"])
        for plan in validated
    ]
    if len(signatures) != len(set(signatures)):
        raise ValueError("visualizations must not repeat the same chart and axes")
    if len(validated) > 1 and any(plan["type"] == "table" for plan in validated):
        raise ValueError("table cannot be combined with other visualizations")
    return validated


def fallback_visualization_plans(question: str, results: list[dict]) -> list[dict]:
    if not results or len(results[0]) < 2:
        return [{
            "type": "table",
            "title": "Query Results",
            "x_column": None,
            "y_column": None,
            "rationale": "The result does not contain enough dimensions for an honest chart.",
        }]

    frame = pd.DataFrame(results)
    columns = frame.columns.tolist()
    numeric = [
        column
        for column in columns
        if pd.api.types.is_numeric_dtype(frame[column])
        and not pd.api.types.is_bool_dtype(frame[column])
    ]
    if not numeric:
        return [{
            "type": "table",
            "title": "Query Results",
            "x_column": None,
            "y_column": None,
            "rationale": "The result has no numeric measure to visualize.",
        }]

    x_column = next((column for column in columns if column not in numeric), columns[0])
    measures = [column for column in numeric if column != x_column]
    question_words = set(re.findall(r"[a-z0-9]+", question.lower()))
    score_preference = [
        "matchup_score",
        "synergy_score",
        "performance_score",
        "win_rate",
        "reliability",
    ]
    if (
        re.search(r"\b(pick|picked|picks|appearance|appearances|played)\b", question, re.IGNORECASE)
        and "appearances" in measures
    ):
        score_preference = ["appearances"] + score_preference
    preferred_score_columns = [
        column
        for preferred in score_preference
        for column in measures
        if column.lower() == preferred
    ]
    requested_measures = [
        column
        for column in measures
        if any(part in question_words for part in column.lower().split("_") if len(part) > 3)
    ]
    selected_measures = (requested_measures or preferred_score_columns or measures[:1])[:4]
    time_words = ("date", "time", "month", "week", "year")
    chart_type = "line" if any(word in x_column.lower() for word in time_words) else "bar"
    return [
        {
            "type": chart_type,
            "title": f"{y_column.replace('_', ' ').title()} by {x_column.replace('_', ' ').title()}",
            "x_column": x_column,
            "y_column": y_column,
            "rationale": "A safe fallback selected this distinct measure because it was requested in the question.",
        }
        for y_column in selected_measures
    ]


def choose_visualization_plans(question: str, sql: str, results: list[dict]) -> tuple[list[dict], int, bool]:
    metadata = result_metadata(results)
    previous_plan = None
    validation_error = None
    try:
        for attempt in range(1, 3):
            previous_plan = request_visualization_plan(
                question, sql, metadata, previous_plan, validation_error
            )
            try:
                return validate_visualization_plans(previous_plan, results), attempt, False
            except ValueError as exc:
                validation_error = str(exc)
                logging.info("Visualization plan rejected: %s", validation_error)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        logging.warning("Visualization agent unavailable; using fallback: %s", exc)

    return fallback_visualization_plans(question, results), 0, True


def generate_answer_summary(
    question: str,
    sql: str,
    results: list[dict],
    chart_specs: list[dict],
) -> tuple[str | None, bool]:
    if not results:
        return "I did not find matching rows for that question.", True

    rows_are_complete = len(results) <= 12
    prompt = f"""
You are the analyst layer on top of a trusted analytics engine.

Question: {question}
SQL/tool used:
{sql}

{"Complete result rows" if rows_are_complete else "Top result rows"}:
{json.dumps(results[:12], default=str)}

Visualizations selected:
{json.dumps(chart_specs, default=str)}

Write a concise user-facing answer:
- Lead with the main finding.
- Mention sample size/reliability columns when present.
- Do not invent facts that are not in the rows.
- Use exact values from the rows. Do not estimate, round, or claim missing periods exist.
- If the rows are grouped by month number, do not call that full year coverage.
- Keep it under 120 words.
""".strip()
    try:
        return chat_completion(
            [
                {
                    "role": "system",
                    "content": "You explain analytics results clearly and cautiously.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=220,
        ), False
    except RuntimeError as exc:
        logging.warning("Answer summary unavailable; using fallback: %s", exc)
        return None, True


def build_chart(plan: dict, results: list[dict]) -> dict:
    if plan["type"] == "table" or not results:
        return {"labels": [], "datasets": []}

    frame = pd.DataFrame(results)
    x_column, y_column = plan["x_column"], plan["y_column"]
    if plan["type"] == "scatter":
        return {
            "datasets": [
                {
                    "label": plan["title"],
                    "data": [
                        {"x": json_value(x), "y": json_value(y)}
                        for x, y in zip(frame[x_column], frame[y_column])
                    ],
                }
            ]
        }

    dataset = {
        "label": y_column.replace("_", " ").title(),
        "data": [json_value(value) for value in frame[y_column].tolist()],
    }
    if plan["type"] == "pie":
        dataset["backgroundColor"] = [
            "#22c55e", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#14b8a6",
            "#ec4899", "#84cc16", "#06b6d4", "#f97316", "#6366f1", "#a855f7",
        ][: len(results)]

    return {
        "labels": [json_value(value) for value in frame[x_column].tolist()],
        "datasets": [dataset],
    }


def import_command_for_mode(mode: str) -> list[str]:
    base = [sys.executable, "-u", str(PROJECT_ROOT / "backend" / "ingest_opendota.py")]
    if mode == "recent":
        return base + [
            "--days", "30",
            "--matches-per-week", "25",
            "--delay", "1.2",
            "--max-api-calls", "1500",
        ]
    if mode == "backfill":
        return base + [
            "--days", "385",
            "--matches-per-week", "75",
            "--delay", "1.2",
            "--max-api-calls", "6000",
        ]
    if mode == "enrich-existing":
        return base + [
            "--enrich-db-existing-only",
            "--delay", "1.2",
            "--max-api-calls", "1500",
        ]
    raise ValueError("mode must be recent, backfill, or enrich-existing")


def import_job_status() -> dict:
    with IMPORT_JOB_LOCK:
        process = IMPORT_JOB.get("process")
        running = bool(process and process.poll() is None)
        exit_code = None if not process else process.poll()
        status = {
            "running": running,
            "exit_code": exit_code,
            "started_at": IMPORT_JOB.get("started_at"),
            "mode": IMPORT_JOB.get("mode"),
            "command": IMPORT_JOB.get("command"),
            "log_path": str(IMPORT_LOG_PATH),
            "rate_limit_policy": {
                "delay_seconds_between_successful_calls": 1.2,
                "honors_429_retry_after": True,
                "commits_each_match": True,
                "skips_existing_matches": True,
            },
        }

    if IMPORT_LOG_PATH.exists():
        lines = IMPORT_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        status["log_tail"] = lines[-40:]
    else:
        status["log_tail"] = []
    return status


@app.get("/import/status")
def import_status():
    return jsonify(import_job_status())


@app.post("/import/start")
def import_start():
    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "recent")
    if not isinstance(mode, str):
        return jsonify({"error": "mode must be recent, backfill, or enrich-existing"}), 400

    try:
        command = import_command_for_mode(mode)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    with IMPORT_JOB_LOCK:
        existing_process = IMPORT_JOB.get("process")
        if existing_process and existing_process.poll() is None:
            already_running = True
        else:
            already_running = False

    if already_running:
        return jsonify({
            "error": "An import job is already running.",
            "status": import_job_status(),
        }), 409

    with IMPORT_JOB_LOCK:
        IMPORT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log_file = IMPORT_LOG_PATH.open("w", encoding="utf-8")
        log_file.write(
            f"Starting OpenDota import at {datetime.now().isoformat(timespec='seconds')}\n"
            f"Mode: {mode}\n"
            f"Command: {' '.join(command)}\n"
            "Rate policy: 1.2s delay, Retry-After honored on 429s, commits each match, skips existing matches.\n\n"
        )
        log_file.flush()

        env = os.environ.copy()
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        log_file.close()
        IMPORT_JOB.update(
            {
                "process": process,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "mode": mode,
                "command": command,
            }
        )

    return jsonify(import_job_status()), 202


@app.get("/health")
def health():
    try:
        with get_db_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return jsonify({
            "status": "ok",
            "database": "connected",
            "model": active_model_label(),
            "ollama_available": ollama_is_available(),
        })
    except psycopg2.Error as exc:
        return jsonify({"status": "error", "database": str(exc)}), 503


@app.get("/meta-dashboard")
def meta_dashboard():
    try:
        requested_hero = (request.args.get("hero") or "Pudge").strip()
        with get_db_connection() as connection:
            connection.set_session(readonly=True)
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '10s'")
                cursor.execute(
                    """
                    SELECT localized_name
                    FROM heroes
                    WHERE LOWER(localized_name) = LOWER(%s)
                    LIMIT 1
                    """,
                    (requested_hero,),
                )
                row = cursor.fetchone()
                hero_name = row[0] if row else "Pudge"

                cursor.execute(
                    """
                    SELECT localized_name
                    FROM heroes
                    WHERE localized_name IS NOT NULL
                    ORDER BY localized_name
                    """
                )
                heroes = [row[0] for row in cursor.fetchall()]

                cursor.execute(
                    """
                    SELECT
                        COUNT(DISTINCT match_id) FILTER (
                            WHERE player_slot IS NOT NULL
                              AND is_radiant IS NOT NULL
                              AND is_winner IS NOT NULL
                        ) AS enriched_matches,
                        COUNT(*) FILTER (
                            WHERE player_slot IS NOT NULL
                              AND is_radiant IS NOT NULL
                              AND is_winner IS NOT NULL
                        ) AS enriched_player_rows
                    FROM players
                    """
                )
                enriched_matches, enriched_player_rows = cursor.fetchone()

                cursor.execute("SELECT COUNT(*) FROM hero_matchups")
                matchup_rows = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM hero_synergies")
                synergy_rows = cursor.fetchone()[0]

                cursor.execute(
                    """
                    SELECT
                        hero_name AS counter_hero,
                        matchup_score,
                        win_rate,
                        games_played,
                        reliability
                    FROM hero_matchups
                    WHERE LOWER(opponent_hero_name) = LOWER(%s)
                      AND games_played >= 5
                    ORDER BY matchup_score DESC, games_played DESC
                    LIMIT 5
                    """,
                    (hero_name,),
                )
                columns = [description[0] for description in cursor.description]
                counters = normalize_results([
                    dict(zip(columns, row)) for row in cursor.fetchall()
                ])

                cursor.execute(
                    """
                    SELECT
                        ally_hero_name AS recommended_ally,
                        synergy_score,
                        win_rate,
                        games_played,
                        reliability
                    FROM hero_synergies
                    WHERE LOWER(hero_name) = LOWER(%s)
                      AND games_played >= 5
                    ORDER BY synergy_score DESC, games_played DESC
                    LIMIT 5
                    """,
                    (hero_name,),
                )
                columns = [description[0] for description in cursor.description]
                synergies = normalize_results([
                    dict(zip(columns, row)) for row in cursor.fetchall()
                ])

                cursor.execute(
                    """
                    SELECT
                        COUNT(DISTINCT match_id) AS appearances
                    FROM players
                    WHERE hero_id = (
                        SELECT hero_id FROM heroes WHERE LOWER(localized_name) = LOWER(%s) LIMIT 1
                    )
                    """,
                    (hero_name,),
                )
                hero_appearances = cursor.fetchone()[0]

                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total_matchup_rows,
                        COUNT(*) FILTER (WHERE games_played >= 20) AS reliable_matchup_rows,
                        COALESCE(MAX(games_played), 0) AS max_matchup_games
                    FROM hero_matchups
                    WHERE LOWER(opponent_hero_name) = LOWER(%s)
                    """,
                    (hero_name,),
                )
                matchup_coverage = dict(zip(
                    ["total_rows", "reliable_rows", "max_games"],
                    cursor.fetchone(),
                ))

                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total_synergy_rows,
                        COUNT(*) FILTER (WHERE games_played >= 20) AS reliable_synergy_rows,
                        COALESCE(MAX(games_played), 0) AS max_synergy_games
                    FROM hero_synergies
                    WHERE LOWER(hero_name) = LOWER(%s)
                    """,
                    (hero_name,),
                )
                synergy_coverage = dict(zip(
                    ["total_rows", "reliable_rows", "max_games"],
                    cursor.fetchone(),
                ))

                cursor.execute(
                    """
                    SELECT
                        DATE_TRUNC('month', start_time)::date AS month,
                        COUNT(DISTINCT match_id) AS matches
                    FROM matches
                    GROUP BY 1
                    ORDER BY 1
                    """
                )
                columns = [description[0] for description in cursor.description]
                match_trend = normalize_results([
                    dict(zip(columns, row)) for row in cursor.fetchall()
                ])

                cursor.execute(
                    """
                    SELECT
                        DATE_TRUNC('month', m.start_time)::date AS month,
                        COUNT(DISTINCT p.match_id) AS appearances,
                        ROUND(AVG(CASE WHEN p.is_winner THEN 1.0 ELSE 0.0 END)::numeric, 4) AS win_rate
                    FROM players p
                    JOIN matches m ON m.match_id = p.match_id
                    JOIN heroes h ON h.hero_id = p.hero_id
                    WHERE LOWER(h.localized_name) = LOWER(%s)
                    GROUP BY 1
                    ORDER BY 1
                    """,
                    (hero_name,),
                )
                columns = [description[0] for description in cursor.description]
                hero_trend = normalize_results([
                    dict(zip(columns, row)) for row in cursor.fetchall()
                ])

        return jsonify(
            {
                "status": "ok",
                "model": active_model_label(),
                "selected_hero": hero_name,
                "heroes": heroes,
                "stats": {
                    "enriched_matches": enriched_matches,
                    "enriched_player_rows": enriched_player_rows,
                    "matchup_rows": matchup_rows,
                    "synergy_rows": synergy_rows,
                },
                "coverage": {
                    "hero_appearances": hero_appearances,
                    "matchups": matchup_coverage,
                    "synergies": synergy_coverage,
                    "trend_months": len(match_trend),
                    "reliable_threshold": 20,
                    "min_hero_appearances": 50,
                },
                "match_trend": match_trend,
                "hero_trend": hero_trend,
                "counters": counters,
                "synergies": synergies,
                # Backward-compatible field for older clients.
                "pudge_counters": counters if hero_name == "Pudge" else [],
                "quick_questions": [
                    f"what counters {hero_name} in Dota 2?",
                    f"what heroes work best with {hero_name}?",
                    "Which 10 heroes have the highest total kills, and how many matches did they appear in?",
                    "How many matches are there by month?",
                ],
            }
        )
    except Exception:
        logging.exception("Meta dashboard failed")
        return jsonify({"error": "The meta dashboard could not be loaded."}), 500


@app.post("/sql-query")
def sql_query():
    body = request.get_json(silent=True) or {}
    question = body.get("question") or body.get("query")
    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": "A non-empty question is required."}), 400

    question = question.strip()
    sql = None
    attempts = 0

    try:
        schema = get_database_schema()
        schema_context = format_schema_context(schema)
        domain_hints = get_domain_hints(schema, question)
        data_profile = get_database_profile(schema)
        quality = get_dota_data_quality(schema)

        if quality and asks_for_dota_matchups(question) and not quality["sufficient_for_matchups"]:
            return insufficient_matchup_response(quality)
        if quality and asks_for_dota_matchups(question):
            deterministic_response = deterministic_dota_matchup_response(question, quality)
            if deterministic_response:
                return deterministic_response
        if quality and asks_for_dota_hero_trend(question):
            deterministic_response = deterministic_dota_hero_trend_response(question, quality)
            if deterministic_response:
                return deterministic_response
        if quality and asks_for_best_hero(question) and not quality["sufficient_for_best_hero"]:
            return insufficient_best_hero_response(quality)

        for attempts in range(1, 3):
            sql = (
                generate_sql_query(question, schema_context, domain_hints)
                if attempts == 1
                else generate_sql_query(question, schema_context, domain_hints, sql, query_error)
            )
            try:
                results = execute_query(sql)
                break
            except QueryExecutionError as exc:
                query_error = str(exc)
                if attempts == 2:
                    raise

        normalized_results = normalize_results(results)
        chart_specs, chart_agent_attempts, chart_fallback = choose_visualization_plans(
            question, sql, normalized_results
        )
        visualizations = [
            {
                "chart_type": chart_spec["type"],
                "chart_spec": chart_spec,
                "chart_data": build_chart(chart_spec, normalized_results),
            }
            for chart_spec in chart_specs
        ]
        primary_visualization = visualizations[0]
        answer, answer_fallback = generate_answer_summary(
            question, sql, normalized_results, chart_specs
        )
        return jsonify(
            {
                "status": "ok",
                "sql": sql,
                "results": normalized_results,
                "visualizations": visualizations,
                "answer": answer,
                "answer_fallback": answer_fallback,
                # Keep the primary fields for clients using the original API contract.
                "chart_type": primary_visualization["chart_type"],
                "chart_data": primary_visualization["chart_data"],
                "chart_spec": primary_visualization["chart_spec"],
                "chart_agent_attempts": chart_agent_attempts,
                "chart_fallback": chart_fallback,
                "data_quality": quality,
                "data_profile": data_profile,
                "schema": schema,
                "model": active_model_label(),
                "attempts": attempts,
            }
        )
    except (RuntimeError, ValueError, QueryExecutionError) as exc:
        logging.warning("Request failed: %s", exc)
        return jsonify({"error": str(exc)}), 502
    except Exception:
        logging.exception("Unexpected API error")
        return jsonify({"error": "The analytics request failed unexpectedly."}), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
