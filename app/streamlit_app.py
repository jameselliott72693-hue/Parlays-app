"""Parlay builder + tracker: a private, password-protected web app (Streamlit).

Run locally:   cd /workspace/parlays && APP_PASSWORD=... streamlit run app/streamlit_app.py
Secrets (env vars or .streamlit/secrets.toml / Streamlit Cloud "Secrets"): APP_PASSWORD (required), ODDS_API_KEY (optional:
adds DraftKings/BetMGM/theScore Bet), GITHUB_TOKEN + GH_REPO (+ optional GH_DATA_BRANCH) for durable storage on GitHub.
"""
import hmac, html, os, sys, time
from datetime import datetime, timezone

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
st.set_page_config(page_title="Parlays", page_icon="\U0001F3AF", layout="centered", initial_sidebar_state="collapsed")


def cfg(name, default=None):
    v = os.environ.get(name)
    if v: return v
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


# secrets -> environment for the builder (never displayed)
for _k in ("ODDS_API_KEY", "ODDS_MAX_CREDITS_PER_RUN"):
    if not os.environ.get(_k) and cfg(_k):
        os.environ[_k] = str(cfg(_k))

import services as S          # noqa: E402
from storage import get_storage  # noqa: E402

CSS = """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 3rem; max-width: 760px;}
.card {border: 1px solid #e3e6ea; border-radius: 14px; padding: 12px 14px; margin: 8px 0 12px; background: #fff;
       box-shadow: 0 1px 2px rgba(0,0,0,.04);}
.card.flag {border-color: #e57373; background: #fff6f6;}
.card .top {display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;}
.card .odds {font-size: 1.5rem; font-weight: 700;}
.card .book {font-weight: 600;}
.badge {font-size: .72rem; padding: 2px 8px; border-radius: 999px; background: #eef1f5; color: #445;}
.badge.red {background: #fde2e2; color: #b71c1c;}
.card .sub {color: #667; font-size: .85rem; margin: 2px 0 6px;}
.card ul {margin: 0 0 6px 0; padding-left: 18px;}
.card li {margin: 3px 0; font-size: .93rem;}
.card li small {color: #778;}
.shop {display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;}
.chip {font-size: .78rem; padding: 3px 8px; border-radius: 8px; background: #f2f4f7; color: #334;}
.chip.best {background: #e3f6e8; color: #136c2e; font-weight: 700; border: 1px solid #9fd9b0;}
.chip.this {outline: 1px dashed #99a;}
.chip.off {background: #fde2e2; color: #b71c1c;}
.chip.miss {background: transparent; color: #99a;}
table.trk {width: 100%; border-collapse: collapse; font-size: .82rem; margin: 4px 0 14px;}
table.trk th {text-align: left; color: #667; font-weight: 600; border-bottom: 1px solid #e3e6ea; padding: 4px 4px;}
table.trk td {padding: 4px 4px; border-bottom: 1px solid #f1f2f4; white-space: nowrap;}
table.trk tr.flag td {color: #c62828;}
table.trk tr.you td {color: #0b5fd8;}
.red {color: #c62828;} .blue {color: #0b5fd8;}
.small {font-size: .8rem; color: #667;}
.stats {display: flex; gap: 8px; margin: 4px 0 8px;}
.stats div {flex: 1; background: #fff; border: 1px solid #e3e6ea; border-radius: 12px; padding: 8px 10px;}
.stats b {display: block; font-size: 1.25rem;}
.stats span {font-size: .72rem; color: #667;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------- password gate ----------------
def gate():
    pw = cfg("APP_PASSWORD")
    if not pw:
        st.error("This app is locked: no APP_PASSWORD secret is set. Add APP_PASSWORD in the app's Secrets (see DEPLOY.md).")
        st.stop()
    if st.session_state.get("auth"):
        return
    st.title("\U0001F512 Parlays")
    with st.form("login"):
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Unlock", use_container_width=True)
    if ok:
        if hmac.compare_digest(p.encode("utf-8"), str(pw).encode("utf-8")):
            st.session_state["auth"] = True
            st.rerun()
        n = st.session_state["fails"] = st.session_state.get("fails", 0) + 1
        time.sleep(min(2 * n, 10))  # slow down guessing
        st.error("Wrong password.")
    st.stop()


gate()


# ---------------- storage ----------------
@st.cache_resource
def storage():
    return get_storage({k: cfg(k) for k in ("GITHUB_TOKEN", "GH_REPO", "GH_DATA_BRANCH", "STORAGE")})


STORE = storage()


def sync_down(force=False):
    last = st.session_state.get("pulled_at", 0)
    if force or time.time() - last > 300:
        try:
            STORE.pull()
            st.session_state["pulled_at"] = time.time()
        except Exception as ex:
            st.warning(f"Could not load the saved ledger: {ex}")


def sync_up(paths, msg):
    try:
        return STORE.push(paths, msg)
    except Exception as ex:
        st.error(f"Saved on this server only; GitHub save failed: {ex}")
        return None


sync_down()


@st.cache_data(ttl=600, show_spinner=False)
def balance():
    rem, used = S.odds_balance()
    return rem, used, datetime.now(S.ET).strftime("%-I:%M %p ET")


def et(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(S.ET).strftime("%a %-I:%M %p ET")
    except Exception:
        return ""


def fam(a):
    return f"+{a}" if a > 0 else str(a)


def card(s):
    e = html.escape
    badges = []
    if s["estimate"]: badges.append('<span class="badge">SGP price is an estimate</span>')
    if s.get("kind"): badges.append(f'<span class="badge">{e(s["kind"])}</span>')
    if s["flagged"]: badges.append('<span class="badge red">\U0001F534 flagged price: may be stale or a boost, check in app</span>')
    legs = "".join(
        f'<li>{"&#128308; " if l["flagged"] else ""}<b>{e(l["label"])}</b> <span class="small">{fam(l["american"])}</span><br>'
        f'<small>{e(l["event"])} · {e(et(l["start"]))} · fair {l["fair"]*100:.0f}% ({l["n_books_fair"]} books)</small></li>' for l in s["legs"])
    chips = []
    for o in s["shop"]:
        cls = "chip" + (" best" if o["best"] else "") + (" this" if o["this_slip"] else "") + (" off" if o["off_market"] else "")
        tag = (" \U0001F3C6" if o["best"] else "") + (" · this slip" if o["this_slip"] else "") + (" · pick'em" if o["pickem"] else "") + (" · off-market" if o["off_market"] else "")
        chips.append(f'<span class="{cls}">{e(o["name"])} {fam(o["american"])}{tag}</span>')
    if s["shop_missing"]:
        chips.append(f'<span class="chip miss">not at: {e(", ".join(s["shop_missing"]))}</span>')
    best = ""
    if s["best_book"] and s["best_book"] != s["book"]:
        best = f' · <b>best: {e(s["best_book"])} {fam(s["best_american"])}</b>'
    return (f'<div class="card{" flag" if s["flagged"] else ""}"><div class="top"><span class="odds">{fam(s["american"])}</span>'
            f'<span class="book">{e(s["book"])}</span>{"".join(badges)}</div>'
            f'<div class="sub">fair hit chance {s["fair_prob"]*100:.1f}% · est. EV {s["est_ev"]*100:+.1f}% · props U{s["props"]["under"]}/O{s["props"]["over"]}{best}</div>'
            f'<ul>{legs}</ul><div class="small">Price shop (same legs at each book):</div><div class="shop">{"".join(chips)}</div></div>')


def table(cols, rows):
    """rows: list of (kind, cells) where kind is main / flag / you."""
    e = html.escape
    h = "".join(f"<th>{e(c)}</th>" for c in cols)
    b = "".join(f'<tr class="{k}">' + "".join(f"<td>{e(str(c))}</td>" for c in cells) + "</tr>" for k, cells in rows)
    return f'<div style="overflow-x:auto"><table class="trk"><tr>{h}</tr>{b}</table></div>'


def units(x):
    return f"{x:+.2f}u"


def rec_cells(kind, label, a, with_odds):
    if kind == "you":
        amt = " / ".join(x for x in [f"{'+' if (a['net'] or 0) >= 0 else '-'}${abs(a['net']):.2f}" if a.get("net") is not None else "",
                                      units(a["units"]) if a.get("units") is not None else ""] if x) or "-"
        c = [label, f"{a['w']}-{a['l']}" + (f" ({a['p']}P)" if a.get("p") else ""), "-",
             f"{100*a['w']/(a['w']+a['l']):.0f}%" if a["w"] + a["l"] else "-", amt, "-"]
        return c + ([S.dec_to_am(a["dsum"] / a["dn"]) if a["dn"] else "-"] if with_odds else [])
    extra = ", ".join(x for x in [f"{a['v']} void" if a["v"] else "", f"{a['o']} ungr." if a["o"] else ""] if x)
    c = [label, f"{a['w']}-{a['l']}" + (f" ({extra})" if extra else ""), str(a["pend"]),
         f"{100*a['w']/(a['w']+a['l']):.0f}%" if a["w"] + a["l"] else "-",
         units(a["units"]) if a["staked"] else "-", f"{100*a['units']/a['staked']:+.0f}%" if a["staked"] else "-"]
    return c + ([S.dec_to_am(a["dsum"] / a["n"])] if with_odds else [])


# ---------------- UI ----------------
st.markdown("### \U0001F3AF Parlays")
tab_build, tab_track, tab_log = st.tabs(["Build", "Tracker", "Log my bet"])

with tab_build:
    key_present = bool(os.environ.get("ODDS_API_KEY"))
    rem, used, at = balance() if key_present else (None, None, None)
    c1, c2 = st.columns(2)
    c1.metric("Odds API credits left", "-" if rem is None else rem, help="Free call; refreshed every 10 minutes. Free plan = 500 per month.")
    sports = st.session_state.get("sports", S.ALL_SPORTS)
    try:
        sports = st.pills("Sports", S.ALL_SPORTS, selection_mode="multi", default=S.ALL_SPORTS, format_func=str.upper, key="sports_pills")
    except Exception:
        sports = st.multiselect("Sports", S.ALL_SPORTS, default=S.ALL_SPORTS, format_func=str.upper)
    ci = S.credit_info(sports or [], key_present)
    c2.metric("A fresh run costs", f"≤ {ci['worst']}" if key_present else "0", help="Worst case. Sports with no game in the next 48 h are skipped (0). Re-runs within 15 minutes reuse cached odds (0).")
    if key_present and ci["cached"]:
        st.caption(f"Odds cached {ci['cache_age_min']:.0f} min ago: a run in the next {ci['ttl_min'] - ci['cache_age_min']:.0f} min reuses them (about 0 credits).")
    elif not key_present:
        st.caption("No ODDS_API_KEY set: FanDuel + Underdog only (most slips need 3+ books, so expect few).")
    t1, t2 = st.columns(2)
    flagged = t1.toggle("Show flagged slips", value=False, help="Slips using a price far off the other books (went 1-for-10). Red. Off by default.")
    long_multi = t2.toggle("Multi-game +300/+400", value=False)
    mode = st.radio("Odds", ["Live odds", "Last snapshot (free, no logging)"], horizontal=True, label_visibility="collapsed")
    live = mode == "Live odds"
    if st.button("Build parlays", type="primary", use_container_width=True, disabled=not sports):
        if not live and not os.path.exists(S.SNAPSHOT):
            st.error("No saved snapshot yet: run once with live odds.")
        else:
            with st.spinner("Fetching odds and building slips (about 30-60 s)..."):
                sync_down(force=True)
                res = S.build(sports, flagged=flagged, show_long_multi=long_multi, live=live)
                if live and res.get("ledger") and "new slips" in res["ledger"]:
                    res["saved"] = sync_up(["ledger/slips.jsonl"], f"Log parlay run {res['generated']}")
                st.session_state["res"] = res
                balance.clear()
    res = st.session_state.get("res")
    if res:
        cr = res["credits"]
        st.caption(f"{res['status']} · strategy {res['strategy']} · Odds API: {cr['credits']} credits used, "
                   f"{cr['cache_hits']} cached (~{cr['saved']} saved)" + (f", skipped {', '.join(cr['skipped_sports'])}" if cr["skipped_sports"] else "")
                   + (f" · remaining {cr['remaining']}" if cr.get("remaining") is not None else ""))
        if res.get("ledger"): st.caption(f"Ledger: {res['ledger']}" + (f" · {res['saved']}" if res.get("saved") else ""))
        if not res["slips"]:
            st.warning("No slips met the rules (or no data). See the fetch log below.")
        lists = [("sgp", "SGP"), ("multi", "Multi-game"), ("3leg", "3-leg")]
        if any(s["flagged"] for s in res["slips"]): lists.append(("flagged", "\U0001F534 Flagged"))
        tabs = st.tabs([n for _, n in lists])
        for (lk, _), tb in zip(lists, tabs):
            with tb:
                sl = [s for s in res["slips"] if (s["flagged"] if lk == "flagged" else (s["list"] == lk and not s["flagged"]))]
                if lk == "multi" and not long_multi: st.caption("+300/+400 hidden (toggle above to show).")
                if not sl: st.info("No slips in this list."); continue
                for t in (100, 200, 300, 400):
                    ts = [s for s in sl if s["target"] == t]
                    if not ts: continue
                    st.markdown(f"**Target +{t}**" + ("" if len(ts) == 3 else f" <span class='small'>({len(ts)} of 3 met the rules)</span>"), unsafe_allow_html=True)
                    st.markdown("".join(card(s) for s in ts), unsafe_allow_html=True)
        if res["check_prices"]:
            with st.expander(f"\U0001F534 Check these prices ({len(res['check_prices'])})"):
                st.markdown(table(["Leg", "Book", "Price", "Others", "Gap"], [("flag", [c["label"], c["book"], fam(c["american"]),
                            ", ".join(f"{k} {fam(v)}" for k, v in c["others"].items()), f"{c['gap_pp']} pp"]) for c in res["check_prices"]]), unsafe_allow_html=True)
        with st.expander("Full report / fetch log"):
            st.download_button("Download report (.md)", res["md"] or "", file_name="parlays.md", use_container_width=True)
            st.code("\n".join(res["log"][-60:]))
    st.caption("Not betting advice. Re-check every price in the sportsbook app. Flat 0.5-1% of bankroll per slip.")

with tab_track:
    top = st.columns([3, 2])
    if top[1].button("Grade now", use_container_width=True, help="Settles finished games from ESPN box scores (free, ~10-60 s)."):
        with st.spinner("Grading from ESPN box scores..."):
            sync_down(force=True)
            out = S.grade()
            saved = sync_up(["ledger/grades.json", "ledger/page_contents.tsx.txt"], "Grade slips (app)")
        st.success("Graded. " + (saved or ""))
        with st.expander("Grader output"): st.code(out[-3000:])
    d = S.tracker_data()
    top[0].caption(f"Last graded: {et(d['graded_at']) if d.get('graded_at') else 'never'} · storage: {STORE.label}")
    o, fl = d["overall"], d["flagged"]
    hr = f"{100*o['hit']/(o['hit']+o['miss']):.1f}%" if o["hit"] + o["miss"] else "-"
    st.markdown(f"<div class='stats'><div><b>{o['hit']}-{o['miss']}</b><span>record · {o['pending']} pending</span></div>"
                f"<div><b>{hr}</b><span>hit rate</span></div><div><b>{units(o['profit'])}</b><span>{o['staked']} staked</span></div></div>",
                unsafe_allow_html=True)
    u = d["user"]
    uw, ul = sum(r["wins"] for r in u), sum(r["losses"] for r in u)
    unet = sum(r["net"] for r in u if r.get("net") is not None)
    st.markdown(f"<div class='red'>\U0001F534 Flagged ({', '.join(d['flagKeys']) or 'none'}): {fl['hit']}-{fl['miss']} · {units(fl['profit'])} · {fl['pending']} pending</div>"
                f"<div class='blue'>Your bets: {uw}-{ul} · net {'+' if unet >= 0 else '-'}${abs(unet):.2f} · {len(u)} days</div>", unsafe_allow_html=True)
    st.caption("Default = regular slips, red = flagged-price slips, blue = your own bets. Never added together. 1 unit per slip.")
    strategies = sorted({x["s"] for x in d["facts"]})
    f1, f2 = st.columns(2)
    strat = f1.selectbox("Strategy", ["all"] + strategies + d["flagKeys"], format_func=lambda x: "All strategies" if x == "all" else ("\U0001F534 " + x if x.endswith("-flagged") else x))
    lst = f2.selectbox("List", ["all", "sgp", "multi", "3leg"], format_func=lambda x: {"all": "All lists", "sgp": "SGP", "multi": "Multi-game", "3leg": "3-leg"}[x])
    st.markdown("**By strategy**")
    rows = [("main", [t["k"], t["n"], f"{t['hit']}-{t['miss']}", t["pending"], f"{100*t['hit']/(t['hit']+t['miss']):.0f}%" if t["hit"] + t["miss"] else "-", units(t["profit"])])
            for t in d["breakdown"]["strategy"]]
    rows += [("flag", ["\U0001F534 " + t["k"], t["n"], f"{t['hit']}-{t['miss']}", t["pending"], f"{100*t['hit']/(t['hit']+t['miss']):.0f}%" if t["hit"] + t["miss"] else "-", units(t["profit"])])
             for t in d["fBreakdown"]["strategy"]]
    st.markdown(table(["Strategy", "Slips", "W-L", "Pend.", "Hit", "Units"], rows), unsafe_allow_html=True)
    R = S.records(d, strat, lst)
    for name, title, with_odds in (("book", "By sportsbook", False), ("target", "By odds target", True), ("sport", "By sport", False), ("list", "By list", False)):
        st.markdown(f"**{title}**")
        cols = ["", "W-L", "Pend.", "Hit", "Units / $", "ROI"] + (["Avg odds"] if with_odds else [])
        st.markdown(table(cols, [(k, rec_cells(k, lbl, a, with_odds)) for k, lbl, a in R[name]]), unsafe_allow_html=True)
    if d["clv"]:
        st.markdown("**Closing line value** <span class='small'>(game lines; vs DraftKings close on ESPN)</span>", unsafe_allow_html=True)
        pp = lambda x: f"{x:+.2f}"
        st.markdown(table(["Strategy", "Legs", "Avg CLV", "Beat close", "ML / Spr / Tot"],
                          [("flag" if c["k"].endswith("-flagged") else "main",
                            [c["k"], c["n"], f"{pp(c['avg'])} pp", f"{c['beat']:.0f}%",
                             " / ".join(pp(c["mkt"][mk][1]) if c.get("mkt", {}).get(mk) else "-" for mk in ("ml", "spread", "total"))]) for c in d["clv"]]),
                    unsafe_allow_html=True)
    if d.get("shop"):
        sh = d["shop"]
        st.caption(f"Price shop (v3): another book paid more for the same legs on {sh['better']} of {sh['n']} slips"
                   + (f" (+{sh['avg_gain_pct']}% payout on average)." if sh["better"] else "."))
    with st.expander("Your bets (latest first)"):
        rows = []
        for r in reversed(u[-30:]):
            for b in (r.get("bets") or [None]):
                if b: rows.append(("you", [r["date"], b["result"], b.get("book") or "-", b.get("sport") or "-", fam(b["odds"]) if b.get("odds") else "-",
                                          f"{b['net']:+.2f}" if b.get("net") is not None else "-"]))
                else: rows.append(("you", [r["date"], f"{r['wins']}-{r['losses']}-{r.get('pushes') or 0}", r.get("book") or "-", r.get("sport") or "-",
                                          fam(r["odds"]) if r.get("odds") else "-", f"{r['net']:+.2f}" if r.get("net") is not None else "-"]))
        st.markdown(table(["Date", "Result", "Book", "Sport", "Odds", "Net $"], rows), unsafe_allow_html=True)

with tab_log:
    st.caption("Adds one of YOUR bets (kept apart from the generated slips; shown in blue on the tracker).")
    with st.form("logbet", clear_on_submit=True):
        res_ = st.radio("Result", ["W", "L", "P"], horizontal=True, format_func=lambda x: {"W": "Won", "L": "Lost", "P": "Push"}[x])
        a, b = st.columns(2)
        book = a.selectbox("Book", S.BOOK_CHOICES)
        sport = b.selectbox("Sport", S.SPORT_CHOICES)
        a, b = st.columns(2)
        odds = a.text_input("Odds (American)", placeholder="+250")
        net = b.number_input("Net $ (+ won / - lost)", value=0.0, step=1.0, format="%.2f")
        date = st.date_input("Date", value=datetime.now(S.ET).date())
        note = st.text_input("Note (optional)")
        go = st.form_submit_button("Log my bet", type="primary", use_container_width=True)
    if go:
        try:
            sync_down(force=True)
            r = S.log_bet(res_, book, sport, odds or None, net, date.strftime("%Y-%m-%d"), note or None)
            saved = sync_up(["ledger/user_results.jsonl"], f"Log my bet {r['date']} {res_}")
            st.success(f"Logged: {res_} {book} {sport} {odds or ''} {net:+.2f} on {r['date']}. " + (saved or ""))
        except ValueError as ex:
            st.error(f"Not logged: {ex}")
