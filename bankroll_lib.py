"""Bankroll ledger (ledger/bankroll.jsonl) and the numbers the app / Page show from it.

One JSON object per line:
  {"kind": "start" | "deposit" | "withdrawal", "amount": 500.0, "date": "2026-11-01", "note": "...", "entered_at": "<UTC ISO>"}
- "start" sets the bankroll on a date. A later "start" resets it (only the latest start counts; older history stays in the file).
- Deposits / withdrawals and your logged bets (user_results.jsonl) dated after the start date move it, plus those dated ON the
  start date that were entered after the start was set (the starting amount already includes that day's earlier bets).
  A bet with no net $ can't move it and is counted as "not in bankroll".
- Staking rule (the reports' note): flat 0.5-1% of bankroll per bet.
"""
import json, os
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
BANKROLL = os.path.join(ROOT, "ledger", "bankroll.jsonl")
KINDS = ("start", "deposit", "withdrawal")
STAKE_MIN_PCT, STAKE_MAX_PCT = 0.005, 0.01


def load(path=None):
    p = path or BANKROLL
    if not os.path.exists(p): return []
    with open(p) as f:
        return [json.loads(x) for x in f if x.strip()]


def save(rows, path=None):
    p = path or BANKROLL
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    os.replace(p + ".tmp", p)


def make_entry(kind, amount, date, note=None):
    if kind not in KINDS: raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    amount = round(float(amount), 2)
    if amount < 0 or (kind != "start" and amount == 0): raise ValueError("amount must be a positive number of dollars")
    datetime.strptime(date, "%Y-%m-%d")
    r = {"kind": kind, "amount": amount, "date": date, "entered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if note: r["note"] = note
    return r


def add(kind, amount, date, note=None, path=None):
    r = make_entry(kind, amount, date, note)
    rows = load(path); rows.append(r); save(rows, path)
    return r


def _bet_nets(user_rows):
    """(date, entered_at, net or None) per bet; a day logged as totals is one item."""
    out = []
    for r in user_rows:
        if r.get("bets"):
            for b in r["bets"]: out.append((r["date"], r.get("entered_at", ""), b.get("net")))
        else:
            out.append((r["date"], r.get("entered_at", ""), r.get("net")))
    return out


def _after(date, entered_at, st):
    return date > st["date"] or (date == st["date"] and (entered_at or "") > st.get("entered_at", ""))


def summary(entries, user_rows):
    """Current bankroll and its daily series. None when no starting bankroll has been set."""
    starts = [e for e in entries if e.get("kind") == "start"]
    if not starts: return None
    st = max(starts, key=lambda e: (e["date"], e.get("entered_at", "")))
    d0 = st["date"]
    moves = defaultdict(float)
    dep = wd = 0.0
    for e in entries:
        if e is st or e.get("kind") == "start" or not _after(e["date"], e.get("entered_at", ""), st): continue
        a = float(e["amount"])
        if e["kind"] == "deposit": dep += a; moves[e["date"]] += a
        elif e["kind"] == "withdrawal": wd += a; moves[e["date"]] -= a
    bets_net, n_bets, n_no_net = 0.0, 0, 0
    for d, ent, net in _bet_nets(user_rows):
        if not _after(d, ent, st): continue
        if net is None: n_no_net += 1; continue
        n_bets += 1; bets_net += net; moves[d] += net
    cur, series = float(st["amount"]), [(d0, round(float(st["amount"]), 2))]
    for d in sorted(moves):
        cur += moves[d]
        if d == d0: series[0] = (d0, round(cur, 2))
        else: series.append((d, round(cur, 2)))
    cur = round(cur, 2)
    return {"start": round(float(st["amount"]), 2), "start_date": d0, "current": cur, "deposits": round(dep, 2),
            "withdrawals": round(wd, 2), "bets_net": round(bets_net, 2), "n_bets": n_bets, "n_no_net": n_no_net,
            "series": series, "stake_min": round(max(cur, 0) * STAKE_MIN_PCT, 2), "stake_max": round(max(cur, 0) * STAKE_MAX_PCT, 2)}


def stake_check(stake, bankroll):
    """Warning text when a stake breaks the flat 0.5-1% rule, else None."""
    if stake is None or not bankroll or bankroll <= 0: return None
    lo, hi = bankroll * STAKE_MIN_PCT, bankroll * STAKE_MAX_PCT
    if stake > hi + 1e-9:
        return (f"${stake:.2f} is {100 * stake / bankroll:.1f}% of your ${bankroll:,.2f} bankroll, above your flat 0.5-1% rule. "
                f"Recommended stake: ${lo:.2f} - ${hi:.2f}.")
    return None
