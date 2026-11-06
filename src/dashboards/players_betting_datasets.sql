-- Datasets for the "Players" and "Betting" pages of the NFL Efficiency dashboard.
-- Each block starting with an at-sign marker is one dataset. Images (headshots, logos) are URLs rendered by table image columns.

-- @passing_leaders
SELECT p.season, RANK() OVER (PARTITION BY p.season ORDER BY p.passing_yards DESC) AS rk,
       p.headshot_url, p.player_name, t.team_logo_url, p.latest_team AS team,
       p.games, p.completions, p.pass_attempts, p.passing_yards, p.passing_tds, p.interceptions,
       ROUND(q.epa_per_dropback, 3) AS epa_per_dropback
FROM workspace.nfl.gold_player_season p
LEFT JOIN workspace.nfl.silver_teams t ON t.team = p.latest_team
LEFT JOIN workspace.nfl.gold_qb_season q ON q.season = p.season AND q.player_id = p.player_id
WHERE p.position = 'QB' AND p.pass_attempts > 0
QUALIFY RANK() OVER (PARTITION BY p.season ORDER BY p.passing_yards DESC) <= 15
ORDER BY p.season DESC, rk;

-- @rushing_leaders
SELECT p.season, RANK() OVER (PARTITION BY p.season ORDER BY p.rushing_yards DESC) AS rk,
       p.headshot_url, p.player_name, p.position, t.team_logo_url, p.latest_team AS team,
       p.games, p.carries, p.rushing_yards, ROUND(p.rushing_yards / NULLIF(p.carries, 0), 1) AS yards_per_carry,
       p.rushing_tds, ROUND(p.rushing_epa, 1) AS rushing_epa
FROM workspace.nfl.gold_player_season p
LEFT JOIN workspace.nfl.silver_teams t ON t.team = p.latest_team
WHERE p.carries > 0
QUALIFY RANK() OVER (PARTITION BY p.season ORDER BY p.rushing_yards DESC) <= 15
ORDER BY p.season DESC, rk;

-- @receiving_leaders
SELECT p.season, RANK() OVER (PARTITION BY p.season ORDER BY p.receiving_yards DESC) AS rk,
       p.headshot_url, p.player_name, p.position, t.team_logo_url, p.latest_team AS team,
       p.games, p.targets, p.receptions, p.receiving_yards, p.receiving_tds, ROUND(p.receiving_epa, 1) AS receiving_epa
FROM workspace.nfl.gold_player_season p
LEFT JOIN workspace.nfl.silver_teams t ON t.team = p.latest_team
WHERE p.targets > 0
QUALIFY RANK() OVER (PARTITION BY p.season ORDER BY p.receiving_yards DESC) <= 15
ORDER BY p.season DESC, rk;

-- @team_betting
SELECT b.season, s.team_logo_url, b.team, s.team_name,
       CONCAT(s.wins, '-', s.losses, IF(s.ties > 0, CONCAT('-', s.ties), '')) AS record,
       CONCAT(b.ats_covers, '-', b.ats_losses, IF(b.ats_pushes > 0, CONCAT('-', b.ats_pushes), '')) AS ats_record,
       ROUND(100 * b.ats_cover_pct, 1) AS ats_cover_pct,
       CONCAT(b.favorite_covers, '-', b.favorite_ats_losses) AS ats_as_favorite,
       CONCAT(b.underdog_covers, '-', b.underdog_ats_losses) AS ats_as_underdog,
       b.outright_underdog_wins,
       CONCAT(b.overs, '-', b.unders, IF(b.ou_pushes > 0, CONCAT('-', b.ou_pushes), '')) AS over_under,
       ROUND(100 * b.over_pct, 1) AS over_pct,
       ROUND(b.avg_cover_margin, 1) AS avg_cover_margin,
       ROUND(b.avg_total_vs_line, 1) AS avg_total_vs_line
FROM workspace.nfl.gold_team_betting b
JOIN workspace.nfl.gold_team_season s ON s.season = b.season AND s.team = b.team
ORDER BY b.season DESC, b.ats_cover_pct DESC;
