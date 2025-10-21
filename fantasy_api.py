from fastapi import FastAPI
from espn_api.basketball import League
import os
from dotenv import load_dotenv

load_dotenv()   # reads .env file if present

from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="ESPN Fantasy Basketball API",
    description="API for accessing ESPN fantasy basketball league data.",
    version="1.0.0"
)

# Custom OpenAPI schema to include 'servers' for ChatGPT Actions
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["servers"] = [{"url": "https://hooping-api.onrender.com"}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Load cookies from environment variables
LEAGUE_ID = 1035166756
YEAR = 2026
ESPN_S2 = os.getenv("ESPN_S2")
SWID = os.getenv("ESPN_SWID")

# Create League object
league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

@app.get("/teams")
def teams():
    """Return basic team info."""
    result = []
    for t in league.teams:
        result.append({
            "id": t.team_id,
            "name": t.team_name,
            "wins": t.wins,
            "losses": t.losses
        })
    return result


@app.get("/transactions")
def transactions(size: int = 10):
    """Return recent league transactions."""
    try:
        acts = league.recent_activity(size=size)
        updates = []
        for act in acts:
            for a in act.actions:
                updates.append({
                    "date": str(act.date),
                    "team": a[0],
                    "action": a[1],
                    "player": a[2]
                })
        return updates
    except Exception as e:
        return {"error": str(e), "hint": "Some private leagues restrict the communication feed."}


@app.get("/rosters")
def rosters():
    """Return full rosters for all teams with player stats."""
    result = []
    for team in league.teams:
        roster = []
        for player in team.roster:
            stats = player.stats.get('avg', {}) if hasattr(player, 'stats') else {}
            roster.append({
                "name": player.name,
                "position": player.position,
                "pro_team": player.proTeam,
                "injury_status": player.injuryStatus,
                "points_avg": stats.get("PTS"),
                "rebounds_avg": stats.get("REB"),
                "assists_avg": stats.get("AST"),
                "blocks_avg": stats.get("BLK"),
                "steals_avg": stats.get("STL")
            })
        result.append({
            "team": team.team_name,
            "roster": roster
        })
    return result
import json, time

# Temporary storage for last-known rosters
last_snapshot = {}

@app.get("/changes")
def changes():
    """Check for adds/drops and post to Discord if any changes are found."""
    global last_snapshot
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    current = {t.team_name: [p.name for p in t.roster] for t in league.teams}
    changes = {}

    # Compare rosters
    if last_snapshot:
        for team, players in current.items():
            old_players = last_snapshot.get(team, [])
            added = list(set(players) - set(old_players))
            removed = list(set(old_players) - set(players))
            if added or removed:
                changes[team] = {"added": added, "removed": removed}

                # Send to Discord
                if webhook:
                    msg = f"🏀 **{team}** roster changes:\n"
                    if added:
                        msg += f"➕ Added: {', '.join(added)}\n"
                    if removed:
                        msg += f"➖ Dropped: {', '.join(removed)}"
                    requests.post(webhook, json={"content": msg})

    last_snapshot = current
    return {"timestamp": time.time(), "changes": changes}

from datetime import datetime, timedelta

from datetime import datetime, timedelta

@app.get("/rosters_detailed")
def rosters_detailed():
    """
    Player + team details with correct weekly projections:
    weekly = per-game projection * games_this_week.
    """
    result = []

    today = datetime.today()
    start_of_week = today - timedelta(days=today.weekday())   # Monday
    end_of_week   = start_of_week + timedelta(days=6)          # Sunday

    for team in league.teams:
        roster_data = []
        team_projected_weekly = {"PTS": 0, "REB": 0, "AST": 0, "BLK": 0, "STL": 0, "FPTS": 0}
        team_season_total     = {"PTS": 0, "REB": 0, "AST": 0, "BLK": 0, "STL": 0, "FPTS": 0}

        for player in team.roster:
            avg_stats   = player.stats.get("avg", {})
            total_stats = player.stats.get("total", {})

            # ESPN projections (nested, then legacy)
            proj_total = (
                player.stats.get(f"{YEAR}_projected", {}).get("total", {})
                or player.stats.get("projected_total", {})
                or {}
            )
            proj_avg = (
                player.stats.get(f"{YEAR}_projected", {}).get("avg", {})
                or player.stats.get("projected_avg", {})
                or {}
            )

            # Flat projection fields (applied totals/averages)
            projected_total_points = getattr(player, "projected_total_points", None)
            projected_avg_points   = getattr(player, "projected_avg_points",   None)

            # Count games the player has this week (from schedule dates)
            games_this_week = sum(
                1 for g in getattr(player, "schedule", {}).values()
                if g.get("date") and start_of_week <= g["date"] <= end_of_week
            )

            # -----------------------------
            # Per-game projection selection:
            # 1) prefer ESPN projected per-game (most accurate for games played)
            # 2) else, derive from season totals if available
            # -----------------------------
            # Per-game fantasy points
            if projected_avg_points:  # ESPN per-game projection present
                per_game_fp = projected_avg_points
            elif projected_total_points and projected_total_points > 0:
                # Derive per-game using expected games if we can estimate it
                # expected_games = season_total / per-game (if available), else cap at 82
                est_games = None
                if proj_avg.get("FPTS"):
                    est_games = max(1, round(projected_total_points / proj_avg["FPTS"]))
                per_game_fp = projected_total_points / float(est_games or 82)
            else:
                per_game_fp = None

            projected_weekly_fantasy_points = (per_game_fp * games_this_week) if (per_game_fp and games_this_week) else None

            # Per-game categories (PTS/REB/AST/BLK/STL)
            per_game_stats = {}
            for stat in ["PTS", "REB", "AST", "BLK", "STL"]:
                if proj_avg.get(stat) is not None:
                    per_game_stats[stat] = proj_avg[stat]
                elif proj_total.get(stat):
                    # fallback: derive per-game from season totals
                    # try estimating expected games from another avg if present
                    est_games = None
                    # use any available avg stat as proxy for expected games
                    for key in ["PTS", "REB", "AST", "BLK", "STL", "FPTS"]:
                        if proj_avg.get(key):
                            # projected_total / projected_avg ~ expected games
                            est_games = max(1, round((proj_total.get(key, 0) or 0) / proj_avg[key])) if proj_total.get(key) else None
                            if est_games:
                                break
                    per_game_stats[stat] = (proj_total[stat] / float(est_games or 82))
                else:
                    per_game_stats[stat] = None

            # Weekly categories = per-game * games_this_week
            weekly_stats = {k: ((per_game_stats[k] * games_this_week) if (per_game_stats[k] is not None and games_this_week) else 0) for k in ["PTS", "REB", "AST", "BLK", "STL"]}

            # Player payload
            player_info = {
                "name": player.name,
                "position": player.position,
                "pro_team": player.proTeam,
                "injury_status": player.injuryStatus,
                "injury_detail": getattr(player, "injuryStatusDetail", None),
                "lineup_slot": getattr(player, "lineupSlot", None),
                "acquisition_type": getattr(player, "acquisitionType", None),

                # Season averages
                "avg_points":   avg_stats.get("PTS"),
                "avg_rebounds": avg_stats.get("REB"),
                "avg_assists":  avg_stats.get("AST"),
                "avg_blocks":   avg_stats.get("BLK"),
                "avg_steals":   avg_stats.get("STL"),
                "avg_fantasy_points": avg_stats.get("FPTS"),
                "avg_fg_pct":   avg_stats.get("FG%"),
                "avg_ft_pct":   avg_stats.get("FT%"),
                "avg_3pm":      avg_stats.get("3PM"),
                "avg_turnovers":avg_stats.get("TO"),

                # Season totals
                "total_points":  total_stats.get("PTS"),
                "total_rebounds":total_stats.get("REB"),
                "total_assists": total_stats.get("AST"),
                "total_blocks":  total_stats.get("BLK"),
                "total_steals":  total_stats.get("STL"),
                "total_fantasy_points": total_stats.get("FPTS"),
                "games_played": total_stats.get("GP"),

                # Projections (season-long + per-game + weekly)
                "projected_points":  proj_total.get("PTS"),
                "projected_rebounds":proj_total.get("REB"),
                "projected_assists": proj_total.get("AST"),
                "projected_blocks":  proj_total.get("BLK"),
                "projected_steals":  proj_total.get("STL"),
                "projected_fantasy_points_season": projected_total_points,   # season total
                "projected_avg_fantasy_points":    projected_avg_points,     # per-game
                "games_this_week": games_this_week,
                "projected_weekly_fantasy_points": projected_weekly_fantasy_points,

                # Weekly per-category projections
                "projected_weekly_points":  weekly_stats["PTS"],
                "projected_weekly_rebounds":weekly_stats["REB"],
                "projected_weekly_assists": weekly_stats["AST"],
                "projected_weekly_blocks":  weekly_stats["BLK"],
                "projected_weekly_steals":  weekly_stats["STL"],
            }

            roster_data.append(player_info)

            # Team rollups
            # add season totals
            for k in team_season_total.keys():
                team_season_total[k] += total_stats.get(k, 0) or 0

            # add weekly FPTS and per-category weekly
            if projected_weekly_fantasy_points:
                team_projected_weekly["FPTS"] += projected_weekly_fantasy_points
            for stat in ["PTS", "REB", "AST", "BLK", "STL"]:
                team_projected_weekly[stat] += weekly_stats[stat]

        result.append({
            "team": team.team_name,
            "season_totals": team_season_total,
            "projected_weekly_totals": team_projected_weekly,
            "roster": roster_data
        })

    return result
