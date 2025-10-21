from fastapi import FastAPI
from espn_api.basketball import League
import os
from dotenv import load_dotenv

load_dotenv()   # reads .env file if present

app = FastAPI(title="ESPN Fantasy Basketball API")

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
    """
    Compare current rosters to the last snapshot and report any adds or cuts.
    """
    global last_snapshot
    current = {t.team_name: [p.name for p in t.roster] for t in league.teams}
    changes = {}

    if last_snapshot:
        for team, players in current.items():
            old_players = last_snapshot.get(team, [])
            added = list(set(players) - set(old_players))
            removed = list(set(old_players) - set(players))
            if added or removed:
                changes[team] = {"added": added, "removed": removed}

    # Update snapshot
    last_snapshot = current
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "changes": changes or "No roster changes since last check."
    }
