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
  python3 add_user_result.py --list
  python3 add_user_result.py --undo          # removes the most recent entry
"""
import re
import argparse, json, os, shlex, sys
from datetime import datetime, timezone

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
    if o is None or o == "-": return None, None
    v = int(str(o).replace("+", "").strip())
    if -100 < v < 100: raise ValueError(f"bad American odds {o}")
    return v, odds_bucket(v)

def odds_bucket(v):
    """Same buckets as the generator's targets: < +150 (incl. any minus odds) -> +100, +150..+249 -> +200,
    +250..+349 -> +300, +350 and longer -> +400."""
    if v < 150: return "+100"
    if v < 250: return "+200"
    if v < 350: return "+300"
    return "+400"

def parse_bet(txt):
    parts = shlex.split(txt)
    if not parts or parts[0].upper() not in ("W", "L", "P"): raise ValueError(f"--bet must start with W, L or P: {txt!r}")
    parts += ["-"] * (5 - len(parts))
    res, book, sport, odds, net = parts[:5]
    ov, bucket = parse_odds(odds)
    return {"result": res.upper(), "book": norm_book(book), "sport": norm_sport(sport), "odds": ov, "bucket": bucket,
            "net": None if net == "-" else float(net)}

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
    ap.add_argument("--date", help="results date YYYY-MM-DD (default: today UTC)"); ap.add_argument("--note")
    ap.add_argument("--book", help="sportsbook for the whole entry, e.g. FanDuel")
    ap.add_argument("--sport", help="sport for the whole entry, e.g. NBA")
    ap.add_argument("--odds", help="American odds (+250) or target bucket (+200) for the whole entry")
    ap.add_argument("--bet", action="append", default=[], help='one bet: "RESULT BOOK SPORT ODDS NET", e.g. "W FanDuel NBA +250 25" (repeatable)')
    ap.add_argument("--list", action="store_true"); ap.add_argument("--undo", action="store_true")
    a = ap.parse_args()
    rows = load()
    if a.list: show(rows); return
    if a.undo:
        if not rows: print("nothing to undo"); return
        r = rows.pop(); save(rows); print("removed:", json.dumps(r)); return
    bets = []
    try:
        bets = [parse_bet(b) for b in a.bet]
        odds, bucket = parse_odds(a.odds)
    except ValueError as ex:
        ap.error(str(ex))
    if bets:
        if a.book or a.sport or a.odds: ap.error("use either --bet (per-bet tags) or --book/--sport/--odds (whole entry), not both")
        a.wins = sum(b["result"] == "W" for b in bets); a.losses = sum(b["result"] == "L" for b in bets)
        a.pushes = sum(b["result"] == "P" for b in bets)
        if a.net is None and all(b["net"] is not None for b in bets): a.net = round(sum(b["net"] for b in bets), 2)
    if a.wins is None or a.losses is None: ap.error("--wins and --losses are required (or log bets with --bet)")
    if min(a.wins, a.losses, a.pushes) < 0: ap.error("counts must be >= 0")
    date = a.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    datetime.strptime(date, "%Y-%m-%d")
    r = {"date": date, "wins": a.wins, "losses": a.losses, "pushes": a.pushes, "net": a.net, "units": a.units,
         "note": a.note, "entered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if a.book: r["book"] = norm_book(a.book)
    if a.sport: r["sport"] = norm_sport(a.sport)
    if odds is not None: r["odds"], r["bucket"] = odds, bucket
    if bets: r["bets"] = bets
    rows.append(r); save(rows); print("added:", json.dumps(r)); show(rows)

if __name__ == "__main__":
    main()
