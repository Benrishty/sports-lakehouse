-- NFL gold layer: business-ready materialized views over silver.
-- Grain is in each view's name. "Scrimmage play" = a pass or a rush with a valid EPA.
-- EPA (expected points added) comes from nflverse's model; success = EPA > 0.

-- ---------------------------------------------------------------- team × game
CREATE OR REFRESH MATERIALIZED VIEW gold_team_games
COMMENT "One row per team per completed game: score, margin and result vs. the closing spread, total points vs. the closing over/under, and EPA efficiency."
AS
WITH team_games AS (
  SELECT game_id, season, game_type, week, game_date,
         home_team AS team, away_team AS opponent, 'home' AS home_away,
         home_score AS points_for, away_score AS points_against,
         result AS margin, spread_line AS expected_margin, total_line
  FROM silver_games WHERE result IS NOT NULL
  UNION ALL
  SELECT game_id, season, game_type, week, game_date,
         away_team, home_team, 'away',
         away_score, home_score,
         -result, -spread_line, total_line
  FROM silver_games WHERE result IS NOT NULL
),
scrimmage AS (
  SELECT game_id, posteam, defteam, epa, success
  FROM silver_plays
  WHERE (is_pass = 1 OR is_rush = 1) AND epa IS NOT NULL AND posteam IS NOT NULL
),
off AS (
  SELECT game_id, posteam AS team, COUNT(*) AS off_plays, AVG(epa) AS off_epa_per_play, AVG(success) AS off_success_rate
  FROM scrimmage GROUP BY game_id, posteam
),
def AS (
  SELECT game_id, defteam AS team, COUNT(*) AS def_plays, AVG(epa) AS def_epa_per_play, AVG(success) AS def_success_rate
  FROM scrimmage GROUP BY game_id, defteam
)
SELECT
  g.*,
  CASE WHEN g.margin > 0 THEN 'W' WHEN g.margin < 0 THEN 'L' ELSE 'T' END AS outcome,
  g.margin - g.expected_margin AS cover_margin,
  CASE WHEN g.expected_margin IS NULL THEN NULL
       WHEN g.margin - g.expected_margin > 0 THEN 'cover'
       WHEN g.margin - g.expected_margin < 0 THEN 'no cover'
       ELSE 'push' END AS ats_outcome,
  CASE WHEN g.expected_margin IS NULL THEN NULL
       WHEN g.expected_margin > 0 THEN 'favorite'
       WHEN g.expected_margin < 0 THEN 'underdog'
       ELSE 'pick' END AS spread_role,
  g.points_for + g.points_against AS total_points,
  CASE WHEN g.total_line IS NULL THEN NULL
       WHEN g.points_for + g.points_against > g.total_line THEN 'over'
       WHEN g.points_for + g.points_against < g.total_line THEN 'under'
       ELSE 'push' END AS ou_outcome,
  o.off_plays, o.off_epa_per_play, o.off_success_rate,
  d.def_plays, d.def_epa_per_play, d.def_success_rate,
  o.off_epa_per_play - d.def_epa_per_play AS net_epa_per_play
FROM team_games g
LEFT JOIN off o ON o.game_id = g.game_id AND o.team = g.team
LEFT JOIN def d ON d.game_id = g.game_id AND d.team = g.team;

-- ---------------------------------------------------------------- team × season
CREATE OR REFRESH MATERIALIZED VIEW gold_team_season
COMMENT "One row per team per regular season: team name, conference and division, record, record against the spread, play-weighted EPA efficiency, league ranks and luck_gap (negative = unlucky, positive = lucky)."
AS
WITH scrimmage AS (
  SELECT season, posteam, defteam, epa, success, is_pass
  FROM silver_plays
  WHERE season_type = 'REG' AND (is_pass = 1 OR is_rush = 1) AND epa IS NOT NULL AND posteam IS NOT NULL
),
off AS (
  SELECT season, posteam AS team, COUNT(*) AS off_plays, AVG(epa) AS off_epa_per_play,
         AVG(success) AS off_success_rate, AVG(is_pass) AS pass_rate,
         AVG(CASE WHEN is_pass = 1 THEN epa END) AS off_pass_epa_per_play,
         AVG(CASE WHEN is_pass = 0 THEN epa END) AS off_rush_epa_per_play
  FROM scrimmage GROUP BY season, posteam
),
def AS (
  SELECT season, defteam AS team, COUNT(*) AS def_plays, AVG(epa) AS def_epa_per_play, AVG(success) AS def_success_rate
  FROM scrimmage GROUP BY season, defteam
),
record AS (
  SELECT season, team,
         COUNT(*) AS games,
         COUNT_IF(outcome = 'W') AS wins, COUNT_IF(outcome = 'L') AS losses, COUNT_IF(outcome = 'T') AS ties,
         COUNT_IF(ats_outcome = 'cover') AS ats_covers, COUNT_IF(ats_outcome = 'no cover') AS ats_losses,
         SUM(points_for) - SUM(points_against) AS point_differential,
         AVG(cover_margin) AS avg_cover_margin
  FROM gold_team_games WHERE game_type = 'REG'
  GROUP BY season, team
)
SELECT
  o.season, o.team, t.team_name, t.conference, t.division, t.team_logo_url,
  r.games, r.wins, r.losses, r.ties, r.ats_covers, r.ats_losses, r.point_differential, r.avg_cover_margin,
  o.off_plays, o.off_epa_per_play, o.off_success_rate, o.pass_rate, o.off_pass_epa_per_play, o.off_rush_epa_per_play,
  d.def_plays, d.def_epa_per_play, d.def_success_rate,
  o.off_epa_per_play - d.def_epa_per_play AS net_epa_per_play,
  RANK() OVER (PARTITION BY o.season ORDER BY o.off_epa_per_play DESC) AS off_epa_rank,
  RANK() OVER (PARTITION BY o.season ORDER BY d.def_epa_per_play ASC) AS def_epa_rank,
  RANK() OVER (PARTITION BY o.season ORDER BY o.off_epa_per_play - d.def_epa_per_play DESC) AS net_epa_rank,
  -- record rank by win percentage (ties count half), 1 = best record
  RANK() OVER (PARTITION BY o.season ORDER BY (r.wins + 0.5 * r.ties) / r.games DESC) AS record_rank,
  -- luck_gap = net_epa_rank - record_rank. Negative = UNLUCKY (plays better than its record);
  -- positive = LUCKY (record better than its play). Stored here so nobody re-derives the sign.
  RANK() OVER (PARTITION BY o.season ORDER BY o.off_epa_per_play - d.def_epa_per_play DESC)
    - RANK() OVER (PARTITION BY o.season ORDER BY (r.wins + 0.5 * r.ties) / r.games DESC) AS luck_gap
FROM off o
JOIN def d ON d.season = o.season AND d.team = o.team
LEFT JOIN record r ON r.season = o.season AND r.team = o.team
LEFT JOIN silver_teams t ON t.team = o.team;

-- ---------------------------------------------------------------- QB × season
CREATE OR REFRESH MATERIALIZED VIEW gold_qb_season
COMMENT "One row per quarterback per regular season (min. 100 dropbacks): full name, headshot, EPA per dropback, CPOE, success rate."
AS
WITH qb AS (
  SELECT
    season,
    dropback_player_id AS player_id,
    MAX_BY(dropback_player_name, game_date) AS player_short_name,
    MAX_BY(posteam, game_date) AS latest_team,
    COUNT(DISTINCT game_id) AS games,
    COUNT(*) AS dropbacks,
    AVG(qb_epa) AS epa_per_dropback,
    SUM(qb_epa) AS total_epa,
    AVG(cpoe) AS cpoe,
    AVG(success) AS success_rate,
    SUM(sack) AS sacks,
    SUM(interception) AS interceptions,
    RANK() OVER (PARTITION BY season ORDER BY AVG(qb_epa) DESC) AS epa_rank
  FROM silver_plays
  WHERE season_type = 'REG' AND qb_dropback = 1 AND qb_epa IS NOT NULL AND dropback_player_id IS NOT NULL
  GROUP BY season, dropback_player_id
  HAVING COUNT(*) >= 100
)
SELECT
  qb.season, qb.player_id,
  COALESCE(p.player_name, qb.player_short_name) AS player_name,
  qb.player_short_name, p.headshot_url,
  qb.latest_team, qb.games, qb.dropbacks, qb.epa_per_dropback, qb.total_epa, qb.cpoe, qb.success_rate,
  qb.sacks, qb.interceptions, qb.epa_rank
FROM qb
LEFT JOIN silver_players p ON p.player_id = qb.player_id;

-- ---------------------------------------------------------------- team × season betting
CREATE OR REFRESH MATERIALIZED VIEW gold_team_betting
COMMENT "One row per team per regular season: record against the spread (overall, as favorite/underdog, home/away) and over/under record, from closing lines."
AS
SELECT
  g.season, g.team,
  COUNT(*) AS games,
  COUNT_IF(g.ats_outcome = 'cover') AS ats_covers,
  COUNT_IF(g.ats_outcome = 'no cover') AS ats_losses,
  COUNT_IF(g.ats_outcome = 'push') AS ats_pushes,
  COUNT_IF(g.ats_outcome = 'cover') / NULLIF(COUNT_IF(g.ats_outcome IN ('cover', 'no cover')), 0) AS ats_cover_pct,
  AVG(g.cover_margin) AS avg_cover_margin,
  COUNT_IF(g.spread_role = 'favorite') AS games_as_favorite,
  COUNT_IF(g.spread_role = 'favorite' AND g.ats_outcome = 'cover') AS favorite_covers,
  COUNT_IF(g.spread_role = 'favorite' AND g.ats_outcome = 'no cover') AS favorite_ats_losses,
  COUNT_IF(g.spread_role = 'underdog') AS games_as_underdog,
  COUNT_IF(g.spread_role = 'underdog' AND g.ats_outcome = 'cover') AS underdog_covers,
  COUNT_IF(g.spread_role = 'underdog' AND g.ats_outcome = 'no cover') AS underdog_ats_losses,
  COUNT_IF(g.spread_role = 'underdog' AND g.outcome = 'W') AS outright_underdog_wins,
  COUNT_IF(g.home_away = 'home' AND g.ats_outcome = 'cover') AS home_covers,
  COUNT_IF(g.home_away = 'home' AND g.ats_outcome = 'no cover') AS home_ats_losses,
  COUNT_IF(g.home_away = 'away' AND g.ats_outcome = 'cover') AS away_covers,
  COUNT_IF(g.home_away = 'away' AND g.ats_outcome = 'no cover') AS away_ats_losses,
  COUNT_IF(g.ou_outcome = 'over') AS overs,
  COUNT_IF(g.ou_outcome = 'under') AS unders,
  COUNT_IF(g.ou_outcome = 'push') AS ou_pushes,
  COUNT_IF(g.ou_outcome = 'over') / NULLIF(COUNT_IF(g.ou_outcome IN ('over', 'under')), 0) AS over_pct,
  AVG(g.total_points - g.total_line) AS avg_total_vs_line
FROM gold_team_games g
WHERE g.game_type = 'REG'
GROUP BY g.season, g.team;

-- ---------------------------------------------------------------- standings
CREATE OR REFRESH MATERIALIZED VIEW gold_standings
COMMENT "One row per team per regular season since 2002 (current 8-division alignment): division rank, division leader, games back and an APPROXIMATE conference seed. Seeds 1-4 = division leaders, then wild cards. 7 playoff teams per conference from 2020, 6 before. Ties are broken by point differential only, not the official NFL tiebreakers."
AS
WITH base AS (
  SELECT s.season, s.team, s.team_name, s.conference, s.division,
         s.games, s.wins, s.losses, s.ties,
         (s.wins + 0.5 * s.ties) / s.games AS win_pct,
         s.point_differential, s.net_epa_rank, s.luck_gap
  FROM gold_team_season s
  WHERE s.season >= 2002 AND s.games > 0 AND s.division IS NOT NULL
),
div AS (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY season, division ORDER BY win_pct DESC, point_differential DESC, team) AS division_rank,
         FIRST_VALUE(wins) OVER (PARTITION BY season, division ORDER BY win_pct DESC, point_differential DESC, team) AS leader_wins,
         FIRST_VALUE(losses) OVER (PARTITION BY season, division ORDER BY win_pct DESC, point_differential DESC, team) AS leader_losses
  FROM base
),
grouped AS (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY season, conference, division_rank = 1
                            ORDER BY win_pct DESC, point_differential DESC, team) AS group_rank
  FROM div
)
SELECT
  season, team, team_name, conference, division,
  games, wins, losses, ties, win_pct, point_differential,
  division_rank,
  division_rank = 1 AS division_leader,
  ((leader_wins - wins) + (losses - leader_losses)) / 2.0 AS division_games_back,
  CASE WHEN division_rank = 1 THEN group_rank ELSE 4 + group_rank END AS conference_seed,
  (CASE WHEN division_rank = 1 THEN group_rank ELSE 4 + group_rank END) <= IF(season >= 2020, 7, 6) AS in_playoff_position,
  net_epa_rank, luck_gap
FROM grouped;

-- ---------------------------------------------------------------- player × season
CREATE OR REFRESH MATERIALIZED VIEW gold_player_season
COMMENT "One row per player per regular season, 1999 → today: full name, position, headshot, passing / rushing / receiving / defensive totals, EPA and fantasy points, with a fantasy rank within position group."
AS
WITH s AS (
  SELECT
    w.season, w.player_id,
    MAX_BY(w.player_name, w.week) AS player_name_week,
    MAX_BY(w.position, w.week) AS position,
    MAX_BY(w.position_group, w.week) AS position_group,
    MAX_BY(w.team, w.week) AS latest_team,
    MAX_BY(w.headshot_url, w.week) AS headshot_url_week,
    COUNT(*) AS games,
    SUM(w.completions) AS completions, SUM(w.attempts) AS pass_attempts, SUM(w.passing_yards) AS passing_yards,
    SUM(w.passing_tds) AS passing_tds, SUM(w.passing_interceptions) AS interceptions, SUM(w.sacks_suffered) AS sacks_taken,
    SUM(w.passing_epa) AS passing_epa,
    SUM(w.carries) AS carries, SUM(w.rushing_yards) AS rushing_yards, SUM(w.rushing_tds) AS rushing_tds,
    SUM(w.rushing_epa) AS rushing_epa,
    SUM(w.targets) AS targets, SUM(w.receptions) AS receptions, SUM(w.receiving_yards) AS receiving_yards,
    SUM(w.receiving_tds) AS receiving_tds, SUM(w.receiving_epa) AS receiving_epa,
    SUM(w.def_tackles_solo) AS solo_tackles, SUM(w.def_tackle_assists) AS assisted_tackles,
    SUM(w.def_sacks) AS sacks, SUM(w.def_interceptions) AS def_interceptions,
    SUM(w.fg_made) AS fg_made, SUM(w.fg_att) AS fg_att,
    SUM(w.fantasy_points_ppr) AS fantasy_points_ppr
  FROM silver_player_week w
  WHERE w.season_type = 'REG'
  GROUP BY w.season, w.player_id
)
SELECT
  s.season, s.player_id,
  COALESCE(p.player_name, s.player_name_week) AS player_name,
  s.position, s.position_group, s.latest_team,
  COALESCE(p.headshot_url, s.headshot_url_week) AS headshot_url,
  s.games,
  s.completions, s.pass_attempts, s.passing_yards, s.passing_tds, s.interceptions, s.sacks_taken, s.passing_epa,
  s.carries, s.rushing_yards, s.rushing_tds, s.rushing_epa,
  s.targets, s.receptions, s.receiving_yards, s.receiving_tds, s.receiving_epa,
  s.solo_tackles, s.assisted_tackles, s.sacks, s.def_interceptions,
  s.fg_made, s.fg_att,
  s.fantasy_points_ppr,
  RANK() OVER (PARTITION BY s.season, s.position_group ORDER BY s.fantasy_points_ppr DESC NULLS LAST) AS fantasy_rank_in_position
FROM s
LEFT JOIN silver_players p ON p.player_id = s.player_id;
