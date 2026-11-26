#!/usr/bin/env python3
"""
Javis v5.0 — Automated Corner Analytics & Hybrid Backtesting Engine
- 100% Exact Parity with v4.2 CN Ultra 3-Layer Scoring, Rounding & Alerts
- Isolated v5 outputs: matches_v5.json & history_v5.json (never modifies v4.2 files)
- 28 Club Competitions + 11 Official Senior Men's International Competitions (120d lookback)
- Enhanced Multi-Competition Schedule Reliability (Retries + Domestic League Auto-Link + Euro-Only Guard)
"""

import json
import os
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    requests = None

# ==============================================================================
# 1. CONFIGURATION & COMPETITIONS
# ==============================================================================
OUTPUT_MATCHES = "matches_v5.json"
OUTPUT_HISTORY = "history_v5.json"
LEGACY_HISTORY = "history.json"
SHARED_CACHE_PATH = "data/event_cache.json"
V5_CACHE_PATH = "data/event_cache_v5.json"

ENGINE_VERSION = "5.0-v42sync"
FORMULA_VERSION = "v4.2"
CACHE_SCHEMA_VERSION = "4.1"
STANDARD_LINE = 9.5
UPCOMING_DAYS = int(os.getenv("UPCOMING_DAYS", "7"))
MIN_SAMPLES_REQUIRED = 2
L3_WINDOW = 3
BOXSCORE_SCAN_BUFFER = 5
MAX_HISTORY_RECORDS = 3000
GRADE_DELAY_HOURS = 2.2
VOID_EXPIRE_DAYS = 5
INTL_LOOKBACK_DAYS = 120

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

if requests is not None:
    SESSION = requests.Session()
    SESSION.headers.update(BROWSER_HEADERS)
else:
    SESSION = None

# Exact 28 Club Leagues & Cups from v4.2
CLUB_LEAGUES = [
    {"slug": "uefa.champions", "code": "UCL", "name": "Champions League", "lookback": 100},
    {"slug": "uefa.europa", "code": "UEL", "name": "Europa League", "lookback": 100},
    {"slug": "uefa.europa.conf", "code": "UECL", "name": "Conference League", "lookback": 100},
    {"slug": "eng.fa", "code": "FAC", "name": "FA Cup", "lookback": 90},
    {"slug": "eng.league_cup", "code": "EFL", "name": "Carabao Cup", "lookback": 90},
    {"slug": "eng.1", "code": "EPL", "name": "Premier League", "lookback": 70},
    {"slug": "esp.1", "code": "LAL", "name": "La Liga", "lookback": 70},
    {"slug": "ita.1", "code": "SER", "name": "Serie A", "lookback": 70},
    {"slug": "ger.1", "code": "BUN", "name": "Bundesliga", "lookback": 70},
    {"slug": "fra.1", "code": "LG1", "name": "Ligue 1", "lookback": 70},
    {"slug": "usa.1", "code": "MLS", "name": "USA MLS", "lookback": 70},
    {"slug": "eng.2", "code": "CHP", "name": "Championship", "lookback": 70},
    {"slug": "aus.1", "code": "ALE", "name": "A-League", "lookback": 70},
    {"slug": "bra.2", "code": "BRB", "name": "Brazil Serie B", "lookback": 70},
    {"slug": "ned.1", "code": "ERE", "name": "Eredivisie", "lookback": 70},
    {"slug": "eng.3", "code": "EFL1", "name": "England League One", "lookback": 70},
    {"slug": "por.1", "code": "POR", "name": "Primeira Liga", "lookback": 70},
    {"slug": "bel.1", "code": "BEL", "name": "Belgian Pro League", "lookback": 70},
    {"slug": "tur.1", "code": "TUR", "name": "Turkish Super Lig", "lookback": 70},
    {"slug": "sco.1", "code": "SCO", "name": "Scottish Premiership", "lookback": 70},
    {"slug": "bra.1", "code": "BRA", "name": "Brazil Serie A", "lookback": 70},
    {"slug": "arg.1", "code": "ARG", "name": "Argentina Liga", "lookback": 70},
    {"slug": "mex.1", "code": "LMX", "name": "Liga MX", "lookback": 70},
    {"slug": "ger.2", "code": "BL2", "name": "2. Bundesliga", "lookback": 70},
    {"slug": "esp.2", "code": "LL2", "name": "La Liga 2", "lookback": 70},
    {"slug": "ita.2", "code": "SRB", "name": "Serie B", "lookback": 70},
    {"slug": "aut.1", "code": "AUT", "name": "Austrian Bundesliga", "lookback": 70},
    {"slug": "den.1", "code": "DEN", "name": "Danish Superliga", "lookback": 70},
]

# 11 Official Senior Men's International Competitions (120-day lookback — NO friendlies/youth/women)
INTL_LEAGUES = [
    {"slug": "uefa.nations", "code": "UNL", "name": "UEFA Nations League", "lookback": INTL_LOOKBACK_DAYS},
    {"slug": "fifa.worldq.uefa", "code": "WCQ", "name": "World Cup Qualifiers (UEFA)", "lookback": INTL_LOOKBACK_DAYS},
    {"slug": "fifa.worldq.conmebol", "code": "WCQ", "name": "World Cup Qualifiers (CONMEBOL)", "lookback": INTL_LOOKBACK_DAYS},
    {"slug": "fifa.worldq.afc", "code": "WCQ", "name": "World Cup Qualifiers (AFC)", "lookback": INTL_LOOKBACK_DAYS},
    {"slug": "fifa.worldq.concacaf", "code": "WCQ", "name": "World Cup Qualifiers (CONCACAF)", "lookback": INTL_LOOKBACK_DAYS},
    {"slug": "fifa.worldq.caf", "code": "WCQ", "name": "World Cup Qualifiers (CAF)", "lookback": INTL_LOOKBACK_DAYS},
    {"slug": "fifa.world", "code": "WC", "name": "FIFA World Cup", "lookback": INTL_LOOKBACK_DAYS},
    {"slug": "uefa.euro", "code": "EURO", "name": "UEFA Euro", "lookback": INTL_LOOKBACK_DAYS},
    {"slug": "conmebol.america", "code": "COPA", "name": "Copa América", "lookback": INTL_LOOKBACK_DAYS},
    {"slug": "afc.asian.cup", "code": "AFC", "name": "AFC Asian Cup", "lookback": INTL_LOOKBACK_DAYS},
    {"slug": "caf.nations", "code": "AFCON", "name": "AFCON", "lookback": INTL_LOOKBACK_DAYS},
]

EURO_CUP_SLUGS = {"uefa.champions", "uefa.europa", "uefa.europa.conf"}
INTL_SLUGS = {lg["slug"] for lg in INTL_LEAGUES}
SLUG_TO_CODE = {lg["slug"]: lg["code"] for lg in CLUB_LEAGUES + INTL_LEAGUES}
SLUG_TO_CODE.update({
    "esp.copa_del_rey": "CDR",
    "ita.coppa_italia": "CIT",
    "ger.dfb_pokal": "DFB",
    "fra.coupe_de_france": "CDF",
})

MMT = timezone(timedelta(hours=6, minutes=30))


# ==============================================================================
# 2. HTTP & PARSING HELPERS
# ==============================================================================
def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(iso_str):
    if not iso_str:
        return None
    s = str(iso_str).strip().replace("Z", "+00:00")
    if len(s) == 22 and s[16] in "+-":
        s = s[:16] + ":00" + s[16:]
    try:
        dt = datetime.fromisoformat(s)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def safe_float(val):
    try:
        if val is None or val == "" or val == "--":
            return None
        return float(str(val).replace("%", "").strip())
    except ValueError:
        return None


def pick_stat(stats_map, *keys):
    for k in keys:
        if stats_map.get(k) is not None:
            return stats_map[k]
    return None


def fetch_json(url, timeout=15, retries=4):
    for attempt in range(retries):
        try:
            if SESSION is not None:
                r = SESSION.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(0.6 * (attempt + 1))
                    continue
                return None
            else:
                req = urllib.request.Request(url, headers=BROWSER_HEADERS)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            time.sleep(0.5 * (attempt + 1))
    return None


def load_json_safe(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


# ==============================================================================
# 3. ESPN SCOREBOARD, SCHEDULE & BOXSCORE EXTRACTION
# ==============================================================================
def fetch_league_boards(lg, comp_type, now_utc):
    slug = lg["slug"]
    base = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
    up_range = f"{now_utc.strftime('%Y%m%d')}-{(now_utc + timedelta(days=UPCOMING_DAYS)).strftime('%Y%m%d')}"
    past_start = (now_utc - timedelta(days=lg.get("lookback", 70))).strftime("%Y%m%d")
    past_end = now_utc.strftime("%Y%m%d")

    default_board = fetch_json(base, retries=3)
    up_board = fetch_json(f"{base}?dates={up_range}", retries=3)
    past_board = fetch_json(f"{base}?dates={past_start}-{past_end}", retries=3)
    return lg, comp_type, default_board, up_board, past_board


def _extract_schedule_events(data, fallback_slug, comp_type, now_utc, intl_cutoff):
    items = {}
    if not data:
        return items
    default_slug = (data.get("league") or {}).get("slug", "")
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        st_type = comp.get("status", {}).get("type", {})
        if not st_type.get("completed") and st_type.get("state") != "post":
            continue
        eid = str(ev.get("id", ""))
        edate = comp.get("date") or ev.get("date") or ""
        dt = parse_utc(edate)
        if not eid or not dt or dt >= now_utc:
            continue

        ev_slug = (ev.get("league") or {}).get("slug") or default_slug or fallback_slug or "all"
        if comp_type == "intl":
            ev_low = ev_slug.lower()
            if dt < intl_cutoff or ev_slug not in INTL_SLUGS:
                continue
            if "friendly" in ev_low or "women" in ev_low or "u21" in ev_low or "u23" in ev_low:
                continue

        items[eid] = (dt.timestamp(), edate, eid, ev_slug)
    return items


def _has_non_euro_recent(events_map, window=3):
    """Return True if at least one of the team's top `window` most recent games is non-European (domestic)."""
    if not events_map:
        return False
    recent = sorted(events_map.values(), key=lambda x: x[0], reverse=True)[:window]
    return any(ev_slug not in EURO_CUP_SLUGS for _, _, _, ev_slug in recent)


def fetch_team_default_league_slug(tid):
    """Query ESPN universal team profile to discover a club's home domestic league slug (e.g. ger.1)."""
    data = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{tid}", retries=3)
    if not isinstance(data, dict):
        return None
    team_obj = data.get("team") or {}
    default_lg = team_obj.get("defaultLeague") or {}
    slug = default_lg.get("slug")
    if slug and slug not in EURO_CUP_SLUGS and slug not in INTL_SLUGS:
        return slug
    return None


def fetch_team_completed_events(tid, candidate_slugs, comp_type, now_utc):
    """
    Fetch completed matches for a team:
    - 'club': fetches all competitions (domestic league + domestic cups + European cups) with 4 retries.
      Prioritizes domestic league backup slugs and verifies against ESPN team defaultLeague if only
      European cup matches were returned in the top 3.
    - 'intl': strictly official senior men's INTL_SLUGS within 120 days (no friendlies/youth/women).
    """
    found = {}
    intl_cutoff = now_utc - timedelta(days=INTL_LOOKBACK_DAYS)

    # Order candidate slugs so domestic leagues are checked before European cups
    unique_slugs = list(dict.fromkeys(s for s in candidate_slugs if s))
    ordered_slugs = (
        [s for s in unique_slugs if s not in EURO_CUP_SLUGS]
        + [s for s in unique_slugs if s in EURO_CUP_SLUGS]
    )

    urls = []
    if comp_type == "club":
        urls.append(("all", f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{tid}/schedule"))
    for slug in ordered_slugs:
        urls.append((slug, f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{tid}/schedule"))

    queried_slugs = set()
    for src_slug, url in urls:
        queried_slugs.add(src_slug)
        data = fetch_json(url, retries=4)
        fallback_slug = ordered_slugs[0] if src_slug == "all" and ordered_slugs else src_slug
        found.update(_extract_schedule_events(data, fallback_slug, comp_type, now_utc, intl_cutoff))

        # Only stop early after soccer/all if we have >= 8 events AND domestic games are present
        if comp_type == "club" and src_slug == "all" and len(found) >= 8 and _has_non_euro_recent(found, L3_WINDOW):
            break

    # Euro-Only Guard: If a club team's top 3 recent games are ALL European cups (UCL/UEL/UECL),
    # explicitly discover and query its home domestic league so league games are never missed.
    if comp_type == "club" and not _has_non_euro_recent(found, L3_WINDOW):
        dom_slug = fetch_team_default_league_slug(tid)
        if dom_slug and dom_slug not in queried_slugs:
            dom_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{dom_slug}/teams/{tid}/schedule"
            dom_data = fetch_json(dom_url, retries=4)
            found.update(_extract_schedule_events(dom_data, dom_slug, comp_type, now_utc, intl_cutoff))

    return list(found.values())


def extract_boxscore_stats(slug, event_id):
    urls = [f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event={event_id}"]
    if slug and slug != "all":
        urls.append(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}")

    data = None
    for u in urls:
        cand = fetch_json(u, retries=3)
        if cand and cand.get("boxscore", {}).get("teams"):
            data = cand
            break
    if not data:
        return None

    header = data.get("header", {})
    header_comp = (header.get("competitions") or [{}])[0]
    status_obj = header_comp.get("status", {})
    status_type = status_obj.get("type", {})
    state = status_type.get("state", "")
    if state and state != "post":
        return None

    status_detail = (status_type.get("shortDetail") or status_type.get("detail") or "").upper()
    period = status_obj.get("period", 2) or 2
    is_extra_time = (
        period > 2
        or "AET" in status_detail
        or "ET" in status_detail
        or "PEN" in status_detail
        or "EXTRA" in status_detail
    )

    ev_date_iso = header_comp.get("date") or ""
    dt_utc = parse_utc(ev_date_iso)
    date_short = dt_utc.astimezone(MMT).strftime("%d %b") if dt_utc else "--"

    league_obj = header.get("league") or {}
    ev_slug = league_obj.get("slug") or slug or ""
    league_code = (
        SLUG_TO_CODE.get(ev_slug)
        or (league_obj.get("abbreviation") or "").upper()
        or "CMP"
    )

    comp_meta = {}
    for c in header_comp.get("competitors", []):
        ctid = str(c.get("team", {}).get("id", ""))
        if ctid:
            comp_meta[ctid] = {
                "name": c.get("team", {}).get("shortDisplayName") or c.get("team", {}).get("displayName") or "Team",
                "venue": "H" if c.get("homeAway") == "home" else "A",
            }

    teams_box = data.get("boxscore", {}).get("teams", [])
    if len(teams_box) != 2:
        return None

    parsed = {}
    for entry in teams_box:
        t_obj = entry.get("team", {})
        tid = str(t_obj.get("id", ""))
        if not tid:
            continue
        stats_map = {}
        for st in entry.get("statistics", []):
            name = (st.get("name") or "").lower().strip()
            label = (st.get("label") or "").lower().strip()
            val = safe_float(st.get("displayValue"))
            if name:
                stats_map[name] = val
            if label:
                stats_map[label] = val

        corners = pick_stat(stats_map, "woncorners", "cornerkicks", "corners", "corner kicks")
        if corners is None:
            return None

        meta = comp_meta.get(tid, {})
        parsed[tid] = {
            "name": meta.get("name") or t_obj.get("shortDisplayName") or t_obj.get("displayName") or "Team",
            "venue": meta.get("venue") or "-",
            "corners": corners,
            "shots_on_target": pick_stat(stats_map, "shotsontarget", "shots on target", "shotsongoal") or 0.0,
            "total_shots": pick_stat(stats_map, "totalshots", "total shots", "shots") or 0.0,
            "blocked_shots": pick_stat(stats_map, "blockedshots", "blocked shots"),
        }

    tids = [k for k in parsed.keys() if not k.startswith("_")]
    if len(tids) != 2:
        return None

    t0, t1 = tids[0], tids[1]
    parsed[t0]["corners_conceded"] = parsed[t1]["corners"]
    parsed[t0]["opponent"] = parsed[t1]["name"]
    parsed[t1]["corners_conceded"] = parsed[t0]["corners"]
    parsed[t1]["opponent"] = parsed[t0]["name"]

    parsed["_meta"] = {
        "v": CACHE_SCHEMA_VERSION,
        "date": date_short,
        "dateISO": ev_date_iso,
        "leagueCode": league_code,
        "totalCorners": parsed[t0]["corners"] + parsed[t1]["corners"],
        "extraTime": is_extra_time,
    }
    return parsed


def detect_spike(seq):
    """Exact v4.2 spike rule."""
    if len(seq) < 2:
        return False
    spread = max(seq) - min(seq)
    if spread >= 7:
        return True
    if len(seq) >= 3:
        s = sorted(seq)
        if s[-1] >= 11 and (s[-1] - s[-2]) >= 5:
            return True
    return False


# ==============================================================================
# 4. SNAPSHOT BUILDER & EXACT v4.2 CN ULTRA 3-LAYER SCORING
# ==============================================================================
def build_team_l3(tid, ev_refs, cache):
    """
    Strictly sorts completed matches by kickoff timestamp descending (most recent first).
    - Full-data teams: takes exact Last 3 matches across all competitions.
    - Partial-data teams: skips matches without valid corner boxscores and takes the 3 most recent matches with data.
    """
    sorted_refs = sorted(ev_refs, key=lambda x: x[0], reverse=True)
    rows = []
    audit = []
    seen_eids = set()

    for _, edate, eid, _ in sorted_refs:
        if eid in seen_eids:
            continue
        seen_eids.add(eid)
        entry = cache.get(eid)
        if isinstance(entry, dict) and tid in entry and isinstance(entry.get("_meta"), dict):
            t_row = entry[tid]
            meta = entry["_meta"]
            rows.append(t_row)

            dt_fb = parse_utc(edate)
            d_str = meta.get("date") if meta.get("date") and meta.get("date") != "--" else (
                dt_fb.astimezone(MMT).strftime("%d %b") if dt_fb else "--"
            )
            audit.append({
                "date": d_str,
                "comp": meta.get("leagueCode", "CMP"),
                "ha": t_row.get("venue", "-"),
                "opp": t_row.get("opponent", "Opponent"),
                "cr": int(round(t_row["corners"])),
                "con": int(round(t_row.get("corners_conceded", 0))),
            })
        if len(rows) >= L3_WINDOW:
            break

    if len(rows) < MIN_SAMPLES_REQUIRED:
        return None

    def avg_required(k):
        vals = [float(r[k]) for r in rows if r.get(k) is not None]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    def avg_optional(k):
        vals = [float(r[k]) for r in rows if r.get(k) is not None]
        if len(vals) == len(rows):
            return round(sum(vals) / len(vals), 2)
        return None

    corners_seq = [int(round(r["corners"])) for r in rows]

    return {
        "sample_size": len(rows),
        "l3_corners": avg_required("corners"),
        "l3_conceded": avg_required("corners_conceded"),
        "l3_sot": avg_required("shots_on_target"),
        "l3_total_shots": avg_required("total_shots"),
        "l3_blocked": avg_optional("blocked_shots"),
        "spike": detect_spike(corners_seq),
        "audit": audit,
    }


def make_match_snapshot(h_l3, a_l3):
    """Build match-level snapshot using exact v4.2 mode detection & 2-decimal precision."""
    has_exact = (h_l3["l3_blocked"] is not None and a_l3["l3_blocked"] is not None)
    if has_exact:
        chaos_mode = "exact"
        h_ch = round(float(h_l3["l3_sot"]) + float(h_l3["l3_blocked"]), 2)
        a_ch = round(float(a_l3["l3_sot"]) + float(a_l3["l3_blocked"]), 2)
    else:
        chaos_mode = "fallback"
        h_ch = round(float(h_l3["l3_total_shots"]), 2)
        a_ch = round(float(a_l3["l3_total_shots"]), 2)

    return {
        "home_samples": h_l3["sample_size"],
        "away_samples": a_l3["sample_size"],
        "home_l3_corners": h_l3["l3_corners"],
        "away_l3_corners": a_l3["l3_corners"],
        "home_l3_chaos": h_ch,
        "away_l3_chaos": a_ch,
        "chaos_mode": chaos_mode,
        "home_l3_conceded": h_l3["l3_conceded"],
        "away_l3_conceded": a_l3["l3_conceded"],
        "home_spike": bool(h_l3["spike"]),
        "away_spike": bool(a_l3["spike"]),
        "spike_flag": bool(h_l3["spike"] or a_l3["spike"]),
        "home_audit": h_l3["audit"],
        "away_audit": a_l3["audit"],
    }


def score_from_snapshot(snap):
    """Exact v4.2 CN Ultra 3-Layer Scoring Formula."""
    h_cr = float(snap["home_l3_corners"])
    a_cr = float(snap["away_l3_corners"])
    total_cr = round(h_cr + a_cr, 2)
    if total_cr > 12.0:
        l1 = 3.0
    elif total_cr >= 10.0:
        l1 = 2.0
    elif total_cr >= 8.0:
        l1 = 1.0
    else:
        l1 = 0.0

    h_ch = float(snap["home_l3_chaos"])
    a_ch = float(snap["away_l3_chaos"])
    total_ch = round(h_ch + a_ch, 2)
    if snap.get("chaos_mode", "exact") == "exact":
        if total_ch > 15.0:
            l2 = 2.0
        elif total_ch >= 10.0:
            l2 = 1.0
        else:
            l2 = 0.0
    else:
        if total_ch > 26.0:
            l2 = 2.0
        elif total_ch >= 19.0:
            l2 = 1.0
        else:
            l2 = 0.0

    def conceded_pts(val):
        if val > 5.0:
            return 1.0
        if val >= 4.0:
            return 0.5
        return -0.5

    h_con = float(snap["home_l3_conceded"])
    a_con = float(snap["away_l3_conceded"])
    l3 = round(conceded_pts(h_con) + conceded_pts(a_con), 1)

    total_score = round(l1 + l2 + l3, 1)
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


def grade_match(actual_corners, score, line=STANDARD_LINE):
    tier = classify_tier(score)
    if tier == "under":
        return "WIN" if actual_corners < line else "LOSE"
    return "WIN" if actual_corners > line else "LOSE"


# ==============================================================================
# 5. HYBRID HISTORY & LEGACY MIGRATION
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
    existing_records = []
    archived = empty_archived()
    if os.path.exists(OUTPUT_HISTORY):
        data = load_json_safe(OUTPUT_HISTORY, {})
        if isinstance(data, dict):
            existing_records = data.get("records", [])
            archived = data.get("all_time_archived") or empty_archived()

    if existing_records:
        return existing_records, archived

    migrated = []
    if os.path.exists(LEGACY_HISTORY):
        raw = load_json_safe(LEGACY_HISTORY, {"records": []})
        items = raw if isinstance(raw, list) else (raw.get("records") or [])
        for item in items:
            ev_id = str(item.get("id") or "").strip()
            if not ev_id:
                continue
            raw_status = str(item.get("status") or "").upper()
            if raw_status == "VOID":
                continue

            score = safe_float(item.get("score")) or 0.0
            actual = safe_float(item.get("actualTotal") if item.get("actualTotal") is not None else item.get("actual_corners"))
            raw_grade = str(item.get("grade") or "").upper()

            if actual is not None:
                actual_int = int(round(actual))
                status = grade_match(actual_int, score)
            elif raw_status in ("GRADED", "WIN", "LOSE", "HIT", "MISS"):
                actual_int = None
                status = "WIN" if raw_grade in ("HIT", "WIN") or raw_status in ("HIT", "WIN") else "LOSE"
            else:
                actual_int = None
                status = "PENDING"

            migrated.append({
                "id": ev_id,
                "formula_ver": FORMULA_VERSION,
                "league": item.get("leagueName") or item.get("league") or "Club Competition",
                "league_slug": item.get("leagueSlug") or item.get("league_slug") or "eng.1",
                "comp_type": "intl" if (item.get("leagueSlug") in INTL_SLUGS) else "club",
                "kickoff_utc": item.get("kickoffUTC") or item.get("kickoff_utc") or iso_utc(utc_now()),
                "home_team": item.get("home") or item.get("home_team") or "Home",
                "away_team": item.get("away") or item.get("away_team") or "Away",
                "home_id": str(item.get("homeId") or item.get("home_id") or ""),
                "away_id": str(item.get("awayId") or item.get("away_id") or ""),
                "score": round(score, 1),
                "ref_exp": safe_float(item.get("refTotal") or item.get("ref_exp")),
                "actual_home_corners": item.get("actualHomeCorners"),
                "actual_away_corners": item.get("actualAwayCorners"),
                "actual_corners": actual_int,
                "status": status,
                "extra_time": bool(item.get("isExtraTime") or item.get("extra_time", False)),
                "snapshot": item.get("snapshot"),
            })
        print(f"[Migrate] Imported {len(migrated)} legacy records from {LEGACY_HISTORY}")

    return migrated, archived


def prune_and_archive(records, archived):
    if len(records) <= MAX_HISTORY_RECORDS:
        return records, archived

    records.sort(key=lambda r: r.get("kickoff_utc") or "")
    kept = []
    excess = len(records) - MAX_HISTORY_RECORDS

    for rec in records:
        if excess > 0 and rec.get("status") in ("WIN", "LOSE"):
            is_win = rec["status"] == "WIN"
            score = safe_float(rec.get("score")) or 0.0
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
# 6. MAIN PIPELINE
# ==============================================================================
def main():
    os.makedirs("data", exist_ok=True)
    now_utc = utc_now()
    print(f"=== Javis {ENGINE_VERSION} Engine Start ({iso_utc(now_utc)}) ===")

    cache = {}
    for p in (SHARED_CACHE_PATH, V5_CACHE_PATH):
        raw_c = load_json_safe(p, {})
        if isinstance(raw_c, dict):
            for k, v in raw_c.items():
                if isinstance(v, dict) and v.get("_meta", {}).get("v") == CACHE_SCHEMA_VERSION:
                    cache[k] = v

    records, archived = load_or_migrate_history()
    records_by_id = {str(r["id"]): r for r in records}

    # Step 1: Fetch scoreboards for 28 Club + 11 Official International competitions
    league_jobs = [(lg, "club") for lg in CLUB_LEAGUES] + [(lg, "intl") for lg in INTL_LEAGUES]
    upcoming_items = []
    seen_upcoming_ids = set()

    active_club_ids = set()
    active_intl_ids = set()
    team_slugs = {"club": {}, "intl": {}}
    team_history_events = {"club": {}, "intl": {}}

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_league_boards, lg, ctype, now_utc) for lg, ctype in league_jobs]
        for fut in as_completed(futs):
            lg, ctype, default_board, up_board, past_board = fut.result()
            slug = lg["slug"]

            for board in (default_board, up_board):
                if not board:
                    continue
                for ev in board.get("events", []):
                    ev_id = str(ev.get("id", ""))
                    if not ev_id or ev_id in seen_upcoming_ids:
                        continue
                    comp = (ev.get("competitions") or [{}])[0]
                    state = comp.get("status", {}).get("type", {}).get("state", "")
                    if state != "pre":
                        continue
                    competitors = comp.get("competitors", [])
                    home_c = next((c for c in competitors if c.get("homeAway") == "home"), None)
                    away_c = next((c for c in competitors if c.get("homeAway") == "away"), None)
                    if not home_c or not away_c:
                        continue
                    hid = str(home_c["team"]["id"])
                    aid = str(away_c["team"]["id"])
                    seen_upcoming_ids.add(ev_id)

                    if ctype == "club":
                        active_club_ids.update([hid, aid])
                    else:
                        active_intl_ids.update([hid, aid])

                    team_slugs[ctype].setdefault(hid, []).append(slug)
                    team_slugs[ctype].setdefault(aid, []).append(slug)
                    upcoming_items.append((lg, ctype, ev, home_c, away_c, hid, aid))

            for board in (default_board, past_board):
                if not board:
                    continue
                for ev in board.get("events", []):
                    comp = (ev.get("competitions") or [{}])[0]
                    st_type = comp.get("status", {}).get("type", {})
                    if not st_type.get("completed") and st_type.get("state") != "post":
                        continue
                    ev_id = str(ev.get("id", ""))
                    ev_date = comp.get("date") or ev.get("date") or ""
                    dt = parse_utc(ev_date)
                    if not ev_id or not dt or dt >= now_utc:
                        continue
                    for c in comp.get("competitors", []):
                        tid = str(c.get("team", {}).get("id", ""))
                        if tid:
                            team_history_events[ctype].setdefault(tid, []).append((dt.timestamp(), ev_date, ev_id, slug))
                            # Auto-link team's domestic/league slug from completed boards too
                            team_slugs[ctype].setdefault(tid, []).append(slug)

    # Step 2: Fetch multi-competition schedules for active teams
    schedule_tasks = []
    for tid in active_club_ids:
        schedule_tasks.append((tid, list(dict.fromkeys(team_slugs["club"].get(tid, []))), "club"))
    for tid in active_intl_ids:
        schedule_tasks.append((tid, list(dict.fromkeys(team_slugs["intl"].get(tid, []))), "intl"))

    if schedule_tasks:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {
                ex.submit(fetch_team_completed_events, tid, slugs, ctype, now_utc): (tid, ctype)
                for tid, slugs, ctype in schedule_tasks
            }
            for fut in as_completed(futs):
                tid, ctype = futs[fut]
                for item in fut.result():
                    team_history_events[ctype].setdefault(tid, []).append(item)

    # Step 3: Fetch missing boxscores for true Last 3 completed matches (with buffer for partial-data teams)
    needed_boxscores = {}
    for ctype, team_set in (("club", active_club_ids), ("intl", active_intl_ids)):
        for tid in team_set:
            ev_refs = sorted(team_history_events[ctype].get(tid, []), key=lambda x: x[0], reverse=True)
            picked = 0
            valid_cached = 0
            seen_eids = set()
            for _, _, eid, slug in ev_refs:
                if eid in seen_eids:
                    continue
                seen_eids.add(eid)
                entry = cache.get(eid)
                if isinstance(entry, dict) and tid in entry and isinstance(entry.get("_meta"), dict):
                    valid_cached += 1
                    if valid_cached >= L3_WINDOW and picked < L3_WINDOW:
                        break
                elif eid not in cache:
                    needed_boxscores[eid] = slug
                picked += 1
                if picked >= L3_WINDOW + BOXSCORE_SCAN_BUFFER:
                    break

    if needed_boxscores:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {
                ex.submit(extract_boxscore_stats, slug, eid): eid
                for eid, slug in needed_boxscores.items()
            }
            for fut in as_completed(futs):
                eid = futs[fut]
                res = fut.result()
                if isinstance(res, dict):
                    cache[eid] = res

    # Step 4: Build Snapshots & Pre-Match Lock into history_v5.json
    matches_v5 = []
    for lg, ctype, ev, home_c, away_c, hid, aid in upcoming_items:
        ev_id = str(ev["id"])
        dt_utc = parse_utc(ev.get("date", ""))
        if not dt_utc:
            continue
        hours_to_ko = (dt_utc - now_utc).total_seconds() / 3600.0
        if hours_to_ko < -0.1:
            continue

        h_l3 = build_team_l3(hid, team_history_events[ctype].get(hid, []), cache)
        a_l3 = build_team_l3(aid, team_history_events[ctype].get(aid, []), cache)
        if not h_l3 or not a_l3:
            continue

        home_name = home_c["team"]["displayName"]
        away_name = away_c["team"]["displayName"]

        snapshot = make_match_snapshot(h_l3, a_l3)
        score, ref_exp = score_from_snapshot(snapshot)
        ko_iso = iso_utc(dt_utc)

        matches_v5.append({
            "id": ev_id,
            "league": lg["name"],
            "league_slug": lg["slug"],
            "comp_type": ctype,
            "kickoff_utc": ko_iso,
            "home_team": home_name,
            "away_team": away_name,
            "snapshot": snapshot,
        })

        # Pre-Match Lock: Insert once; refresh PENDING records if created under old formula
        if ev_id not in records_by_id:
            records_by_id[ev_id] = {
                "id": ev_id,
                "formula_ver": FORMULA_VERSION,
                "league": lg["name"],
                "league_slug": lg["slug"],
                "comp_type": ctype,
                "kickoff_utc": ko_iso,
                "home_team": home_name,
                "away_team": away_name,
                "home_id": hid,
                "away_id": aid,
                "score": score,
                "ref_exp": ref_exp,
                "actual_home_corners": None,
                "actual_away_corners": None,
                "actual_corners": None,
                "status": "PENDING",
                "extra_time": False,
                "snapshot": snapshot,
            }
        elif (
            records_by_id[ev_id].get("status") == "PENDING"
            and (
                records_by_id[ev_id].get("snapshot") is None
                or records_by_id[ev_id].get("formula_ver") != FORMULA_VERSION
            )
            and hours_to_ko > 0
        ):
            records_by_id[ev_id]["formula_ver"] = FORMULA_VERSION
            records_by_id[ev_id]["snapshot"] = snapshot
            records_by_id[ev_id]["score"] = score
            records_by_id[ev_id]["ref_exp"] = ref_exp

    matches_v5.sort(key=lambda x: x["kickoff_utc"])

    # Step 5: Auto-Grade Pending History Records (>= 2.2h post-kickoff)
    to_grade = []
    for ev_id, rec in records_by_id.items():
        if rec.get("status") != "PENDING":
            continue
        kdt = parse_utc(rec.get("kickoff_utc"))
        if kdt and (now_utc - kdt).total_seconds() >= GRADE_DELAY_HOURS * 3600:
            to_grade.append(rec)

    if to_grade:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {}
            for rec in to_grade[:45]:
                eid = str(rec["id"])
                if eid in cache:
                    continue
                futs[ex.submit(extract_boxscore_stats, rec.get("league_slug", ""), eid)] = eid
            for fut in as_completed(futs):
                eid = futs[fut]
                res = fut.result()
                if isinstance(res, dict):
                    cache[eid] = res

    graded_count = 0
    void_ids = []
    for rec in to_grade:
        eid = str(rec["id"])
        box = cache.get(eid)
        if not isinstance(box, dict):
            kdt = parse_utc(rec.get("kickoff_utc"))
            if kdt and (now_utc - kdt).days >= VOID_EXPIRE_DAYS:
                void_ids.append(eid)
            continue

        hid = str(rec.get("home_id") or "")
        aid = str(rec.get("away_id") or "")
        tids = [k for k in box.keys() if not k.startswith("_")]

        if hid in box and aid in box:
            h_box, a_box = box[hid], box[aid]
        elif len(tids) == 2:
            h_box = next((box[t] for t in tids if box[t].get("venue") == "H"), box[tids[0]])
            a_box = next((box[t] for t in tids if box[t].get("venue") == "A"), box[tids[1]])
        else:
            continue

        act_h = int(round(h_box["corners"]))
        act_a = int(round(a_box["corners"]))
        act_tot = act_h + act_a
        score = safe_float(rec.get("score"))
        if score is None and rec.get("snapshot"):
            score, _ = score_from_snapshot(rec["snapshot"])
        score = score or 0.0

        rec["actual_home_corners"] = act_h
        rec["actual_away_corners"] = act_a
        rec["actual_corners"] = act_tot
        rec["status"] = grade_match(act_tot, score, STANDARD_LINE)
        rec["extra_time"] = bool(box.get("_meta", {}).get("extraTime", False))
        graded_count += 1

    for vid in void_ids:
        records_by_id.pop(vid, None)

    final_records = list(records_by_id.values())
    final_records.sort(key=lambda r: r.get("kickoff_utc") or "", reverse=True)
    final_records, archived = prune_and_archive(final_records, archived)

    # Step 6: Save v5 JSON Feeds & Cache
    generated_at = iso_utc(utc_now())

    with open(OUTPUT_MATCHES, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": generated_at,
                "engine_version": ENGINE_VERSION,
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
                "engine_version": ENGINE_VERSION,
                "max_records": MAX_HISTORY_RECORDS,
                "all_time_archived": archived,
                "records": final_records,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    if len(cache) > 3500:
        cache = dict(list(cache.items())[-3500:])
    with open(V5_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f)

    g_cnt = sum(1 for m in matches_v5 if score_from_snapshot(m["snapshot"])[0] >= 6.0)
    v_cnt = sum(1 for m in matches_v5 if 4.5 <= score_from_snapshot(m["snapshot"])[0] < 6.0)
    n_cnt = sum(1 for m in matches_v5 if 3.0 <= score_from_snapshot(m["snapshot"])[0] < 4.5)
    u_cnt = sum(1 for m in matches_v5 if score_from_snapshot(m["snapshot"])[0] < 3.0)
    print(
        f"=== Done! Total: {len(matches_v5)} (Golden={g_cnt}, Value={v_cnt}, Normal={n_cnt}, Under={u_cnt}) "
        f"| History: {len(final_records)} | Graded: {graded_count} ==="
    )


if __name__ == "__main__":
    main()
