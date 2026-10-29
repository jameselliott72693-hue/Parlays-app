#!/usr/bin/env python3
"""
Grade every slip in ledger/slips.jsonl from final results (ESPN public JSON, keyless; no Odds API credits),
write ledger/grades.json, and regenerate the Parlay Tracker Page source (ledger/page_contents.tsx.txt).

Sports: NFL, NBA, NHL, NCAAF, NCAAB (ESPN keys in ESPN, stat families in FAMILY). Unknown stats stay ungraded, never a false miss.
Leg results: win / loss / push / void (confirmed DNP) / pending (game not final) / ungraded (stat not found; reason given).
Slip results: miss if any leg lost; else pending if any leg pending; else ungraded if any leg ungraded;
else hit (all non-void/push legs won; payout recomputed without void/push legs); void if every leg void/push.
Profit: 1 unit per unique slip at the displayed odds (hit: adjusted decimal - 1, miss: -1, void: 0).
Manual overrides: ledger/leg_overrides.json (see README) can force a leg to void / push / win / loss, e.g. a player confirmed
inactive but missing from the box score. Matching is by player (or label) + game + date; slips.jsonl is never edited.
Strategy: ledger rows carry "strategy" (v2 from 2026-10-23, v3 from 2026-10-29); rows without it are v1. The Page splits them.
Flagged-price slips ("v2-flagged", "v3-flagged": any strategy ending in "-flagged") are tracked apart from every regular total.
Closing prices (free, no Odds API credits): for moneyline / spread / total legs on final games, the DraftKings line ESPN
shows in the game summary ("pickcenter", effectively the closing line) is stored on the leg grade as `close`, with
`clv_pp` = implied(close) - implied(price taken), in percentage points (positive = beat the close). Same line only for
spreads/totals. Player props have no free closing source, so they get no close.
"""
import json, os, re, sys, time, unicodedata, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ledger_lib import load_ledger, ROOT

ESPN = {"nba": "basketball/nba", "nfl": "football/nfl", "nhl": "hockey/nhl",
        "ncaaf": "football/college-football", "ncaab": "basketball/mens-college-basketball"}
# stat families: how a sport's ESPN box score is read (basketball: NBA + college; football: NFL + college; hockey: NHL)
FAMILY = {"nba": "basketball", "ncaab": "basketball", "nfl": "football", "ncaaf": "football", "nhl": "hockey"}
COLLEGE = {"ncaaf", "ncaab"}
# scoreboard query extras (college scoreboards default to a featured subset; ask for all FBS / all Division I games)
SB_EXTRA = {"ncaaf": "&groups=80&limit=300", "ncaab": "&groups=50&limit=400"}
SPORT_LABEL = {"nba": "NBA", "nfl": "NFL", "nhl": "NHL", "ncaaf": "NCAAF", "ncaab": "NCAAB", "mlb": "MLB"}
CACHE = os.path.join(ROOT, "ledger", "espn_cache")
GRADES = os.path.join(ROOT, "ledger", "grades.json")
USER = os.path.join(ROOT, "ledger", "user_results.jsonl")
TEMPLATE = os.path.join(ROOT, "ledger", "page_template.tsx.txt")
PAGE_OUT = os.path.join(ROOT, "ledger", "page_contents.tsx.txt")
UA = {"User-Agent": "Mozilla/5.0"}
LOOKAHEAD_DAYS = 21
OVERRIDES = os.path.join(ROOT, "ledger", "leg_overrides.json")
os.makedirs(CACHE, exist_ok=True)

def get(url, cache_name=None, final_only=True):
    p = os.path.join(CACHE, cache_name) if cache_name else None
    if p and os.path.exists(p): return json.load(open(p))
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                d = json.loads(r.read()); break
        except Exception:
            if i == 2: raise
            time.sleep(1.5)
    return d

def nname(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'`-]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()

_sb = {}
def scoreboard(sport, day):
    k = (sport, day)
    if k not in _sb:
        cp = os.path.join(CACHE, f"sb_{sport}_{day}.json")
        try:
            if os.path.exists(cp): _sb[k] = json.load(open(cp))
            else:
                _sb[k] = get(f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/scoreboard?dates={day}{SB_EXTRA.get(sport, '')}").get("events", [])
                # cache a past day once every game on it is final
                if day < datetime.now(timezone.utc).strftime("%Y%m%d") and all(e["status"]["type"].get("completed") for e in _sb[k]):
                    json.dump(_sb[k], open(cp, "w"))
        except Exception as ex: _sb[k] = []; print(f"[warn] scoreboard {sport} {day}: {ex}", file=sys.stderr)
    return _sb[k]

def team_match(espn_comp, our_team, sport=None):
    t = espn_comp["team"]
    o = nname(our_team)
    if o == nname(t.get("displayName", "~~")): return True
    if sport in COLLEGE:
        # college mascots repeat (Bulldogs, Tigers ...): require the school name too, never the mascot alone
        locs = {nname(t.get("location", "~~")), nname(t.get("shortDisplayName", "~~"))}
        return o.endswith(nname(t.get("name", "~~"))) and any(l and o.startswith(l) for l in locs)
    return o.endswith(nname(t.get("name", "~~")))

def find_event(leg, run_ts):
    """Earliest ESPN game after the run with both teams; tries nba then nfl if sport unknown."""
    start = datetime.fromisoformat(run_ts)
    sports = [leg["sport"]] if leg.get("sport") in ESPN else ["nba", "nfl"]
    for sp in sports:
        for d in range(0, LOOKAHEAD_DAYS + 1):
            day = (start + timedelta(days=d)).strftime("%Y%m%d")
            for e in scoreboard(sp, day):
                comps = e["competitions"][0]["competitors"]
                if datetime.fromisoformat(e["date"].replace("Z", "+00:00")) < start - timedelta(hours=1): continue
                home = next(c for c in comps if c["homeAway"] == "home"); away = next(c for c in comps if c["homeAway"] == "away")
                if team_match(home, leg["home"], sp) and team_match(away, leg["away"], sp):
                    return sp, e
    return None, None

_sum = {}
def summary(sport, eid, final):
    k = (sport, eid)
    if k not in _sum:
        name = f"{sport}_{eid}.json"
        p = os.path.join(CACHE, name)
        if os.path.exists(p): _sum[k] = json.load(open(p))
        else:
            d = get(f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/summary?event={eid}")
            if final: json.dump(d, open(p, "w"))
            _sum[k] = d
    return _sum[k]

def box_players(sport, summ):
    """name -> {'dnp': bool, 'stats': {canonical: value}}. Only stats ESPN actually shows are filled; anything else stays
    missing so the leg falls to "ungraded" (never a false miss)."""
    out = {}
    fam = FAMILY.get(sport)
    def num(vals, k):
        try: return float(vals[k])
        except Exception: return None
    for team in summ.get("boxscore", {}).get("players", []):
        for cat in team.get("statistics", []):
            keys = cat.get("keys", [])
            for a in cat.get("athletes", []):
                nm = nname(a["athlete"]["displayName"])
                rec = out.setdefault(nm, {"dnp": False, "stats": {}, "display": a["athlete"]["displayName"]})
                if a.get("didNotPlay") or not a.get("stats"):
                    if fam == "basketball": rec["dnp"] = True
                    continue
                vals = dict(zip(keys, a["stats"]))
                st = rec["stats"]
                if fam == "basketball":
                    st["points"], st["rebounds"], st["assists"] = num(vals, "points"), num(vals, "rebounds"), num(vals, "assists")
                    st["steals"], st["blocks"] = num(vals, "steals"), num(vals, "blocks")
                    tp = vals.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "")
                    st["three_points_made"] = float(tp.split("-")[0]) if "-" in tp else None
                elif fam == "hockey":
                    cn = cat.get("name")
                    if cn == "goalies":
                        st["saves"], st["goals_against"] = num(vals, "saves"), num(vals, "goalsAgainst")
                    else:  # forwards / defenses (and any future skater group)
                        g, ast = num(vals, "goals"), num(vals, "assists")
                        st["goals"], st["assists"], st["shots"] = g, ast, num(vals, "shotsTotal")
                        st["blocked_shots"] = num(vals, "blockedShots")
                        st["points"] = None if g is None or ast is None else g + ast
                    rec["played"] = True
                elif fam == "football":
                    cn = cat.get("name")
                    if cn == "passing": st["passing_yds"], st["passing_tds"] = num(vals, "passingYards"), num(vals, "passingTouchdowns")
                    if cn == "rushing": st["rushing_yds"] = num(vals, "rushingYards"); st["rushing_tds"] = num(vals, "rushingTouchdowns")
                    if cn == "receiving": st["receiving_yds"], st["receiving_rec"] = num(vals, "receivingYards"), num(vals, "receptions")
                    rec["played"] = True
    return out

def stat_value(sport, rec, stat):
    s = rec["stats"]
    combos = {"pts_rebs_asts": ["points", "rebounds", "assists"], "pts_rebs": ["points", "rebounds"],
              "pts_asts": ["points", "assists"], "rebs_asts": ["rebounds", "assists"]}
    if stat in combos:
        v = [s.get(k) for k in combos[stat]]
        return None if None in v else sum(v)
    if FAMILY.get(sport) == "football":
        if stat == "rush_rec_yds":
            if "rushing_yds" not in s and "receiving_yds" not in s: return None
            return (s.get("rushing_yds") or 0) + (s.get("receiving_yds") or 0)
        if stat in ("receiving_yds", "receiving_rec") and stat not in s and rec.get("played"):
            return None  # appeared in box but not in receiving table: 0 catches OR not targeted - can't tell inactive vs 0 safely
    return s.get(stat)

def imp(a): return 100 / (a + 100) if a > 0 else -a / (-a + 100)

def closing_price(leg, sp, ev):
    """DraftKings line from ESPN's pickcenter for a final game (one cached summary fetch per game; keyless)."""
    try:
        pcs = summary(sp, ev["id"], True).get("pickcenter") or []
    except Exception:
        return None
    pc = next((p for p in pcs if p.get("homeTeamOdds") or p.get("overUnder") is not None), None)
    if not pc: return None
    prov = (pc.get("provider") or {}).get("name", "ESPN")
    m = leg["market"]
    try:
        if m == "total":
            line, am = pc.get("overUnder"), pc.get("overOdds" if leg["side"] == "over" else "underOdds")
        else:
            mine = "home" if leg["team"] == leg["home"] else "away"
            to = pc.get(f"{mine}TeamOdds") or {}
            if m == "ml": line, am = None, to.get("moneyLine")
            else:
                hs = pc.get("spread")
                line = None if hs is None else (hs if mine == "home" else -hs)
                am = to.get("spreadOdds")
        if am is None: return None
        am = int(am)
        out = {"provider": prov, "american": am, "line": line}
        if m == "ml" or (line is not None and leg.get("line") is not None and abs(float(line) - float(leg["line"])) < 1e-9):
            out["clv_pp"] = round(100 * (imp(am) - imp(leg["american"])), 2)
        return out
    except Exception:
        return None

def in_shootout(status):
    """True when an NHL game was decided in a shootout (ESPN detail like "Final/SO")."""
    t = str(status.get("shortDetail") or status.get("detail") or "")
    return bool(re.search(r"/\s*SO\b", t)) or "shootout" in t.lower()

def cmp_result(val, line, side):
    if val == line: return "push"
    return "win" if (val > line) == (side == "over") else "loss"

def grade_leg(leg, run_ts):
    sp, ev = find_event(leg, run_ts)
    if not ev:
        if datetime.now(timezone.utc) - datetime.fromisoformat(run_ts) < timedelta(days=LOOKAHEAD_DAYS):
            return {"result": "pending", "reason": "game not yet on ESPN scoreboard"}
        return {"result": "ungraded", "reason": f"game not found on ESPN scoreboard within {LOOKAHEAD_DAYS} days of the run"}
    status = ev["status"]["type"]
    base = {"espn_event": ev["id"], "sport": sp, "commence": ev["date"]}
    if status.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED"):
        return dict(base, result="void", reason=status.get("name"))
    if not status.get("completed"):
        return dict(base, result="pending", reason=status.get("description", "not final"))
    comps = ev["competitions"][0]["competitors"]
    score = {}
    for c in comps:
        score["home" if c["homeAway"] == "home" else "away"] = float(c["score"])
    m = leg["market"]
    if m in ("ml", "spread", "total"):
        cl = closing_price(leg, sp, ev)
        if cl: base["close"] = cl
    if m == "total":
        tot = score["home"] + score["away"]
        if FAMILY.get(sp) == "hockey" and in_shootout(status):
            tot -= 1  # NHL shootout: ESPN adds 1 goal to the winner's score, sportsbook totals exclude it
        return dict(base, result=cmp_result(tot, leg["line"], leg["side"]), actual=f"total {tot:g}")
    if m in ("ml", "spread"):
        mine = "home" if leg["team"] == leg["home"] else "away"
        other = "away" if mine == "home" else "home"
        margin = score[mine] - score[other] + (leg["line"] or 0 if m == "spread" else 0)
        res = "push" if margin == 0 else "win" if margin > 0 else "loss"
        return dict(base, result=res, actual=f"{leg['away']} {score['away']:g} - {score['home']:g} {leg['home']}")
    if m == "prop":
        if (leg.get("stat") or "").startswith("unknown"):
            return dict(base, result="ungraded", reason=f"unsupported stat {leg['stat']}")
        players = box_players(sp, summary(sp, ev["id"], True))
        rec = players.get(nname(leg["player"]))
        if rec is None:
            # fallback: unique last-name + first-initial match
            p = nname(leg["player"]).split()
            cands = [r for k, r in players.items() if k.split() and k.split()[-1] == p[-1] and k[0] == p[0][0]]
            rec = cands[0] if len(cands) == 1 else None
        if rec is None:
            return dict(base, result="ungraded", reason="player not in ESPN box score (inactive => would be void; not assumed)")
        if rec["dnp"] and not rec["stats"]:
            return dict(base, result="void", reason="did not play (DNP)")
        val = stat_value(sp, rec, leg["stat"])
        if val is None:
            return dict(base, result="ungraded", reason=f"stat {leg['stat']} not found for {rec['display']}")
        return dict(base, result=cmp_result(val, leg["line"], leg["side"]), actual=f"{val:g}")
    return dict(base, result="ungraded", reason="unrecognized market")

def load_overrides():
    """ledger/leg_overrides.json: {"overrides": [{"player" or "label", "event" (optional, "Away @ Home"), "date" (YYYY-MM-DD, ET game date),
    "stat"/"side"/"line" (optional extra filters), "result": void|push|win|loss, "reason", "note"}]}"""
    if not os.path.exists(OVERRIDES): return []
    return json.load(open(OVERRIDES)).get("overrides", [])

def override_for(leg, g, ovs):
    """First override matching this leg, or None. A date needs the game's start time (ESPN, falling back to the ledger leg)."""
    commence = g.get("commence") or leg.get("commence")
    day = None
    if commence:
        from zoneinfo import ZoneInfo
        day = datetime.fromisoformat(commence.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    for o in ovs:
        if o.get("player") and nname(o["player"]) != nname(leg.get("player") or ""): continue
        if o.get("label") and o["label"].strip().lower() != leg["label"].strip().lower(): continue
        if not o.get("player") and not o.get("label"): continue
        if o.get("event") and o["event"].strip().lower() != (leg.get("event") or "").strip().lower(): continue
        if o.get("date") and o["date"] != day: continue
        if o.get("market") and o["market"] != leg.get("market"): continue
        if o.get("stat") and o["stat"] != leg.get("stat"): continue
        if o.get("side") and o["side"] != leg.get("side"): continue
        if o.get("line") is not None and o["line"] != leg.get("line"): continue
        return o
    return None

def apply_override(leg, g, ovs):
    o = override_for(leg, g, ovs)
    if not o: return g
    if o["result"] not in ("void", "push", "win", "loss"): raise ValueError(f"bad override result {o['result']!r}")
    out = dict(g, result=o["result"], reason=o.get("reason") or "manual override", override=True)
    if o.get("note"): out["note"] = o["note"]
    if g["result"] not in ("ungraded", "pending"): out["auto_result"] = g["result"]
    return out

def am_to_dec(a): return 1 + (a / 100 if a > 0 else 100 / -a)
def dec_to_am(d): return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))

def grade_slip(slip, leg_grades):
    rs = [g["result"] for g in leg_grades]
    if "loss" in rs: res = "miss"
    elif "pending" in rs: res = "pending"
    elif "ungraded" in rs: res = "ungraded"
    elif all(r in ("void", "push") for r in rs): res = "void"
    else: res = "hit"
    dec = slip["decimal"]
    for l, g in zip(slip["legs"], leg_grades):
        if g["result"] in ("void", "push"): dec /= am_to_dec(l["american"])
    profit = {"hit": dec - 1, "miss": -1.0, "void": 0.0}.get(res)
    return res, dec, profit

BOOKN = {"fanduel": "FanDuel", "draftkings": "DraftKings", "betmgm": "BetMGM", "espnbet": "theScore Bet", "underdog": "Underdog", "williamhill_us": "Caesars"}

def main():
    slips = load_ledger()
    ovs = load_overrides()
    graded = []
    n_ov = 0
    for s in slips:
        lg = []
        for l in s["legs"]:
            try: g = grade_leg(l, s["run_ts"])
            except Exception as ex: g = {"result": "ungraded", "reason": f"fetch error: {ex}"}
            g2 = apply_override(l, g, ovs)
            if g2 is not g:
                n_ov += 1
                if g.get("result") not in ("ungraded", "pending"):
                    print(f"  WARNING override replaces a decided result ({g['result']}) on {s['run_ts'][:16]} {l['label']}")
            lg.append(g2)
        res, dec, profit = grade_slip(s, lg)
        graded.append({"slip_id": s["slip_id"], "run_ts": s["run_ts"], "result": res, "settled_decimal": round(dec, 4),
                       "profit": None if profit is None else round(profit, 4), "legs": lg})
    json.dump({"graded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "slips": graded}, open(GRADES, "w"), indent=1)
    data = build_page_data(slips, graded)
    tpl = open(TEMPLATE).read()
    open(PAGE_OUT, "w").write(tpl.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":"))))
    t = data["overall"]
    print(f"graded {len(graded)} slips (regular totals below exclude *-flagged): {t['hit']} hit / {t['miss']} miss / {t['pending']} pending / {t['other']} void+ungraded; "
          f"profit {t['profit']:+.2f}u")
    for g, s in zip(graded, slips):
        for l, lg in zip(s["legs"], g["legs"]):
            if lg["result"] == "ungraded": print(f"  UNGRADED {s['run_ts'][:16]} {l['label']} ({l['event']}): {lg['reason']}")
    if ovs: print(f"manual overrides: {len(ovs)} rule(s) loaded, applied to {n_ov} leg instance(s)")
    fl = data["flagged"]
    print(f"flagged-price slips (*-flagged, tracked apart): {fl['n']} logged, {fl['hit']} hit / {fl['miss']} miss / {fl['pending']} pending, profit {fl['profit']:+.2f}u")
    print(f"page source -> {PAGE_OUT}")

def tally(items):
    t = {"n": 0, "hit": 0, "miss": 0, "pending": 0, "other": 0, "profit": 0.0, "staked": 0}
    for s, g in items:
        t["n"] += 1
        r = g["result"]
        if r in ("hit", "miss", "pending"): t[r] += 1
        else: t["other"] += 1
        if g["profit"] is not None and r in ("hit", "miss"):
            t["profit"] += g["profit"]; t["staked"] += 1
    t["profit"] = round(t["profit"], 2)
    return t

RECENT_ON_PAGE = 50
def short_game(l):
    nick = lambda t: (t or "").split()[-1] if t else "?"
    return f"{nick(l.get('away'))} @ {nick(l.get('home'))}"

FLAG = "v2-flagged"  # historical tag; is_flag() accepts any "*-flagged" strategy (v3-flagged since 2026-10-29)
def is_flag(s): return str(s.get("strategy", "v1")).endswith("-flagged")
LIST_LABEL = {"sgp": "SGP", "multi": "Multi-game", "3leg": "3-leg"}

def shop_summary(pairs):
    """v3 price shopping: how often another book paid more for the same legs, and the average gain in decimal odds."""
    rows = [s for s, _ in pairs if s.get("best_book")]
    if not rows: return None
    better = [s for s in rows if s["best_book"] not in s["books"]]
    gain = [am_to_dec(s["best_american"]) / s["decimal"] - 1 for s in better if s.get("best_american")]
    return {"n": len(rows), "better": len(better), "avg_gain_pct": round(100 * sum(gain) / len(gain), 1) if gain else 0.0}

def build_page_data(slips, graded):
    allpairs = list(zip(slips, graded))
    # Flagged-price slips (strategy v2-flagged) are tracked apart: every regular total/table below uses `pairs` only, and the
    # flagged slips get their own tally, breakdown rows, run rows and record facts (shown in red on the Page).
    pairs = [(s, g) for s, g in allpairs if not is_flag(s)]
    fpairs = [(s, g) for s, g in allpairs if is_flag(s)]
    def bookgrp(s): return BOOKN.get(s["books"][0], s["books"][0]) if len(s["books"]) == 1 else "Mixed books"
    def strat(s): return s.get("strategy", "v1")
    def propgrp(s):
        u = sum(1 for l in s["legs"] if l.get("market") == "prop" and l.get("side") == "under")
        o = sum(1 for l in s["legs"] if l.get("market") == "prop" and l.get("side") == "over")
        return "No props" if u + o == 0 else "Unders only" if o == 0 else "Overs only" if u == 0 else "Over + under"
    groups = {
        "strategy": lambda s: [strat(s)],
        "props": lambda s: [propgrp(s)],
        "list": lambda s: [LIST_LABEL.get(s["list"], s["list"])],
        "report": lambda s: sorted({"Best price" if a["report"] == "best_price" else "Single-book" for a in s["appearances"]}),
    }
    breakdown = {}
    for gname, fn in groups.items():
        b = defaultdict(list)
        for s, g in pairs:
            for k in fn(s): b[k].append((s, g))
        breakdown[gname] = [{"k": k, **tally(v)} for k, v in sorted(b.items())]
    fbreakdown = {}
    for gname, fn in groups.items():
        b = defaultdict(list)
        for s, g in fpairs:
            for k in fn(s): b[k].append((s, g))
        fbreakdown[gname] = [{"k": k, **tally(v)} for k, v in sorted(b.items())]
    runs = defaultdict(list)
    for s, g in pairs: runs[s["run_ts"]].append((s, g))
    by_run = [{"run": k[:16].replace("T", " ") + f" ({strat(v[0][0])})", **tally(v)} for k, v in sorted(runs.items())]
    fruns = defaultdict(list)
    for s, g in fpairs: fruns[s["run_ts"]].append((s, g))
    by_run += [{"run": k[:16].replace("T", " ") + f" ({strat(v[0][0])})", "flagged": True, **tally(v)} for k, v in sorted(fruns.items())]
    by_run.sort(key=lambda r: r["run"][:16])
    # closing-line value: unique game-line legs per run with an ESPN closing price on the same line
    clv, clv_mkt = defaultdict(dict), defaultdict(lambda: defaultdict(dict))
    for s, g in allpairs:
        for l, lg in zip(s["legs"], g["legs"]):
            c = lg.get("close") or {}
            if "clv_pp" in c:
                key = (s["run_ts"], l["label"], l["event"], l["book"], l["american"])
                clv[strat(s)][key] = c["clv_pp"]
                clv_mkt[strat(s)][l.get("market") or "?"][key] = c["clv_pp"]
    def _avg(v): return round(sum(v) / len(v), 2) if v else None
    # compact per-strategy CLV summary: legs with a same-line close, average CLV (pp), % of legs that beat the close, and the
    # average split by market (ML / spread / total) as [n, avg]
    clv_rows = [{"k": k, "n": len(v), "avg": _avg(list(v.values())),
                 "beat": round(100 * sum(1 for x in v.values() if x > 0) / len(v), 1),
                 "mkt": {m: [len(clv_mkt[k][m]), _avg(list(clv_mkt[k][m].values()))] for m in ("ml", "spread", "total") if clv_mkt[k].get(m)}}
                for k, v in sorted(clv.items()) if v]
    # (the per-slip / per-leg "Recent slips" listing was removed from the Page on 2026-10-23; full history stays in the ledger)
    user = [json.loads(x) for x in open(USER)] if os.path.exists(USER) else []
    # compact per-slip facts for the Page's record tables (filtered client-side by strategy and list)
    facts, ffacts = [], []
    for s, g in allpairs:
        sps = set()
        for l, lg in zip(s["legs"], g["legs"]):
            sps.add((lg.get("sport") or l.get("sport") or "?").upper())
        sport = "Unknown" if "?" in sps else next(iter(sps)) if len(sps) == 1 else "Mixed (" + " + ".join(sorted(sps)) + ")"
        (ffacts if strat(s) == FLAG else facts).append({"s": strat(s), "l": s["list"], "b": bookgrp(s), "t": s["first_seen"]["target"], "sp": sport,
                      "r": g["result"], "p": g["profit"], "d": s["decimal"]})
    # user's own results, expanded per bet when bets were logged; "Untagged" when no tag was given.
    # Shown next to (never merged into) the slip records on the Page.
    mk = lambda: {"w": 0, "l": 0, "p": 0, "net": None, "units": None, "dsum": 0.0, "dn": 0}
    ub = {"book": defaultdict(mk), "sport": defaultdict(mk), "odds": defaultdict(mk)}
    def add_u(tags, w, l, p, net, units, odds):
        for dim, key in tags.items():
            b = ub[dim][key or "Untagged"]
            b["w"] += w; b["l"] += l; b["p"] += p
            if net is not None: b["net"] = round((b["net"] or 0) + net, 2)
            if units is not None: b["units"] = round((b["units"] or 0) + units, 2)
            if odds is not None:
                b["dsum"] += 1 + (odds / 100 if odds > 0 else 100 / -odds); b["dn"] += 1
    for r in user:
        if r.get("bets"):
            for bt in r["bets"]:
                add_u({"book": bt.get("book"), "sport": bt.get("sport"), "odds": bt.get("bucket")},
                      int(bt["result"] == "W"), int(bt["result"] == "L"), int(bt["result"] == "P"), bt.get("net"), None, bt.get("odds"))
        else:
            add_u({"book": r.get("book"), "sport": r.get("sport"), "odds": r.get("bucket")},
                  r["wins"], r["losses"], r.get("pushes") or 0, r.get("net"), r.get("units"), r.get("odds"))
    user_break = {dim: [{"k": k, **v, "dsum": round(v["dsum"], 4)} for k, v in sorted(d.items(), key=lambda kv: (kv[0] == "Untagged", kv[0]))] for dim, d in ub.items()}
    return {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "overall": tally(pairs),
            "breakdown": breakdown, "fBreakdown": fbreakdown, "flagged": tally(fpairs), "fFacts": ffacts,
            "flagKeys": sorted({strat(s) for s, _ in fpairs}), "shop": shop_summary(pairs), "byRun": by_run, "user": user, "clv": clv_rows, "facts": facts, "userBreak": user_break,
            "lost": ["2026-10-19 22:26 single-book report (never saved; its best-price report was recovered)"]}

if __name__ == "__main__":
    main()
