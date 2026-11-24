import json
import math
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

MMT = timezone(timedelta(hours=6, minutes=30))
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

ALERT_MIN_LAMBDA = float(os.getenv("ALERT_MIN_LAMBDA", "10.8"))
MIN_EDGE_TARGET = 0.04
UPCOMING_DAYS = int(os.getenv("UPCOMING_DAYS", "7"))
MIN_SAMPLES_REQUIRED = 2
MAX_SAMPLES_PER_TEAM = 6
NOTI_WINDOW_HOURS = 12.0


# ==========================================
# 2. PURE CORNER MODEL (Full + Lite Fallback)
# ==========================================
class PureCornerModel:
    def __init__(self, use_home_adv=True):
        self.w_avg_corners = 0.25
        self.w_blocked_shots = 0.22
        self.w_shots_on_target = 0.12
        self.w_crosses = 0.08
        self.w_touches_in_box = 0.03
        self.w_corners_conceded = 0.50
        self.w_opp_clearances = 0.09
        self.use_home_adv = use_home_adv

    def _has_full_stats(self, s):
        keys = ("blocked_shots", "crosses", "touches_in_box", "opp_clearances")
        return all(s.get(k) is not None for k in keys)

    def calculate_attack_score(self, s, full=True):
        if full:
            return (
                s["avg_corners"] * self.w_avg_corners
                + s["blocked_shots"] * self.w_blocked_shots
                + s["shots_on_target"] * self.w_shots_on_target
                + s["crosses"] * self.w_crosses
                + s["touches_in_box"] * self.w_touches_in_box
            )
        return (
            s["avg_corners"] * 0.58
            + s["shots_on_target"] * 0.24
            + s.get("total_shots", 12.0) * 0.06
        )

    def calculate_defense_score(self, s, full=True):
        if full:
            return (
                s["corners_conceded"] * self.w_corners_conceded
                + s["opp_clearances"] * self.w_opp_clearances
            )
        return (
            s["corners_conceded"] * 0.66
            + s.get("shots_conceded", 12.0) * 0.063
        )

    def get_expected_corners(self, home_stats, away_stats):
        is_full = self._has_full_stats(home_stats) and self._has_full_stats(away_stats)
        att_h = self.calculate_attack_score(home_stats, is_full)
        def_h = self.calculate_defense_score(home_stats, is_full)
        att_a = self.calculate_attack_score(away_stats, is_full)
        def_a = self.calculate_defense_score(away_stats, is_full)

        exp_h = (att_h + def_a) / 2.0
        exp_a = (att_a + def_h) / 2.0

        if self.use_home_adv:
            exp_h *= 1.05
            exp_a *= 0.95

        total_lambda = exp_h + exp_a
        mode = "full" if is_full else "lite"
        return round(exp_h, 2), round(exp_a, 2), round(total_lambda, 2), mode

    @staticmethod
    def poisson_probability(lam, k):
        return ((lam ** k) * math.exp(-lam)) / math.factorial(k)

    def calculate_over_under_prob(self, total_lambda, line):
        if line % 1 == 0:
            line_int = int(line)
            under_prob = sum(self.poisson_probability(total_lambda, k) for k in range(line_int))
            push_prob = self.poisson_probability(total_lambda, line_int)
            over_prob = max(0.0, 1.0 - under_prob - push_prob)
            return over_prob, under_prob, push_prob
        under_prob = sum(self.poisson_probability(total_lambda, k) for k in range(int(line) + 1))
        over_prob = max(0.0, 1.0 - under_prob)
        return over_prob, under_prob, 0.0

    def suggest_target_line(self, total_lambda):
        best_line = max(7.5, round(total_lambda - 0.5) - 0.5)
        over_p, under_p, push_p = self.calculate_over_under_prob(total_lambda, best_line)
        fair_odds = round(1.0 / over_p, 2) if over_p > 0.05 else 9.99
        min_ev_odds = round(1.0 / max(0.05, over_p - MIN_EDGE_TARGET), 2)
        return {
            "line": best_line,
            "overProb": round(over_p * 100, 1),
            "underProb": round(under_p * 100, 1),
            "pushProb": round(push_p * 100, 1),
            "fairOdds": fair_odds,
            "minValueOdds": min_ev_odds,
        }


# ==========================================
# 3. RESILIENT DATA FETCHER & CONSISTENCY ENGINE
# ==========================================
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


def fetch_team_schedule_events(slug, tid):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{tid}/schedule"
    data = fetch_json(url)
    found = []
    if not data:
        return found
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if comp.get("status", {}).get("type", {}).get("completed"):
            eid = str(ev.get("id", ""))
            edate = ev.get("date", "")
            if eid:
                found.append((edate, eid, slug))
    return found


def extract_boxscore_stats(slug, event_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}"
    data = fetch_json(url)
    if not data:
        return None

    header_comp = (data.get("header", {}).get("competitions") or [{}])[0]
    state = header_comp.get("status", {}).get("type", {}).get("state", "")
    if state and state != "post":
        return None

    teams_box = data.get("boxscore", {}).get("teams", [])
    if len(teams_box) != 2:
        return None

    parsed = {}
    for entry in teams_box:
        tid = str(entry.get("team", {}).get("id", ""))
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

        parsed[tid] = {
            "corners": corners,
            "shots_on_target": pick_stat(stats_map, "shotsontarget", "shots on target", "shotsongoal") or 4.0,
            "total_shots": pick_stat(stats_map, "totalshots", "total shots", "shots") or 12.0,
            "blocked_shots": pick_stat(stats_map, "blockedshots", "blocked shots"),
            "crosses": pick_stat(stats_map, "totalcrosses", "accuratecrosses", "crosses", "total crosses"),
            "touches_in_box": pick_stat(stats_map, "touchesinoppbox", "touchesinbox", "touches in opposition box"),
            "clearances": pick_stat(stats_map, "clearances", "totalclearances"),
        }

    tids = list(parsed.keys())
    if len(tids) == 2:
        t0, t1 = tids[0], tids[1]
        parsed[t0]["corners_conceded"] = parsed[t1]["corners"]
        parsed[t1]["corners_conceded"] = parsed[t0]["corners"]
        parsed[t0]["shots_conceded"] = parsed[t1]["total_shots"]
        parsed[t1]["shots_conceded"] = parsed[t0]["total_shots"]
        parsed["_total_corners"] = parsed[t0]["corners"] + parsed[t1]["corners"]
    return parsed


def calc_std_dev(vals):
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return round(math.sqrt(var), 2)


def compute_team_averages(team_ids, team_history_events, cache):
    averages = {}
    for tid in team_ids:
        ev_refs = sorted(team_history_events.get(tid, []), key=lambda x: x[0], reverse=True)
        rows = []
        match_totals = []
        seen_eids = set()
        for _, eid, _ in ev_refs:
            if eid in seen_eids:
                continue
            seen_eids.add(eid)
            entry = cache.get(eid)
            if isinstance(entry, dict) and tid in entry:
                rows.append(entry[tid])
                if "_total_corners" in entry:
                    match_totals.append(entry["_total_corners"])
            if len(rows) >= MAX_SAMPLES_PER_TEAM:
                break

        if not rows:
            averages[tid] = {"sample_size": 0}
            continue

        def avg_key(k):
            vals = [r[k] for r in rows if r.get(k) is not None]
            return round(sum(vals) / len(vals), 2) if vals else None

        team_corners_seq = [r["corners"] for r in rows]
        std_team = calc_std_dev(team_corners_seq)
        std_total = calc_std_dev(match_totals) if len(match_totals) >= 2 else std_team

        averages[tid] = {
            "avg_corners": avg_key("corners") or 5.0,
            "shots_on_target": avg_key("shots_on_target") or 4.2,
            "total_shots": avg_key("total_shots") or 12.0,
            "corners_conceded": avg_key("corners_conceded") or 5.0,
            "shots_conceded": avg_key("shots_conceded") or 12.0,
            "blocked_shots": avg_key("blocked_shots"),
            "crosses": avg_key("crosses"),
            "touches_in_box": avg_key("touches_in_box"),
            "opp_clearances": avg_key("clearances"),
            "sample_size": len(rows),
            "std_dev": std_total,
            "recent_corners": team_corners_seq[:5],
        }
    return averages


def classify_stability(h_stats, a_stats):
    avg_std = (h_stats.get("std_dev", 2.0) + a_stats.get("std_dev", 2.0)) / 2.0
    if avg_std <= 2.15:
        return "Stable", round(avg_std, 2)
    if avg_std <= 2.95:
        return "Moderate", round(avg_std, 2)
    return "Volatile", round(avg_std, 2)


# ==========================================
# 4. AUTO-RESULT BACKTEST GRADER
# ==========================================
def grade_pending_history(history_list, cache, now_utc):
    to_check = []
    for item in history_list:
        if item.get("status") != "PENDING":
            continue
        try:
            ko = datetime.fromisoformat(item["kickoffUTC"].replace("Z", "+00:00"))
            if (now_utc - ko).total_seconds() >= 2.2 * 3600:
                to_check.append(item)
        except Exception:
            continue

    if to_check:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {}
            for item in to_check[:35]:
                eid = item["id"]
                if eid in cache and isinstance(cache[eid], dict):
                    continue
                slug = item.get("leagueSlug", "")
                if slug:
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
            try:
                ko = datetime.fromisoformat(item["kickoffUTC"].replace("Z", "+00:00"))
                if (now_utc - ko).days >= 5:
                    item["status"] = "VOID"
            except Exception:
                pass
            continue

        hid = str(item.get("homeId", ""))
        aid = str(item.get("awayId", ""))
        if hid in box and aid in box:
            act_h = box[hid]["corners"]
            act_a = box[aid]["corners"]
            act_tot = round(act_h + act_a, 1)
            line = float(item["targetLine"])
            lam = float(item["totalLambda"])

            if act_tot > line:
                grade = "HIT"
            elif act_tot == line:
                grade = "PUSH"
            else:
                grade = "MISS"

            item["actualHomeCorners"] = act_h
            item["actualAwayCorners"] = act_a
            item["actualTotal"] = act_tot
            item["grade"] = grade
            item["absError"] = round(abs(act_tot - lam), 2)
            item["biasError"] = round(act_tot - lam, 2)
            item["status"] = "GRADED"
            item["gradedAtMMT"] = now_utc.astimezone(MMT).strftime("%d %b, %I:%M %p")

    return build_history_summary(history_list)


def build_history_summary(history_list):
    graded = [h for h in history_list if h.get("status") == "GRADED"]
    hits = sum(1 for h in graded if h.get("grade") == "HIT")
    misses = sum(1 for h in graded if h.get("grade") == "MISS")
    pushes = sum(1 for h in graded if h.get("grade") == "PUSH")
    decided = hits + misses
    hit_rate = round((hits / decided) * 100, 1) if decided > 0 else 0.0
    avg_err = round(sum(h["absError"] for h in graded) / len(graded), 2) if graded else 0.0
    avg_bias = round(sum(h["biasError"] for h in graded) / len(graded), 2) if graded else 0.0

    prime = [h for h in graded if h.get("isPrimeSignal") and h.get("grade") in ("HIT", "MISS")]
    prime_hits = sum(1 for h in prime if h.get("grade") == "HIT")
    prime_rate = round((prime_hits / len(prime)) * 100, 1) if prime else 0.0

    full_g = [h for h in graded if h.get("modelMode") == "full" and h.get("grade") in ("HIT", "MISS")]
    lite_g = [h for h in graded if h.get("modelMode") == "lite" and h.get("grade") in ("HIT", "MISS")]
    full_rate = round((sum(1 for h in full_g if h["grade"] == "HIT") / len(full_g)) * 100, 1) if full_g else 0.0
    lite_rate = round((sum(1 for h in lite_g if h["grade"] == "HIT") / len(lite_g)) * 100, 1) if lite_g else 0.0

    by_league = {}
    for h in graded:
        code = h.get("leagueCode", "OTH")
        rec = by_league.setdefault(code, {"code": code, "name": h.get("leagueName", code), "hits": 0, "misses": 0, "pushes": 0, "errSum": 0.0, "total": 0})
        rec["total"] += 1
        rec["errSum"] += h.get("absError", 0.0)
        if h["grade"] == "HIT":
            rec["hits"] += 1
        elif h["grade"] == "MISS":
            rec["misses"] += 1
        else:
            rec["pushes"] += 1

    league_stats = []
    for rec in by_league.values():
        dec = rec["hits"] + rec["misses"]
        league_stats.append({
            "code": rec["code"],
            "name": rec["name"],
            "hits": rec["hits"],
            "misses": rec["misses"],
            "pushes": rec["pushes"],
            "hitRate": round((rec["hits"] / dec) * 100, 1) if dec > 0 else 0.0,
            "avgError": round(rec["errSum"] / rec["total"], 2) if rec["total"] > 0 else 0.0,
        })
    league_stats.sort(key=lambda x: (x["hits"] + x["misses"] > 0, x["hitRate"], x["hits"]), reverse=True)

    return {
        "totalGraded": len(graded),
        "pendingCount": sum(1 for h in history_list if h.get("status") == "PENDING"),
        "hits": hits,
        "misses": misses,
        "pushes": pushes,
        "hitRate": hit_rate,
        "avgAbsError": avg_err,
        "avgBias": avg_bias,
        "primeHits": prime_hits,
        "primeTotal": len(prime),
        "primeHitRate": prime_rate,
        "fullModeHitRate": full_rate,
        "fullModeCount": len(full_g),
        "liteModeHitRate": lite_rate,
        "liteModeCount": len(lite_g),
        "byLeague": league_stats,
    }


# ==========================================
# 5. SMART 12-HOUR KICKOFF PUSH ALERTS
# ==========================================
def send_push_alerts(prime_alerts):
    if not prime_alerts:
        return

    ntfy_topic = os.getenv("NTFY_TOPIC", "").strip()
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    for m in prime_alerts[:12]:
        title = f"JAVIS PRIME +EV | {m['leagueCode']} (λ {m['totalLambda']})"
        body = (
            f"{m['home']} vs {m['away']}\n"
            f"Competition: {m['leagueName']} ({m['stability']})\n"
            f"Kickoff (MMT): {m['kickoffMMT']}\n"
            f"Exp Corners: {m['expHome']} - {m['expAway']} (Total λ: {m['totalLambda']})\n"
            f"Target: Over {m['target']['line']} ({m['target']['overProb']}%)\n"
            f"Min Odds for +EV: >= {m['target']['minValueOdds']}\n"
            f"Stake: 1% - 2% Flat"
        )

        if ntfy_topic:
            try:
                SESSION.post(
                    f"https://ntfy.sh/{ntfy_topic}",
                    data=body.encode("utf-8"),
                    headers={"Title": title, "Priority": "high", "Tags": "bar_chart,fire"},
                    timeout=10,
                )
            except Exception as e:
                print("ntfy error:", e)

        if tg_token and tg_chat:
            try:
                SESSION.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": tg_chat, "text": f"⚡ {title}\n\n{body}"},
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
    cache = {k: v for k, v in raw_cache.items() if isinstance(v, dict)}
    notified = set(load_json_safe(notified_path, []))
    raw_history = load_json_safe(history_path, {"records": []})
    history_records = raw_history.get("records", []) if isinstance(raw_history, dict) else []
    history_map = {str(r["id"]): r for r in history_records if "id" in r}

    model = PureCornerModel(use_home_adv=True)
    now_utc = datetime.now(timezone.utc)

    # Step 1: Grade any completed matches in history.json first
    history_summary = grade_pending_history(history_records, cache, now_utc)

    # Step 2: Fetch all 28 curated competitions
    upcoming_items = []
    seen_upcoming_ids = set()
    active_team_ids = set()
    team_primary_slug = {}
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
                    team_primary_slug.setdefault(hid, slug)
                    team_primary_slug.setdefault(aid, slug)
                    upcoming_items.append((lg, ev, home_c, away_c, hid, aid))

            for board in (default_board, past_board):
                if not board:
                    continue
                for ev in board.get("events", []):
                    comp = (ev.get("competitions") or [{}])[0]
                    if not comp.get("status", {}).get("type", {}).get("completed"):
                        continue
                    ev_id = str(ev.get("id", ""))
                    ev_date = ev.get("date", "")
                    for c in comp.get("competitors", []):
                        tid = str(c.get("team", {}).get("id", ""))
                        if tid:
                            team_history_events.setdefault(tid, []).append((ev_date, ev_id, slug))

    # Step 2b: Backfill team schedules for any active team with < 3 completed events found
    sparse_teams = [tid for tid in active_team_ids if len({e[1] for e in team_history_events.get(tid, [])}) < 3]
    if sparse_teams:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {
                ex.submit(fetch_team_schedule_events, team_primary_slug[tid], tid): tid
                for tid in sparse_teams[:60] if tid in team_primary_slug
            }
            for fut in as_completed(futs):
                tid = futs[fut]
                for item in fut.result():
                    team_history_events.setdefault(tid, []).append(item)

    # Step 3: Fetch boxscores for active teams' recent completed games
    needed_boxscores = {}
    for tid in active_team_ids:
        ev_refs = sorted(team_history_events.get(tid, []), key=lambda x: x[0], reverse=True)
        picked = 0
        seen_eids = set()
        for _, eid, slug in ev_refs:
            if eid in seen_eids:
                continue
            seen_eids.add(eid)
            if eid not in cache:
                needed_boxscores[eid] = slug
            picked += 1
            if picked >= MAX_SAMPLES_PER_TEAM + 1:
                break

    if needed_boxscores:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {
                ex.submit(extract_boxscore_stats, slug, eid): eid
                for eid, slug in needed_boxscores.items()
            }
            for fut in as_completed(futs):
                eid = futs[fut]
                res = fut.result()
                if isinstance(res, dict):
                    cache[eid] = res

    # Step 4: Strict >= 2g Data Filter & Chronological Build
    team_avgs = compute_team_averages(active_team_ids, team_history_events, cache)
    all_matches = []
    prime_alerts = []
    filtered_low_data = 0

    for lg, ev, home_c, away_c, hid, aid in upcoming_items:
        ev_id = str(ev["id"])
        h_stats = team_avgs.get(hid, {"sample_size": 0})
        a_stats = team_avgs.get(aid, {"sample_size": 0})

        if h_stats.get("sample_size", 0) < MIN_SAMPLES_REQUIRED or a_stats.get("sample_size", 0) < MIN_SAMPLES_REQUIRED:
            filtered_low_data += 1
            continue

        exp_h, exp_a, total_lam, mode = model.get_expected_corners(h_stats, a_stats)
        target = model.suggest_target_line(total_lam)
        stability, avg_std = classify_stability(h_stats, a_stats)

        dt_utc = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        dt_mmt = dt_utc.astimezone(MMT)
        hours_to_ko = (dt_utc - now_utc).total_seconds() / 3600.0

        if hours_to_ko < -0.1:
            continue

        is_prime = (total_lam >= ALERT_MIN_LAMBDA) and (stability != "Volatile")
        signal_tier = "PRIME" if is_prime else ("STRONG" if total_lam >= 10.4 else "STANDARD")

        match_obj = {
            "id": ev_id,
            "leagueSlug": lg["slug"],
            "leagueCode": lg["code"],
            "leagueName": lg["name"],
            "leagueGroup": lg["group"],
            "homeId": hid,
            "awayId": aid,
            "home": home_c["team"]["displayName"],
            "away": away_c["team"]["displayName"],
            "kickoffUTC": ev["date"],
            "kickoffMMT": dt_mmt.strftime("%d %b, %I:%M %p"),
            "modelMode": mode,
            "stability": stability,
            "stdDev": avg_std,
            "expHome": exp_h,
            "expAway": exp_a,
            "totalLambda": total_lam,
            "target": target,
            "homeStats": h_stats,
            "awayStats": a_stats,
            "isPrimeSignal": is_prime,
            "signalTier": signal_tier,
        }
        all_matches.append(match_obj)

        if ev_id not in history_map and hours_to_ko > 0:
            rec = {
                "id": ev_id,
                "leagueSlug": lg["slug"],
                "leagueCode": lg["code"],
                "leagueName": lg["name"],
                "leagueGroup": lg["group"],
                "homeId": hid,
                "awayId": aid,
                "home": match_obj["home"],
                "away": match_obj["away"],
                "kickoffUTC": ev["date"],
                "kickoffMMT": match_obj["kickoffMMT"],
                "modelMode": mode,
                "stability": stability,
                "expHome": exp_h,
                "expAway": exp_a,
                "totalLambda": total_lam,
                "targetLine": target["line"],
                "overProb": target["overProb"],
                "fairOdds": target["fairOdds"],
                "minValueOdds": target["minValueOdds"],
                "isPrimeSignal": is_prime,
                "status": "PENDING",
                "actualHomeCorners": None,
                "actualAwayCorners": None,
                "actualTotal": None,
                "grade": None,
                "absError": None,
                "biasError": None,
            }
            history_records.append(rec)
            history_map[ev_id] = rec

        if is_prime and ev_id not in notified and (0 < hours_to_ko <= NOTI_WINDOW_HOURS):
            prime_alerts.append(match_obj)
            notified.add(ev_id)

    all_matches.sort(key=lambda x: x["kickoffUTC"])

    history_summary = build_history_summary(history_records)
    history_records.sort(key=lambda x: x.get("kickoffUTC", ""), reverse=True)

    output = {
        "updatedAtUTC": now_utc.isoformat(),
        "updatedAtMMT": now_utc.astimezone(MMT).strftime("%d %b %Y, %I:%M %p"),
        "leagueCount": len(LEAGUES),
        "matchCount": len(all_matches),
        "filteredLowDataCount": filtered_low_data,
        "matches": all_matches,
    }

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump({
            "updatedAtMMT": output["updatedAtMMT"],
            "summary": history_summary,
            "records": history_records[:400],
        }, f, ensure_ascii=False, indent=2)

    if len(cache) > 2500:
        cache = dict(list(cache.items())[-2500:])
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)

    with open(notified_path, "w", encoding="utf-8") as f:
        json.dump(list(notified)[-500:], f)

    send_push_alerts(prime_alerts)
    print(f"Javis v3.0 Scan: verified={len(all_matches)}, filtered_low_data={filtered_low_data}, graded={history_summary['totalGraded']}, alerts={len(prime_alerts)}")


if __name__ == "__main__":
    main()
