-- Datasets for the "NFL Efficiency" AI/BI dashboard. Each block = one dataset (Data tab → Create from SQL).

-- @team_season
SELECT
  season, team, games, wins, losses, ties,
  CONCAT(wins, '-', losses, IF(ties > 0, CONCAT('-', ties), '')) AS record,
  CONCAT(ats_covers, '-', ats_losses) AS ats_record,
  ROUND(off_epa_per_play, 3)  AS offense_epa,
  ROUND(-def_epa_per_play, 3) AS defense_epa,   -- sign flipped: higher = better defense
  ROUND(net_epa_per_play, 3)  AS net_epa,
  net_epa_rank,
  record_rank,
  luck_gap   -- governed in gold: negative = unlucky, positive = lucky
FROM workspace.nfl.gold_team_season;
-- @qb_leaders
SELECT season, epa_rank, player_name, latest_team, dropbacks,
       ROUND(epa_per_dropback, 3) AS epa_per_dropback, ROUND(cpoe, 1) AS cpoe
FROM workspace.nfl.gold_qb_season
WHERE epa_rank <= 15;
-- @team_games
SELECT season, week, game_date, team, opponent, home_away, outcome,
       CONCAT(points_for, '-', points_against) AS score,
       ROUND(net_epa_per_play, 3) AS net_epa, cover_margin, ats_outcome
FROM workspace.nfl.gold_team_games
WHERE game_type = 'REG';
