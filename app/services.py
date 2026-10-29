"""Thin, testable wrappers around the existing CLI modules (no Streamlit imports here)."""
import contextlib, io, json, os, sys, threading
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
import parlay_builder as pb          # noqa: E402
import grade_slips as gs             # noqa: E402
import add_user_result as aur        # noqa: E402
import ledger_lib as ll              # noqa: E402

ET = ZoneInfo("America/New_York")
LOCK = threading.Lock()
SNAPSHOT = os.path.join(ROOT, "reports", "snapshot_latest.json")
LATEST_MD = os.path.join(ROOT, "reports", "latest.md")
ALL_SPORTS = ["nfl", "nba", "nhl", "ncaaf", "ncaab"]
BOOK_CHOICES = ["FanDuel", "DraftKings", "BetMGM", "theScore Bet", "Underdog", "Caesars", "bet365", "Fanatics", "Other"]
SPORT_CHOICES = ["NBA", "NFL", "NHL", "NCAAF", "NCAAB", "MLB", "Mixed (NBA + NFL)", "Mixed (NBA + NHL)", "Mixed (NFL + NHL)", "Other"]


# ---------- build ----------
def credit_info(sports, key_present):
    worst, per = pb.credit_estimate(sports)
    age = newest_cache_age_min()
    bal = None
    try: bal = json.load(open(pb.BALANCE_FILE))
    except Exception: pass
    return {"worst": worst, "per_sport": per, "cache_age_min": age, "ttl_min": pb.CACHE_TTL_S / 60,
            "cached": age is not None and age < pb.CACHE_TTL_S / 60, "balance": bal, "key": key_present}


def newest_cache_age_min():
    d = pb.CACHE_DIR
    if not os.path.isdir(d): return None
    ts = [os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d) if f.endswith(".json")]
    return (datetime.now().timestamp() - max(ts)) / 60 if ts else None


def build(sports, flagged=False, show_long_multi=False, live=True, log=True, snapshot=SNAPSHOT):
    """Run the builder in-process. Live runs save the snapshot and log to the ledger (skipped when another run was logged in
    the last 15 minutes, so cached re-runs are not double-counted). Snapshot replays never log."""
    argv = ["--sports", ",".join(sports), "--out", LATEST_MD if live else os.path.join(ROOT, "reports", "app_replay.md")]
    if live: argv += ["--save-snapshot", snapshot, "--log-gap-min", "15"]
    else: argv += ["--from-file", snapshot, "--no-ledger"]
    if not log: argv.append("--no-ledger")
    cap = os.environ.get("ODDS_MAX_CREDITS_PER_RUN")  # optional secret/env: lower the per-run credit cap (default 40)
    if cap: argv += ["--oddsapi-max-credits", str(int(cap))]
    if flagged: argv.append("--flagged")
    if show_long_multi: argv.append("--show-long-multi")
    with LOCK:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            res = pb.execute(pb.parse_args(argv), write_out=True, echo=False)
    res["stderr"] = err.getvalue()
    res["argv"] = argv
    return res


def odds_balance():
    key = os.environ.get("ODDS_API_KEY")
    if not key: return None, None
    return pb.oa_balance(key)


# ---------- grade ----------
def grade():
    with LOCK:
        gs._sb.clear(); gs._sum.clear()  # don't reuse scoreboards from an earlier run in this process
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            gs.main()
    return out.getvalue()


# ---------- user bets ----------
def log_bet(result, book, sport, odds, net, date, note=None):
    """Append one bet to ledger/user_results.jsonl exactly like `add_user_result.py --bet "R BOOK SPORT ODDS NET" --date D`."""
    result = result.upper().strip()
    if result not in ("W", "L", "P"): raise ValueError("result must be W, L or P")
    datetime.strptime(date, "%Y-%m-%d")
    ov, bucket = aur.parse_odds(odds.strip() if isinstance(odds, str) and odds.strip() else None)
    bet = {"result": result, "book": aur.norm_book(book) if book and book != "Other" else None,
           "sport": aur.norm_sport(sport) if sport and sport != "Other" else None, "odds": ov, "bucket": bucket,
           "net": None if net is None else round(float(net), 2)}
    r = {"date": date, "wins": int(result == "W"), "losses": int(result == "L"), "pushes": int(result == "P"),
         "net": bet["net"], "units": None, "note": note or "logged in the app",
         "entered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bets": [bet]}
    with LOCK:
        rows = aur.load(); rows.append(r); aur.save(rows)
    return r


def today_et():
    return datetime.now(ET).strftime("%Y-%m-%d")


# ---------- tracker ----------
def tracker_data():
    """Same data the Parlay Tracker Page uses (grade_slips.build_page_data), from the ledger + the last grades.json.
    Slips logged after the last grading count as pending."""
    slips = ll.load_ledger()
    try: g = json.load(open(gs.GRADES))
    except Exception: g = {"slips": [], "graded_at": None}
    by = {(x["run_ts"], x["slip_id"]): x for x in g.get("slips", [])}
    graded = [by.get((s["run_ts"], s["slip_id"])) or {"slip_id": s["slip_id"], "run_ts": s["run_ts"], "result": "pending", "profit": None,
              "settled_decimal": s["decimal"], "legs": [{"result": "pending"} for _ in s["legs"]]} for s in slips]
    d = gs.build_page_data(slips, graded)
    d["graded_at"] = g.get("graded_at")
    return d


def agg(facts, key):
    m = {}
    for x in facts:
        k = key(x)
        a = m.setdefault(k, {"k": k, "n": 0, "w": 0, "l": 0, "v": 0, "o": 0, "pend": 0, "units": 0.0, "staked": 0, "dsum": 0.0})
        a["n"] += 1; a["dsum"] += x["d"]
        r = x["r"]
        if r == "hit": a["w"] += 1
        elif r == "miss": a["l"] += 1
        elif r == "void": a["v"] += 1
        elif r == "pending": a["pend"] += 1
        else: a["o"] += 1
        if r in ("hit", "miss") and x["p"] is not None: a["units"] += x["p"]; a["staked"] += 1
    return list(m.values())


def records(data, strategy="all", lst="all"):
    """Record tables (book / odds target / sport / list), like the Page: regular rows, red flagged rows, blue 'You' rows."""
    flag_only = strategy.endswith("-flagged")
    pick = lambda src: [x for x in src if lst == "all" or x["l"] == lst]
    f = [x for x in pick(data["fFacts"]) if x["s"] == strategy] if flag_only else [x for x in pick(data["facts"]) if strategy == "all" or x["s"] == strategy]
    ff = pick(data["fFacts"]) if strategy == "all" else []
    dims = {"book": (lambda x: x["b"], "book"), "target": (lambda x: f"+{x['t']}", "odds"), "sport": (lambda x: x["sp"], "sport"),
            "list": (lambda x: gs.LIST_LABEL.get(x["l"], x["l"]), None)}
    out = {}
    for name, (key, udim) in dims.items():
        rows = []
        main = agg(f, key)
        main.sort(key=(lambda a: int(a["k"].lstrip("+"))) if name == "target" else (lambda a: (a["k"] in ("Mixed books", "Unknown"), a["k"])))
        fl = {a["k"]: a for a in agg(ff, key)}
        mine = {u["k"]: u for u in (data["userBreak"].get(udim, []) if udim else [])}
        used_f, used_u = set(), set()
        for a in main:
            rows.append(("flag" if flag_only else "main", a["k"], a))
            if a["k"] in fl: rows.append(("flag", "\u21b3 \U0001F534 Flagged", fl[a["k"]])); used_f.add(a["k"])
            if a["k"] in mine: rows.append(("you", "\u21b3 You", mine[a["k"]])); used_u.add(a["k"])
        rows += [("flag", f"\U0001F534 Flagged \u00b7 {k}", v) for k, v in fl.items() if k not in used_f]
        rows += [("you", f"You \u00b7 {k}", v) for k, v in mine.items() if k not in used_u]
        out[name] = rows
    return out


def dec_to_am(d):
    return f"+{round((d - 1) * 100)}" if d >= 2 else f"{-round(100 / (d - 1))}"
