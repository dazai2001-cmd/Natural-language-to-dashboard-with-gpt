CREATE OR REPLACE VIEW hero_performance_scores AS
WITH hero_aggregates AS (
    SELECT
        h.hero_id,
        h.localized_name AS hero_name,
        COUNT(DISTINCT p.match_id)::integer AS matches_played,
        AVG(p.kills)::double precision AS avg_kills,
        AVG(p.deaths)::double precision AS avg_deaths,
        AVG(p.assists)::double precision AS avg_assists,
        AVG(p.gold_per_min)::double precision AS avg_gold_per_min,
        AVG(p.xp_per_min)::double precision AS avg_xp_per_min
    FROM players p
    JOIN heroes h ON h.hero_id = p.hero_id
    GROUP BY h.hero_id, h.localized_name
),
eligible AS (
    SELECT *
    FROM hero_aggregates
    WHERE matches_played >= 30
),
normalized AS (
    SELECT
        e.*,
        COALESCE((avg_kills - AVG(avg_kills) OVER ()) / NULLIF(STDDEV_POP(avg_kills) OVER (), 0), 0) AS kills_z,
        COALESCE((avg_deaths - AVG(avg_deaths) OVER ()) / NULLIF(STDDEV_POP(avg_deaths) OVER (), 0), 0) AS deaths_z,
        COALESCE((avg_assists - AVG(avg_assists) OVER ()) / NULLIF(STDDEV_POP(avg_assists) OVER (), 0), 0) AS assists_z,
        COALESCE((avg_gold_per_min - AVG(avg_gold_per_min) OVER ()) / NULLIF(STDDEV_POP(avg_gold_per_min) OVER (), 0), 0) AS gpm_z,
        COALESCE((avg_xp_per_min - AVG(avg_xp_per_min) OVER ()) / NULLIF(STDDEV_POP(avg_xp_per_min) OVER (), 0), 0) AS xpm_z
    FROM eligible e
)
SELECT
    hero_id,
    hero_name,
    matches_played,
    ROUND(avg_kills::numeric, 2) AS avg_kills,
    ROUND(avg_deaths::numeric, 2) AS avg_deaths,
    ROUND(avg_assists::numeric, 2) AS avg_assists,
    ROUND(avg_gold_per_min::numeric, 2) AS avg_gold_per_min,
    ROUND(avg_xp_per_min::numeric, 2) AS avg_xp_per_min,
    ROUND((matches_played::numeric / (matches_played + 30)), 4) AS reliability,
    ROUND((
        50 + 10 * (matches_played::numeric / (matches_played + 30)) *
        (0.25 * kills_z + 0.20 * assists_z - 0.20 * deaths_z + 0.20 * gpm_z + 0.15 * xpm_z)
    )::numeric, 2) AS performance_score
FROM normalized;

CREATE OR REPLACE VIEW player_match_facts AS
SELECT
    p.match_id,
    m.start_time,
    m.patch,
    p.account_id,
    p.hero_id,
    h.localized_name AS hero_name,
    p.player_slot,
    p.is_radiant,
    p.is_winner,
    p.kills,
    p.deaths,
    p.assists,
    p.gold_per_min,
    p.xp_per_min,
    p.lane,
    p.lane_role,
    p.is_roaming,
    p.item_0,
    p.item_1,
    p.item_2,
    p.item_3,
    p.item_4,
    p.item_5,
    p.item_neutral,
    p.ability_upgrades_arr
FROM players p
JOIN matches m ON m.match_id = p.match_id
JOIN heroes h ON h.hero_id = p.hero_id;

CREATE OR REPLACE VIEW hero_matchups AS
SELECT
    p.hero_id,
    h.localized_name AS hero_name,
    opponent.hero_id AS opponent_hero_id,
    opponent_hero.localized_name AS opponent_hero_name,
    COUNT(*)::integer AS games_played,
    SUM(CASE WHEN p.is_winner THEN 1 ELSE 0 END)::integer AS wins,
    ROUND(AVG(CASE WHEN p.is_winner THEN 1.0 ELSE 0.0 END)::numeric, 4) AS win_rate,
    ROUND((COUNT(*)::numeric / (COUNT(*) + 30)), 4) AS reliability,
    ROUND((
        50
        + 100
        * (AVG(CASE WHEN p.is_winner THEN 1.0 ELSE 0.0 END) - 0.5)
        * (COUNT(*)::numeric / (COUNT(*) + 30))
    )::numeric, 2) AS matchup_score,
    ROUND(AVG(p.kills)::numeric, 2) AS avg_kills,
    ROUND(AVG(p.deaths)::numeric, 2) AS avg_deaths,
    ROUND(AVG(p.assists)::numeric, 2) AS avg_assists
FROM players p
JOIN players opponent
  ON opponent.match_id = p.match_id
 AND opponent.is_radiant IS DISTINCT FROM p.is_radiant
JOIN heroes h ON h.hero_id = p.hero_id
JOIN heroes opponent_hero ON opponent_hero.hero_id = opponent.hero_id
WHERE p.hero_id IS NOT NULL
  AND opponent.hero_id IS NOT NULL
  AND p.is_winner IS NOT NULL
  AND p.is_radiant IS NOT NULL
  AND opponent.is_radiant IS NOT NULL
GROUP BY p.hero_id, h.localized_name, opponent.hero_id, opponent_hero.localized_name;

CREATE OR REPLACE VIEW hero_synergies AS
SELECT
    p.hero_id,
    h.localized_name AS hero_name,
    ally.hero_id AS ally_hero_id,
    ally_hero.localized_name AS ally_hero_name,
    COUNT(*)::integer AS games_played,
    SUM(CASE WHEN p.is_winner THEN 1 ELSE 0 END)::integer AS wins,
    ROUND(AVG(CASE WHEN p.is_winner THEN 1.0 ELSE 0.0 END)::numeric, 4) AS win_rate,
    ROUND((COUNT(*)::numeric / (COUNT(*) + 30)), 4) AS reliability,
    ROUND((
        50
        + 100
        * (AVG(CASE WHEN p.is_winner THEN 1.0 ELSE 0.0 END) - 0.5)
        * (COUNT(*)::numeric / (COUNT(*) + 30))
    )::numeric, 2) AS synergy_score
FROM players p
JOIN players ally
  ON ally.match_id = p.match_id
 AND ally.is_radiant = p.is_radiant
 AND ally.hero_id <> p.hero_id
JOIN heroes h ON h.hero_id = p.hero_id
JOIN heroes ally_hero ON ally_hero.hero_id = ally.hero_id
WHERE p.hero_id IS NOT NULL
  AND ally.hero_id IS NOT NULL
  AND p.is_winner IS NOT NULL
  AND p.is_radiant IS NOT NULL
GROUP BY p.hero_id, h.localized_name, ally.hero_id, ally_hero.localized_name;

CREATE OR REPLACE VIEW team_comps AS
SELECT
    p.match_id,
    m.start_time,
    m.patch,
    p.is_radiant,
    BOOL_OR(p.is_winner) AS won,
    ARRAY_AGG(p.hero_id ORDER BY h.localized_name) AS hero_ids,
    ARRAY_AGG(h.localized_name ORDER BY h.localized_name) AS hero_names,
    SUM(p.kills)::integer AS team_kills,
    SUM(p.deaths)::integer AS team_deaths,
    SUM(p.assists)::integer AS team_assists
FROM players p
JOIN matches m ON m.match_id = p.match_id
JOIN heroes h ON h.hero_id = p.hero_id
WHERE p.is_radiant IS NOT NULL
  AND p.is_winner IS NOT NULL
GROUP BY p.match_id, m.start_time, m.patch, p.is_radiant;

CREATE OR REPLACE VIEW hero_item_usage AS
WITH item_slots AS (
    SELECT hero_id, is_winner, item_0 AS item_id FROM players WHERE item_0 IS NOT NULL AND item_0 <> 0
    UNION ALL SELECT hero_id, is_winner, item_1 FROM players WHERE item_1 IS NOT NULL AND item_1 <> 0
    UNION ALL SELECT hero_id, is_winner, item_2 FROM players WHERE item_2 IS NOT NULL AND item_2 <> 0
    UNION ALL SELECT hero_id, is_winner, item_3 FROM players WHERE item_3 IS NOT NULL AND item_3 <> 0
    UNION ALL SELECT hero_id, is_winner, item_4 FROM players WHERE item_4 IS NOT NULL AND item_4 <> 0
    UNION ALL SELECT hero_id, is_winner, item_5 FROM players WHERE item_5 IS NOT NULL AND item_5 <> 0
    UNION ALL SELECT hero_id, is_winner, item_neutral FROM players WHERE item_neutral IS NOT NULL AND item_neutral <> 0
)
SELECT
    h.hero_id,
    h.localized_name AS hero_name,
    item_slots.item_id,
    COALESCE(i.name, item_slots.item_id::text) AS item_name,
    COUNT(*)::integer AS times_used,
    SUM(CASE WHEN item_slots.is_winner THEN 1 ELSE 0 END)::integer AS wins,
    ROUND(AVG(CASE WHEN item_slots.is_winner THEN 1.0 ELSE 0.0 END)::numeric, 4) AS win_rate
FROM item_slots
JOIN heroes h ON h.hero_id = item_slots.hero_id
LEFT JOIN items i ON i.item_id::text = item_slots.item_id::text
WHERE item_slots.is_winner IS NOT NULL
GROUP BY h.hero_id, h.localized_name, item_slots.item_id, i.name;
