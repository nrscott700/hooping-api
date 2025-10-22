from fastapi import FastAPI
from espn_api.basketball import League
import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
import time
import json

# --- Setup ---

load_dotenv()   # reads .env file if present

from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="ESPN Fantasy Basketball API",
    description="API for accessing ESPN fantasy basketball league data.",
    version="1.0.0"
)

# Custom OpenAPI schema for ChatGPT Actions
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


# --- Basic Endpoints ---

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


# --- Roster Changes (Discord Integration) ---

last_snapshot = {}

@app.get("/changes")
def changes():
    """Check for adds/drops and post to Discord if any changes are found."""
    global last_snapshot
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    current = {t.team_name: [p.name for p in t.roster] for t in league.teams}
    changes = {}

    if last_snapshot:
        for team, players in current.items():
            old_players = last_snapshot.get(team, [])
            added = list(set(players) - set(old_players))
            removed = list(set(old_players) - set(players))
            if added or removed:
                changes[team] = {"added": added, "removed": removed}

                if webhook:
                    msg = f"🏀 **{team}** roster changes:\n"
                    if added:
                        msg += f"➕ Added: {', '.join(added)}\n"
                    if removed:
                        msg += f"➖ Dropped: {', '.join(removed)}"
                    requests.post(webhook, json={"content": msg})

    last_snapshot = current
    return {"timestamp": time.time(), "changes": changes}


# --- Detailed Roster Data (Core Endpoint) ---

@app.get("/rosters_detailed")
def rosters_detailed():
    """
    Player + team details with correct weekly projections.
    weekly = ESPN projected average * games_this_week.
    Includes per-category and fantasy point summaries.
    """
    result = []
    today = datetime.today()
    start_of_week = today - timedelta(days=today.weekday())   # Monday
    end_of_week = start_of_week + timedelta(days=6)           # Sunday

    for team in league.teams:
        roster_data = []
        team_projected_weekly = {"PTS": 0, "REB": 0, "AST": 0, "BLK": 0, "STL": 0, "FPTS": 0}
        team_season_total = {"PTS": 0, "REB": 0, "AST": 0, "BLK": 0, "STL": 0, "FPTS": 0}

        for player in team.roster:
            avg_stats = player.stats.get("avg", {})
            total_stats = player.stats.get("total", {})

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

            games_this_week = sum(
                1 for g in getattr(player, "schedule", {}).values()
                if g.get("date") and start_of_week <= g["date"] <= end_of_week
            )

            # ESPN-sourced projections
            projected_total_points = getattr(player, "projected_total_points", None)
            projected_avg_points = getattr(player, "projected_avg_points", None)

            per_game_fp = projected_avg_points or (
                (projected_total_points / 82) if projected_total_points else 0
            )
            projected_weekly_fp = per_game_fp * games_this_week

            player_info = {
                "name": player.name,
                "position": player.position,
                "pro_team": player.proTeam,
                "injury_status": player.injuryStatus,
                "games_this_week": games_this_week,
                "projection_source": "ESPN",

                # Core stats
                "avg_points": avg_stats.get("PTS"),
                "avg_rebounds": avg_stats.get("REB"),
                "avg_assists": avg_stats.get("AST"),
                "avg_blocks": avg_stats.get("BLK"),
                "avg_steals": avg_stats.get("STL"),
                "avg_fantasy_points": avg_stats.get("FPTS"),
                "total_points": total_stats.get("PTS"),
                "total_rebounds": total_stats.get("REB"),
                "total_assists": total_stats.get("AST"),
                "total_blocks": total_stats.get("BLK"),
                "total_steals": total_stats.get("STL"),

                # ESPN Projections
                "projected_avg_fantasy_points": projected_avg_points,
                "projected_total_fantasy_points": projected_total_points,
                "projected_weekly_fantasy_points": round(projected_weekly_fp, 2),
            }

            roster_data.append(player_info)

            # Team-level aggregation
            if projected_weekly_fp:
                team_projected_weekly["FPTS"] += projected_weekly_fp
            for stat in ["PTS", "REB", "AST", "BLK", "STL"]:
                team_projected_weekly[stat] += proj_avg.get(stat, 0) * games_this_week
                team_season_total[stat] += total_stats.get(stat, 0) or 0

        result.append({
            "team": team.team_name,
            "projection_source": "ESPN",
            "season_totals": {k: round(v, 2) for k, v in team_season_total.items()},
            "projected_weekly_totals": {k: round(v, 2) for k, v in team_projected_weekly.items()},
            "roster": roster_data
        })

    return result


# --- Summary Endpoint ---

@app.get("/rosters_summary")
def rosters_summary():
    """
    Lightweight summary for team projections.
    Aggregates ESPN-sourced per-game projections and games_this_week.
    """
    today = datetime.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    summary = []

    for team in league.teams:
        team_weekly = {"PTS": 0, "REB": 0, "AST": 0, "BLK": 0, "STL": 0, "FPTS": 0}

        for player in team.roster:
            proj_avg = (
                player.stats.get(f"{YEAR}_projected", {}).get("avg", {})
                or player.stats.get("projected_avg", {})
                or {}
            )
            games_this_week = sum(
                1 for g in getattr(player, "schedule", {}).values()
                if g.get("date") and start_of_week <= g["date"] <= end_of_week
            )

            projected_avg_points = getattr(player, "projected_avg_points", None)
            per_game_fp = projected_avg_points or 0
            projected_weekly_fp = per_game_fp * games_this_week

            for stat in ["PTS", "REB", "AST", "BLK", "STL"]:
                team_weekly[stat] += (proj_avg.get(stat, 0) or 0) * games_this_week
            team_weekly["FPTS"] += projected_weekly_fp

        summary.append({
            "team": team.team_name,
            "projection_source": "ESPN",
            "projected_weekly_totals": {k: round(v, 2) for k, v in team_weekly.items()}
        })

    summary.sort(key=lambda x: x["projected_weekly_totals"]["FPTS"], reverse=True)
    return summary
