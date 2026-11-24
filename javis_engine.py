import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import requests

# ==========================================
# 1. GLOBAL LEAGUES, UEFA & CUPS (45 Competitions)
# ==========================================
LEAGUES = [
    # UEFA & International Cups
    {"slug": "uefa.champions", "code": "UCL", "name": "Champions League", "group": "cups", "lookback": 75},
    {"slug": "uefa.europa", "code": "UEL", "name": "Europa League", "group": "cups", "lookback": 75},
    {"slug": "uefa.europa.conf", "code": "UECL", "name": "Conference League", "group": "cups", "lookback": 75},
    {"slug": "uefa.nations", "code": "UNL", "name": "UEFA Nations League", "group": "cups", "lookback": 120},
    {"slug": "fifa.world", "code": "WCP", "name": "FIFA World Cup", "group": "cups", "lookback": 120},
    {"slug": "fifa.worldq.uefa", "code": "WCQ-E", "name": "WC Qualifiers EU", "group": "cups", "lookback": 120},
    {"slug": "fifa.worldq.conmebol", "code": "WCQ-S", "name": "WC Qualifiers SA", "group": "cups", "lookback": 120},
    {"slug": "conmebol.libertadores", "code": "LIB", "name": "Copa Libertadores", "group": "cups", "lookback": 75},
    {"slug": "conmebol.sudamericana", "code": "SUD", "name": "Copa Sudamericana", "group": "cups", "lookback": 75},

    # Domestic Cups
    {"slug": "eng.fa", "code": "FAC", "name": "FA Cup", "group": "cups", "lookback": 60},
    {"slug": "eng.league_cup", "code": "EFL", "name": "Carabao Cup", "group": "cups", "lookback": 60},
    {"slug": "esp.copa_del_rey", "code": "CDR", "name": "Copa del Rey", "group": "cups", "lookback": 60},
    {"slug": "ger.dfb_pokal", "code": "DFB", "name": "DFB-Pokal", "group": "cups", "lookback": 60},
    {"slug": "ita.coppa_italia", "code": "CIT", "name": "Coppa Italia", "group": "cups", "lookback": 60},
    {"slug": "fra.coupe_de_france", "code": "CDF", "name": "Coupe de France", "group": "cups", "lookback": 60},

    # Top 5 European Leagues
    {"slug": "eng.1", "code": "EPL", "name": "Premier League", "group": "top5", "lookback": 45},
    {"slug": "esp.1", "code": "LAL", "name": "La Liga", "group": "top5", "lookback": 45},
    {"slug": "ita.1", "code": "SER", "name": "Serie A", "group": "top5", "lookback": 45},
    {"slug": "ger.1", "code": "BUN", "name": "Bundesliga", "group": "top5", "lookback": 45},
    {"slug": "fra.1", "code": "LG1", "name": "Ligue 1", "group": "top5", "lookback": 45},

    # High-Corner Priority 5
    {"slug": "usa.1", "code": "MLS", "name": "USA MLS", "group": "high5", "lookback": 45},
    {"slug": "eng.2", "code": "CHP", "name": "Championship", "group": "high5", "lookback": 45},
    {"slug": "aus.1", "code": "ALE", "name": "A-League", "group": "high5", "lookback": 45},
    {"slug": "bra.2", "code": "BRB", "name": "Brazil Serie B", "group": "high5", "lookback": 45},
    {"slug": "ned.1", "code": "ERE", "name": "Eredivisie", "group": "high5", "lookback": 45},

    # Extended Global Coverage
    {"slug": "eng.3", "code": "EFL1", "name": "England League One", "group": "global", "lookback": 45},
    {"slug": "por.1", "code": "POR", "name": "Primeira Liga", "group": "global", "lookback": 45},
    {"slug": "bel.1", "code": "BEL", "name": "Belgian Pro League", "group": "global", "lookback": 45},
    {"slug": "tur.1", "code": "TUR", "name": "Turkish Super Lig", "group": "global", "lookback": 45},
    {"slug": "sco.1", "code": "SCO", "name": "Scottish Premiership", "group": "global", "lookback": 45},
    {"slug": "bra.1", "code": "BRA", "name": "Brazil Serie A", "group": "global", "lookback": 45},
    {"slug": "arg.1", "code": "ARG", "name": "Argentina Liga", "group": "global", "lookback": 45},
    {"slug": "mex.1", "code": "LMX", "name": "Liga MX", "group": "global", "lookback": 45},
    {"slug": "ger.2", "code": "BL2", "name": "2. Bundesliga", "group": "global", "lookback": 45},
    {"slug": "esp.2", "code": "LL2", "name": "La Liga 2", "group": "global", "lookback": 45},
    {"slug": "ita.2", "code": "SRB", "name": "Serie B", "group": "global", "lookback": 45},
    {"slug": "fra.2", "code": "L2F", "name": "Ligue 2", "group": "global", "lookback": 45},
    {"slug": "aut.1", "code": "AUT", "name": "Austrian Bundesliga", "group": "global", "lookback": 45},
    {"slug": "sui.1", "code": "SUI", "name": "Swiss Super League", "group": "global", "lookback": 45},
    {"slug": "den.1", "code": "DEN", "name": "Danish Superliga", "group": "global", "lookback": 45},
    {"slug": "nor.1", "code": "NOR", "name": "Eliteserien", "group": "global", "lookback": 45},
    {"slug": "swe.1", "code": "SWE", "name": "Allsvenskan", "group": "global", "lookback": 45},
    {"slug": "gre.1", "code": "GRE", "name": "Greek Super League", "group": "global", "lookback": 45},
    {"slug": "jpn.1", "code": "JPN", "name": "J1 League", "group": "global", "lookback": 45},
    {"slug": "ksa.1", "code": "KSA", "name": "Saudi Pro League", "group": "global", "lookback": 45},
]

MMT = timezone(timedelta(hours=6, minutes=30))
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "JavisCornerTerminal/2.1"})

ALERT_MIN_LAMBDA = float(os.getenv("ALERT_MIN_LAMBDA", "10.8"))
MIN_EDGE_TARGET = 0.04
UPCOMING_DAYS = int(os.getenv("UPCOMING_DAYS", "7"))
MAX_SAMPLES_PER_TEAM = 5


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
# 3. PARALLEL GLOBAL DATA FETCHER
# ==========================================
def safe_float(val):
    try:
        if val is None or val == "" or val == "--":
            return None
        return float(str(val).replace("%", "").strip())
    except ValueError:
        return None


def fetch_json(url, timeout=12):
    try:
        r = SESSION.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def fetch_league_boards(lg, now_utc):
    slug = lg["slug"]
    up_range = f"{now_utc.strftime('%Y%m%d')}-{(now_utc + timedelta(days=UPCOMING_DAYS)).strftime('%Y%m%d')}"
    past_start = (now_utc - timedelta(days=lg.get("lookback", 45))).strftime("%Y%m%d")
    past_end = now_utc.strftime("%Y%m%d")

    up_board = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={up_range}")
    past_board = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={past_start}-{past_end}")
    return lg, up_board, past_board


def extract_boxscore_stats(slug, event_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}"
    data = fetch_json(url)
    if not data:
        return False

    teams_box = data.get("boxscore", {}).get("teams", [])
    if len(teams_box) != 2:
        return False

    parsed = {}
    for entry in teams_box:
        tid = str(entry.get("team", {}).get("id", ""))
        stats_map = {}
        for st in entry.get("statistics", []):
            name = (st.get("name") or "").lower()
            stats_map[name] = safe_float(st.get("displayValue"))

        corners = stats_map.get("woncorners")
        if corners is None:
            return False

        parsed[tid] = {
            "corners": corners,
            "shots_on_target": stats_map.get("shotsontarget") or 4.0,
            "total_shots": stats_map.get("totalshots") or 12.0,
            "blocked_shots": stats_map.get("blockedshots"),
            "crosses": stats_map.get("totalcrosses") or stats_map.get("accuratecrosses"),
            "touches_in_box": stats_map.get("touchesinoppbox") or stats_map.get("touchesinbox"),
            "clearances": stats_map.get("clearances"),
        }

    tids = list(parsed.keys())
    if len(tids) == 2:
        t0, t1 = tids[0], tids[1]
        parsed[t0]["corners_conceded"] = parsed[t1]["corners"]
        parsed[t1]["corners_conceded"] = parsed[t0]["corners"]
        parsed[t0]["shots_conceded"] = parsed[t1]["total_shots"]
        parsed[t1]["shots_conceded"] = parsed[t0]["total_shots"]
    return parsed


def compute_team_averages(team_ids, team_history_events, cache):
    averages = {}
    for tid in team_ids:
        ev_refs = sorted(team_history_events.get(tid, []), key=lambda x: x[0], reverse=True)
        rows = []
        seen_eids = set()
        for _, eid, _ in ev_refs:
            if eid in seen_eids:
                continue
            seen_eids.add(eid)
            entry = cache.get(eid)
            if isinstance(entry, dict) and tid in entry:
                rows.append(entry[tid])
            if len(rows) >= MAX_SAMPLES_PER_TEAM:
                break

        if not rows:
            averages[tid] = {
                "avg_corners": 5.0,
                "shots_on_target": 4.2,
                "total_shots": 12.0,
                "corners_conceded": 5.0,
                "shots_conceded": 12.0,
                "sample_size": 0,
            }
            continue

        def avg_key(k):
            vals = [r[k] for r in rows if r.get(k) is not None]
            return round(sum(vals) / len(vals), 2) if vals else None

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
        }
    return averages


# ==========================================
# 4. PUSH NOTIFICATIONS (ntfy + Telegram)
# ==========================================
def send_push_alerts(hot_matches):
    if not hot_matches:
        return

    ntfy_topic = os.getenv("NTFY_TOPIC", "").strip()
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    for m in hot_matches[:15]:
        title = f"JAVIS +EV RADAR | {m['leagueCode']} (λ {m['totalLambda']})"
        body = (
            f"{m['home']} vs {m['away']}\n"
            f"League: {m['leagueName']}\n"
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
                    headers={"Title": title, "Priority": "high", "Tags": "soccer,fire"},
                    timeout=10,
                )
            except Exception as e:
                print("ntfy error:", e)

        if tg_token and tg_chat:
            try:
                SESSION.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": tg_chat, "text": f"🔥 {title}\n\n{body}"},
                    timeout=10,
                )
            except Exception as e:
                print("Telegram error:", e)


# ==========================================
# 5. MAIN EXECUTION
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

    cache = load_json_safe(cache_path, {})
    notified = set(load_json_safe(notified_path, []))

    model = PureCornerModel(use_home_adv=True)
    now_utc = datetime.now(timezone.utc)

    upcoming_items = []
    seen_upcoming_ids = set()
    active_team_ids = set()
    team_history_events = {}

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(fetch_league_boards, lg, now_utc) for lg in LEAGUES]
        for fut in as_completed(futs):
            lg, up_board, past_board = fut.result()
            slug = lg["slug"]

            if up_board:
                for ev in up_board.get("events", []):
                    ev_id = str(ev.get("id", ""))
                    if not ev_id or ev_id in seen_upcoming_ids:
                        continue
                    comp = (ev.get("competitions") or [{}])[0]
                    state = comp.get("status", {}).get("type", {}).get("state", "")
                    if state == "post":
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
                    upcoming_items.append((lg, ev, home_c, away_c, hid, aid))

            if past_board:
                for ev in past_board.get("events", []):
                    comp = (ev.get("competitions") or [{}])[0]
                    if not comp.get("status", {}).get("type", {}).get("completed"):
                        continue
                    ev_id = str(ev.get("id", ""))
                    ev_date = ev.get("date", "")
                    for c in comp.get("competitors", []):
                        tid = str(c.get("team", {}).get("id", ""))
                        if tid:
                            team_history_events.setdefault(tid, []).append((ev_date, ev_id, slug))

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
        with ThreadPoolExecutor(max_workers=12) as ex:
            futs = {
                ex.submit(extract_boxscore_stats, slug, eid): eid
                for eid, slug in needed_boxscores.items()
            }
            for fut in as_completed(futs):
                eid = futs[fut]
                cache[eid] = fut.result()

    team_avgs = compute_team_averages(active_team_ids, team_history_events, cache)
    all_matches = []
    hot_alerts = []

    for lg, ev, home_c, away_c, hid, aid in upcoming_items:
        ev_id = str(ev["id"])
        h_stats = team_avgs[hid]
        a_stats = team_avgs[aid]

        if h_stats["sample_size"] == 0 and a_stats["sample_size"] == 0:
            continue

        exp_h, exp_a, total_lam, mode = model.get_expected_corners(h_stats, a_stats)
        target = model.suggest_target_line(total_lam)

        dt_utc = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        dt_mmt = dt_utc.astimezone(MMT)
        has_solid_data = h_stats["sample_size"] >= 2 and a_stats["sample_size"] >= 2
        is_hot = total_lam >= ALERT_MIN_LAMBDA and has_solid_data

        match_obj = {
            "id": ev_id,
            "leagueCode": lg["code"],
            "leagueName": lg["name"],
            "leagueGroup": lg["group"],
            "home": home_c["team"]["displayName"],
            "away": away_c["team"]["displayName"],
            "kickoffUTC": ev["date"],
            "kickoffMMT": dt_mmt.strftime("%d %b, %I:%M %p"),
            "modelMode": mode,
            "expHome": exp_h,
            "expAway": exp_a,
            "totalLambda": total_lam,
            "target": target,
            "homeStats": h_stats,
            "awayStats": a_stats,
            "isHotSignal": is_hot,
        }
        all_matches.append(match_obj)

        if is_hot and ev_id not in notified:
            hot_alerts.append(match_obj)
            notified.add(ev_id)

    all_matches.sort(key=lambda x: x["totalLambda"], reverse=True)

    output = {
        "updatedAtUTC": now_utc.isoformat(),
        "updatedAtMMT": now_utc.astimezone(MMT).strftime("%d %b %Y, %I:%M %p"),
        "leagueCount": len(LEAGUES),
        "matchCount": len(all_matches),
        "matches": all_matches,
    }

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    if len(cache) > 2500:
        cache = dict(list(cache.items())[-2500:])
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)

    with open(notified_path, "w", encoding="utf-8") as f:
        json.dump(list(notified)[-500:], f)

    send_push_alerts(hot_alerts)
    print(f"Javis Global Scan Complete: {len(all_matches)} matches across {len(LEAGUES)} competitions, {len(hot_alerts)} alerts.")


if __name__ == "__main__":
    main()
