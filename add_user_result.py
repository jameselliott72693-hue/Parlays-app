#!/usr/bin/env python3
"""
Log the user's OWN betting results (kept separate from the auto-graded displayed slips).

  python3 add_user_result.py --wins 3 --losses 2 [--pushes 0] [--net 45.50] [--units 1.2] [--date 2026-10-22] [--note "..."]
  Optional tags for the whole entry: --book FanDuel --sport NBA --odds +250   (--odds: American odds or a target such as +200)
  Sports: NBA, NFL, NHL, NCAAF (also "college football"/CFB), NCAAB (also "college basketball"/CBB), MLB; mixed parlays: "NBA/NHL" -> "Mixed (NBA + NHL)"
  Per-bet logging (repeatable; wins/losses/pushes/net are then computed from the bets):
    python3 add_user_result.py --date 2026-10-23 --bet "W FanDuel NBA +250 25" --bet "L DraftKings NFL +300 -10"
    each --bet is "RESULT BOOK SPORT ODDS NET": RESULT is W, L or P; use - for any unknown field; multi-word books need
    quotes inside, e.g. --bet "W 'theScore Bet' NBA +200 20"
  Optional stake (risked $), legs and bet type: --stake 10 --legs 3 --type SGP (whole entry, or the single --bet), or per bet as
    extra key=value words: --bet "W FanDuel NBA +250 25 stake=10 legs=3 type=SGP"   (type: SGP, Multi-game, Straight)
  python3 add_user_result.py --list
  python3 add_user_result.py --undo          # removes the most recent entry
  Bankroll (ledger/bankroll.jsonl): --bankroll-start 500 [--date D] | --deposit 100 | --withdraw 50 | --bankroll (show)
"""
import re
import argparse, json, os, shlex, sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ledger", "user_results.jsonl")

def load():
    return [json.loads(l) for l in open(LEDGER) if l.strip()] if os.path.exists(LEDGER) else []

def save(rows):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER + ".tmp", "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    os.replace(LEDGER + ".tmp", LEDGER)

BOOKS = {"fanduel": "FanDuel", "draftkings": "DraftKings", "betmgm": "BetMGM", "thescore": "theScore Bet", "thescore bet": "theScore Bet",
         "espnbet": "theScore Bet", "underdog": "Underdog", "caesars": "Caesars", "bet365": "bet365", "fanatics": "Fanatics"}

def norm_book(b):
    if not b or b == "-": return None
    return BOOKS.get(b.strip().lower(), b.strip())

SPORT_ALIASES = {"NBA": "NBA", "NFL": "NFL", "NHL": "NHL", "MLB": "MLB", "NCAAF": "NCAAF", "NCAAB": "NCAAB",
                 "CFB": "NCAAF", "CBB": "NCAAB", "NCAAM": "NCAAB", "NCAAMB": "NCAAB",
                 "COLLEGE FOOTBALL": "NCAAF", "NCAA FOOTBALL": "NCAAF", "COLLEGE FB": "NCAAF", "CFOOTBALL": "NCAAF",
                 "COLLEGE BASKETBALL": "NCAAB", "NCAA BASKETBALL": "NCAAB", "COLLEGE BB": "NCAAB", "CBASKETBALL": "NCAAB", "MENS COLLEGE BASKETBALL": "NCAAB",
                 "HOCKEY": "NHL", "NHL HOCKEY": "NHL", "PRO FOOTBALL": "NFL", "FOOTBALL": "NFL", "BASKETBALL": "NBA", "BASEBALL": "MLB"}

def one_sport(x):
    t = re.sub(r"[^A-Za-z ]", " ", x).upper().strip()
    t = re.sub(r"\s+", " ", t)
    return SPORT_ALIASES.get(t, x.strip().upper())

def norm_sport(sp):
    """Standardise a sport tag to the labels the slip tables use: NBA, NFL, NHL, NCAAF (college football / CFB), NCAAB (college
    basketball / CBB), MLB. Mixed parlays become 'Mixed (NBA + NHL)' (labels sorted, joined with ' + '): 'Mixed' / 'NBA/NHL' /
    'NHL+NBA' / 'NBA & NHL' / 'Mixed (NBA + NHL)' all work. A bare 'Mixed' keeps the old default 'Mixed (NBA + NFL)'.
    Older entries are never rewritten."""
    if not sp or sp == "-": return None
    t = sp.strip()
    if t.lower() in ("mixed", "mix", "multi"): return "Mixed (NBA + NFL)"
    if t.lower().startswith("mixed (") and t.endswith(")"): t = t[7:-1]
    parts = sorted({one_sport(x) for x in re.split(r"\s*(?:/|\+|&|,|\band\b)\s*", t, flags=re.I) if x.strip()})
    if len(parts) > 1: return "Mixed (" + " + ".join(parts) + ")"
    return parts[0] if parts else None

def parse_odds(o):
    """American odds (+250, -110) or a target (+200) -> (odds int or None, bucket label)."""
    if o is None or str(o).strip() in ("", "-"): return None, None
    t = re.sub(r"[\u2212\u2013\u2014]", "-", str(o)).replace(" ", "").strip()  # "−110" (Unicode minus) as pasted from apps
    if t.upper() in ("EVEN", "EV", "EVS"): t = "100"
    if not re.fullmatch(r"[+-]?\d+(?:\.0+)?", t): raise ValueError(f"bad American odds {o!r} (use e.g. +250 or -110)")
    v = int(float(t))
    if -100 < v < 100: raise ValueError(f"bad American odds {o}")
    return v, odds_bucket(v)

def odds_bucket(v):
    """Same buckets as the generator's targets: < +150 (incl. any minus odds) -> +100, +150..+249 -> +200,
    +250..+349 -> +300, +350 and longer -> +400."""
    if v < 150: return "+100"
    if v < 250: return "+200"
    if v < 350: return "+300"
    return "+400"

TYPES = {"sgp": "SGP", "same game": "SGP", "same game parlay": "SGP", "multi": "Multi-game", "multi-game": "Multi-game",
         "multigame": "Multi-game", "multi game": "Multi-game", "parlay": "Multi-game", "straight": "Straight", "single": "Straight"}

def norm_type(t):
    """Bet type -> SGP / Multi-game / Straight (None for empty / '-')."""
    if t is None or str(t).strip() in ("", "-"): return None
    k = str(t).strip().lower()
    if k not in TYPES: raise ValueError(f"bet type must be SGP, Multi-game or Straight, not {t!r}")
    return TYPES[k]

def parse_stake(v):
    if v is None or str(v).strip() in ("", "-"): return None
    x = round(float(str(v).replace("$", "").replace(",", "")), 2)
    if x <= 0: raise ValueError("stake must be a positive dollar amount")
    return x

def parse_legs(v):
    if v is None or str(v).strip() in ("", "-"): return None
    n = int(v)
    if not 1 <= n <= 25: raise ValueError("legs must be between 1 and 25")
    return n

def extras(stake=None, legs=None, typ=None):
    """Optional per-bet fields (only the ones given), so old records and new ones read the same."""
    out = {}
    for k, v in (("stake", parse_stake(stake)), ("legs", parse_legs(legs)), ("type", norm_type(typ))):
        if v is not None: out[k] = v
    return out

def parse_bet(txt):
    parts = shlex.split(txt)
    if not parts or parts[0].upper() not in ("W", "L", "P"): raise ValueError(f"--bet must start with W, L or P: {txt!r}")
    kv = {}
    for x in [x for x in parts if "=" in x]:
        k, v = x.split("=", 1)
        if k.lower() not in ("stake", "legs", "type"): raise ValueError(f"unknown --bet field {k!r} (use stake=, legs=, type=)")
        kv[k.lower()] = v
    parts = [x for x in parts if "=" not in x]
    parts += ["-"] * (5 - len(parts))
    res, book, sport, odds, net = parts[:5]
    ov, bucket = parse_odds(odds)
    return {"result": res.upper(), "book": norm_book(book), "sport": norm_sport(sport), "odds": ov, "bucket": bucket,
            "net": None if net == "-" else float(net), **extras(kv.get("stake"), kv.get("legs"), kv.get("type"))}

def show(rows):
    w = sum(r["wins"] for r in rows); l = sum(r["losses"] for r in rows); p = sum(r.get("pushes") or 0 for r in rows)
    net = sum(r["net"] for r in rows if r.get("net") is not None); u = sum(r["units"] for r in rows if r.get("units") is not None)
    for i, r in enumerate(rows, 1):
        tags = " ".join(f"{k}={r[k]}" for k in ("book", "sport", "odds") if r.get(k) is not None)
        bets = f" bets={len(r['bets'])}" if r.get("bets") else ""
        print(f"{i:>3}. {r['date']}  {r['wins']}-{r['losses']}-{r.get('pushes') or 0}  net={r.get('net')}  units={r.get('units')}  {tags}{bets}  {r.get('note') or ''}  (entered {r['entered_at']})")
    dec = w + l
    print(f"TOTAL {w}-{l}-{p}  win% {100*w/dec:.1f}%  net ${net:+.2f}  units {u:+.2f}" if dec else "TOTAL no decided bets yet")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wins", type=int); ap.add_argument("--losses", type=int); ap.add_argument("--pushes", type=int, default=0)
    ap.add_argument("--net", type=float, help="net $ won (+) or lost (-)"); ap.add_argument("--units", type=float, help="net units")
    ap.add_argument("--date", help="results date YYYY-MM-DD (default: today, US Eastern)"); ap.add_argument("--note")
    ap.add_argument("--book", help="sportsbook for the whole entry, e.g. FanDuel")
    ap.add_argument("--sport", help="sport for the whole entry, e.g. NBA")
    ap.add_argument("--odds", help="American odds (+250) or target bucket (+200) for the whole entry")
    ap.add_argument("--bet", action="append", default=[], help='one bet: "RESULT BOOK SPORT ODDS NET", e.g. "W FanDuel NBA +250 25" (repeatable)')
    ap.add_argument("--stake", help="risked $ (whole entry, or the single --bet)")
    ap.add_argument("--legs", help="number of legs (whole entry, or the single --bet)")
    ap.add_argument("--type", help="bet type: SGP, Multi-game or Straight (whole entry, or the single --bet)")
    ap.add_argument("--bankroll-start", type=float, help="set the starting bankroll ($) on --date (default today ET)")
    ap.add_argument("--deposit", type=float, help="record a deposit ($) into the bankroll"); ap.add_argument("--withdraw", type=float, help="record a withdrawal ($)")
    ap.add_argument("--bankroll", action="store_true", help="show the current bankroll")
    ap.add_argument("--list", action="store_true"); ap.add_argument("--undo", action="store_true")
    a = ap.parse_args()
    rows = load()
    if a.list: show(rows); return
    if a.bankroll_start is not None or a.deposit is not None or a.withdraw is not None or a.bankroll:
        import bankroll_lib as bl
        d = a.date or datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        try:
            for kind, amt in (("start", a.bankroll_start), ("deposit", a.deposit), ("withdrawal", a.withdraw)):
                if amt is not None: print("added:", json.dumps(bl.add(kind, amt, d, a.note)))
        except ValueError as ex:
            ap.error(str(ex))
        sm = bl.summary(bl.load(), rows)
        print("no starting bankroll set (use --bankroll-start)" if not sm else
              f"bankroll ${sm['current']:,.2f} (start ${sm['start']:,.2f} on {sm['start_date']}, deposits ${sm['deposits']:,.2f}, "
              f"withdrawals ${sm['withdrawals']:,.2f}, bets net ${sm['bets_net']:+,.2f} over {sm['n_bets']} bets"
              + (f", {sm['n_no_net']} bets without net $ not counted" if sm["n_no_net"] else "")
              + f"); flat 0.5-1% stake = ${sm['stake_min']:.2f}-${sm['stake_max']:.2f}")
        return
    if a.undo:
        if not rows: print("nothing to undo"); return
        r = rows.pop(); save(rows); print("removed:", json.dumps(r)); return
    bets = []
    try:
        bets = [parse_bet(b) for b in a.bet]
        odds, bucket = parse_odds(a.odds)
        ex_ = extras(a.stake, a.legs, a.type)
    except ValueError as ex:
        ap.error(str(ex))
    if bets and ex_:
        if len(bets) > 1: ap.error("--stake/--legs/--type apply to one bet; with several --bet use stake=/legs=/type= inside each --bet")
        bets[0] = {**bets[0], **ex_}; ex_ = {}
    if bets:
        if a.book or a.sport or a.odds: ap.error("use either --bet (per-bet tags) or --book/--sport/--odds (whole entry), not both")
        a.wins = sum(b["result"] == "W" for b in bets); a.losses = sum(b["result"] == "L" for b in bets)
        a.pushes = sum(b["result"] == "P" for b in bets)
        if a.net is None and all(b["net"] is not None for b in bets): a.net = round(sum(b["net"] for b in bets), 2)
    if a.wins is None or a.losses is None: ap.error("--wins and --losses are required (or log bets with --bet)")
    if min(a.wins, a.losses, a.pushes) < 0: ap.error("counts must be >= 0")
    date = a.date or datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")  # the user's day (ET), not UTC
    datetime.strptime(date, "%Y-%m-%d")
    r = {"date": date, "wins": a.wins, "losses": a.losses, "pushes": a.pushes, "net": a.net, "units": a.units,
         "note": a.note, "entered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if a.book: r["book"] = norm_book(a.book)
    if a.sport: r["sport"] = norm_sport(a.sport)
    if odds is not None: r["odds"], r["bucket"] = odds, bucket
    r.update(ex_)
    if bets: r["bets"] = bets
    rows.append(r); save(rows); print("added:", json.dumps(r)); show(rows)

if __name__ == "__main__":
    main()
