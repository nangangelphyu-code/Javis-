```python
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import requests

# ==========================================
# 1. CURATED 28 HIGH-RELIABILITY COMPETITIONS
# ==========================================
LEAGUES = [
    # UEFA & Domestic Cups (5)
    {"slug": "uefa.champions", "code": "UCL", "name": "Champions League", "group": "cups", "lookback": 100},
    {"slug": "uefa.europa", "code": "UEL", "name": "Europa League", "group": "cups", "lookback": 100},
    {"slug": "uefa.europa.conf", "code": "UECL", "name": "Conference League", "group": "cups", "lookback": 100},
    {"slug": "eng.fa", "code": "FAC", "name": "FA Cup", "group": "cups", "lookback": 90},
    {"slug": "eng.league_cup", "code": "EFL", "name": "Carabao Cup", "group": "cups", "lookback": 90},

    # Top 5 European Leagues (5)
    {"slug": "eng.1", "code": "EPL", "name": "Premier League", "group": "top5", "lookback": 70},
    {"slug": "esp.1", "code": "LAL", "name": "La Liga", "group": "top5", "lookback": 70},
    {"slug": "ita.1", "code": "SER", "name": "Serie A", "group": "top5", "lookback": 70},
    {"slug": "ger.1", "code": "BUN", "name": "Bundesliga", "group": "top5", "lookback": 70},
    {"slug": "fra.1", "code": "LG1", "name": "Ligue 1", "group": "top5", "lookback": 70},

    # High-Corner Priority 5 (5)
    {"slug": "usa.1", "code": "MLS", "name": "USA MLS", "group": "high5", "lookback": 70},
    {"slug": "eng.2", "code": "CHP", "name": "Championship", "group": "high5", "lookback": 70},
    {"slug": "aus.1", "code": "ALE", "name": "A-League", "group": "high5", "lookback": 70},
    {"slug": "bra.2", "code": "BRB", "name": "Brazil Serie B", "group": "high5", "lookback": 70},
    {"slug": "ned.1", "code": "ERE", "name": "Eredivisie", "group": "high5", "lookback": 70},

    # Verified Global Leagues (13)
    {"slug": "eng.3", "code": "EFL1", "name": "England League One", "group": "global", "lookback": 70},
    {"slug": "por.1", "code": "POR", "name": "Primeira Liga", "group": "global", "lookback": 70},
    {"slug": "bel.1", "code": "BEL", "name": "Belgian Pro League", "group": "global", "lookback": 70},
    {"slug": "tur.1", "code": "TUR", "name": "Turkish Super Lig", "group": "global", "lookback": 70},
    {"slug": "sco.1", "code": "SCO", "name": "Scottish Premiership", "group": "global", "lookback": 70},
    {"slug": "bra.1", "code": "BRA", "name": "Brazil Serie A", "group": "global", "lookback": 70},
    {"slug": "arg.1", "code": "ARG", "name": "Argentina Liga", "group": "global", "lookback": 70},
    {"slug": "mex.1", "code": "LMX", "name": "Liga MX", "group": "global", "lookback": 70},
    {"slug": "ger.2", "code": "BL2", "name": "2. Bundesliga", "group": "global", "lookback": 70},
    {"slug": "esp.2", "code": "LL2", "name": "La Liga 2", "group": "global", "lookback": 70},
    {"slug": "ita.2", "code": "SRB", "name": "Serie B", "group": "global", "lookback": 70},
    {"slug": "aut.1", "code": "AUT", "name": "Austrian Bundesliga", "group": "global", "lookback": 70},
    {"slug": "den.1", "code": "DEN", "name": "Danish Superliga", "group": "global", "lookback": 70},
]

SLUG_TO_CODE = {lg["slug"]: lg["code"] for lg in LEAGUES}
SLUG_TO_CODE.update({
    "esp.copa_del_rey": "CDR",
    "ita.coppa_italia": "CIT",
    "ger.dfb_pokal": "DFB",
    "fra.coupe_de_france": "CDF",
    "fifa.worldq.uefa": "WCQ",
    "fifa.worldq.conmebol": "WCQ",
    "uefa.nations": "UNL",
})

MMT = timezone(timedelta(hours=6, minutes=30))
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

ENGINE_VERSION = "4.1-cn-ultra-3L"
CACHE_SCHEMA_VERSION = "4.1"
STANDARD_LINE = 9.5
UPCOMING_DAYS = int(os.getenv("UPCOMING_DAYS", "7"))
MIN_SAMPLES_REQUIRED = 2   # Strict >= 2g data verification
L3_WINDOW = 3              # Exact Last 3 completed matches
NOTI_WINDOW_HOURS = 12.0
MAX_HISTORY_RECORDS = 1000


# ==========================================
# 2. CN ULTRA 3-LAYER SCORING ENGINE (MAX 7.0)
# ==========================================
def score_cn_ultra_3layer(home_stats, away_stats, home_name, away_name):
    # --- Layer 1: Momentum (L3 Corner Avg, Max +3) ---
    h_cr = float(home_stats["l3_corners"])
    a_cr = float(away_stats["l3_corners"])
    total_cr = round(h_cr + a_cr, 2)
    if total_cr > 12.0:
        l1 = 3.0
    elif 10.0 <= total_cr <= 12.0:
        l1 = 2.0
    elif 8.0 <= total_cr < 10.0:
        l1 = 1.0
    else:
        l1 = 0.0

    # --- Layer 2: Chaos (SOT + Blocked Exact OR Total Shots Fallback, Max +2) ---
    has_exact = (
        home_stats.get("l3_blocked") is not None
        and away_stats.get("l3_blocked") is not None
    )
    if has_exact:
        l2_mode = "exact"
        h_ch = round(float(home_stats["l3_sot"]) + float(home_stats["l3_blocked"]), 2)
        a_ch = round(float(away_stats["l3_sot"]) + float(away_stats["l3_blocked"]), 2)
        total_ch = round(h_ch + a_ch, 2)
        if total_ch > 15.0:
            l2 = 2.0
        elif 10.0 <= total_ch <= 15.0:
            l2 = 1.0
        else:
            l2 = 0.0
    else:
        l2_mode = "fallback"
        h_ch = round(float(home_stats["l3_total_shots"]), 2)
        a_ch = round(float(away_stats["l3_total_shots"]), 2)
        total_ch = round(h_ch + a_ch, 2)
        if total_ch > 26.0:
            l2 = 2.0
        elif 19.0 <= total_ch <= 26.0:
            l2 = 1.0
        else:
            l2 = 0.0

    # --- Layer 3: Conceded Corners (Individual Sum, Max +2 / Min -1) ---
    def conceded_pts(val):
        if val > 5.0:
            return 1.0
        if 4.0 <= val <= 5.0:
            return 0.5
        return -0.5

    h_con = float(home_stats["l3_conceded"])
    a_con = float(away_stats["l3_conceded"])
    h_con_pts = conceded_pts(h_con)
    a_con_pts = conceded_pts(a_con)
    l3 = round(h_con_pts + a_con_pts, 1)

    # --- Total Score & Verdict Classification ---
    total_score = round(l1 + l2 + l3, 1)
    if total_score >= 6.0:
        tier = "GOLDEN"
        verdict = "GOLDEN BET"
    elif total_score >= 4.5:
        tier = "VALUE"
        verdict = "VALUE BET"
    elif total_score >= 3.0:
        tier = "RISKY"
        verdict = "RISKY"
    else:
        tier = "NO_BET"
        verdict = "NO BET"

    # --- Reference Expected Corners ---
    exp_home = round((h_cr + a_con) / 2.0, 1)
    exp_away = round((a_cr + h_con) / 2.0, 1)
    ref_total = round(exp_home + exp_away, 1)

    # --- Single-Team Corner Dominance Alert ---
    gap = round(h_cr - a_cr, 2)
    dominance = None
    if (h_cr >= 6.5 and a_con >= 5.5) or (gap >= 3.0 and h_cr >= 6.5):
        dominance = {
            "side": "HOME",
            "team": home_name,
            "teamAvg": h_cr,
            "oppConceded": a_con,
            "gap": round(abs(gap), 1),
            "expTeam": exp_home,
            "note": (
                f"{home_name} တစ်သင်းတည်း ထောင့်ကန်ဘော ပျမ်းမျှ {h_cr} လုံးအထိ အားသာနေပြီး "
                f"ပြိုင်ဘက်ကလည်း ပျမ်းမျှ {a_con} လုံး ပြန်ပေးနေရသည်။ Total Over 9.5 အပြင် "
                f"Home Team Corner Over သို့မဟုတ် Corner Handicap ကိုပါ စဉ်းစားနိုင်သည်။"
            ),
        }
    elif (a_cr >= 6.5 and h_con >= 5.5) or (gap <= -3.0 and a_cr >= 6.5):
        dominance = {
            "side": "AWAY",
            "team": away_name,
            "teamAvg": a_cr,
            "oppConceded": h_con,
            "gap": round(abs(gap), 1),
            "expTeam": exp_away,
            "note": (
                f"{away_name} တစ်သင်းတည်း ထောင့်ကန်ဘော ပျမ်းမျှ {a_cr} လုံးအထိ အားသာနေပြီး "
                f"အိမ်ရှင်ကလည်း ပျမ်းမျှ {h_con} လုံး ပြန်ပေးနေရသည်။ Total Over 9.5 အပြင် "
                f"Away Team Corner Over သို့မဟုတ် Corner Handicap ကိုပါ စဉ်းစားနိုင်သည်။"
            ),
        }

    # --- Outlier Spike Detection ---
    spike_teams = []
    if home_stats.get("has_spike"):
        spike_teams.append(home_name)
    if away_stats.get("has_spike"):
        spike_teams.append(away_name)
    has_spike = len(spike_teams) > 0
    spike_note = (
        f"{' နှင့် '.join(spike_teams)} ၏ နောက်ဆုံး ၃ ပွဲမှတ်တမ်းတွင် တစ်ပွဲတည်း ထောင့်ကန်ဘော "
        f"အလွန်များ/နည်း ကွာဟမှု (Outlier Spike) ရှိနေ၍ ပျမ်းမျှဂဏန်းကို သတိထားစစ်ဆေးပါ။"
        if has_spike else None
    )

    # --- Clear Burmese Analytical Reasoning ---
    reasons = []
    if l1 >= 2.0:
        reasons.append(f"L3 ထောင့်ကန်ဘောပေါင်း {total_cr} လုံးဖြင့် အရှိန်ကောင်းနေသည် (+{l1:g})")
    elif l1 == 1.0:
        reasons.append(f"L3 ထောင့်ကန်ဘောပေါင်း {total_cr} လုံးဖြင့် သင့်တင့်အဆင့်ရှိသည် (+1)")
    else:
        reasons.append(f"L3 ထောင့်ကန်ဘောပေါင်း {total_cr} လုံးသာရှိ၍ အရှိန်နည်းနေသည် (0)")

    l2_label = "SOT+Blocked" if l2_mode == "exact" else "Total Shots"
    if l2 == 2.0:
        reasons.append(f"{l2_label} စုစုပေါင်း {total_ch} ကြိမ်ဖြင့် ဂိုးပေါက်ဖိအားမြင့်သည် (+2)")
    elif l2 == 1.0:
        reasons.append(f"{l2_label} စုစုပေါင်း {total_ch} ကြိမ်ဖြင့် ဖိအားသင့်တင့်သည် (+1)")
    else:
        reasons.append(f"{l2_label} စုစုပေါင်း {total_ch} ကြိမ်သာရှိ၍ ဂိုးပေါက်ဖိအားနည်းသည် (0)")

    if l3 >= 1.5:
        reasons.append(f"နှစ်ဖက်ခံစစ်လုံး ထောင့်ကန်ဘော ပြန်ပေးရမှုများသည် ({h_con} / {a_con}, +{l3:g})")
    elif l3 <= 0:
        tight = []
        if h_con < 4.0:
            tight.append(f"{home_name} ({h_con})")
        if a_con < 4.0:
            tight.append(f"{away_name} ({a_con})")
        if tight:
            reasons.append(f"{' နှင့် '.join(tight)} ခံစစ်ကျစ်လျစ်၍ အမှတ်နှုတ်ခံရသည် ({l3:g})")
        else:
            reasons.append(f"ခံစစ်ပြန်ပေးရမှု သာမန်အဆင့်သာရှိသည် ({l3:g})")
    else:
        reasons.append(f"ခံစစ်ပြန်ပေးရမှု သင့်တင့်သည် ({h_con} / {a_con}, +{l3:g})")

    if tier == "GOLDEN":
        summary_text = f"အလွှာ ၃ ခုလုံး အားကောင်းပြီး {total_score}/7.0 ရရှိထားသဖြင့် Over 9.5 အတွက် အခိုင်မာဆုံး Golden Pick ဖြစ်သည်။"
    elif tier == "VALUE":
        summary_text = f"စုစုပေါင်း {total_score}/7.0 ရရှိထားသော Value Pick ဖြစ်သည်။ Lineup နှင့် ပွဲအခြေအနေ ကိုက်ညီပါက ဝင်နိုင်သည်။"
    elif tier == "RISKY":
        summary_text = f"စုစုပေါင်း {total_score}/7.0 သာ ရရှိပြီး အချက်အလက်အချို့ အားနည်းနေသဖြင့် သတိထား/ကျော်သင့်သောပွဲ ဖြစ်သည်။"
    else:
        summary_text = f"စုစုပေါင်း {total_score}/7.0 သာ ရှိသဖြင့် ထောင့်ကန်ဘောနည်းနိုင်သောကြောင့် ရှောင်သင့်သောပွဲ (No Bet) ဖြစ်သည်။"

    return {
        "score": total_score,
        "maxScore": 7.0,
        "tier": tier,
        "verdict": verdict,
        "targetLine": STANDARD_LINE,
        "l1": {"pts": l1, "max": 3.0, "home": h_cr, "away": a_cr, "total": total_cr},
        "l2": {"pts": l2, "max": 2.0, "mode": l2_mode, "home": h_ch, "away": a_ch, "total": total_ch},
        "l3": {
            "pts": l3,
            "max": 2.0,
            "home": h_con,
            "away": a_con,
            "homePts": h_con_pts,
            "awayPts": a_con_pts,
        },
        "refExpHome": exp_home,
        "refExpAway": exp_away,
        "refTotal": ref_total,
        "dominance": dominance,
        "hasSpike": has_spike,
        "spikeNote": spike_note,
        "summaryText": summary_text,
        "reasons": reasons,
    }


# ==========================================
# 3. MULTI-COMPETITION ESPN DATA FETCHER & AUDIT TRAIL
# ==========================================
def parse_utc(iso_str):
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
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


def fetch_json(url, timeout=15, retries=2):
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.6 * (attempt + 1))
                continue
            return None
        except Exception:
            time.sleep(0.4 * (attempt + 1))
    return None


def fetch_league_boards(lg, now_utc):
    slug = lg["slug"]
    base = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
    up_range = f"{now_utc.strftime('%Y%m%d')}-{(now_utc + timedelta(days=UPCOMING_DAYS)).strftime('%Y%m%d')}"
    past_start = (now_utc - timedelta(days=lg.get("lookback", 70))).strftime("%Y%m%d")
    past_end = now_utc.strftime("%Y%m%d")

    default_board = fetch_json(base)
    up_board = fetch_json(f"{base}?dates={up_range}")
    past_board = fetch_json(f"{base}?dates={past_start}-{past_end}")
    return lg, default_board, up_board, past_board


def fetch_team_all_completed_events(tid, candidate_slugs, now_utc):
    """
    Fetch ALL completed matches for a team across ALL competitions (League + Cups + UEFA),
    so domestic cup or European matches between league games are NEVER skipped.
    """
    found = {}
    urls = [f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{tid}/schedule"]
    for slug in candidate_slugs:
        if slug:
            urls.append(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{tid}/schedule")

    for url in urls:
        data = fetch_json(url)
        if not data:
            continue
        default_slug = data.get("league", {}).get("slug", "")
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
            ev_slug = (ev.get("league") or {}).get("slug") or default_slug or (candidate_slugs[0] if candidate_slugs else "all")
            found[eid] = (dt.timestamp(), edate, eid, ev_slug)
        if len(found) >= 8 and "soccer/all/" in url:
            break

    return list(found.values())


def extract_boxscore_stats(slug, event_id):
    """
    Fetch boxscore using universal 'all' endpoint first (with league slug fallback)
    and store complete match metadata for Last 3 Games Audit Trail verification.
    """
    urls = [f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event={event_id}"]
    if slug and slug != "all":
        urls.append(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}")

    data = None
    for u in urls:
        cand = fetch_json(u)
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


def compute_team_l3_stats(team_ids, team_history_events, cache):
    results = {}
    for tid in team_ids:
        # Strictly sort completed matches by actual kickoff timestamp descending (most recent first)
        ev_refs = sorted(team_history_events.get(tid, []), key=lambda x: x[0], reverse=True)
        rows = []
        audit_matches = []
        seen_eids = set()

        for _, edate, eid, _ in ev_refs:
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
                audit_matches.append({
                    "id": eid,
                    "date": d_str,
                    "leagueCode": meta.get("leagueCode", "CMP"),
                    "venue": t_row.get("venue", "-"),
                    "opponent": t_row.get("opponent", "Opponent"),
                    "cornersWon": int(round(t_row["corners"])),
                    "cornersConceded": int(round(t_row.get("corners_conceded", 0))),
                })
            if len(rows) >= L3_WINDOW:
                break

        if not rows:
            results[tid] = {"sample_size": 0}
            continue

        def avg_required(k):
            vals = [float(r[k]) for r in rows if r.get(k) is not None]
            return round(sum(vals) / len(vals), 2) if vals else 0.0

        def avg_optional(k):
            vals = [float(r[k]) for r in rows if r.get(k) is not None]
            if len(vals) == len(rows):
                return round(sum(vals) / len(vals), 2)
            return None

        corners_seq = [int(round(r["corners"])) for r in rows]
        conceded_seq = [int(round(r.get("corners_conceded", 0))) for r in rows]

        results[tid] = {
            "sample_size": len(rows),
            "l3_corners": avg_required("corners"),
            "l3_conceded": avg_required("corners_conceded"),
            "l3_sot": avg_required("shots_on_target"),
            "l3_total_shots": avg_required("total_shots"),
            "l3_blocked": avg_optional("blocked_shots"),
            "recent_corners": corners_seq,
            "recent_conceded": conceded_seq,
            "recent_matches": audit_matches,
            "has_spike": detect_spike(corners_seq),
        }
    return results


# ==========================================
# 4. AUTO-RESULT BACKTEST GRADER (OVER 9.5)
# ==========================================
def grade_pending_history(history_list, cache, now_utc):
    to_check = []
    for item in history_list:
        if item.get("status") != "PENDING":
            continue
        ko = parse_utc(item.get("kickoffUTC", ""))
        if ko and (now_utc - ko).total_seconds() >= 2.2 * 3600:
            to_check.append(item)

    if to_check:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {}
            for item in to_check[:40]:
                eid = item["id"]
                if eid in cache and isinstance(cache[eid], dict) and cache[eid].get("_meta", {}).get("v") == CACHE_SCHEMA_VERSION:
                    continue
                slug = item.get("leagueSlug", "")
                futs[ex.submit(extract_boxscore_stats, slug, eid)] = eid
            for fut in as_completed(futs):
                eid = futs[fut]
                res = fut.result()
                if isinstance(res, dict):
                    cache[eid] = res

    for item in history_list:
        if item.get("status") != "PENDING":
            continue
        eid = item["id"]
        box = cache.get(eid)
        if not isinstance(box, dict):
            ko = parse_utc(item.get("kickoffUTC", ""))
            if ko and (now_utc - ko).days >= 5:
                item["status"] = "VOID"
            continue

        hid = str(item.get("homeId", ""))
        aid = str(item.get("awayId", ""))
        if hid in box and aid in box:
            act_h = int(round(box[hid]["corners"]))
            act_a = int(round(box[aid]["corners"]))
            act_tot = act_h + act_a
            line = float(item.get("targetLine", STANDARD_LINE))
            grade = "HIT" if act_tot > line else "MISS"

            item["actualHomeCorners"] = act_h
            item["actualAwayCorners"] = act_a
            item["actualTotal"] = act_tot
            item["grade"] = grade
            item["isExtraTime"] = bool(box.get("_meta", {}).get("extraTime", False))
            item["status"] = "GRADED"
            item["gradedAtMMT"] = now_utc.astimezone(MMT).strftime("%d %b, %I:%M %p")

    return build_history_summary(history_list)


def build_history_summary(history_list):
    graded_all = [h for h in history_list if h.get("status") == "GRADED"]
    cn_graded = [h for h in graded_all if str(h.get("engineVersion", "")).startswith("4.")]
    active_graded = cn_graded if cn_graded else graded_all

    def calc_bucket(items):
        hits = sum(1 for x in items if x.get("grade") == "HIT")
        misses = sum(1 for x in items if x.get("grade") == "MISS")
        tot = hits + misses
        rate = round((hits / tot) * 100, 1) if tot > 0 else 0.0
        return {"hits": hits, "misses": misses, "total": tot, "hitRate": rate}

    picks_items = [h for h in active_graded if h.get("tier") in ("GOLDEN", "VALUE")]
    tier_stats = {
        "GOLDEN": calc_bucket([h for h in active_graded if h.get("tier") == "GOLDEN"]),
        "VALUE": calc_bucket([h for h in active_graded if h.get("tier") == "VALUE"]),
        "RISKY": calc_bucket([h for h in active_graded if h.get("tier") == "RISKY"]),
        "NO_BET": calc_bucket([h for h in active_graded if h.get("tier") == "NO_BET"]),
    }

    exact_stats = calc_bucket([h for h in picks_items if h.get("l2Mode") == "exact"])
    fallback_stats = calc_bucket([h for h in picks_items if h.get("l2Mode") == "fallback"])

    by_league = {}
    for h in picks_items:
        code = h.get("leagueCode", "OTH")
        rec = by_league.setdefault(code, {"code": code, "name": h.get("leagueName", code), "hits": 0, "misses": 0})
        if h.get("grade") == "HIT":
            rec["hits"] += 1
        elif h.get("grade") == "MISS":
            rec["misses"] += 1

    league_stats = []
    for rec in by_league.values():
        tot = rec["hits"] + rec["misses"]
        league_stats.append({
            "code": rec["code"],
            "name": rec["name"],
            "hits": rec["hits"],
            "misses": rec["misses"],
            "total": tot,
            "hitRate": round((rec["hits"] / tot) * 100, 1) if tot > 0 else 0.0,
        })
    league_stats.sort(key=lambda x: (x["total"] > 0, x["hitRate"], x["hits"]), reverse=True)

    return {
        "standardLine": STANDARD_LINE,
        "totalGraded": len(active_graded),
        "pendingCount": sum(1 for h in history_list if h.get("status") == "PENDING"),
        "picksSummary": calc_bucket(picks_items),
        "allSummary": calc_bucket(active_graded),
        "byTier": tier_stats,
        "exactMode": exact_stats,
        "fallbackMode": fallback_stats,
        "byLeague": league_stats,
    }


# ==========================================
# 5. OPTIONAL PUSH NOTIFICATIONS (GOLDEN ONLY)
# ==========================================
def send_push_alerts(golden_alerts):
    if not golden_alerts:
        return
    ntfy_topic = os.getenv("NTFY_TOPIC", "").strip()
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not ntfy_topic and not (tg_token and tg_chat):
        return

    for m in golden_alerts[:10]:
        c = m["cn"]
        title = f"JAVIS GOLDEN ({c['score']}/7) | {m['leagueCode']}"
        body = (
            f"{m['home']} vs {m['away']}\n"
            f"{m['leagueName']} · {m['kickoffMMT']}\n"
            f"Score: {c['score']}/7.0 (Target: Over {STANDARD_LINE})\n"
            f"L1: +{c['l1']['pts']:g} ({c['l1']['total']}) | L2: +{c['l2']['pts']:g} ({c['l2']['mode']}) | L3: {c['l3']['pts']:+g}\n"
            f"Ref Avg Total: {c['refTotal']} corners"
        )
        if ntfy_topic:
            try:
                SESSION.post(
                    f"https://ntfy.sh/{ntfy_topic}",
                    data=body.encode("utf-8"),
                    headers={"Title": title, "Priority": "high"},
                    timeout=10,
                )
            except Exception as e:
                print("ntfy error:", e)
        if tg_token and tg_chat:
            try:
                SESSION.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": tg_chat, "text": f"{title}\n\n{body}"},
                    timeout=10,
                )
            except Exception as e:
                print("Telegram error:", e)


# ==========================================
# 6. MAIN EXECUTION
# ==========================================
def load_json_safe(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def main():
    os.makedirs("data", exist_ok=True)
    cache_path = "data/event_cache.json"
    notified_path = "data/notified.json"
    history_path = "history.json"

    raw_cache = load_json_safe(cache_path, {})
    # Keep only v4.1 schema entries so any old unverified cache entries are cleanly rebuilt
    cache = {
        k: v for k, v in raw_cache.items()
        if isinstance(v, dict) and v.get("_meta", {}).get("v") == CACHE_SCHEMA_VERSION
    }
    notified = set(load_json_safe(notified_path, []))
    raw_history = load_json_safe(history_path, {"records": []})
    history_records = raw_history.get("records", []) if isinstance(raw_history, dict) else []
    history_map = {str(r["id"]): r for r in history_records if "id" in r}

    now_utc = datetime.now(timezone.utc)

    # Step 1: Grade pending matches in history.json
    grade_pending_history(history_records, cache, now_utc)

    # Step 2: Fetch upcoming & recent boards for all 28 leagues
    upcoming_items = []
    seen_upcoming_ids = set()
    active_team_ids = set()
    team_slugs = {}
    team_history_events = {}

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_league_boards, lg, now_utc) for lg in LEAGUES]
        for fut in as_completed(futs):
            lg, default_board, up_board, past_board = fut.result()
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
                    active_team_ids.update([hid, aid])
                    team_slugs.setdefault(hid, []).append(slug)
                    team_slugs.setdefault(aid, []).append(slug)
                    upcoming_items.append((lg, ev, home_c, away_c, hid, aid))

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
                            team_history_events.setdefault(tid, []).append((dt.timestamp(), ev_date, ev_id, slug))

    # Step 2b: Fetch full multi-competition schedules for every active team
    # Ensures cup / European games played between league matches are ALWAYS included
    if active_team_ids:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {
                ex.submit(fetch_team_all_completed_events, tid, list(dict.fromkeys(team_slugs.get(tid, []))), now_utc): tid
                for tid in active_team_ids
            }
            for fut in as_completed(futs):
                tid = futs[fut]
                for item in fut.result():
                    team_history_events.setdefault(tid, []).append(item)

    # Step 3: Fetch boxscores for active teams' true Last 3 completed matches (with buffer up to 6)
    needed_boxscores = {}
    for tid in active_team_ids:
        ev_refs = sorted(team_history_events.get(tid, []), key=lambda x: x[0], reverse=True)
        picked = 0
        seen_eids = set()
        for _, _, eid, slug in ev_refs:
            if eid in seen_eids:
                continue
            seen_eids.add(eid)
            if eid not in cache:
                needed_boxscores[eid] = slug
            picked += 1
            if picked >= L3_WINDOW + 3:
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

    # Step 4: Strict >= 2g Verification + CN Ultra 3-Layer Scoring
    team_stats = compute_team_l3_stats(active_team_ids, team_history_events, cache)
    all_matches = []
    golden_alerts = []
    filtered_low_data = 0

    for lg, ev, home_c, away_c, hid, aid in upcoming_items:
        ev_id = str(ev["id"])
        h_stats = team_stats.get(hid, {"sample_size": 0})
        a_stats = team_stats.get(aid, {"sample_size": 0})

        if h_stats.get("sample_size", 0) < MIN_SAMPLES_REQUIRED or a_stats.get("sample_size", 0) < MIN_SAMPLES_REQUIRED:
            filtered_low_data += 1
            continue

        dt_utc = parse_utc(ev.get("date", ""))
        if not dt_utc:
            continue
        dt_mmt = dt_utc.astimezone(MMT)
        hours_to_ko = (dt_utc - now_utc).total_seconds() / 3600.0
        if hours_to_ko < -0.1:
            continue

        home_name = home_c["team"]["displayName"]
        away_name = away_c["team"]["displayName"]
        cn = score_cn_ultra_3layer(h_stats, a_stats, home_name, away_name)

        match_obj = {
            "id": ev_id,
            "leagueSlug": lg["slug"],
            "leagueCode": lg["code"],
            "leagueName": lg["name"],
            "leagueGroup": lg["group"],
            "homeId": hid,
            "awayId": aid,
            "home": home_name,
            "away": away_name,
            "kickoffUTC": ev["date"],
            "kickoffMMT": dt_mmt.strftime("%d %b, %I:%M %p"),
            "homeStats": h_stats,
            "awayStats": a_stats,
            "cn": cn,
        }
        all_matches.append(match_obj)

        # Pre-match lock into history.json
        if ev_id not in history_map and hours_to_ko > 0:
            rec = {
                "id": ev_id,
                "engineVersion": ENGINE_VERSION,
                "leagueSlug": lg["slug"],
                "leagueCode": lg["code"],
                "leagueName": lg["name"],
                "homeId": hid,
                "awayId": aid,
                "home": home_name,
                "away": away_name,
                "kickoffUTC": ev["date"],
                "kickoffMMT": match_obj["kickoffMMT"],
                "score": cn["score"],
                "tier": cn["tier"],
                "verdict": cn["verdict"],
                "l2Mode": cn["l2"]["mode"],
                "refTotal": cn["refTotal"],
                "targetLine": STANDARD_LINE,
                "dominanceSide": cn["dominance"]["side"] if cn["dominance"] else None,
                "hasSpike": cn["hasSpike"],
                "status": "PENDING",
                "actualHomeCorners": None,
                "actualAwayCorners": None,
                "actualTotal": None,
                "grade": None,
                "isExtraTime": False,
            }
            history_records.append(rec)
            history_map[ev_id] = rec
        elif (
            ev_id in history_map
            and history_map[ev_id].get("status") == "PENDING"
            and history_map[ev_id].get("engineVersion") != ENGINE_VERSION
            and hours_to_ko > 0
        ):
            rec = history_map[ev_id]
            rec.update({
                "engineVersion": ENGINE_VERSION,
                "score": cn["score"],
                "tier": cn["tier"],
                "verdict": cn["verdict"],
                "l2Mode": cn["l2"]["mode"],
                "refTotal": cn["refTotal"],
                "targetLine": STANDARD_LINE,
                "dominanceSide": cn["dominance"]["side"] if cn["dominance"] else None,
                "hasSpike": cn["hasSpike"],
            })

        if cn["tier"] == "GOLDEN" and ev_id not in notified and (0 < hours_to_ko <= NOTI_WINDOW_HOURS):
            golden_alerts.append(match_obj)
            notified.add(ev_id)

    all_matches.sort(key=lambda x: x["kickoffUTC"])

    history_summary = build_history_summary(history_records)
    history_records.sort(key=lambda x: x.get("kickoffUTC", ""), reverse=True)

    output = {
        "engineVersion": ENGINE_VERSION,
        "standardLine": STANDARD_LINE,
        "updatedAtUTC": now_utc.isoformat(),
        "updatedAtMMT": now_utc.astimezone(MMT).strftime("%d %b %Y, %I:%M %p"),
        "leagueCount": len(LEAGUES),
        "matchCount": len(all_matches),
        "goldenCount": sum(1 for m in all_matches if m["cn"]["tier"] == "GOLDEN"),
        "valueCount": sum(1 for m in all_matches if m["cn"]["tier"] == "VALUE"),
        "filteredLowDataCount": filtered_low_data,
        "matches": all_matches,
    }

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump({
            "engineVersion": ENGINE_VERSION,
            "updatedAtMMT": output["updatedAtMMT"],
            "summary": history_summary,
            "records": history_records[:MAX_HISTORY_RECORDS],
        }, f, ensure_ascii=False, indent=2)

    if len(cache) > 3000:
        cache = dict(list(cache.items())[-3000:])
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)

    with open(notified_path, "w", encoding="utf-8") as f:
        json.dump(list(notified)[-600:], f)

    send_push_alerts(golden_alerts)
    print(
        f"Javis v4.1 CN Ultra Scan: verified={len(all_matches)}, "
        f"golden={output['goldenCount']}, value={output['valueCount']}, "
        f"filtered_low_data={filtered_low_data}, graded={history_summary['totalGraded']}"
    )


if __name__ == "__main__":
    main()
```
