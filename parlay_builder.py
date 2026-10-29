#!/usr/bin/env python3
"""
On-demand "favorable" parlay generator (prototype).

Data sources (auto-detected at run time):
  * fanduel   - keyless, public JSON used by sportsbook.fanduel.com (NJ host). Game lines + player props.
  * underdog  - keyless, public JSON used by Underdog Fantasy pick'em (api.underdogfantasy.com/v1).
                Pick'em prices are INDICATIVE (per-pick american_price derived from payout multipliers).
  * oddsapi   - The Odds API (the-odds-api.com). Only if ODDS_API_KEY is set. Adds DraftKings, BetMGM,
                Caesars (paid plans only), theScore Bet (key 'espnbet'), FanDuel (deduped against the direct feed).
Books that are NOT reachable keylessly from this box: DraftKings, Caesars, BetMGM, bet365 (403 / bot wall),
theScore Bet (GraphQL requires an authorized session), Chalkboard (no public API).

Method:
  1. Normalize every two-way market (moneyline, spread, total, player O/U) per book.
  2. Remove vig per book (multiplicative normalization), average across books -> consensus fair prob.
  3. Best available price per leg across books; edge = fair_prob * best_decimal - 1.
  4. Search combinations whose combined American odds land closest to each target and pick up to 3 slips per target.
  SGP prices are ESTIMATES: books apply correlation adjustments, so the real SGP price will differ.

Strategy v2 (default since 2026-10-23; `--legacy` reproduces v1):
  * leg eligibility, checked per (leg, book):
      - reject if the price is >= 5 pp of implied probability better than the median of the OTHER sportsbooks
        (Underdog excluded from that median) -> listed under "Check these prices", never used in slips;
      - >= 3 books behind the fair price (an Underdog pick'em leg needs >= 3 books other than Underdog);
      - >= 2 sportsbooks quoting the leg, i.e. at least one other sportsbook within 3 pp of the price used;
  * every slip is placeable at one book (SGP and multi-game); max 2 legs (the separate 3-leg list below is the one exception);
    each leg (outcome) in at most 2 slips per run;
  * slips ranked by fair hit probability (EV shown for information only), ties broken toward prop unders;
  * SGP listed first; multi-game +300/+400 hidden unless --show-long-multi;
  * slips must land within +-20% of the target's decimal odds (closest tier first: 6%, 12%, 20%); no identical slip at two targets;
  * if the rules leave fewer than 3 slips at a target, fewer are shown (rules are never relaxed).
  * 3-LEG PARLAYS (added 2026-10-27, user-requested exception to max-2-legs; `--no-3leg` hides it): a third list after the
    SGP and multi-game lists, same targets (+100..+400, up to 3 slips each, +300/+400 NOT hidden). Exactly 3 legs at ONE book: all
    in one game (SGP-3, price is an ESTIMATE) or one leg in each of 3 games (Multi-game-3). All other v2 rules apply (leg checks,
    +-20% of target odds, ranking by fair hit probability, each leg in <= 2 slips of this list, no identical slip at two targets,
    fewer slips rather than relaxing). Ledger: strategy v2, list "3leg" (tracked separately on the Page's list filter/breakdown).
    Flagged-price slips stay max 2 legs.
  * SPORTS (default nfl,nba,nhl,ncaaf,ncaab; mlb optional): out-of-season / no-game sports are skipped automatically (Odds API
    /sports "active" flag is free; empty FanDuel page; no Underdog lines) and shown as NO DATA in the report. College team names
    are rewritten to ESPN names so books join and the grader finds the game. NHL player props: Underdog (shots/points/assists/goals),
    Odds API (points, shots on goal), FanDuel "Total Goals" O/U (FanDuel's other NHL props are one-sided "2+" ladders, not usable).
  * FLAGGED-PRICE SLIPS (on by default; `--no-flagged` hides them): legs rejected as off-market (>= 5 pp better than the other
    sportsbooks' median) are NOT dropped from view. A separate "Flagged-price slips" section (after the regular lists) builds
    up to 3 slips per target (same targets as the regular lists) that each contain >= 1 flagged leg. Only the off-market
    rejection (and the "second sportsbook within 3 pp" confirmation, which a stale price can't meet by definition) is relaxed:
    max 2 legs, one book per slip, leg reuse <= 2 per section, >= 3 books behind the fair price (falls back to 2 only when the
    section would otherwise be short; such slips rank last and are labeled), other legs in the slip must pass every regular
    check. A flagged leg's fair probability EXCLUDES the flagged book's own price. Every flagged slip and leg is marked with a
    red circle and a warning; ledger strategy tag `v2-flagged`, tracked apart from regular v2.

Strategy v3 (default since 2026-10-29; `--v2-props` = v2 prop rules, tagged v2):
  * player-prop legs only when >= 4 books quote that exact line (Underdog counts once) AND the books' no-vig fair probabilities
    are within 4 pp of each other; game lines (ML / spread / total) unchanged. Fewer slips rather than relaxing.
  * price shopping: every displayed slip lists what each other book pays for the same legs (product of that book's leg prices
    when it offers all legs; SGP = estimate) and marks the best-paying book (never an off-market price). Logged as shop /
    best_book / best_american on the ledger row.
  * flagged-price slips are OFF by default (`--flagged` shows and logs them, tag v3-flagged); "Check these prices" stays.
  * Odds API credit savings: 15-minute disk cache of paid responses (reports/cache/oddsapi; `--no-cache`, `--cache-ttl-min`),
    a sport is skipped (0 credits) when the free /events list and FanDuel/Underdog show no game within 48 h
    (`--gameline-window-h`, 0 = never skip), NCAAF props off (they can never reach 4 books). Hard cap 40/run unchanged.
  * `execute(parse_args([...]))` runs the builder in-process and returns structured slips (used by the web app in app/).

Usage:
  python3 parlay_builder.py                       # live keyless data, NFL+NBA+NHL+NCAAF+NCAAB (mlb off by default)
  python3 parlay_builder.py --sports nfl,nba,nhl --max-prop-events 6
  python3 parlay_builder.py   # with ODDS_API_KEY set: adds DK/BetMGM/theScore lines (3 credits/sport) + props for the next games within 48h
                              # (per sport: nfl 1, nba 1, nhl 2, ncaaf 2, ncaab 1 events; worst case 35 credits, typical 20-30; hard cap 40)
  python3 parlay_builder.py --save-snapshot snap.json / --from-file snap.json
  python3 parlay_builder.py --single-book          # v1: multi-game slips constrained to one book each (v2: always; flag is a no-op)
  python3 parlay_builder.py --legacy               # reproduce strategy v1 (best-price mixed books, EV ranking, up to 4 legs)
  python3 parlay_builder.py --show-long-multi      # v2: also show 2-leg multi-game slips at +300/+400 (3-leg list always shows them)
  python3 parlay_builder.py --no-3leg              # v2: hide the 3-leg parlays list (and don't log it)
  python3 parlay_builder.py --flagged              # v3: show (and log) the Flagged-price slips section (off by default)
  python3 parlay_builder.py --from-file snap.json --no-ledger --out x.md     # replay a snapshot, log nothing
  python3 parlay_builder.py --from-file snap.json --flagged-only-ledger      # replay and log ONLY the flagged slips (backfill)
"""
import argparse, itertools, json, math, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

TARGETS = [100, 200, 300, 400]
STRATEGY = "v3"                       # v3 (2026-10-29) = v2 + stricter player-prop legs + price shopping; v2 history stays in the ledger
FLAG_STRATEGY = STRATEGY + "-flagged"  # older flagged slips are tagged v2-flagged; any "*-flagged" tag is tracked apart
PROP_MIN_BOOKS = 4         # v3: a player-prop leg needs >= 4 books quoting that exact line (Underdog counts once)
PROP_MAX_FAIR_SPREAD = 0.04  # v3: ... and the books' no-vig fair probabilities within 4 pp of each other (max - min)
CACHE_DIR = os.environ.get("PARLAY_CACHE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "cache", "oddsapi")
CACHE_TTL_S = 15 * 60      # reuse a cached Odds API response for 15 minutes
FLAG_MARK = "\U0001F534"  # red circle
FLAG_WARNING = "price is far off the other books; may be stale or a boost, check in app"
OUTLIER_PP = 0.05      # reject a leg priced >= 5 pp (implied prob) better than the other sportsbooks' median
CONFIRM_PP = 0.03      # "confirmed": another sportsbook within 3 pp of the price used
MIN_FAIR_BOOKS = 3     # books behind the no-vig fair price
LEG_REUSE_MAX = 2      # a leg (outcome) may appear in at most this many displayed slips per run
V2_MAX_LEGS = 2
LONG_MULTI = (300, 400)
NON_SPORTSBOOKS = {"underdog", "underdog_mkt"}
STAKING_NOTE = ("Staking: flat 0.5-1% of bankroll per slip. No Kelly sizing: across the first 105 settled v1 slips the measured "
                "edge was zero or negative (ROI -27%), so Kelly would say bet nothing.")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
FD_HOST = "https://sbapi.nj.sportsbook.fanduel.com/api"
FD_AK = "FhMFpcPWXMeyZxOx"  # public app key embedded in FanDuel's own web client (not a user credential)
DEFAULT_SPORTS = "nfl,nba,nhl,ncaaf,ncaab"  # MLB stays available (--sports ...,mlb) but is off by default
FD_PAGES = {"nfl": "nfl", "nba": "nba", "nhl": "nhl", "mlb": "mlb", "ncaaf": "ncaaf", "ncaab": "ncaab"}
UD_SPORTS = {"nfl": "NFL", "nba": "NBA", "nhl": "NHL", "mlb": "MLB", "ncaaf": "CFB", "ncaab": "CBB"}
OA_SPORTS = {"nfl": "americanfootball_nfl", "nba": "basketball_nba", "nhl": "icehockey_nhl",
             "mlb": "baseball_mlb", "ncaaf": "americanfootball_ncaaf", "ncaab": "basketball_ncaab"}
ESPN_SPORT = {"ncaaf": ("football/college-football", 80), "ncaab": ("basketball/mens-college-basketball", 50)}
COLLEGE = set(ESPN_SPORT)
# FanDuel event-page tabs that carry two-way player O/U props, per sport (default: any tab named "...props" / "player ...")
FD_PROP_TAB_RE = {"nhl": r"^goals$"}  # NHL shots/points/assists tabs are one-sided "2+" ladders (no under side, cannot be de-vigged)
# Odds API prop events per sport per run (frugal: credits = markets x events). --oddsapi-prop-events N overrides for every sport.
OA_PROP_EVENTS = {"nfl": 1, "nba": 1, "nhl": 2, "ncaaf": 0, "ncaab": 1, "mlb": 1}  # v3: ncaaf 0 (Odds API college props come from 2 books at most: can never pass the 4-book prop rule)
OA_PROP_WINDOW_H = 48  # only pull props for games starting within this many hours (props are rarely posted earlier)
OA_BOOKS = "draftkings,fanduel,betmgm,williamhill_us,espnbet"  # espnbet = theScore Bet; williamhill_us (Caesars) only returns on paid plans
OA_PROPS = {"nfl": "player_pass_yds,player_rush_yds,player_reception_yds,player_receptions",
            "nba": "player_points,player_rebounds,player_assists,player_threes,player_points_rebounds_assists",
            "nhl": "player_points,player_shots_on_goal", "mlb": "batter_total_bases,pitcher_strikeouts",
            "ncaaf": "player_pass_yds,player_rush_yds",
            "ncaab": "player_points,player_rebounds,player_assists"}
FAIR_EXCLUDE = {"underdog"}  # flat pick'em payouts (~-115 both sides) carry no probability info
CONSENSUS_ONLY = {"underdog_mkt"}  # sources used for fair probabilities but never offered as a leg price
BOOK_NAMES = {"underdog_mkt": "Underdog market price (consensus only)", "fanduel": "FanDuel", "underdog": "Underdog pick'em (indicative)", "draftkings": "DraftKings",
              "betmgm": "BetMGM", "williamhill_us": "Caesars", "espnbet": "theScore Bet", "bet365": "bet365", "underdog_mkt": "Underdog market price (consensus only)"}

# canonical stat names (Underdog's vocabulary) <- other books' labels
STAT_MAP = {
    "passing yds": "passing_yds", "rushing yds": "rushing_yds", "receiving yds": "receiving_yds",
    "total receptions": "receiving_rec", "receptions": "receiving_rec", "rushing + receiving yds": "rush_rec_yds",
    "passing tds": "passing_tds", "points": "points", "rebounds": "rebounds", "assists": "assists",
    "made threes": "three_points_made", "threes": "three_points_made", "3-pointers made": "three_points_made",
    "pts + reb + ast": "pts_rebs_asts", "points + rebounds + assists": "pts_rebs_asts",
    "pts + reb": "pts_rebs", "pts + ast": "pts_asts", "reb + ast": "rebs_asts", "shots on goal": "shots",
    "goals": "goals", "saves": "saves",
    # The Odds API market keys
    "player_pass_yds": "passing_yds", "player_rush_yds": "rushing_yds", "player_reception_yds": "receiving_yds",
    "player_receptions": "receiving_rec", "player_points": "points", "player_rebounds": "rebounds",
    "player_assists": "assists", "player_threes": "three_points_made",
    "player_points_rebounds_assists": "pts_rebs_asts", "player_shots_on_goal": "shots",
    "batter_total_bases": "total_bases", "pitcher_strikeouts": "strikeouts",
}
UD_STATS_OK = set(STAT_MAP.values())

LOG = []
def log(msg):
    LOG.append(msg); print(msg, file=sys.stderr)

def get_json(url, headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")), dict(r.headers)

# ---------- odds math ----------
def am_to_dec(a):
    a = float(a); return 1 + (a / 100 if a > 0 else 100 / -a)
def dec_to_am(d):
    if d <= 1: return float("nan")
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))
def fmt_am(a):
    return f"+{a}" if a > 0 else str(a)
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()  # Montréal == Montreal, San José == San Jose
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace(".", "")).strip()
def fmt_line(x):
    return ("+" if x > 0 else "") + (str(int(x)) if float(x).is_integer() else str(x))

# ---------- quote record ----------
# group: identifies a two-way market (both sides share it); side: identifies one outcome within group
def quote(sport, event, start, group, side, label, book, american, kind):
    return {"sport": sport, "event": event, "start": start, "group": group, "side": side,
            "label": label, "book": book, "american": int(american), "kind": kind}

def ev_key(name):
    # "Away @ Home" normalized; used to join books
    return norm(name.replace(" at ", " @ "))

# ---------- FanDuel ----------
def fd_runner_price(r):
    try: return r["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"]
    except Exception: return None

def fd_parse_markets(sport, events, markets, out):
    for m in markets.values():
        if m.get("marketStatus") != "OPEN" or m.get("inPlay"): continue
        e = events.get(m["eventId"]) or events.get(str(m["eventId"]))
        if not e or " @ " not in e["name"] or "(" in e["name"]: continue
        ename, ek, start = e["name"], ev_key(e["name"]), e.get("openDate")
        mt, runners = m["marketType"], [r for r in m["runners"] if r.get("runnerStatus") == "ACTIVE"]
        prices = [fd_runner_price(r) for r in runners]
        if len(runners) != 2 or None in prices: continue
        if mt == "MONEY_LINE":
            for r, p in zip(runners, prices):
                out.append(quote(sport, ename, start, (ek, "ml"), norm(r["runnerName"]), f"{r['runnerName']} ML", "fanduel", p, "game"))
        elif mt == "MATCH_HANDICAP_(2-WAY)":
            ln = abs(runners[0]["handicap"])
            for r, p in zip(runners, prices):
                out.append(quote(sport, ename, start, (ek, "spread", ln), norm(r["runnerName"]),
                                 f"{r['runnerName']} {fmt_line(r['handicap'])}", "fanduel", p, "game"))
        elif mt == "TOTAL_POINTS_(OVER/UNDER)":
            ln = runners[0]["handicap"]
            for r, p in zip(runners, prices):
                s = "over" if "over" in r["runnerName"].lower() else "under"
                out.append(quote(sport, ename, start, (ek, "total", ln), s, f"Game {s.title()} {ln}", "fanduel", p, "game"))
        elif mt == "PLAYER_TOTAL_GOALS" and m["marketName"].endswith(" Total Goals") and all(re.search(r" - (Over|Under)$", r["runnerName"]) for r in runners):
            player, ln = m["marketName"][:-len(" Total Goals")], runners[0]["handicap"]  # NHL "X Total Goals": Over/Under 0.5
            for r, p in zip(runners, prices):
                s = "over" if r["runnerName"].endswith("Over") else "under"
                out.append(quote(sport, ename, start, (ek, "prop", norm(player), "goals", ln), s,
                                 f"{player} {s.title()} {ln} Goals", "fanduel", p, "prop"))
        elif " - " in m["marketName"] and all(re.search(r" (Over|Under)$", r["runnerName"]) for r in runners):
            player, stat = m["marketName"].split(" - ", 1)
            if "alt" in stat.lower() or "qtr" in stat.lower() or "half" in stat.lower(): continue
            cstat = STAT_MAP.get(stat.strip().lower(), "fd:" + norm(stat))
            ln = runners[0]["handicap"]
            for r, p in zip(runners, prices):
                s = "over" if r["runnerName"].endswith("Over") else "under"
                out.append(quote(sport, ename, start, (ek, "prop", norm(player), cstat, ln), s,
                                 f"{player} {s.title()} {ln} {stat}", "fanduel", p, "prop"))

def fetch_fanduel(sports, max_prop_events, out):
    for sp in sports:
        page = FD_PAGES.get(sp)
        if not page: continue
        try:
            d, _ = get_json(f"{FD_HOST}/content-managed-page?page=CUSTOM&customPageId={page}&_ak={FD_AK}")
        except Exception as ex:
            log(f"[fanduel] {sp}: FAILED {ex}"); continue
        a = d.get("attachments", {})
        events = {int(k): v for k, v in a.get("events", {}).items()}
        n0 = len(out)
        fd_parse_markets(sp, events, a.get("markets", {}), out)
        log(f"[fanduel] {sp}: {len(out)-n0} game-line quotes" + ("" if len(out) > n0 else " (no games listed: out of season or between slates)"))
        now = datetime.now(timezone.utc).isoformat()
        games = sorted([e for e in events.values() if " @ " in e["name"] and "(" not in e["name"] and e.get("openDate", "") > now],
                       key=lambda e: e["openDate"])[:max_prop_events]
        for e in games:
            n1 = len(out)
            try:
                ed, _ = get_json(f"{FD_HOST}/event-page?_ak={FD_AK}&eventId={e['eventId']}")
                tabs = [t["title"] for t in ed.get("layout", {}).get("tabs", {}).values()]
                ptabs = [t for t in tabs if re.search(FD_PROP_TAB_RE.get(sp, r"props|^player "), t, re.I) and "defense" not in t.lower()]
                for t in ptabs:
                    slug = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
                    td, _ = get_json(f"{FD_HOST}/event-page?_ak={FD_AK}&eventId={e['eventId']}&tab={slug}")
                    ta = td.get("attachments", {})
                    evs = {int(k): v for k, v in ta.get("events", {}).items()}
                    fd_parse_markets(sp, evs, ta.get("markets", {}), out)
                    time.sleep(0.15)
            except Exception as ex:
                log(f"[fanduel] props {e['name']}: FAILED {ex}")
            log(f"[fanduel] props {e['name']}: {len(out)-n1} quotes")

# ---------- Underdog (pick'em) ----------
def fetch_underdog(sports, out):
    try:
        d, _ = get_json("https://api.underdogfantasy.com/v1/over_under_lines", timeout=60)
    except Exception as ex:
        log(f"[underdog] FAILED {ex}"); return
    want = {UD_SPORTS[s]: s for s in sports if s in UD_SPORTS}
    games = {g["id"]: g for g in d.get("games", []) if g.get("sport_id") in want and g.get("status") == "scheduled"}
    apps = {a["id"]: a for a in d.get("appearances", [])}
    players = {p["id"]: p for p in d.get("players", [])}
    n0 = len(out)
    for l in d.get("over_under_lines", []):
        if l.get("status") != "active" or l.get("live_event"): continue
        st = l["over_under"]["appearance_stat"]
        if st["stat"] not in UD_STATS_OK: continue
        a = apps.get(st["appearance_id"])
        if not a or a.get("match_id") not in games: continue
        g, p = games[a["match_id"]], players.get(a["player_id"])
        if not p: continue
        opts = [o for o in l["options"] if o.get("status") == "active" and o.get("american_price")]
        if len(opts) != 2: continue  # one-sided lines can't be de-vigged
        pname = f"{p['first_name']} {p['last_name']}"
        ename = g["full_team_names_title"]
        ln = float(l["stat_value"])
        for o in opts:
            s = "over" if o["choice"] == "higher" else "under"
            grp = (ev_key(ename), "prop", norm(pname), st["stat"], ln)
            lab = f"{pname} {s.title()} {ln} {st['display_stat']}"
            # american_price: side-specific market price (~5% overround) -> used for fair-prob consensus only
            out.append(quote(want[g["sport_id"]], ename, g["scheduled_at"], grp, s, lab, "underdog_mkt", int(o["american_price"]), "prop"))
            # odds.fantasy: per-pick pick'em payout (what an Underdog entry actually pays per leg) -> usable leg price
            fo = ((o.get("odds") or {}).get("fantasy") or {}).get("american")
            if fo: out.append(quote(want[g["sport_id"]], ename, g["scheduled_at"], grp, s, lab, "underdog", int(fo), "prop"))
    per = defaultdict(int)
    for q in out[n0:]: per[q["sport"]] += 1
    log(f"[underdog] {len(out)-n0} pick'em quotes (two-sided lines only); by sport: " + (", ".join(f"{k} {v}" for k, v in sorted(per.items())) or "none")
        + ("; no lines for: " + ", ".join(s for s in sports if s in UD_SPORTS and not per.get(s)) if any(s in UD_SPORTS and not per.get(s) for s in sports) else ""))

# ---------- college team names ----------
# FanDuel says "Miami Florida" / "Ole Miss" / "Connecticut", Underdog and The Odds API say "Miami Hurricanes" / "Ole Miss Rebels" /
# "UConn Huskies". To join books and to grade against ESPN, every college team is rewritten to ESPN's displayName.
TEAM_ALIASES = {"miami florida": "Miami Hurricanes", "miami fl": "Miami Hurricanes", "miami ohio": "Miami (OH) RedHawks",
                "miami oh": "Miami (OH) RedHawks", "connecticut": "UConn Huskies", "uconn": "UConn Huskies",
                "southern miss": "Southern Mississippi Golden Eagles", "fiu": "Florida International Panthers",
                "umass": "Massachusetts Minutemen", "app state": "Appalachian State Mountaineers",
                "hawaii": "Hawai'i Rainbow Warriors", "louisiana": "Louisiana Ragin' Cajuns",
                "ul lafayette": "Louisiana Ragin' Cajuns", "ole miss": "Ole Miss Rebels", "pitt": "Pittsburgh Panthers",
                "unc": "North Carolina Tar Heels", "usc": "USC Trojans", "ucf": "UCF Knights", "smu": "SMU Mustangs",
                "tcu": "TCU Horned Frogs", "byu": "BYU Cougars", "lsu": "LSU Tigers", "unlv": "UNLV Rebels", "utep": "UTEP Miners",
                "uab": "UAB Blazers", "nc state": "NC State Wolfpack", "ncsu": "NC State Wolfpack",
                "appalachian state": "App State Mountaineers", "appalachian state mountaineers": "App State Mountaineers",
                "sam houston state": "Sam Houston Bearkats", "sam houston state bearkats": "Sam Houston Bearkats",
                "southern mississippi golden eagles": "Southern Miss Golden Eagles", "southern miss golden eagles": "Southern Miss Golden Eagles",
                "southern miss": "Southern Miss Golden Eagles", "san jose state spartans": "San José State Spartans"}

def _tkey(s):
    k = norm(s)
    return re.sub(r"\bst\b", "state", k)

def espn_team_index(sport, days=16):
    """ESPN displayName index for teams with games in the next ~2 weeks (keys: displayName, location, shortDisplayName).
    Ambiguous keys (two teams) are dropped. Returns {} if ESPN is unreachable (names are then left as the books give them)."""
    path, grp = ESPN_SPORT[sport]
    teams = {}
    for d in range(days):
        day = (datetime.now(timezone.utc) + timedelta(days=d - 1)).strftime("%Y%m%d")
        try:
            data, _ = get_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={day}&groups={grp}&limit=300")
        except Exception as ex:
            log(f"[names] {sport}: ESPN scoreboard {day} failed: {ex}"); continue
        for e in data.get("events", []):
            for c in e["competitions"][0]["competitors"]:
                teams[c["team"]["id"]] = c["team"]
    idx = {}
    for t in teams.values():
        for k in {_tkey(t.get("displayName")), _tkey(t.get("location")), _tkey(t.get("shortDisplayName"))}:
            if not k: continue
            if idx.get(k, t["displayName"]) != t["displayName"]: idx[k] = None  # ambiguous
            else: idx[k] = t["displayName"]
    return {k: v for k, v in idx.items() if v}, {t["displayName"] for t in teams.values()}

def canon_college(quotes, sports):
    """Rewrite college event/team names to ESPN displayName so books join and the grader can find the game."""
    for sp in [x for x in sports if x in COLLEGE]:
        qs = [q for q in quotes if q["sport"] == sp]
        if not qs: continue
        idx, names = espn_team_index(sp)
        if not idx:
            log(f"[names] {sp}: no ESPN team index; names left as given (cross-book joins may fail)"); continue
        cache, unresolved = {}, set()
        def canon(raw):
            if raw in cache: return cache[raw]
            k = _tkey(raw)
            v = raw if raw in names else idx.get(k) or (TEAM_ALIASES.get(k) if TEAM_ALIASES.get(k) in names else None)
            if v is None:
                unresolved.add(raw); v = raw
            cache[raw] = v; return v
        for q in qs:
            if " @ " not in q["event"]: continue
            a, h = q["event"].split(" @ ", 1)
            ca, ch = canon(a), canon(h)
            if (ca, ch) == (a, h): continue
            old_side_team = {norm(a): (a, ca), norm(h): (h, ch)}
            q["event"] = f"{ca} @ {ch}"
            g = list(q["group"]); g[0] = ev_key(q["event"]); q["group"] = tuple(g)
            if g[1] in ("ml", "spread") and q["side"] in old_side_team:
                raw, new = old_side_team[q["side"]]
                if q["label"].startswith(raw): q["label"] = new + q["label"][len(raw):]
                q["side"] = norm(new)
        if unresolved:
            log(f"[names] {sp}: {len(unresolved)} team name(s) not matched to an ESPN team, left as given: " + "; ".join(sorted(unresolved)[:12]))
        log(f"[names] {sp}: team names standardized to ESPN names ({len(cache)} teams)")

# ---------- The Odds API ----------
OA_SPENT = {"credits": 0, "remaining": None, "cache_hits": 0, "saved": 0, "skipped_sports": [], "fresh_calls": 0}
BALANCE_FILE = os.path.join(os.path.dirname(CACHE_DIR), "oddsapi_balance.json")  # last known balance (for the app; no key inside)
_CACHE_OPTS = {"ttl": CACHE_TTL_S, "enabled": True}

def _cache_path(url):
    """Cache key = the URL without the API key and without commenceTimeFrom (which changes every run)."""
    u = urllib.parse.urlsplit(url)
    qs = [(k, v) for k, v in urllib.parse.parse_qsl(u.query) if k not in ("apiKey", "commenceTimeFrom")]
    key = u.path + "?" + urllib.parse.urlencode(sorted(qs))
    import hashlib
    return os.path.join(CACHE_DIR, hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")

def cache_age_s(url):
    p = _cache_path(url)
    return time.time() - os.path.getmtime(p) if os.path.exists(p) else None

def _save_balance():
    try:
        os.makedirs(os.path.dirname(BALANCE_FILE), exist_ok=True)
        json.dump({"remaining": OA_SPENT["remaining"], "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, open(BALANCE_FILE, "w"))
    except Exception:
        pass

def oa_get(url, key, budget, cost_estimate, cache=True):
    """GET with credit accounting and a 15-minute disk cache for paid calls. Refuses calls that would exceed the per-run
    budget or reserve. A cache hit costs 0 credits."""
    if cache and cost_estimate > 0 and _CACHE_OPTS["enabled"]:
        p = _cache_path(url)
        age = cache_age_s(url)
        if age is not None and age < _CACHE_OPTS["ttl"]:
            try:
                c = json.load(open(p))
                OA_SPENT["cache_hits"] += 1; OA_SPENT["saved"] += int(c.get("cost", cost_estimate))
                return c["data"], {"x-requests-last": f"0 (cached {int(age // 60)} min ago)", "x-requests-remaining": OA_SPENT["remaining"]}
            except Exception:
                pass
    rem = OA_SPENT["remaining"]
    if OA_SPENT["credits"] + cost_estimate > budget["max_credits"]:
        raise RuntimeError(f"skipped: per-run credit cap {budget['max_credits']} would be exceeded")
    if rem is not None and rem - cost_estimate < budget["reserve"]:
        raise RuntimeError(f"skipped: would drop below reserve of {budget['reserve']} credits")
    try:
        d, hdr = get_json(url)
    except Exception as ex:
        raise RuntimeError(str(ex).replace(key, "***"))
    h = {k.lower(): v for k, v in hdr.items()}
    cost = int(float(h.get("x-requests-last", 0) or 0))
    OA_SPENT["credits"] += cost
    if cost_estimate > 0: OA_SPENT["fresh_calls"] += 1
    if h.get("x-requests-remaining") is not None:
        OA_SPENT["remaining"] = int(float(h["x-requests-remaining"]))
        _save_balance()
    if cache and cost_estimate > 0 and _CACHE_OPTS["enabled"]:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = _cache_path(url) + ".tmp"
            json.dump({"cost": cost, "fetched": time.time(), "data": d}, open(tmp, "w")); os.replace(tmp, _cache_path(url))
        except Exception as ex:
            log(f"[oddsapi] cache write failed: {ex}")
    return d, h

def oa_balance(key):
    """Free call (0 credits): remaining credits on the account. Returns (remaining, used) or (None, None)."""
    try:
        _, hdr = get_json(f"https://api.the-odds-api.com/v4/sports?apiKey={key}")
        h = {k.lower(): v for k, v in hdr.items()}
        rem = int(float(h["x-requests-remaining"])) if h.get("x-requests-remaining") else None
        used = int(float(h["x-requests-used"])) if h.get("x-requests-used") else None
        if rem is not None:
            OA_SPENT["remaining"] = rem; _save_balance()
        return rem, used
    except Exception:
        return None, None

def credit_estimate(sports, props=True, prop_events=None):
    """Worst-case Odds API credits for one fresh run (no cache hits, every sport in season with games in the window)."""
    per = {}
    for sp in sports:
        if sp not in OA_SPORTS: continue
        n_ev = prop_events if prop_events is not None else OA_PROP_EVENTS.get(sp, 1)
        per[sp] = 3 + ((len(OA_PROPS[sp].split(",")) * n_ev) if props and sp in OA_PROPS else 0)
    return sum(per.values()), per

def _parse_ts(x):
    try: return datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except Exception: return None

def keyless_events_in_window(quotes, sp, hours):
    """Events FanDuel / Underdog list for a sport that start within `hours` (from quotes already fetched)."""
    now = datetime.now(timezone.utc); hz = now + timedelta(hours=hours)
    evs = set()
    for q in quotes:
        if q["sport"] != sp or q["book"] not in ("fanduel", "underdog", "underdog_mkt"): continue
        t = _parse_ts(q.get("start"))
        if t and now <= t <= hz: evs.add(q["group"][0])
    return evs

def fetch_oddsapi(sports, key, props, prop_events, budget, out, window_h=48):
    """Odds API: game lines (3 credits/sport) + props for games inside the window. Savings (v3):
    * every paid response is cached on disk for 15 minutes (a re-run inside that window costs 0 credits);
    * a sport is skipped entirely (0 credits) when the free /events list shows no game starting within `window_h` hours AND
      FanDuel / Underdog list none either (window_h <= 0 disables this);
    * props only for games starting within OA_PROP_WINDOW_H hours (as before); ncaaf props are off by default."""
    base = "https://api.the-odds-api.com/v4/sports"
    nb = len(OA_BOOKS.split(","))
    regions_equiv = math.ceil(nb / 10)  # with bookmakers=..., every 10 books bill as 1 region
    active = None
    try:
        sl, _ = oa_get(f"{base}?apiKey={key}", key, budget, 0, cache=False)  # free call: current balance + which sports are in season
        active = {x["key"] for x in sl if x.get("active")}
        log(f"[oddsapi] starting balance: {OA_SPENT['remaining']} credits")
    except Exception as ex:
        log(f"[oddsapi] FAILED {ex}"); return
    now_dt = datetime.now(timezone.utc)
    now = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    for sp in sports:
        sk = OA_SPORTS.get(sp)
        if not sk: continue
        if active is not None and sk not in active:
            log(f"[oddsapi] {sp}: out of season (inactive on The Odds API); skipped, 0 credits"); OA_SPENT["skipped_sports"].append(sp); continue
        if window_h and window_h > 0:
            hz = (now_dt + timedelta(hours=window_h)).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                q = urllib.parse.urlencode({"apiKey": key, "commenceTimeFrom": now, "commenceTimeTo": hz})
                el, h = oa_get(f"{base}/{sk}/events?{q}", key, budget, 0, cache=False)  # free: event list, no odds
                if str(h.get("x-requests-last", "0")) not in ("0", "0.0"):
                    log(f"[oddsapi] {sp}: WARNING /events reported cost {h.get('x-requests-last')}")
                kl = keyless_events_in_window(out, sp, window_h)
                if not el and not kl:
                    log(f"[oddsapi] {sp}: no game starts within {window_h}h (Odds API events list, FanDuel and Underdog agree); "
                        f"game lines and props skipped, 0 credits")
                    OA_SPENT["skipped_sports"].append(sp); continue
                log(f"[oddsapi] {sp}: {len(el)} event(s) within {window_h}h (free events list); FanDuel/Underdog list {len(kl)}")
            except Exception as ex:
                log(f"[oddsapi] {sp}: events list failed ({ex}); fetching odds anyway")
        try:
            q = urllib.parse.urlencode({"apiKey": key, "markets": "h2h,spreads,totals", "oddsFormat": "american",
                                        "bookmakers": OA_BOOKS, "commenceTimeFrom": now})
            evs, h = oa_get(f"{base}/{sk}/odds?{q}", key, budget, 3 * regions_equiv)
            evs = [e for e in evs if e.get("commence_time", "") > now]  # a cached copy may include games that have started since
            books = sorted({b["key"] for e in evs for b in e.get("bookmakers", [])})
            log(f"[oddsapi] {sp}: {len(evs)} events, books={books}; cost={h.get('x-requests-last')} remaining={h.get('x-requests-remaining')}")
        except Exception as ex:
            log(f"[oddsapi] {sp}: {ex}"); continue
        evs = sorted(evs, key=lambda e: e["commence_time"])
        for e in evs:
            oa_parse(sp, f"{e['away_team']} @ {e['home_team']}", e, out)
        if not props or sp not in OA_PROPS: continue
        nm = len(OA_PROPS[sp].split(","))
        horizon = (datetime.now(timezone.utc) + timedelta(hours=OA_PROP_WINDOW_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
        soon = [e for e in evs if e["commence_time"] <= horizon]
        n_ev = prop_events if prop_events is not None else OA_PROP_EVENTS.get(sp, 1)
        if n_ev <= 0:
            log(f"[oddsapi] {sp}: props off for this sport by default (v3: they can't reach {PROP_MIN_BOOKS} books); 0 credits"); continue
        if not soon:
            log(f"[oddsapi] {sp}: no game starts within {OA_PROP_WINDOW_H}h; props skipped, 0 credits"); continue
        for e in soon[:n_ev]:
            ename = f"{e['away_team']} @ {e['home_team']}"
            try:
                q = urllib.parse.urlencode({"apiKey": key, "markets": OA_PROPS[sp], "oddsFormat": "american",
                                            "bookmakers": OA_BOOKS})
                pe, h = oa_get(f"{base}/{sk}/events/{e['id']}/odds?{q}", key, budget, nm * regions_equiv)
                n0 = len(out); oa_parse(sp, ename, pe, out)
                books = sorted({b["key"] for b in pe.get("bookmakers", [])})
                log(f"[oddsapi] props {ename}: {len(out)-n0} quotes, books={books}; cost={h.get('x-requests-last')} remaining={h.get('x-requests-remaining')}")
            except Exception as ex:
                log(f"[oddsapi] props {ename}: {ex}")
    log(f"[oddsapi] credits used this run: {OA_SPENT['credits']}; remaining: {OA_SPENT['remaining']}; "
        f"cache hits: {OA_SPENT['cache_hits']} (saved ~{OA_SPENT['saved']} credits)")

def oa_parse(sp, ename, e, out):
    ek, start = ev_key(ename), e.get("commence_time")
    for b in e.get("bookmakers", []):
        bk = b["key"]
        for m in b.get("markets", []):
            oc = m.get("outcomes", [])
            k = m["key"]
            if k == "h2h" and len(oc) == 2:
                for o in oc: out.append(quote(sp, ename, start, (ek, "ml"), norm(o["name"]), f"{o['name']} ML", bk, o["price"], "game"))
            elif k == "spreads" and len(oc) == 2:
                for o in oc: out.append(quote(sp, ename, start, (ek, "spread", abs(o["point"])), norm(o["name"]),
                                              f"{o['name']} {fmt_line(o['point'])}", bk, o["price"], "game"))
            elif k == "totals" and len(oc) == 2:
                for o in oc: out.append(quote(sp, ename, start, (ek, "total", o["point"]), o["name"].lower(),
                                              f"Game {o['name']} {o['point']}", bk, o["price"], "game"))
            elif k in STAT_MAP:
                byp = defaultdict(list)
                for o in oc: byp[(o.get("description"), o.get("point"))].append(o)
                for (pl, pt), os_ in byp.items():
                    if len(os_) != 2 or pl is None: continue
                    for o in os_:
                        out.append(quote(sp, ename, start, (ek, "prop", norm(pl), STAT_MAP[k], pt), o["name"].lower(),
                                         f"{pl} {o['name']} {pt} {k.replace('player_','')}", bk, o["price"], "prop"))

# ---------- fair probs & legs ----------
def build_legs(quotes, dfs_as_legs=True):
    by_gb = defaultdict(dict)  # (group, book) -> side -> quote
    for q in quotes:
        q["group"] = tuple(q["group"])
        by_gb[(q["group"], q["book"])][q["side"]] = q
    fair = defaultdict(lambda: defaultdict(list))  # group -> side -> [fair probs per book]
    for (g, b), sides in by_gb.items():
        if len(sides) != 2 or b in FAIR_EXCLUDE: continue
        imp = {s: 1 / am_to_dec(q["american"]) for s, q in sides.items()}
        tot = sum(imp.values())
        if not (1.0 <= tot < 1.25): continue  # sanity: overround between 0% and 25%
        for s, p in imp.items(): fair[g][s].append((b, p / tot))
    legs = []
    for (g, b), sides in by_gb.items():
        for s, q in sides.items():
            fps = fair.get(g, {}).get(s)
            if not fps: continue
            legs.append(dict(q))
    # aggregate per (group, side)
    agg = {}
    for l in legs:
        k = (l["group"], l["side"])
        fps = fair[l["group"]][l["side"]]
        fp = sum(p for _, p in fps) / len(fps)
        a = agg.setdefault(k, {"group": l["group"], "side": l["side"], "label": l["label"], "event": l["event"],
                               "sport": l["sport"], "start": l["start"], "kind": l["kind"], "fair": fp,
                               "n_books_fair": len(fps), "fair_books": sorted({b for b, _ in fps}),
                               "fair_by_book": {b: p for b, p in fps}, "prices": {}})
        a["prices"][l["book"]] = l["american"]
    out = []
    for a in agg.values():
        a["prices"] = {b: p for b, p in a["prices"].items() if b not in CONSENSUS_ONLY} or {}
        books = {b: p for b, p in a["prices"].items() if b not in CONSENSUS_ONLY and (dfs_as_legs or b != "underdog")}
        if not books: continue
        bb = max(books, key=lambda b: am_to_dec(books[b]))
        a["best_book"], a["best_am"] = bb, books[bb]
        a["best_dec"] = am_to_dec(books[bb])
        a["edge"] = a["fair"] * a["best_dec"] - 1
        out.append(a)
    return out

# ---------- v2/v3 leg checks ----------
PROP_RULE = {"on": True}  # v3 prop rule; --v2-props turns it off (then slips are tagged v2)

def prop_books(l):
    """Distinct books quoting this exact prop line (Underdog pick'em and Underdog's market price count as one book)."""
    return {"underdog" if b == "underdog_mkt" else b for b in set(l.get("prices", {})) | set(l.get("fair_by_book", {}))}

def prop_fair_spread(l, exclude=None):
    """max - min of the per-book no-vig fair probabilities (pp/100), optionally leaving one book out."""
    fps = [p for b, p in l.get("fair_by_book", {}).items() if b != exclude]
    return (max(fps) - min(fps)) if len(fps) >= 2 else 1.0

def prop_ok(l, exclude=None):
    """v3: (ok, reason) for a player-prop leg: >= PROP_MIN_BOOKS books quote it and their fair probs are within PROP_MAX_FAIR_SPREAD."""
    if l.get("kind") != "prop" or not PROP_RULE["on"]: return True, "ok"
    nb = len(prop_books(l))
    if nb < PROP_MIN_BOOKS: return False, f"prop: only {nb} book(s) quote it (v3 needs {PROP_MIN_BOOKS})"
    sp = prop_fair_spread(l, exclude)
    if sp > PROP_MAX_FAIR_SPREAD: return False, f"prop: books' fair probs {sp*100:.1f} pp apart (v3 max {PROP_MAX_FAIR_SPREAD*100:.0f})"
    return True, "ok"

def leg_check(l, book):
    """Return (ok, reason, gap_pp, other_median_implied) for using leg l at `book` (strategy v2)."""
    ip = 1 / am_to_dec(l["prices"][book])
    others = sorted(1 / am_to_dec(p) for b, p in l["prices"].items() if b != book and b not in NON_SPORTSBOOKS)
    fair_n = len([b for b in l.get("fair_books", []) if b not in NON_SPORTSBOOKS]) if book == "underdog" else l["n_books_fair"]
    if not others:
        return False, "no other sportsbook quotes it", None, None
    med = others[len(others) // 2] if len(others) % 2 else (others[len(others) // 2 - 1] + others[len(others) // 2]) / 2
    gap = med - ip
    if gap >= OUTLIER_PP:
        return False, "outlier", gap, med
    if fair_n < MIN_FAIR_BOOKS:
        return False, f"only {fair_n} book(s) behind the fair price", gap, med
    pok, pwhy = prop_ok(l)
    if not pok:
        return False, pwhy, gap, med
    if book == "underdog" and len(others) < 2:
        return False, "fewer than 2 sportsbooks quote it", gap, med
    if not any(o - ip <= CONFIRM_PP for o in others):
        return False, "no other sportsbook within 3 pp", gap, med
    return True, "ok", gap, med

def prop_sides(c):
    u = sum(1 for x in c if x["kind"] == "prop" and x["side"] == "under")
    o = sum(1 for x in c if x["kind"] == "prop" and x["side"] == "over")
    return u, o

# ---------- combination search ----------
def conflict(a, b, sgp):
    ga, gb = a["group"], b["group"]
    if ga[:2] == gb[:2] and ga[1] in ("ml", "spread", "total"): return True       # same game-line market (any line)
    if ga[0] == gb[0] and {ga[1], gb[1]} == {"ml", "spread"}: return True        # ML + spread same game
    if ga[1] == "prop" and gb[1] == "prop" and ga[0] == gb[0] and ga[2] == gb[2]: return True  # same player twice
    if not sgp and ga[0] == gb[0]: return True                                     # multi-game: 1 leg per game
    return False

def combos(pool, sgp, max_legs, price_of, min_legs=2):
    res = []
    for n in range(min_legs, max_legs + 1):
        for c in itertools.combinations(pool, n):
            if any(conflict(x, y, sgp) for x, y in itertools.combinations(c, 2)): continue
            dec = math.prod(price_of(x) for x in c)
            pf = math.prod(x["fair"] for x in c)
            res.append((c, dec, pf * dec - 1, pf))
    return res

def pick_slips(cands, target, k=3):
    tdec = am_to_dec(target)
    for tol in (0.06, 0.12, 0.2, 0.35):
        ok = [c for c in cands if abs(c[1] / tdec - 1) <= tol]
        ok.sort(key=lambda c: (-c[2], abs(c[1] - tdec)))
        chosen = []
        for c in ok:
            ids = {(x["group"], x["side"]) for x in c[0]}
            if all(len(ids & {(x["group"], x["side"]) for x in ch[0]}) <= 1 for ch in chosen):
                chosen.append(c)
            if len(chosen) == k: return chosen, tol
        if len(chosen) == k or tol == 0.35: return chosen, tol
    return [], None

V2_TOLERANCES = (0.06, 0.12, 0.2)  # v2 never goes wider than +-20% of the target's decimal odds (v1 went to 35%)

def pick_slips_v2(cands, target, usage, shown, k=3, extra=lambda c: 0):
    """Closest tolerance tier first; within a tier rank by fair hit probability (ties -> more prop unders, then
    closeness to target). Enforces: no shared leg within a target, each leg in <= LEG_REUSE_MAX slips per run,
    and no identical slip at two targets."""
    tdec = am_to_dec(target)
    def tier(c):
        d = abs(c[1] / tdec - 1)
        return next((i for i, t in enumerate(V2_TOLERANCES) if d <= t), None)
    ok = [(tier(c), c) for c in cands]
    ok = [(t, c) for t, c in ok if t is not None]
    ok.sort(key=lambda tc: (tc[0], extra(tc[1]), -round(tc[1][3] * 200) / 200, -prop_sides(tc[1][0])[0], abs(tc[1][1] - tdec)))
    chosen, worst = [], 0
    for t, c in ok:
        ids = [(x["group"], x["side"]) for x in c[0]]
        key = (frozenset(ids), c[0][0]["use_book"])
        if key in shown: continue
        if any(usage[i] >= LEG_REUSE_MAX for i in ids): continue
        if any(set(ids) & {(x["group"], x["side"]) for x in ch[0]} for ch in chosen): continue
        chosen.append(c); worst = max(worst, t); shown.add(key)
        for i in ids: usage[i] += 1
        if len(chosen) == k: break
    return chosen, (V2_TOLERANCES[worst] if chosen else None)

PRICE_BUCKETS = ((1.2, 1.6), (1.6, 2.0), (2.0, 2.6), (2.6, 4.01))

def strat_pool(pool, n, price_of, fair_of=lambda l: l["fair"]):
    """v2 candidate pool: an equal share of legs from each price bucket (so every target is reachable), keeping the
    lowest-vig legs (highest fair prob relative to price) inside each bucket. Pool choice only; slips are ranked by fair prob."""
    per = max(2, n // len(PRICE_BUCKETS))
    out = []
    for lo, hi in PRICE_BUCKETS:
        b = [l for l in pool if lo <= price_of(l) < hi]
        b.sort(key=lambda l: -(fair_of(l) * price_of(l)))
        out += b[:per]
    return out

def run_search_v2(legs, args):
    legs = [l for l in legs if 1.2 <= l["best_dec"] <= 4.0 or any(1.2 <= am_to_dec(p) <= 4.0 for p in l["prices"].values())]
    flagged, elig, reasons = [], defaultdict(list), defaultdict(int)
    for l in legs:
        for b, p in l["prices"].items():
            if b in NON_SPORTSBOOKS and b != "underdog": continue
            if not (1.2 <= am_to_dec(p) <= 4.0): continue
            ok, why, gap, med = leg_check(l, b)
            reasons[why if why in ("ok", "outlier") else ("fair books" if "behind the fair" in why else
                    "prop books" if why.startswith("prop: only") else "prop spread" if why.startswith("prop:") else "unconfirmed")] += 1
            if ok:
                elig[b].append(l)
                if l["kind"] == "prop": reasons["props_ok"] += 1
            elif why == "outlier": flagged.append((l, b, gap, med))
    max_legs = min(args.max_legs, V2_MAX_LEGS)
    sgp_cands, multi_cands = [], []
    for b, ls in elig.items():
        price = lambda l, b=b: am_to_dec(l["prices"][b])
        by_ev = defaultdict(list)
        for l in ls: by_ev[l["group"][0]].append(l)
        for ek, evl in by_ev.items():
            pool = strat_pool(evl, args.pool_sgp, price)
            for c, dec, ev, pf in combos(pool, True, max_legs, leg_price(b)):
                sgp_cands.append((tuple(dict(x, use_book=b, use_am=x["prices"][b]) for x in c), dec, ev, pf))
        pool = strat_pool(dedupe_by_event(sorted(ls, key=lambda l: -(l["fair"] * price(l))), 10**6, 2), args.pool_multi, price)
        for c, dec, ev, pf in combos(pool, False, max_legs, leg_price(b)):
            multi_cands.append((tuple(dict(x, use_book=b, use_am=x["prices"][b]) for x in c), dec, ev, pf))
    three_cands = []
    if not getattr(args, "no_3leg", False):
        # 3-leg list (explicit user exception to the 2-leg rule): exactly 3 legs at ONE book, either all in one game (SGP-3, estimated
        # price) or one leg per game in 3 different games (Multi-game-3). Same leg checks as every other v2 list.
        for b, ls in elig.items():
            price = lambda l, b=b: am_to_dec(l["prices"][b])
            wrap3 = lambda c, b=b: tuple(dict(x, use_book=b, use_am=x["prices"][b]) for x in c)
            by_ev = defaultdict(list)
            for l in ls: by_ev[l["group"][0]].append(l)
            for ek, evl in by_ev.items():
                for c, dec, ev, pf in combos(strat_pool(evl, args.pool_sgp, price), True, 3, leg_price(b), min_legs=3):
                    three_cands.append((wrap3(c), dec, ev, pf))
            pool = strat_pool(dedupe_by_event(sorted(ls, key=lambda l: -(l["fair"] * price(l))), 10**6, 2), args.pool_multi, price)
            for c, dec, ev, pf in combos(pool, False, 3, leg_price(b), min_legs=3):
                three_cands.append((wrap3(c), dec, ev, pf))
    usage, shown = defaultdict(int), set()
    results = {"sgp": {}, "multi": {}}
    for t in TARGETS: results["sgp"][t] = pick_slips_v2(sgp_cands, t, usage, shown)
    for t in TARGETS:
        if t in LONG_MULTI and not args.show_long_multi: results["multi"][t] = "hidden"
        else: results["multi"][t] = pick_slips_v2(multi_cands, t, usage, shown)
    if not getattr(args, "no_3leg", False):
        u3, sh3 = defaultdict(int), set()  # own leg-reuse counter (<= 2 slips per leg within this list) and own duplicate check
        results["three"] = {t: pick_slips_v2(three_cands, t, u3, sh3) for t in TARGETS}
        LOG.append(f"3-leg search: {len(three_cands)} candidates evaluated")
    flagged.sort(key=lambda f: -f[2])
    fres = None
    if not args.no_flagged:
        fres, fs_n, fm_n = flagged_search(flagged, elig, args, max_legs)
        LOG.append(f"flagged search: {fs_n} SGP candidates, {fm_n} multi-game candidates with >= 1 flagged leg")
    return results, len(sgp_cands), len(multi_cands), {"flagged": flagged, "reasons": dict(reasons), "flagged_slips": fres,
                                                        "props_ok": reasons.get("props_ok", 0)}

def leg_price(book):
    return lambda x: am_to_dec(x["prices"][book]) if book else x["best_dec"]

FLAG_MIN_FAIR_FALLBACK = 2  # flagged legs normally need >= 3 independent books behind the fair price; 2 only as a labeled fallback

def flagged_legs_by_book(flagged):
    """Turn (leg, book, gap, median) rejects into usable flagged-leg copies. The fair probability EXCLUDES the flagged book
    itself (it is the off-market price), and `n_books_fair` counts only the other books."""
    byb = defaultdict(list)
    for l, b, gap, med in flagged:
        ex = {k: p for k, p in l.get("fair_by_book", {}).items() if k != b}
        if len(ex) < FLAG_MIN_FAIR_FALLBACK: continue
        others = [k for k in l["prices"] if k != b and k not in NON_SPORTSBOOKS]
        if b == "underdog" and len(others) < 2: continue
        if not prop_ok(l, exclude=b)[0]: continue  # v3 prop rule (spread measured without the flagged book's own price)
        byb[b].append(dict(l, fair=sum(ex.values()) / len(ex), n_books_fair=len(ex), fair_books=sorted(ex), flagged=True,
                           flag_gap=gap, flag_med=med))
    return byb

def flagged_search(flagged, elig, args, max_legs):
    """Slips with >= 1 flagged leg; every other leg passes the regular v2 checks at the same book. Own leg-reuse counters."""
    fbb = flagged_legs_by_book(flagged)
    sgp_c, multi_c = [], []
    for b, fls in fbb.items():
        price = lambda l, b=b: am_to_dec(l["prices"][b])
        reg = elig.get(b, [])
        fls = sorted(fls, key=lambda l: -l["flag_gap"])
        def wrap(c): return tuple(dict(x, use_book=b, use_am=x["prices"][b]) for x in c)
        by_ev = defaultdict(list)
        for l in reg: by_ev[l["group"][0]].append(l)
        fev = defaultdict(list)
        for l in fls: fev[l["group"][0]].append(l)
        for ek, fl_e in fev.items():
            pool = strat_pool(by_ev.get(ek, []), args.pool_sgp, price) + fl_e[:8]
            for c, dec, ev, pf in combos(pool, True, max_legs, leg_price(b)):
                if any(x.get("flagged") for x in c): sgp_c.append((wrap(c), dec, ev, pf))
        pool = strat_pool(dedupe_by_event(sorted(reg, key=lambda l: -(l["fair"] * price(l))), 10**6, 2), args.pool_multi, price) + fls[:12]
        for c, dec, ev, pf in combos(pool, False, max_legs, leg_price(b)):
            if any(x.get("flagged") for x in c): multi_c.append((wrap(c), dec, ev, pf))
    weak = lambda c: 1 if any(x.get("flagged") and x["n_books_fair"] < MIN_FAIR_BOOKS for x in c[0]) else 0
    usage, shown = defaultdict(int), set()
    res = {"sgp": {}, "multi": {}}
    for t in TARGETS: res["sgp"][t] = pick_slips_v2(sgp_c, t, usage, shown, extra=weak)
    for t in TARGETS:
        if t in LONG_MULTI and not args.show_long_multi: res["multi"][t] = "hidden"
        else: res["multi"][t] = pick_slips_v2(multi_c, t, usage, shown, extra=weak)
    return res, len(sgp_c), len(multi_c)

def run_search(legs, args):
    legs = [l for l in legs if 1.2 <= l["best_dec"] <= 4.0]
    results = {"sgp": {}, "multi": {}}
    # --- SGP: per event, per book (an SGP must be placed at one book)
    sgp_cands = []
    by_ev = defaultdict(list)
    for l in legs: by_ev[l["group"][0]].append(l)
    for ek, ls in by_ev.items():
        books = {b for l in ls for b in l["prices"]}
        for b in sorted(books):
            pool = [l for l in ls if b in l["prices"] and 1.2 <= am_to_dec(l["prices"][b]) <= 4.0]
            pool.sort(key=lambda l: -(l["fair"] * am_to_dec(l["prices"][b]) - 1))
            pool = bucket_pool(pool, args.pool_sgp, lambda l: am_to_dec(l["prices"][b]))
            for c, dec, ev, pf in combos(pool, True, args.max_legs, leg_price(b)):
                sgp_cands.append((tuple(dict(x, use_book=b, use_am=x["prices"][b]) for x in c), dec, ev, pf))
    # --- Multi-game
    multi_cands = []
    if args.single_book:
        books = {b for l in legs for b in l["prices"]}
        for b in books:
            pool = sorted([l for l in legs if b in l["prices"]], key=lambda l: -(l["fair"] * am_to_dec(l["prices"][b]) - 1))
            pool = bucket_pool(dedupe_by_event(pool, 10**6, 2), args.pool_multi, lambda l: am_to_dec(l["prices"][b]))
            for c, dec, ev, pf in combos(pool, False, args.max_legs, leg_price(b)):
                multi_cands.append((tuple(dict(x, use_book=b, use_am=x["prices"][b]) for x in c), dec, ev, pf))
    else:
        pool = bucket_pool(dedupe_by_event(sorted(legs, key=lambda l: -l["edge"]), 10**6, 2), args.pool_multi, lambda l: l["best_dec"])
        for c, dec, ev, pf in combos(pool, False, args.max_legs, leg_price(None)):
            multi_cands.append((tuple(dict(x, use_book=x["best_book"], use_am=x["best_am"]) for x in c), dec, ev, pf))
    for t in TARGETS:
        results["sgp"][t] = pick_slips(sgp_cands, t)
        results["multi"][t] = pick_slips(multi_cands, t)
    return results, len(sgp_cands), len(multi_cands)

def bucket_pool(pool, n, price_of, per_event=None):
    """top legs by edge, but guarantee short-priced legs too so low targets (+100) are reachable"""
    short = [l for l in pool if price_of(l) < 1.6][: n // 2]
    rest = [l for l in pool if l not in short][: n - len(short)]
    out = short + rest
    return dedupe_by_event(out, n, per_event) if per_event else out

def dedupe_by_event(pool, n, per_event=3):
    cnt, out = defaultdict(int), []
    for l in pool:
        if cnt[l["group"][0]] < per_event:
            out.append(l); cnt[l["group"][0]] += 1
        if len(out) >= n: break
    return out

# ---------- price shopping (v3) ----------
SHOP_BEST = "\U0001F3C6"  # trophy

def price_shop(c, scope=None):
    """What every book that offers ALL legs of slip `c` would pay for the same legs (product of that book's leg prices).
    SGP / SGP-3 prices are estimates (books apply correlation pricing). A book whose price on any leg is off-market (>= 5 pp better
    than the other sportsbooks' median) is shown but never picked as best. Returns dict(offers, best, missing, sgp)."""
    sets = [set(x["prices"]) for x in c]
    common = set.intersection(*sets) if sets else set()
    allb = set.union(*sets) if sets else set()
    use = c[0]["use_book"]
    offers = []
    for b in common:
        dec = math.prod(am_to_dec(x["prices"][b]) for x in c)
        off = any(leg_check(x, b)[1] == "outlier" for x in c)
        offers.append({"book": b, "name": BOOK_NAMES.get(b, b).split(" (")[0].replace(" pick'em", ""), "decimal": round(dec, 4),
                       "american": dec_to_am(dec), "off_market": off, "this_slip": b == use, "pickem": b == "underdog"})
    offers.sort(key=lambda o: (-o["decimal"], not o["this_slip"]))
    ok = [o for o in offers if not o["off_market"]]
    best = ok[0] if ok else None
    for o in offers: o["best"] = best is not None and o["book"] == best["book"]
    sgp = len({x["group"][0] for x in c}) == 1
    return {"offers": offers, "best": best, "missing": sorted(allb - common), "sgp": sgp}

def price_shop_line(c, scope=None):
    ps = price_shop(c, scope)
    items = []
    for o in ps["offers"]:
        t = f"{o['name']} {fmt_am(o['american'])}"
        if o["best"]: t = f"{SHOP_BEST} **{t}**"
        tags = (["this slip"] if o["this_slip"] else []) + (["pick'em"] if o["pickem"] else []) + (["off-market"] if o["off_market"] else [])
        items.append(t + (f" ({', '.join(tags)})" if tags else ""))
    if ps["missing"]:
        items.append("not offered at: " + ", ".join(BOOK_NAMES.get(b, b).split(" (")[0].replace(" pick'em", "") for b in ps["missing"]))
    hdr = "Price shop (same legs at each book; SGP estimate)" if ps["sgp"] else "Price shop (same legs at each book)"
    return f"{hdr}: " + " \u00b7 ".join(items)

# ---------- report ----------
def report(results, legs, quotes, meta, args):
    L = []
    L.append(f"# Parlay report - {meta['generated']}")
    L.append("")
    L.append(f"**Data status: {meta['status']}**  ")
    L.append(f"Sources with data: {', '.join(BOOK_NAMES.get(b,b) for b in meta['books']) or 'none'}  ")
    L.append(f"Quotes: {len(quotes)} | legs with a no-vig fair price: {len(legs)} | sports: {', '.join(args.sports)}")
    L.append("")
    L.append("> Not betting advice. EV assumes the consensus no-vig price is the true probability and that legs are "
             "independent. With few books in the consensus (keyless mode = FanDuel + Underdog only), most legs show "
             "negative EV equal to the vig; 'favorable' here means the best EV available, not necessarily +EV.")
    L.append("> Underdog leg prices are the per-pick pick'em payout (odds.fantasy) and are indicative; Underdog's side-specific american_price feeds the fair-price consensus only; "
             "Underdog entries pay by Underdog's own rules, not as a sportsbook parlay.")
    L.append("> Large cross-book gaps (e.g. one book +170 vs others +140/+150) often mean a stale or mismatched line; "
             "re-check the price in the app before betting. Odds API prices are cached snapshots, not streaming.")
    if not args.single_book:
        L.append("> Multi-game slips use the best price per leg across books; legs at different books cannot be placed "
                 "on one ticket - use `--single-book` for placeable single-book slips.")
    L.append("")
    for scope, title in (("sgp", "Single-game parlays (SGP) - ESTIMATED prices"), ("multi", "Multi-game parlays")):
        L.append(f"## {title}")
        if scope == "sgp":
            L.append("_SGP combined odds are the product of individual leg prices. Books apply correlation pricing to "
                     "SGPs, so the real quoted SGP price will differ (usually shorter). Treat as estimates._")
        L.append("")
        for t in TARGETS:
            slips, tol = results[scope][t]
            L.append(f"### Target {fmt_am(t)}")
            if not slips:
                L.append("_No combinations within tolerance from available legs._\n"); continue
            if tol and tol > 0.06: L.append(f"_(closest matches within ±{int(tol*100)}% of target decimal odds)_")
            for i, (c, dec, ev, pf) in enumerate(slips, 1):
                books = {x["use_book"] for x in c}
                L.append(f"**Slip {i}: {fmt_am(dec_to_am(dec))}** (decimal {dec:.2f}) | fair win prob {pf*100:.1f}% | "
                         f"est. EV {ev*100:+.1f}% | book(s): {', '.join(BOOK_NAMES.get(b,b) for b in sorted(books))}")
                L.append("")
                L.append("| Leg | Game | Book | Price | Fair prob | Leg EV | Other books |")
                L.append("|---|---|---|---|---|---|---|")
                for x in c:
                    others = ", ".join(f"{BOOK_NAMES.get(b,b).split(' ')[0]} {fmt_am(p)}" for b, p in x["prices"].items() if b != x["use_book"]) or "-"
                    lev = x["fair"] * am_to_dec(x["use_am"]) - 1
                    L.append(f"| {x['label']} | {x['event']} | {BOOK_NAMES.get(x['use_book'],x['use_book'])} | "
                             f"{fmt_am(x['use_am'])} | {x['fair']*100:.1f}% ({x['n_books_fair']} bk) | {lev*100:+.1f}% | {others} |")
                L.append("")
    L.append("## Top single legs by edge")
    L.append("| Leg | Game | Best book | Price | Fair prob | Edge |")
    L.append("|---|---|---|---|---|---|")
    for x in sorted(legs, key=lambda l: -l["edge"])[:15]:
        L.append(f"| {x['label']} | {x['event']} | {BOOK_NAMES.get(x['best_book'],x['best_book'])} | {fmt_am(x['best_am'])} | {x['fair']*100:.1f}% | {x['edge']*100:+.1f}% |")
    L.append("")
    L.append("## Fetch log")
    L += [f"- {m}" for m in meta["log"]]
    return "\n".join(L) + "\n"

def report_v2(results, legs, quotes, meta, args, info):
    L = [f"# Parlay report - {meta['generated']}", "",
         f"**Data status: {meta['status']}**  ",
         f"Strategy: {STRATEGY} (placeable single-book slips only; `--legacy` for v1)  ",
         *([f"v3 prop rule: a player-prop leg needs {PROP_MIN_BOOKS}+ books quoting the same line (Underdog counts) and their no-vig fair "
            f"probabilities within {PROP_MAX_FAIR_SPREAD*100:.0f} pp; game lines unchanged. Each slip shows what every other book pays for the same legs (price shop).  "]
           if STRATEGY == "v3" else []),
         f"Odds API: {OA_SPENT['credits']} credits used this run, {OA_SPENT['cache_hits']} cached response(s) reused (~{OA_SPENT['saved']} credits saved), "
         f"remaining {OA_SPENT['remaining'] if OA_SPENT['remaining'] is not None else 'unknown'}"
         + (f"; skipped sports: {', '.join(OA_SPENT['skipped_sports'])}" if OA_SPENT['skipped_sports'] else "") + "  ",
         f"Sources with data: {', '.join(BOOK_NAMES.get(b,b) for b in meta['books']) or 'none'}  ",
         f"Quotes: {len(quotes)} | legs with a no-vig fair price: {len(legs)} | sports: {', '.join(args.sports)}", ""]
    cov = defaultdict(int)
    for q in quotes: cov[q["sport"]] += 1
    L.append("Sports coverage (quotes): " + ", ".join(f"{sp} {cov[sp]}" if cov.get(sp) else f"{sp} NO DATA (out of season / no games listed)" for sp in args.sports) + "  ")
    L.append("")
    r = info["reasons"]
    L.append(f"Leg checks (leg x book pairs priced -400..+300): {r.get('ok',0)} eligible | {r.get('outlier',0)} rejected as outliers "
             f"(>= 5 pp better than other sportsbooks) | {r.get('fair books',0)} rejected for < 3 books behind the fair price | "
             f"{r.get('unconfirmed',0)} rejected as unconfirmed (no other sportsbook within 3 pp)"
             + (f" | props: {r.get('prop books',0)} rejected for < {PROP_MIN_BOOKS} books, {r.get('prop spread',0)} for books' fair probs > "
                f"{PROP_MAX_FAIR_SPREAD*100:.0f} pp apart; {info.get('props_ok', 0)} prop leg x book pairs eligible" if PROP_RULE["on"] else ""))
    L.append("")
    L.append("> Not betting advice. Every slip below can be placed at the one book named. Slips are ranked by fair hit "
             "probability (consensus no-vig price, legs assumed independent). Est. EV is shown for information only: a "
             "positive EV usually means one book's price is stale or off-market, not an edge (v1 positive-EV slips went 2-for-34).")
    L.append(f"> {STAKING_NOTE}")
    L.append("> Underdog leg prices are the per-pick pick'em payout (indicative); Underdog entries pay by Underdog's own rules. "
             "Underdog legs are only used when 3+ other books are behind the fair price and 2+ sportsbooks quote the leg.")
    L.append("> Re-check every price in the app before betting. Odds API prices are cached snapshots, not streaming.")
    if args.single_book:
        L.append("> `--single-book` is a no-op in v2: every slip is already single-book.")
    L.append("")
    short = []
    scopes = [("sgp", "Single-game parlays (SGP) - ESTIMATED prices"), ("multi", "Multi-game parlays (one book per slip)")]
    if "three" in results: scopes.append(("three", "3-leg parlays (SGP-3 same game, estimated prices / Multi-game-3 across 3 games)"))
    for scope, title in scopes:
        L.append(f"## {title}")
        if scope == "sgp":
            L.append("_SGP combined odds are the product of individual leg prices. Books apply correlation pricing to "
                     "SGPs, so the real quoted SGP price will differ (usually shorter). Treat as estimates._")
        if scope == "three":
            L.append("_Exactly 3 legs per slip, all at one book, either all in one game (**SGP-3**: price is an ESTIMATE, the product of the "
                     "leg prices; the book's real SGP price will differ, usually shorter) or one leg in each of 3 different games "
                     "(**Multi-game-3**). This list is an explicit exception to the max-2-legs rule; the other rules apply unchanged "
                     "(off-market legs rejected, 3+ books behind the fair price, a second sportsbook within 3 pp, ranked by fair hit probability, "
                     "each leg in at most 2 slips of this list, within +-20% of the target odds). Fewer slips are shown rather than relaxing a rule. "
                     "+300/+400 are shown. Tracked in the ledger as list `3leg`._")
        L.append("")
        for t in TARGETS:
            res = results[scope][t]
            L.append(f"### Target {fmt_am(t)}")
            if res == "hidden":
                L.append("_Hidden by default in v2 (v1 multi-game slips at +300/+400 went 2-for-32). Use `--show-long-multi` to show._\n")
                continue
            slips, tol = res
            if len(slips) < 3:
                short.append(f"{ {'sgp': 'SGP', 'multi': 'Multi-game', 'three': '3-leg'}[scope] } {fmt_am(t)}: {len(slips)} of 3")
                L.append(f"_Only {len(slips)} of 3 slips met the rules within ±20% of the target's decimal odds; the rules were not relaxed._")
            if not slips:
                L.append(""); continue
            if tol and tol > 0.06: L.append(f"_(closest matches within ±{int(tol*100)}% of target decimal odds)_")
            for i, (c, dec, ev, pf) in enumerate(slips, 1):
                books = {x["use_book"] for x in c}
                u, o = prop_sides(c)
                kind = ""
                if scope == "three":
                    kind = " | SGP-3 (estimated price)" if len({x["group"][0] for x in c}) == 1 else " | Multi-game-3"
                L.append(f"**Slip {i}: {fmt_am(dec_to_am(dec))}** (decimal {dec:.2f}) | fair win prob {pf*100:.1f}% | "
                         f"est. EV {ev*100:+.1f}% | book(s): {', '.join(BOOK_NAMES.get(b,b) for b in sorted(books))} | props: U{u}/O{o}{kind}")
                L.append("")
                L.append("| Leg | Game | Book | Price | Fair prob | Leg EV | Other books |")
                L.append("|---|---|---|---|---|---|---|")
                for x in c:
                    others = ", ".join(f"{BOOK_NAMES.get(b,b).split(' ')[0]} {fmt_am(p)}" for b, p in x["prices"].items() if b != x["use_book"]) or "-"
                    lev = x["fair"] * am_to_dec(x["use_am"]) - 1
                    L.append(f"| {x['label']} | {x['event']} | {BOOK_NAMES.get(x['use_book'],x['use_book'])} | "
                             f"{fmt_am(x['use_am'])} | {x['fair']*100:.1f}% ({x['n_books_fair']} bk) | {lev*100:+.1f}% | {others} |")
                L.append("")
                L.append(price_shop_line(c, scope)); L.append("")
    fsl = info.get("flagged_slips")
    fshort = []
    if fsl is not None:
        M = FLAG_MARK
        L.append(f"## {M} Flagged-price slips")
        L.append(f"> {M} **WARNING: {FLAG_WARNING}.** Every slip in this section contains at least one leg whose price is 5+ pp of "
                 "implied probability better than the median of the other sportsbooks. These legs were rejected from the regular lists "
                 "above; the slips below relax ONLY that rule (max 2 legs, one book per slip, leg reuse limit and the other legs' checks "
                 f"still apply). A flagged leg's fair probability excludes the flagged book's own price. Tracked separately in the ledger as `{FLAG_STRATEGY}`; "
                 "never mixed into the regular results. Off by default since v3 (flagged slips went 1-for-10); shown because `--flagged` was given.")
        L.append("")
        for scope, title in (("sgp", "Single-game parlays (SGP) - ESTIMATED prices"), ("multi", "Multi-game parlays (one book per slip)")):
            L.append(f"### {M} Flagged - {title}")
            L.append("")
            for t in TARGETS:
                res = fsl[scope][t]
                L.append(f"#### {M} Flagged target {fmt_am(t)}")
                if res == "hidden":
                    L.append("_Hidden by default (multi-game +300/+400). Use `--show-long-multi` to show._\n"); continue
                slips, tol = res
                if len(slips) < 3:
                    fshort.append(f"Flagged {'SGP' if scope=='sgp' else 'Multi-game'} {fmt_am(t)}: {len(slips)} of 3")
                    L.append(f"_Only {len(slips)} of 3 flagged-price slips met the rules within ±20% of the target's decimal odds._")
                if not slips:
                    L.append(""); continue
                if tol and tol > 0.06: L.append(f"_(closest matches within ±{int(tol*100)}% of target decimal odds)_")
                for i, (c, dec, ev, pf) in enumerate(slips, 1):
                    books = {x["use_book"] for x in c}
                    u, o = prop_sides(c)
                    nf = sum(1 for x in c if x.get("flagged"))
                    weak = any(x.get("flagged") and x["n_books_fair"] < MIN_FAIR_BOOKS for x in c)
                    L.append(f"{M} **Slip {i}: {fmt_am(dec_to_am(dec))}** (decimal {dec:.2f}) | fair win prob {pf*100:.1f}% | "
                             f"est. EV {ev*100:+.1f}% | book(s): {', '.join(BOOK_NAMES.get(b,b) for b in sorted(books))} | props: U{u}/O{o} | {M} flagged legs: {nf}")
                    L.append("")
                    L.append(f"{M} **WARNING: {FLAG_WARNING}.**" + (" Fewer than 3 books behind a flagged leg's fair price (fallback)." if weak else ""))
                    L.append("")
                    L.append("| Leg | Game | Book | Price | Fair prob | Leg EV | Other books | Flag |")
                    L.append("|---|---|---|---|---|---|---|---|")
                    for x in c:
                        others = ", ".join(f"{BOOK_NAMES.get(b,b).split(' ')[0]} {fmt_am(p)}" for b, p in x["prices"].items() if b != x["use_book"]) or "-"
                        lev = x["fair"] * am_to_dec(x["use_am"]) - 1
                        if x.get("flagged"):
                            flag = (f"{M} {x['flag_gap']*100:.1f} pp better than other books' median "
                                    f"(median implied {x['flag_med']*100:.1f}% vs {100/am_to_dec(x['use_am']):.1f}%)")
                            label = f"{M} {x['label']}"
                        else:
                            flag, label = "-", x["label"]
                        L.append(f"| {label} | {x['event']} | {BOOK_NAMES.get(x['use_book'],x['use_book'])} | "
                                 f"{fmt_am(x['use_am'])} | {x['fair']*100:.1f}% ({x['n_books_fair']} bk) | {lev*100:+.1f}% | {others} | {flag} |")
                    L.append("")
                    L.append(price_shop_line(c, scope)); L.append("")
        if fshort:
            L.append(f"_{M} Flagged-price targets short of 3 slips: " + "; ".join(fshort) + "._")
            L.append("")
    if short:
        L.append("## Targets short of 3 slips")
        L += [f"- {s}" for s in short]
        L.append("")
    fl = info["flagged"]
    if fl:
        L.append(f"## {FLAG_MARK} Check these prices")
        L.append(f"_{len(fl)} leg prices are 5+ pp of implied probability better than the median of the other sportsbooks "
                 f"(Underdog excluded from the median). They are likely stale, mismatched or boosted and were NOT used in any regular slip" + (f" (slips that use them are in the {FLAG_MARK} Flagged-price slips section above)" if info.get("flagged_slips") is not None else " (`--flagged` builds slips from them)") + ". "
                 f"Showing the largest {min(len(fl), 30)}._")
        L.append("")
        L.append("| Leg | Game | Book | Price | Other sportsbooks | Median implied | Price implied | Gap |")
        L.append("|---|---|---|---|---|---|---|---|")
        for l, b, gap, med in fl[:30]:
            others = ", ".join(f"{BOOK_NAMES.get(k,k).split(' ')[0]} {fmt_am(p)}" for k, p in l["prices"].items() if k != b and k not in NON_SPORTSBOOKS)
            L.append(f"| {l['label']} | {l['event']} | {BOOK_NAMES.get(b,b)} | {fmt_am(l['prices'][b])} | {others} | "
                     f"{med*100:.1f}% | {100/am_to_dec(l['prices'][b]):.1f}% | {gap*100:.1f} pp |")
        L.append("")
    L.append("## Fetch log")
    L += [f"- {m}" for m in meta["log"]]
    return "\n".join(L) + "\n"

def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sports", default=DEFAULT_SPORTS, help="comma list of nfl,nba,nhl,ncaaf,ncaab,mlb (default %(default)s; mlb is off by default)")
    ap.add_argument("--sources", default="fanduel,underdog,oddsapi")
    ap.add_argument("--max-prop-events", type=int, default=6, help="events per sport to pull props for")
    ap.add_argument("--max-legs", type=int, default=None, help="v2/v3: capped at 2 (default 2); --legacy default 4")
    ap.add_argument("--pool-sgp", type=int, default=16)
    ap.add_argument("--pool-multi", type=int, default=24)
    ap.add_argument("--single-book", action="store_true")
    ap.add_argument("--no-dfs-legs", action="store_true", help="use Underdog only for consensus, not as a leg book")
    ap.add_argument("--no-oddsapi-props", dest="oddsapi_props", action="store_false",
                    help="skip Odds API props (props are ON by default, capped by --oddsapi-prop-events/--oddsapi-max-credits)")
    ap.add_argument("--oddsapi-props", dest="oddsapi_props", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--oddsapi-prop-events", type=int, default=None,
                    help="events per sport for Odds API props; default is per sport (nfl 1, nba 1, nhl 2, ncaaf 0, ncaab 1), only games starting within 48h")
    ap.add_argument("--oddsapi-max-credits", type=int, default=40, help="hard cap on Odds API credits spent per run")
    ap.add_argument("--oddsapi-reserve", type=int, default=50, help="never let the account balance drop below this")
    ap.add_argument("--cache-ttl-min", type=float, default=CACHE_TTL_S / 60, help="reuse cached Odds API responses younger than this (default 15)")
    ap.add_argument("--no-cache", action="store_true", help="always fetch fresh Odds API data (still writes the cache)")
    ap.add_argument("--gameline-window-h", type=float, default=48,
                    help="skip a sport's Odds API calls when no game starts within this many hours (free events list + FanDuel/Underdog agree); 0 = never skip")
    ap.add_argument("--save-snapshot"); ap.add_argument("--from-file")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-ledger", action="store_true", help="don't log displayed slips to ledger/slips.jsonl")
    ap.add_argument("--legacy", action="store_true", help="reproduce strategy v1 (EV ranking, mixed-book multi unless --single-book, up to 4 legs, no leg filters)")
    ap.add_argument("--v2-props", action="store_true", help="turn the v3 prop rule off (slips are then tagged v2)")
    ap.add_argument("--show-long-multi", action="store_true", help="also show 2-leg multi-game slips at +300/+400")
    ap.add_argument("--no-3leg", action="store_true", help="hide the 3-leg parlays list (and don't log it)")
    ap.add_argument("--flagged", action="store_true", help="show (and log) the Flagged-price slips section (OFF by default since v3)")
    ap.add_argument("--no-flagged", action="store_true", help="(default since v3) hide the Flagged-price slips section; kept for old commands")
    ap.add_argument("--flagged-only-ledger", action="store_true", help="log ONLY the flagged-price slips to the ledger (backfill for a run whose regular slips are already logged; use with --from-file; implies --flagged)")
    ap.add_argument("--log-gap-min", type=float, default=0,
                    help="don't log this run if the ledger already has a run from the last N minutes (the app uses 15 to avoid double-counting cached re-runs)")
    return ap

def parse_args(argv=None):
    args = build_parser().parse_args(argv)
    if args.max_legs is None: args.max_legs = 4 if args.legacy else V2_MAX_LEGS
    elif not args.legacy and args.max_legs > V2_MAX_LEGS:
        print(f"[v2] --max-legs {args.max_legs} capped at {V2_MAX_LEGS} (use --legacy for more)", file=sys.stderr)
    args.sports = [x.strip() for x in args.sports.split(",") if x.strip()] if isinstance(args.sports, str) else list(args.sports)
    if args.flagged_only_ledger: args.flagged = True
    args.no_flagged = (args.no_flagged or not args.flagged) and not args.flagged_only_ledger
    return args

def execute(args, write_out=True, echo=True):
    """Run the builder once. Returns a dict for programmatic callers (the web app):
    md, slips (structured, per list/target), credits, log, ledger message, status, generated."""
    global STRATEGY, FLAG_STRATEGY
    LOG.clear()
    OA_SPENT.update({"credits": 0, "cache_hits": 0, "saved": 0, "skipped_sports": [], "fresh_calls": 0})
    _CACHE_OPTS["ttl"] = 0 if args.no_cache else args.cache_ttl_min * 60
    PROP_RULE["on"] = not args.v2_props
    STRATEGY = "v2" if args.v2_props else "v3"
    FLAG_STRATEGY = STRATEGY + "-flagged"
    srcs = set(args.sources.split(","))
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if args.from_file:
        snap = json.load(open(args.from_file))
        quotes = snap["quotes"]; LOG.extend(snap.get("log", []))
        status = f"SNAPSHOT replay of data captured {snap.get('captured')} (not current)"
        live = False
    else:
        live = True
        quotes = []
        if "fanduel" in srcs: fetch_fanduel(args.sports, args.max_prop_events, quotes)
        if "underdog" in srcs: fetch_underdog(args.sports, quotes)
        key = os.environ.get("ODDS_API_KEY")
        if "oddsapi" in srcs:
            if key:
                n_before = len(quotes)
                have_fd = any(q["book"] == "fanduel" for q in quotes)
                fetch_oddsapi(args.sports, key, args.oddsapi_props, args.oddsapi_prop_events,
                              {"max_credits": args.oddsapi_max_credits, "reserve": args.oddsapi_reserve}, quotes,
                              window_h=args.gameline_window_h)
                if have_fd:  # keep FanDuel's own direct feed; drop the duplicate copy relayed by The Odds API
                    quotes[n_before:] = [q for q in quotes[n_before:] if q["book"] != "fanduel"]
            else: log("[oddsapi] skipped: ODDS_API_KEY not set (needed for DraftKings/BetMGM/Caesars/theScore Bet)")
        canon_college(quotes, args.sports)
        status = f"LIVE (fetched {gen})"
        if args.save_snapshot:
            os.makedirs(os.path.dirname(os.path.abspath(args.save_snapshot)), exist_ok=True)
            json.dump({"captured": gen, "quotes": quotes, "log": LOG}, open(args.save_snapshot, "w"))
    res = {"generated": gen, "status": status, "live": live, "credits": dict(OA_SPENT), "log": LOG, "slips": [], "md": None,
           "ledger": None, "strategy": STRATEGY, "check_prices": [], "reasons": {}, "out": None}
    if not quotes:
        msg = f"# Parlay report - {gen}\n\n**NO LIVE DATA AVAILABLE.** No source returned odds; no parlays generated. " \
              "Nothing was invented.\n\n## Fetch log\n" + "\n".join(f"- {m}" for m in LOG) + "\n"
        res["md"] = msg
        return res
    legs = build_legs(quotes, dfs_as_legs=not args.no_dfs_legs)
    if args.legacy:
        results, ns, nm = run_search(legs, args); info = None
    else:
        results, ns, nm, info = run_search_v2(legs, args)
    LOG.append(f"search: {ns} SGP candidates, {nm} multi-game candidates evaluated")
    meta = {"generated": gen, "status": status, "books": sorted({q["book"] for q in quotes}), "log": LOG}
    md = report(results, legs, quotes, meta, args) if args.legacy else report_v2(results, legs, quotes, meta, args, info)
    res["md"] = md
    res["credits"] = dict(OA_SPENT)
    if info is not None:
        res["slips"] = structured_slips(results, info)
        res["reasons"] = info["reasons"]
        res["check_prices"] = [{"label": l["label"], "event": l["event"], "book": BOOK_NAMES.get(b, b), "american": l["prices"][b],
                                "others": {BOOK_NAMES.get(k, k).split(" (")[0]: p for k, p in l["prices"].items() if k != b and k not in NON_SPORTSBOOKS},
                                "gap_pp": round(gap * 100, 1)} for l, b, gap, med in info["flagged"][:30]]
    if write_out:
        out = args.out or f"/workspace/parlays/reports/parlays_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        open(out, "w", encoding="utf-8").write(md); res["out"] = out
        print(f"[saved] {out}", file=sys.stderr)
    if echo: print(md)
    if not args.no_ledger or args.flagged_only_ledger:
        res["ledger"] = log_to_ledger(md, legs, args)
    return res

def structured_slips(results, info):
    """Displayed slips as plain dicts (for the web app): list, target, slip_no, odds, fair prob, book, legs, price shop."""
    out = []
    def add(section, scope, t, res, flagged=False):
        if res == "hidden" or not res: return
        slips, tol = res
        for i, (c, dec, ev, pf) in enumerate(slips, 1):
            ps = price_shop(c, scope)
            kind = None
            if scope == "three": kind = "SGP-3" if len({x["group"][0] for x in c}) == 1 else "Multi-game-3"
            u, o = prop_sides(c)
            out.append({"section": section, "list": {"sgp": "sgp", "multi": "multi", "three": "3leg"}[scope], "target": t, "slip_no": i,
                        "american": dec_to_am(dec), "decimal": round(dec, 3), "fair_prob": round(pf, 4), "est_ev": round(ev, 4),
                        "book": BOOK_NAMES.get(c[0]["use_book"], c[0]["use_book"]).split(" (")[0].replace(" pick'em", ""),
                        "book_key": c[0]["use_book"], "kind": kind, "flagged": flagged, "tolerance": tol, "props": {"under": u, "over": o},
                        "estimate": len({x["group"][0] for x in c}) == 1,
                        "legs": [{"label": x["label"], "event": x["event"], "sport": x["sport"], "start": x["start"], "kind": x["kind"],
                                  "american": x["use_am"], "fair": round(x["fair"], 4), "n_books_fair": x["n_books_fair"], "flagged": bool(x.get("flagged")),
                                  "others": {BOOK_NAMES.get(b, b).split(" (")[0].replace(" pick'em", ""): p for b, p in x["prices"].items() if b != x["use_book"]}}
                                 for x in c],
                        "shop": ps["offers"], "shop_missing": [BOOK_NAMES.get(b, b).split(" (")[0].replace(" pick'em", "") for b in ps["missing"]],
                        "best_book": ps["best"]["name"] if ps["best"] else None, "best_american": ps["best"]["american"] if ps["best"] else None})
    for scope in ("sgp", "multi", "three"):
        if scope not in results: continue
        for t in TARGETS: add("regular", scope, t, results[scope][t])
    fs = info.get("flagged_slips")
    if fs:
        for scope in ("sgp", "multi"):
            for t in TARGETS: add("flagged", scope, t, fs[scope][t], flagged=True)
    return out

def main(argv=None):
    res = execute(parse_args(argv))
    if res["md"] and "NO LIVE DATA AVAILABLE" in res["md"] and not res["slips"]:
        print(res["md"]); sys.exit(2)

def log_to_ledger(md, legs, args):
    """Append displayed slips to ledger/slips.jsonl and archive the report. Returns a one-line status message.
    Live runs always log (unless --log-gap-min finds a run logged in the last N minutes).
    A --from-file replay logs only as the companion report of a live run already in the ledger."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from ledger_lib import parse_report, append_slips, load_ledger, run_has_report, ROOT
    except Exception as ex:
        print(f"[ledger] skipped: {ex}", file=sys.stderr); return f"ledger skipped: {ex}"
    # v2/v3 reports contain only single-book slips -> logged as the run's single_book report, so the old
    # "--from-file ... --single-book" companion replay is recognized as already logged and skipped.
    rtype = "single_book" if (args.single_book or not args.legacy) else "best_price"
    run_ts, slips = parse_report(md, rtype)
    if args.flagged_only_ledger:  # backfill: log only the flagged slips (their report type is always "flagged")
        slips = [s for s in slips if str(s.get("strategy", "")).endswith("-flagged")]; rtype = "flagged"
    if not run_ts or not slips:
        print("[ledger] nothing to log", file=sys.stderr); return "nothing to log"
    if args.from_file:
        if not any(r["run_ts"] == run_ts for r in load_ledger()):
            m = f"replay of {run_ts} not logged: no live run with that timestamp in the ledger"
            print(f"[ledger] {m}", file=sys.stderr); return m
        if run_has_report(run_ts, rtype):
            m = f"{rtype} report for run {run_ts} already logged"
            print(f"[ledger] {m}", file=sys.stderr); return m
    elif getattr(args, "log_gap_min", 0):
        cut = datetime.fromisoformat(run_ts) - timedelta(minutes=args.log_gap_min)
        recent = [r["run_ts"] for r in load_ledger() if r["run_ts"] != run_ts and datetime.fromisoformat(r["run_ts"]) > cut]
        if recent:
            m = f"not logged: run {max(recent)[:16]} UTC was logged less than {args.log_gap_min:g} min ago (avoids double-counting re-runs)"
            print(f"[ledger] {m}", file=sys.stderr); return m
    meta = {(l["label"], l["event"]): {"sport": l["sport"], "commence": l["start"]} for l in legs}
    a, t = append_slips(run_ts, slips, ("replay-companion" if args.from_file else "live") + ":" + rtype, meta)
    arch = os.path.join(ROOT, "reports", "archive", f"{run_ts[:16].replace('T', '_').replace(':', '').replace('-', '-')}_{rtype}.md")
    os.makedirs(os.path.dirname(arch), exist_ok=True)
    open(arch, "w", encoding="utf-8").write(md)
    m = f"run {run_ts} {rtype}: {a} new slips, {t} duplicate tags; archived {os.path.basename(arch)}"
    print(f"[ledger] {m}", file=sys.stderr)
    return m

if __name__ == "__main__":
    main()
