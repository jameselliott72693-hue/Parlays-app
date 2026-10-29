"""Shared helpers for the slip ledger: parse report markdown into structured slips, append idempotently."""
import hashlib, json, os, re
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(ROOT, "ledger", "slips.jsonl")
BOOK_KEYS = {"FanDuel": "fanduel", "DraftKings": "draftkings", "BetMGM": "betmgm", "theScore Bet": "espnbet",
             "Caesars": "williamhill_us", "bet365": "bet365"}
STAT_LABELS = {
    "assists": "assists", "rebounds": "rebounds", "points": "points",
    "made threes": "three_points_made", "3-pointers made": "three_points_made", "threes": "three_points_made",
    "total receptions": "receiving_rec", "receptions": "receiving_rec",
    "pts + reb + ast": "pts_rebs_asts", "pts + rebs + asts": "pts_rebs_asts", "points_rebounds_assists": "pts_rebs_asts",
    "pts + reb": "pts_rebs", "pts + rebs": "pts_rebs", "pts + ast": "pts_asts", "pts + asts": "pts_asts",
    "reb + ast": "rebs_asts", "rebs + asts": "rebs_asts",
    "rush yards": "rushing_yds", "rushing yds": "rushing_yds", "rush_yds": "rushing_yds",
    "receiving yards": "receiving_yds", "receiving yds": "receiving_yds", "reception_yds": "receiving_yds",
    "pass yards": "passing_yds", "passing yds": "passing_yds", "pass_yds": "passing_yds",
    "passing tds": "passing_tds", "pass tds": "passing_tds", "pass_tds": "passing_tds",
    "rush + rec yards": "rush_rec_yds", "rushing + receiving yds": "rush_rec_yds",
    "steals": "steals", "blocks": "blocks",
    # hockey (Underdog "Shots"/"Goals", FanDuel "Goals", Odds API player_shots_on_goal / player_points)
    "shots on goal": "shots", "shots_on_goal": "shots", "shots": "shots", "goals": "goals", "saves": "saves",
    "pts_rebs_asts": "pts_rebs_asts", "points_rebounds_assists": "pts_rebs_asts", "threes_made": "three_points_made",
}

def book_key(name):
    name = name.strip()
    if name.startswith("Underdog"): return "underdog"
    return BOOK_KEYS.get(name, name.lower())

def parse_leg(label, game, book, price):
    away, home = [t.strip() for t in game.split(" @ ")] if " @ " in game else (None, None)
    leg = {"label": label, "event": game, "away": away, "home": home, "book": book_key(book),
           "american": int(price.replace("+", "")), "market": None, "team": None, "player": None,
           "stat": None, "line": None, "side": None}
    m = re.match(r"^Game (Over|Under) ([\d.]+)$", label)
    if m:
        leg.update(market="total", side=m.group(1).lower(), line=float(m.group(2))); return leg
    m = re.match(r"^(.+) ML$", label)
    if m:
        leg.update(market="ml", team=m.group(1), side=m.group(1)); return leg
    m = re.match(r"^(.+) ([+-][\d.]+)$", label)
    if m and m.group(1) in (away, home):
        leg.update(market="spread", team=m.group(1), side=m.group(1), line=float(m.group(2))); return leg
    m = re.match(r"^(.+?) (Over|Under) ([\d.]+) (.+)$", label)
    if m:
        st = STAT_LABELS.get(m.group(4).strip().lower())
        leg.update(market="prop", player=m.group(1), side=m.group(2).lower(), line=float(m.group(3)),
                   stat=st or ("unknown:" + m.group(4).strip()))
        return leg
    leg["market"] = "unknown"
    return leg

def parse_report(md_text, report_type):
    """Return (run_ts_iso, [slip dicts]) from a parlay report markdown."""
    m = re.search(r"(?:fetched|captured) (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC", md_text)
    run_ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).isoformat() if m else None
    sm = re.search(r"^Strategy: (v\d+)", md_text, re.M)
    strategy = sm.group(1) if sm else "v1"  # reports without a Strategy line predate v2
    slips, lst, target, cur = [], None, None, None
    flagged = False  # inside the "Flagged-price slips" section (strategy tag v2-flagged, report type "flagged")
    for line in md_text.splitlines():
        if line.startswith("## "):
            flagged = "Flagged-price slips" in line
            lst = None if flagged else "3leg" if "3-leg" in line else "sgp" if "Single-game" in line else "multi" if "Multi-game" in line else None
            cur = None; continue
        if flagged and line.startswith("### "):
            lst = "sgp" if "Single-game" in line else "multi" if "Multi-game" in line else None
            cur = None; continue
        if lst is None: continue
        m = re.match(r"^#{3,4} (?:\S+ )?(?:Flagged )?[Tt]arget ([+-]\d+)", line)
        if m: target = int(m.group(1)); cur = None; continue
        m = re.match(r"^(?:\S+ )?\*\*Slip (\d+): ([+-]\d+)\*\* \(decimal ([\d.]+)\) \| fair win prob ([\d.]+)% \| est\. EV ([+-][\d.]+)% \| book\(s\): ([^|]+?)(?: \| .*)?$", line)
        if m:
            cur = {"list": lst, "target": target, "slip_no": int(m.group(1)), "american": int(m.group(2)),
                   "decimal": float(m.group(3)), "fair_prob": float(m.group(4)) / 100, "est_ev": float(m.group(5)) / 100,
                   "books": sorted({book_key(b) for b in m.group(6).split(", ")}), "legs": [],
                   "report": "flagged" if flagged else report_type, "strategy": f"{strategy}-flagged" if flagged else strategy}
            km = re.search(r"\| (SGP-3|Multi-game-3)\b", line)
            if km: cur["kind"] = km.group(1)
            slips.append(cur); continue
        if cur is not None and line.startswith("Price shop"):
            cur.update(parse_price_shop(line)); continue
        if cur is not None and line.startswith("| ") and not line.startswith("| Leg ") and not line.startswith("|---"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4:
                cur["legs"].append(parse_leg(cells[0].replace("\U0001F534", "").strip(), cells[1], cells[2], cells[3]))
    return run_ts, slips

SHOP_ITEM = re.compile(r"^(\U0001F3C6 )?(?:\*\*)?(.+?) ([+-]\d+)(?:\*\*)?(?: \((.*)\))?$")

def parse_price_shop(line):
    """'Price shop (...): \U0001F3C6 **DraftKings +215** (this slip) \u00b7 FanDuel +200 \u00b7 ...' -> shop fields for the ledger record.
    shop = {book_key: american} for every book offering all legs; best_book / best_american = the best non-off-market price."""
    body = line.split(": ", 1)[1] if ": " in line else ""
    shop, best, off = {}, None, []
    for it in body.split(" \u00b7 "):
        it = it.strip()
        if not it or it.startswith("not offered at"): continue
        m = SHOP_ITEM.match(it)
        if not m: continue
        bk, am = book_key(m.group(2)), int(m.group(3).replace("+", ""))
        shop[bk] = am
        if m.group(4) and "off-market" in m.group(4): off.append(bk)
        if m.group(1): best = (bk, am)
    out = {"shop": shop}
    if best: out.update(best_book=best[0], best_american=best[1])
    if off: out["shop_off_market"] = off
    return out

def slip_id(slip):
    key = sorted((l["label"], l["event"], l["book"], l["american"]) for l in slip["legs"])
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()[:12]

def load_ledger():
    if not os.path.exists(LEDGER): return []
    return [json.loads(l) for l in open(LEDGER) if l.strip()]

def save_ledger(rows):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    tmp = LEDGER + ".tmp"
    with open(tmp, "w") as f:
        for r in sorted(rows, key=lambda r: (r["run_ts"], r["first_seen"]["report"], r["first_seen"]["list"], r["first_seen"]["target"], r["first_seen"]["slip_no"])):
            f.write(json.dumps(r) + "\n")
    os.replace(tmp, LEDGER)

def append_slips(run_ts, slips, source, leg_meta=None):
    """Idempotent: one record per (run_ts, slip_id); extra appearances (other report/list/target) are merged as tags."""
    rows = load_ledger()
    idx = {(r["run_ts"], r["slip_id"]): r for r in rows}
    added = tagged = 0
    for s in slips:
        sid = slip_id(s)
        app = {"report": s["report"], "list": s["list"], "target": s["target"], "slip_no": s["slip_no"]}
        legs = s["legs"]
        for l in legs:
            meta = (leg_meta or {}).get((l["label"], l["event"]))
            if meta: l.update({k: v for k, v in meta.items() if v is not None})
        r = idx.get((run_ts, sid))
        if r:
            if app not in r["appearances"]:
                r["appearances"].append(app); tagged += 1
            continue
        ps = {"under": sum(1 for l in legs if l.get("market") == "prop" and l.get("side") == "under"),
              "over": sum(1 for l in legs if l.get("market") == "prop" and l.get("side") == "over")}
        r = {"slip_id": sid, "run_ts": run_ts, "source": source, "strategy": s.get("strategy", "v1"), "prop_sides": ps,
             "list": s["list"], "american": s["american"],
             "decimal": s["decimal"], "fair_prob": s["fair_prob"], "est_ev": s["est_ev"], "books": s["books"],
             "legs": legs, "appearances": [app], "first_seen": app,
             **({"kind": s["kind"]} if s.get("kind") else {}),
             # v3 price shopping (absent on older rows): {book: american} for books offering all legs, and the best-paying book
             **({k: s[k] for k in ("shop", "best_book", "best_american", "shop_off_market") if s.get(k) is not None}),
             "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        rows.append(r); idx[(run_ts, sid)] = r; added += 1
    save_ledger(rows)
    return added, tagged

def run_has_report(run_ts, report_type):
    return any(r["run_ts"] == run_ts and any(a["report"] == report_type for a in r["appearances"]) for r in load_ledger())
