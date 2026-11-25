#!/usr/bin/env python3
"""
Javis v5.0 — Automated Corner Analytics & Hybrid Backtesting Engine
- Zero external dependencies (Python 3 standard library only)
- Safe isolated v5 outputs: matches_v5.json & history_v5.json (never modifies v4.2 files)
- Strict separation of Club (45d lookback) and Official Senior Men's International (120d lookback)
- Pre-match Snapshot Lock + Auto-Grading (2.2h post-kickoff) + Hybrid 3,000-record Archive
"""

import json
import os
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

# ==============================================================================
# CONFIGURATION
# ==============================================================================
OUTPUT_MATCHES = "matches_v5.json"
OUTPUT_HISTORY = "history_v5.json"
LEGACY_HISTORY = "history.json"

MAX_HISTORY_RECORDS = 3000
UPCOMING_DAYS = 7
CLUB_LOOKBACK_DAYS = 45
INTL_LOOKBACK_DAYS = 120
GRADE_DELAY_HOURS = 2.2
VOID_EXPIRE_DAYS = 5
DEFAULT_TARGET_LINE = 9.5
MAX_WORKERS = 8
HTTP_TIMEOUT = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JavisCornerEngine/5.0)",
    "Accept": "application/json",
}

# Club Leagues & Cups (28 Competitions — 45-day lookback)
CLUB_LEAGUES = [
    ("eng.1", "Premier League", "EPL"),
    ("eng.2", "Championship", "EFL"),
    ("eng.fa", "FA Cup", "FAC"),
    ("eng.league_cup", "Carabao Cup", "CAR"),
    ("esp.1", "La Liga", "LAL"),
    ("esp.2", "La Liga 2", "LA2"),
    ("esp.copa_del_rey", "Copa del Rey", "CDR"),
    ("ger.1", "Bundesliga", "BUN"),
    ("ger.2", "2. Bundesliga", "BL2"),
    ("ger.dfb_pokal", "DFB-Pokal", "DFB"),
    ("ita.1", "Serie A", "SEA"),
    ("ita.2", "Serie B", "SEB"),
    ("ita.coppa_italia", "Coppa Italia", "COP"),
    ("fra.1", "Ligue 1", "L1"),
    ("fra.2", "Ligue 2", "L2"),
    ("fra.coupe_de_france", "Coupe de France", "CDF"),
    ("ned.1", "Eredivisie", "ERE"),
    ("por.1", "Primeira Liga", "POR"),
    ("bel.1", "Belgian Pro League", "BEL"),
    ("tur.1", "Süper Lig", "TUR"),
    ("sco.1", "Scottish Premiership", "SCO"),
    ("uefa.champions", "Champions League", "UCL"),
    ("uefa.europa", "Europa League", "UEL"),
    ("uefa.europa.conf", "Conference League", "UECL"),
    ("usa.1", "USA MLS", "MLS"),
    ("mex.1", "Liga MX", "LMX"),
    ("bra.1", "Brasileirão", "BRA"),
    ("arg.1", "Liga Profesional", "ARG"),
]

# Official Senior Men's International Competitions (120-day lookback — NO friendlies/youth/women)
INTL_LEAGUES = [
    ("uefa.nations", "UEFA Nations League", "UNL"),
    ("fifa.worldq.uefa", "World Cup Qualifiers (UEFA)", "WCQ"),
    ("fifa.worldq.conmebol", "World Cup Qualifiers (CONMEBOL)", "WCQ"),
    ("fifa.worldq.afc", "World Cup Qualifiers (AFC)", "WCQ"),
    ("fifa.worldq.concacaf", "World Cup Qualifiers (CONCACAF)", "WCQ"),
    ("fifa.worldq.caf", "World Cup Qualifiers (CAF)", "WCQ"),
    ("fifa.world", "FIFA World Cup", "WC"),
    ("uefa.euro", "UEFA Euro", "EURO"),
    ("conmebol.america", "Copa América", "COPA"),
    ("afc.asian.cup", "AFC Asian Cup", "AFC"),
    ("caf.nations", "AFCON", "AFCON"),
]

# ==============================================================================
# HELPERS
# ==============================================================================
def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(raw):
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Handle timestamps missing seconds like 2026-11-25T19:45+00:00
    if len(s) == 22 and s[16] in "+-":
        s = s[:16] + ":00" + s[16:]
    try:
        dt = datetime.fromisoformat(s)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_float(val):
    if val is None:
        return None
    s = str(val).strip().replace("%", "")
    if not s or s in ("-", "--", "N/A", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_json(url, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
    return None


def date_chunks(start_dt, end_dt, step_days):
    chunks = []
    cur = start_dt
    while cur <= end_dt:
        nxt = min(cur + timedelta(days=step_days - 1), end_dt)
        chunks.append((cur.strftime("%Y%m%d"), nxt.strftime("%Y%m%d")))
        cur = nxt + timedelta(days=1)
    return chunks


# ==============================================================================
# ESPN FETCHING & BOXSCORE EXTRACTION
# ==============================================================================
def fetch_scoreboard_events(slug, start_str, end_str):
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
        f"?dates={start_str}-{end_str}&limit=300"
    )
    data = fetch_json(url)
    if not data or "events" not in data:
        return []
    return data.get("events", [])


def parse_event_meta(ev, slug, league_name, comp_code, comp_type):
    event_id = str(ev.get("id", "")).strip()
    if not event_id:
        return None
    comps = ev.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    competitors = comp.get("competitors") or []
    if len(competitors) < 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    home_team = home.get("team") or {}
    away_team = away.get("team") or {}
    home_id = str(home_team.get("id", "")).strip()
    away_id = str(away_team.get("id", "")).strip()
    if not home_id or not away_id:
        return None

    dt = parse_iso_utc(ev.get("date") or comp.get("date"))
    if not dt:
        return None

    status_obj = (comp.get("status") or ev.get("status") or {}).get("type") or {}
    state = status_obj.get("state", "")  # 'pre', 'in', 'post'
    status_name = status_obj.get("name", "")

    return {
        "id": event_id,
        "slug": slug,
        "league": league_name,
        "comp_code": comp_code,
        "comp_type": comp_type,
        "kickoff_dt": dt,
        "kickoff_utc": iso_utc(dt),
        "home_id": home_id,
        "away_id": away_id,
        "home_team": home_team.get("displayName") or home_team.get("shortDisplayName") or "Home",
        "away_team": away_team.get("displayName") or away_team.get("shortDisplayName") or "Away",
        "home_short": home_team.get("shortDisplayName") or home_team.get("displayName") or "Home",
        "away_short": away_team.get("shortDisplayName") or away_team.get("displayName") or "Away",
        "state": state,
        "status_name": status_name,
    }


def extract_team_stats(stats_list):
    """Extract corners, SOT, blockedShots, totalShots from ESPN statistics array."""
    out = {"corners": None, "sot": None, "blocked": None, "shots": None}
    for st in stats_list or []:
        name = (st.get("name") or "").lower()
        label = (st.get("label") or "").lower()
        val = parse_float(st.get("displayValue"))
        if val is None:
            continue
        if name == "woncorners" or ("corner" in name and "conceded" not in name) or label == "corners":
            out["corners"] = val
        elif name in ("shotsontarget", "shotsongoal") or label == "shots on target":
            out["sot"] = val
        elif name in ("blockedshots", "shotsblocked") or "blocked" in name:
            out["blocked"] = val
        elif name in ("totalshots", "shots") or label in ("shots", "total shots"):
            out["shots"] = val
    return out


def fetch_boxscore_summary(slug, event_id, home_id=None, away_id=None):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}"
    data = fetch_json(url)
    if not data:
        return None

    # Determine status & extra time
    header = data.get("header") or {}
    h_comps = header.get("competitions") or []
    h_comp = h_comps[0] if h_comps else {}
    status_type = (h_comp.get("status") or {}).get("type") or {}
    state = status_type.get("state", "")
    status_name = status_type.get("name", "")
    extra_time = any(k in status_name.upper() for k in ("AET", "PEN", "EXTRA"))

    # Resolve home/away IDs from header if not provided
    if (not home_id or not away_id) and h_comp.get("competitors"):
        for c in h_comp["competitors"]:
            tid = str((c.get("team") or {}).get("id", ""))
            if c.get("homeAway") == "home":
                home_id = tid
            elif c.get("homeAway") == "away":
                away_id = tid

    box_teams = (data.get("boxscore") or {}).get("teams") or []
    if len(box_teams) < 2:
        return {"state": state, "extra_time": extra_time, "valid": False}

    stats_by_id = {}
    for bt in box_teams:
        tid = str((bt.get("team") or {}).get("id", ""))
        stats_by_id[tid] = extract_team_stats(bt.get("statistics"))

    h_st = stats_by_id.get(str(home_id))
    a_st = stats_by_id.get(str(away_id))
    if not h_st or not a_st:
        # Positional fallback only if IDs unavailable
        if not home_id or not away_id:
            h_st = extract_team_stats(box_teams[0].get("statistics"))
            a_st = extract_team_stats(box_teams[1].get("statistics"))
        else:
            return {"state": state, "extra_time": extra_time, "valid": False}

    if h_st["corners"] is None or a_st["corners"] is None:
        return {"state": state, "extra_time": extra_time, "valid": False}

    return {
        "state": state,
        "extra_time": extra_time,
        "valid": True,
        "home": h_st,
        "away": a_st,
    }


# ==============================================================================
# CN ULTRA 3-LAYER MODEL & GRADING (MIRRORS javis_v5.html DEFAULT_MODEL)
# ==============================================================================
def score_from_snapshot(snap):
    h_cr = snap["home_l3_corners"]
    a_cr = snap["away_l3_corners"]
    l1_total = round(h_cr + a_cr, 2)
    if l1_total >= 12.0:
        l1 = 3.0
    elif l1_total >= 10.5:
        l1 = 2.0
    elif l1_total >= 9.0:
        l1 = 1.0
    else:
        l1 = 0.0

    l2_total = round(snap["home_l3_chaos"] + snap["away_l3_chaos"], 2)
    if l2_total >= 16.5:
        l2 = 2.0
    elif l2_total >= 13.5:
        l2 = 1.0
    elif l2_total >= 11.5:
        l2 = 0.5
    else:
        l2 = 0.0

    h_con = snap["home_l3_conceded"]
    a_con = snap["away_l3_conceded"]
    h_pts = 1.0 if h_con >= 5.0 else (0.5 if h_con >= 4.2 else 0.0)
    a_pts = 1.0 if a_con >= 5.0 else (0.5 if a_con >= 4.2 else 0.0)
    l3 = round(h_pts + a_pts, 1)

    total_score = round(min(7.0, l1 + l2 + l3), 1)
    ref_home = round((h_cr + a_con) / 2.0, 1)
    ref_away = round((a_cr + h_con) / 2.0, 1)
    ref_exp = round(ref_home + ref_away, 1)
    return total_score, ref_exp


def classify_tier(score):
    if score >= 6.0:
        return "golden"
    if score >= 4.5:
        return "value"
    if score >= 3.0:
        return "normal"
    return "under"


def grade_match(actual_corners, score, line=DEFAULT_TARGET_LINE):
    tier = classify_tier(score)
    if tier == "under":
        return "WIN" if actual_corners < line else "LOSE"
    return "WIN" if actual_corners > line else "LOSE"


def build_team_l3(team_id, completed_games, summary_cache):
    """Build up to 3 most recent valid games with corners for team_id."""
    audit = []
    cr_list, con_list = [], []
    exact_chaos_list, fallback_chaos_list = [], []
    all_exact = True
    spike_flag = False

    for g in completed_games:
        if len(audit) >= 3:
            break
        ev_id = g["id"]
        if ev_id not in summary_cache:
            summary_cache[ev_id] = fetch_boxscore_summary(
                g["slug"], ev_id, g["home_id"], g["away_id"]
            )
        box = summary_cache[ev_id]
        if not box or not box.get("valid"):
            continue

        is_home = (g["home_id"] == team_id)
        my_st = box["home"] if is_home else box["away"]
        opp_st = box["away"] if is_home else box["home"]
        opp_name = g["away_short"] if is_home else g["home_short"]

        my_cr = int(round(my_st["corners"]))
        my_con = int(round(opp_st["corners"]))
        if my_cr >= 11:
            spike_flag = True

        cr_list.append(my_cr)
        con_list.append(my_con)

        # Layer 2: Exact (SOT + Blocked) vs Scaled Fallback (Total Shots * 0.62)
        if my_st["sot"] is not None and my_st["blocked"] is not None:
            exact_chaos_list.append(my_st["sot"] + my_st["blocked"])
            fallback_chaos_list.append(my_st["sot"] + my_st["blocked"])
        else:
            all_exact = False
            if my_st["shots"] is not None:
                fallback_chaos_list.append(my_st["shots"] * 0.62)
            elif my_st["sot"] is not None:
                fallback_chaos_list.append(my_st["sot"] * 1.75)
            else:
                fallback_chaos_list.append(0.0)

        audit.append({
            "date": g["kickoff_dt"].strftime("%d %b"),
            "comp": g["comp_code"],
            "ha": "H" if is_home else "A",
            "opp": opp_name,
            "cr": my_cr,
            "con": my_con,
        })

    if len(audit) < 2:
        return None

    n = len(audit)
    avg_cr = round(sum(cr_list) / n, 1)
    avg_con = round(sum(con_list) / n, 1)
    chaos_vals = exact_chaos_list if all_exact else fallback_chaos_list
    avg_chaos = round(sum(chaos_vals) / n, 1)

    return {
        "avg_cr": avg_cr,
        "avg_con": avg_con,
        "avg_chaos": avg_chaos,
        "exact": all_exact,
        "spike": spike_flag,
        "audit": audit,
    }


# ==============================================================================
# HYBRID HISTORY MANAGEMENT & ONE-TIME LEGACY MIGRATION
# ==============================================================================
def empty_archived():
    return {
        "total": 0,
        "wins": 0,
        "losses": 0,
        "by_tier": {
            "golden": {"w": 0, "l": 0},
            "value": {"w": 0, "l": 0},
            "normal": {"w": 0, "l": 0},
            "under": {"w": 0, "l": 0},
        },
        "by_comp": {
            "club": {"w": 0, "l": 0},
            "intl": {"w": 0, "l": 0},
        },
    }


def load_or_migrate_history():
    if os.path.exists(OUTPUT_HISTORY):
        try:
            with open(OUTPUT_HISTORY, "r", encoding="utf-8") as f:
                data = json.load(f)
            records = data.get("records", []) if isinstance(data, dict) else []
            archived = data.get("all_time_archived") or empty_archived()
            return records, archived
        except Exception:
            return [], empty_archived()

    # One-time read-only migration from v4.2 history.json (if present)
    migrated = []
    if os.path.exists(LEGACY_HISTORY):
        try:
            with open(LEGACY_HISTORY, "r", encoding="utf-8") as f:
                raw = json.load(f)
            items = raw if isinstance(raw, list) else (raw.get("records") or raw.get("matches") or [])
            for item in items:
                ev_id = str(item.get("id") or item.get("event_id") or "").strip()
                if not ev_id:
                    continue
                actual = parse_float(item.get("actual_corners"))
                raw_status = str(item.get("status") or "").upper()
                if raw_status == "VOID":
                    continue
                score = parse_float(item.get("score")) or 0.0
                if actual is not None:
                    actual_int = int(round(actual))
                    status = grade_match(actual_int, score)
                else:
                    actual_int = None
                    status = "WIN" if raw_status in ("HIT", "WIN") else ("LOSE" if raw_status in ("MISS", "LOSE") else "PENDING")

                migrated.append({
                    "id": ev_id,
                    "league": item.get("league") or "Club Competition",
                    "league_slug": item.get("league_slug") or item.get("slug") or "eng.1",
                    "comp_type": "club",
                    "kickoff_utc": item.get("kickoff_utc") or item.get("date") or iso_utc(utc_now()),
                    "home_team": item.get("home_team") or item.get("home") or "Home",
                    "away_team": item.get("away_team") or item.get("away") or "Away",
                    "home_id": str(item.get("home_id") or ""),
                    "away_id": str(item.get("away_id") or ""),
                    "score": round(score, 1),
                    "ref_exp": parse_float(item.get("ref_exp") or item.get("ref_total")),
                    "actual_home_corners": item.get("actual_home_corners"),
                    "actual_away_corners": item.get("actual_away_corners"),
                    "actual_corners": actual_int,
                    "status": status,
                    "extra_time": bool(item.get("extra_time", False)),
                    "snapshot": None,  # Pre-v5 record
                })
            print(f"[Migrate] Imported {len(migrated)} legacy records from {LEGACY_HISTORY}")
        except Exception as e:
            print(f"[Migrate] Skipped legacy import due to error: {e}")

    return migrated, empty_archived()


def prune_and_archive(records, archived):
    """Keep newest MAX_HISTORY_RECORDS; fold older graded records into all_time_archived."""
    if len(records) <= MAX_HISTORY_RECORDS:
        return records, archived

    # Sort oldest first to archive only graded items
    records.sort(key=lambda r: r.get("kickoff_utc") or "")
    kept = []
    excess = len(records) - MAX_HISTORY_RECORDS

    for rec in records:
        if excess > 0 and rec.get("status") in ("WIN", "LOSE"):
            is_win = (rec["status"] == "WIN")
            score = parse_float(rec.get("score")) or 0.0
            tier = classify_tier(score)
            ctype = "intl" if rec.get("comp_type") == "intl" else "club"

            archived["total"] += 1
            if is_win:
                archived["wins"] += 1
                archived["by_tier"][tier]["w"] += 1
                archived["by_comp"][ctype]["w"] += 1
            else:
                archived["losses"] += 1
                archived["by_tier"][tier]["l"] += 1
                archived["by_comp"][ctype]["l"] += 1
            excess -= 1
        else:
            kept.append(rec)

    kept.sort(key=lambda r: r.get("kickoff_utc") or "", reverse=True)
    return kept, archived


# ==============================================================================
# MAIN PIPELINE
# ==============================================================================
def main():
    now = utc_now()
    print(f"=== Javis v5.0 Engine Start ({iso_utc(now)}) ===")

    records, archived = load_or_migrate_history()
    records_by_id = {str(r["id"]): r for r in records}
    summary_cache = {}

    # ------------------------------------------------------------------
    # PHASE 1: Scan Upcoming Fixtures (Next 7 Days)
    # ------------------------------------------------------------------
    start_up = (now - timedelta(hours=3)).strftime("%Y%m%d")
    end_up = (now + timedelta(days=UPCOMING_DAYS)).strftime("%Y%m%d")

    all_league_specs = [
        (slug, name, code, "club") for slug, name, code in CLUB_LEAGUES
    ] + [
        (slug, name, code, "intl") for slug, name, code in INTL_LEAGUES
    ]

    upcoming_events = []
    seen_up_ids = set()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut_map = {
            ex.submit(fetch_scoreboard_events, slug, start_up, end_up): (slug, name, code, ctype)
            for slug, name, code, ctype in all_league_specs
        }
        for fut in as_completed(fut_map):
            slug, name, code, ctype = fut_map[fut]
            for ev in fut.result() or []:
                meta = parse_event_meta(ev, slug, name, code, ctype)
                if not meta or meta["id"] in seen_up_ids:
                    continue
                if meta["state"] in ("pre", "in"):
                    seen_up_ids.add(meta["id"])
                    upcoming_events.append(meta)

    club_teams_needed = set()
    intl_teams_needed = set()
    for m in upcoming_events:
        if m["comp_type"] == "club":
            club_teams_needed.add(m["home_id"])
            club_teams_needed.add(m["away_id"])
        else:
            intl_teams_needed.add(m["home_id"])
            intl_teams_needed.add(m["away_id"])

    print(
        f"[Phase 1] Upcoming: {len(upcoming_events)} matches "
        f"(Club teams: {len(club_teams_needed)}, Intl teams: {len(intl_teams_needed)})"
    )

    # ------------------------------------------------------------------
    # PHASE 2: Build Isolated Completed Match Pools (Club 45d | Intl 120d)
    # ------------------------------------------------------------------
    club_pool = {}  # team_id -> list of completed event metas
    intl_pool = {}  # team_id -> list of completed event metas

    scan_tasks = []
    if club_teams_needed:
        club_chunks = date_chunks(now - timedelta(days=CLUB_LOOKBACK_DAYS), now, 15)
        for slug, name, code in CLUB_LEAGUES:
            for c_start, c_end in club_chunks:
                scan_tasks.append((slug, name, code, "club", c_start, c_end))

    if intl_teams_needed:
        intl_chunks = date_chunks(now - timedelta(days=INTL_LOOKBACK_DAYS), now, 30)
        for slug, name, code in INTL_LEAGUES:
            for c_start, c_end in intl_chunks:
                scan_tasks.append((slug, name, code, "intl", c_start, c_end))

    seen_comp_ids = {"club": set(), "intl": set()}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut_map = {
            ex.submit(fetch_scoreboard_events, slug, cs, ce): (slug, name, code, ctype)
            for slug, name, code, ctype, cs, ce in scan_tasks
        }
        for fut in as_completed(fut_map):
            slug, name, code, ctype = fut_map[fut]
            needed = club_teams_needed if ctype == "club" else intl_teams_needed
            pool = club_pool if ctype == "club" else intl_pool
            for ev in fut.result() or []:
                meta = parse_event_meta(ev, slug, name, code, ctype)
                if not meta or meta["state"] != "post":
                    continue
                if meta["id"] in seen_comp_ids[ctype]:
                    continue
                seen_comp_ids[ctype].add(meta["id"])
                if meta["home_id"] in needed:
                    pool.setdefault(meta["home_id"], []).append(meta)
                if meta["away_id"] in needed:
                    pool.setdefault(meta["away_id"], []).append(meta)

    for pool in (club_pool, intl_pool):
        for tid in pool:
            pool[tid].sort(key=lambda x: x["kickoff_dt"], reverse=True)

    # ------------------------------------------------------------------
    # PHASE 3: Prefetch Candidate Boxscore Summaries Concurrently
    # ------------------------------------------------------------------
    candidate_summaries = {}
    for tid in club_teams_needed:
        for g in club_pool.get(tid, [])[:5]:
            candidate_summaries[g["id"]] = g
    for tid in intl_teams_needed:
        for g in intl_pool.get(tid, [])[:5]:
            candidate_summaries[g["id"]] = g

    print(f"[Phase 3] Fetching {len(candidate_summaries)} recent boxscores...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut_map = {
            ex.submit(fetch_boxscore_summary, g["slug"], g["id"], g["home_id"], g["away_id"]): ev_id
            for ev_id, g in candidate_summaries.items()
        }
        for fut in as_completed(fut_map):
            summary_cache[fut_map[fut]] = fut.result()

    # ------------------------------------------------------------------
    # PHASE 4: Compute v5 Signals & Pre-Match Lock into history_v5.json
    # ------------------------------------------------------------------
    matches_v5 = []
    for m in upcoming_events:
        pool = club_pool if m["comp_type"] == "club" else intl_pool
        h_l3 = build_team_l3(m["home_id"], pool.get(m["home_id"], []), summary_cache)
        a_l3 = build_team_l3(m["away_id"], pool.get(m["away_id"], []), summary_cache)
        if not h_l3 or not a_l3:
            continue

        snapshot = {
            "home_l3_corners": h_l3["avg_cr"],
            "away_l3_corners": a_l3["avg_cr"],
            "home_l3_chaos": h_l3["avg_chaos"],
            "away_l3_chaos": a_l3["avg_chaos"],
            "chaos_mode": "exact" if (h_l3["exact"] and a_l3["exact"]) else "fallback",
            "home_l3_conceded": h_l3["avg_con"],
            "away_l3_conceded": a_l3["avg_con"],
            "spike_flag": bool(h_l3["spike"] or a_l3["spike"]),
            "home_audit": h_l3["audit"],
            "away_audit": a_l3["audit"],
        }

        score, ref_exp = score_from_snapshot(snapshot)
        match_obj = {
            "id": m["id"],
            "league": m["league"],
            "league_slug": m["slug"],
            "comp_type": m["comp_type"],
            "kickoff_utc": m["kickoff_utc"],
            "home_team": m["home_team"],
            "away_team": m["away_team"],
            "snapshot": snapshot,
        }
        matches_v5.append(match_obj)

        # Pre-Match Lock: Insert once; never overwrite locked pre-match snapshot
        if m["id"] not in records_by_id:
            records_by_id[m["id"]] = {
                "id": m["id"],
                "league": m["league"],
                "league_slug": m["slug"],
                "comp_type": m["comp_type"],
                "kickoff_utc": m["kickoff_utc"],
                "home_team": m["home_team"],
                "away_team": m["away_team"],
                "home_id": m["home_id"],
                "away_id": m["away_id"],
                "score": score,
                "ref_exp": ref_exp,
                "actual_home_corners": None,
                "actual_away_corners": None,
                "actual_corners": None,
                "status": "PENDING",
                "extra_time": False,
                "snapshot": snapshot,
            }

    matches_v5.sort(key=lambda x: x["kickoff_utc"])

    # ------------------------------------------------------------------
    # PHASE 5: Auto-Grade Pending History Records (>= 2.2h post-kickoff)
    # ------------------------------------------------------------------
    to_grade = []
    void_ids = []
    for ev_id, rec in records_by_id.items():
        if rec.get("status") != "PENDING":
            continue
        kdt = parse_iso_utc(rec.get("kickoff_utc"))
        if not kdt:
            continue
        elapsed_h = (now - kdt).total_seconds() / 3600.0
        if elapsed_h >= GRADE_DELAY_HOURS:
            to_grade.append((ev_id, rec, elapsed_h))

    graded_count = 0
    if to_grade:
        print(f"[Phase 5] Checking {len(to_grade)} pending matches for grading...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            fut_map = {
                ex.submit(
                    fetch_boxscore_summary,
                    rec.get("league_slug") or "eng.1",
                    ev_id,
                    rec.get("home_id") or None,
                    rec.get("away_id") or None,
                ): (ev_id, rec, elapsed_h)
                for ev_id, rec, elapsed_h in to_grade
            }
            for fut in as_completed(fut_map):
                ev_id, rec, elapsed_h = fut_map[fut]
                box = fut.result()
                if box and box.get("valid") and box.get("state") == "post":
                    act_h = int(round(box["home"]["corners"]))
                    act_a = int(round(box["away"]["corners"]))
                    act_tot = act_h + act_a
                    score = parse_float(rec.get("score"))
                    if score is None and rec.get("snapshot"):
                        score, _ = score_from_snapshot(rec["snapshot"])
                    score = score or 0.0

                    rec["actual_home_corners"] = act_h
                    rec["actual_away_corners"] = act_a
                    rec["actual_corners"] = act_tot
                    rec["status"] = grade_match(act_tot, score, DEFAULT_TARGET_LINE)
                    rec["extra_time"] = bool(box.get("extra_time", False))
                    graded_count += 1
                elif elapsed_h >= VOID_EXPIRE_DAYS * 24:
                    void_ids.append(ev_id)

    for vid in void_ids:
        records_by_id.pop(vid, None)

    final_records = list(records_by_id.values())
    final_records.sort(key=lambda r: r.get("kickoff_utc") or "", reverse=True)
    final_records, archived = prune_and_archive(final_records, archived)

    # ------------------------------------------------------------------
    # PHASE 6: Write v5 Outputs (matches_v5.json & history_v5.json)
    # ------------------------------------------------------------------
    generated_at = iso_utc(utc_now())

    with open(OUTPUT_MATCHES, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": generated_at,
                "engine_version": "5.0",
                "matches": matches_v5,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open(OUTPUT_HISTORY, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": generated_at,
                "engine_version": "5.0",
                "max_records": MAX_HISTORY_RECORDS,
                "all_time_archived": archived,
                "records": final_records,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"=== Done! Signals: {len(matches_v5)} | History: {len(final_records)} "
        f"| Graded: {graded_count} | Pruned Void: {len(void_ids)} ==="
    )


if __name__ == "__main__":
    main()
