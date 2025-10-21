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

@app.get("/rosters_detailed")
def rosters_detailed():
    """
    Return player-level and team-level fantasy data.
    Includes averages, totals, projections, and metadata.
    Excludes live game stats.
    """
    result = []

    for team in league.teams:
        roster_data = []
        team_projected = {"PTS": 0, "REB": 0, "AST": 0, "BLK": 0, "STL": 0, "FPTS": 0}
        team_total = {"PTS": 0, "REB": 0, "AST": 0, "BLK": 0, "STL": 0, "FPTS": 0}

        for player in team.roster:
            # Get all relevant stat dictionaries safely
            avg_stats = player.stats.get("avg", {})
            total_stats = player.stats.get("total", {})

            # ESPN projection handling (your version stores projections under YEAR_projected)
            proj_stats = (
                player.stats.get(f"{YEAR}_projected", {}).get("total", {})
                or player.stats.get("projected_total", {})
                or {}
            )
            proj_avg = (
                player.stats.get(f"{YEAR}_projected", {}).get("avg", {})
                or player.stats.get("projected_avg", {})
                or {}
            )

            # Player-level info
            player_info = {
                "name": player.name,
                "position": player.position,
                "pro_team": player.proTeam,
                "injury_status": player.injuryStatus,
                "injury_detail": getattr(player, "injuryStatusDetail", None),
                "lineup_slot": getattr(player, "lineupSlot", None),
                "acquisition_type": getattr(player, "acquisitionType", None),

                # Season averages
                "avg_points": avg_stats.get("PTS"),
                "avg_rebounds": avg_stats.get("REB"),
                "avg_assists": avg_stats.get("AST"),
                "avg_blocks": avg_stats.get("BLK"),
                "avg_steals": avg_stats.get("STL"),
                "avg_fantasy_points": avg_stats.get("FPTS"),
                "avg_fg_pct": avg_stats.get("FG%"),
                "avg_ft_pct": avg_stats.get("FT%"),
                "avg_3pm": avg_stats.get("3PM"),
                "avg_turnovers": avg_stats.get("TO"),

                # Season totals
                "total_points": total_stats.get("PTS"),
                "total_rebounds": total_stats.get("REB"),
                "total_assists": total_stats.get("AST"),
                "total_blocks": total_stats.get("BLK"),
                "total_steals": total_stats.get("STL"),
                "total_fantasy_points": total_stats.get("FPTS"),
                "games_played": total_stats.get("GP"),

                # Projections (for rest of matchup week)
                "projected_points": proj_stats.get("PTS"),
                "projected_rebounds": proj_stats.get("REB"),
                "projected_assists": proj_stats.get("AST"),
                "projected_blocks": proj_stats.get("BLK"),
                "projected_steals": proj_stats.get("STL"),
                "projected_fantasy_points": proj_stats.get("FPTS"),
                "projected_avg_points": proj_avg.get("PTS"),
                "projected_avg_fantasy_points": proj_avg.get("FPTS"),
            }

            roster_data.append(player_info)

            # Aggregate team totals
            for k in team_projected.keys():
                team_projected[k] += proj_stats.get(k, 0) or 0
                team_total[k] += total_stats.get(k, 0) or 0

        result.append({
            "team": team.team_name,
            "season_totals": team_total,
            "projected_week_totals": team_projected,
            "roster": roster_data
        })

    return result
