import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import requests

# ==========================================
# 1. TARGET 10 LEAGUES (100% Free Public Feed)
# ==========================================
LEAGUES = [
    {"slug": "eng.1", "code": "EPL", "name": "Premier League", "group": "top5"},
    {"slug": "esp.1", "code": "LAL", "name": "La Liga", "group": "top5"},
    {"slug": "ita.1", "code": "SER", "name": "Serie A", "group": "top5"},
    {"slug": "ger.1", "code": "BUN", "name": "Bundesliga", "group": "top5"},
    {"slug": "fra.1", "code": "LG1", "name": "Ligue 1", "group": "top5"},
    {"slug": "usa.1", "code": "MLS", "name": "USA MLS", "group": "high5"},
    {"slug": "eng.2", "code": "CHP", "name": "England Championship", "group": "high5"},
    {"slug": "aus.1", "code": "ALE", "name": "A-League", "group": "high5"},
    {"slug": "bra.2", "code": "BRB", "name": "Brazil Serie B", "group": "high5"},
    {"slug": "ned.1", "code": "ERE", "name": "Eredivisie", "group": "high5"},
]

MMT = timezone(timedelta(hours=6, minutes=30))
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "JavisCornerTerminal/1.0"})

# Alert Thresholds (ပြင်ချင်ပါက ဤနေရာတွင် ပြောင်းနိုင်သည်)
ALERT_MIN_LAMBDA = float(os.getenv("ALERT_MIN_LAMBDA", "10.8"))
MIN_EDGE_TARGET = 0.04  # 4% Minimum Edge


# ==========================================
# 2. PURE CORNER MODEL (Full + Lite Fallback)
# ==========================================
class PureCornerModel:
    def __init__(self, use_home_adv=True):
        # Full Model Weights
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
        # Calibrated Lite Fallback (when advanced stats unavailable)
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
# 3. DATA FETCHER (ESPN Public Soccer API)
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


def extract_boxscore_stats(slug, event_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}"
    data = fetch_json(url)
    if not data:
        return None

    teams_box = data.get("boxscore", {}).get("teams", [])
    if len(teams_box) != 2:
        return None

    parsed = {}
    for entry in teams_box:
        tid = str(entry.get("team", {}).get("id", ""))
        stats_map = {}
        for st in entry.get("statistics", []):
            name = (st.get("name") or "").lower()
            stats_map[name] = safe_float(st.get("displayValue"))

        corners = stats_map.get("woncorners")
        if corners is None:
            return None  # Corner stat မပါသောပွဲ ကျော်မည်

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


def build_team_averages(slug, target_team_ids, cache):
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=38)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={start}-{end}"
    board = fetch_json(url)
    if not board:
        return {}

    team_event_ids = {tid: [] for tid in target_team_ids}
    for ev in reversed(board.get("events", [])):
        comp = (ev.get("competitions") or [{}])[0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        ev_id = str(ev.get("id"))
        for c in comp.get("competitors", []):
            tid = str(c.get("team", {}).get("id", ""))
            if tid in team_event_ids and len(team_event_ids[tid]) < 5:
                team_event_ids[tid].append(ev_id)

    needed_events = set()
    for ev_list in team_event_ids.values():
        for eid in ev_list:
            if eid not in cache:
                needed_events.add(eid)

    if needed_events:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(extract_boxscore_stats, slug, eid): eid for eid in needed_events}
            for fut in as_completed(futs):
                eid = futs[fut]
                res = fut.result()
                if res:
                    cache[eid] = res

    averages = {}
    for tid, ev_list in team_event_ids.items():
        rows = [cache[eid][tid] for eid in ev_list if eid in cache and tid in cache[eid]]
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

    for m in hot_matches:
        title = f"JAVIS +EV RADAR | {m['leagueCode']} (λ {m['totalLambda']})"
        body = (
            f"{m['home']} vs {m['away']}\n"
            f"Kickoff (MMT): {m['kickoffMMT']}\n"
            f"Exp Corners: {m['expHome']} - {m['expAway']} (Total λ: {m['totalLambda']})\n"
            f"Target: Over {m['target']['line']} ({m['target']['overProb']}%)\n"
            f"Min Odds for +EV: >= {m['target']['minValueOdds']}\n"
            f"Stake: 1% - 2% Flat"
        )

        # 1) Send via ntfy (Zero-config Android Push Noti)
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

        # 2) Send via Telegram Bot (Optional)
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
def main():
    os.makedirs("data", exist_ok=True)
    cache_path = "data/event_cache.json"
    notified_path = "data/notified.json"

    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    notified = set(json.load(open(notified_path))) if os.path.exists(notified_path) else set()

    model = PureCornerModel(use_home_adv=True)
    now_utc = datetime.now(timezone.utc)
    date_range = f"{now_utc.strftime('%Y%m%d')}-{(now_utc + timedelta(days=2)).strftime('%Y%m%d')}"

    all_matches = []
    hot_alerts = []

    for lg in LEAGUES:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg['slug']}/scoreboard?dates={date_range}"
        board = fetch_json(url)
        if not board:
            continue

        upcoming = []
        team_ids = set()
        for ev in board.get("events", []):
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
            team_ids.update([hid, aid])
            upcoming.append((ev, home_c, away_c, hid, aid))

        if not upcoming:
            continue

        team_avgs = build_team_averages(lg["slug"], team_ids, cache)

        for ev, home_c, away_c, hid, aid in upcoming:
            ev_id = str(ev["id"])
            h_stats = team_avgs.get(hid, {"avg_corners": 5.0, "shots_on_target": 4.2, "corners_conceded": 5.0, "sample_size": 0})
            a_stats = team_avgs.get(aid, {"avg_corners": 5.0, "shots_on_target": 4.2, "corners_conceded": 5.0, "sample_size": 0})

            exp_h, exp_a, total_lam, mode = model.get_expected_corners(h_stats, a_stats)
            target = model.suggest_target_line(total_lam)

            dt_utc = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            dt_mmt = dt_utc.astimezone(MMT)
            is_hot = total_lam >= ALERT_MIN_LAMBDA and h_stats.get("sample_size", 0) >= 2 and a_stats.get("sample_size", 0) >= 2

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

    # Sort highest expected corners first
    all_matches.sort(key=lambda x: x["totalLambda"], reverse=True)

    output = {
        "updatedAtUTC": now_utc.isoformat(),
        "updatedAtMMT": now_utc.astimezone(MMT).strftime("%d %b %Y, %I:%M %p"),
        "matchCount": len(all_matches),
        "matches": all_matches,
    }

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Keep cache compact (last 600 events)
    if len(cache) > 600:
        cache = dict(list(cache.items())[-600:])
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)

    with open(notified_path, "w", encoding="utf-8") as f:
        json.dump(list(notified)[-300:], f)

    send_push_alerts(hot_alerts)
    print(f"Javis Scan Complete: {len(all_matches)} matches, {len(hot_alerts)} new alerts sent.")


if __name__ == "__main__":
    main()
