"""Parlay builder + tracker: a private, password-protected web app (Streamlit).

Run locally:   cd /workspace/parlays && APP_PASSWORD=... streamlit run app/streamlit_app.py
Secrets (env vars or .streamlit/secrets.toml / Streamlit Cloud "Secrets"): APP_PASSWORD (required), ODDS_API_KEY (optional:
adds DraftKings/BetMGM/theScore Bet), GITHUB_TOKEN + GH_REPO (+ optional GH_DATA_BRANCH) for durable storage on GitHub.
"""
import hmac, html, os, re, sys, time
from datetime import datetime, timezone

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
st.set_page_config(page_title="Parlays", page_icon="🎯", layout="centered", initial_sidebar_state="collapsed")


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

CSS = """
<style>
/* ---- layout & chrome ---- */
.block-container {padding-top: 1rem; padding-bottom: 2.5rem; max-width: 760px;}
header[data-testid="stHeader"] {background: transparent;}
#MainMenu, footer, [data-testid="stToolbar"] {visibility: hidden; height: 0;}
div[data-testid="stDecoration"] {display: none;}

/* ---- pill tabs ---- */
div[data-testid="stTabs"] [data-baseweb="tab-list"],
div[data-testid="stTabs"] [role="tablist"] {
  gap: 6px !important; background: #0f1520 !important; padding: 6px !important;
  border-radius: 999px !important; border: 1px solid #243044 !important;
  margin-bottom: 0.6rem !important;
}
div[data-testid="stTabs"] [data-baseweb="tab"],
div[data-testid="stTabs"] [role="tab"] {
  border-radius: 999px !important; padding: 0.4rem 1rem !important;
  color: #9aacc4 !important; background: transparent !important; border: none !important;
}
div[data-testid="stTabs"] [role="tab"][aria-selected="true"],
div[data-testid="stTabs"] [role="tab"][data-selected="true"],
div[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
  background: #1e293b !important; color: #e8eef7 !important;
  box-shadow: 0 0 0 1px #38bdf855, inset 0 0 12px #38bdf811 !important;
}
div[data-testid="stTabs"] [data-baseweb="tab-highlight"],
div[data-testid="stTabs"] [data-baseweb="tab-border"] {display: none !important; height: 0 !important;}

/* ---- buttons ---- */
.stButton > button, .stFormSubmitButton > button {
  border-radius: 12px; font-weight: 600; letter-spacing: .01em;
  border: 1px solid #2a3a52; transition: transform .12s ease, box-shadow .12s ease, background .12s ease;
  padding-top: 0.55rem; padding-bottom: 0.55rem;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"], .stFormSubmitButton > button[data-testid="baseButton-primary"] {
  background: linear-gradient(180deg, #38bdf8 0%, #0ea5e9 100%);
  color: #041018; border: none;
  box-shadow: 0 4px 14px rgba(56, 189, 248, .28);
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(0,0,0,.28);
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover,
.stButton > button[data-testid="baseButton-primary"]:hover, .stFormSubmitButton > button[data-testid="baseButton-primary"]:hover {
  box-shadow: 0 6px 20px rgba(56, 189, 248, .4);
}

/* ---- inputs ---- */
div[data-baseweb="select"] > div, .stTextInput input, .stNumberInput input, .stTextArea textarea,
div[data-baseweb="input"] {
  border-radius: 10px !important; border-color: #2a3a52 !important;
  background-color: #121826 !important;
}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
  border-color: #38bdf8 !important; box-shadow: 0 0 0 1px #38bdf855 !important;
}

/* ---- metrics ---- */
div[data-testid="stMetric"] {
  background: #151b24; border: 1px solid #243044; border-radius: 14px;
  padding: 12px 14px; box-shadow: 0 1px 0 rgba(255,255,255,.03), 0 8px 24px rgba(0,0,0,.22);
}
div[data-testid="stMetric"] label {color: #8b9bb4 !important; font-size: .78rem !important;}
div[data-testid="stMetricValue"] {font-size: 1.45rem !important; color: #e8eef7 !important;}
/* Keep metric rows as a real 2x2 on phones (Streamlit otherwise stacks each column). */
div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) {
  flex-wrap: nowrap !important; gap: 0.5rem !important;
}
div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) > div[data-testid="stColumn"] {
  flex: 1 1 50% !important; min-width: 0 !important; width: 50% !important;
}

/* ---- cards (slips) ---- */
.card {
  border: 1px solid #243044; border-radius: 16px; padding: 14px 16px; margin: 8px 0 12px;
  background: linear-gradient(180deg, #171e2a 0%, #121826 100%);
  box-shadow: 0 1px 0 rgba(255,255,255,.04), 0 10px 28px rgba(0,0,0,.28);
}
.card.flag {border-color: #7f1d1d; background: linear-gradient(180deg, #2a1518 0%, #1a1012 100);}
.card .top {display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;}
.card .odds {font-size: 1.55rem; font-weight: 700; color: #e8eef7; letter-spacing: -.02em;}
.card .book {font-weight: 600; color: #cbd5e1;}
.badge {font-size: .72rem; padding: 3px 9px; border-radius: 999px; background: #1e293b; color: #9aacc4; border: 1px solid #2a3a52;}
.badge.red {background: #3f1215; color: #fca5a5; border-color: #7f1d1d;}
.card .sub {color: #8b9bb4; font-size: .85rem; margin: 4px 0 8px;}
.card ul {margin: 0 0 8px 0; padding-left: 18px;}
.card li {margin: 4px 0; font-size: .93rem; color: #d5deea;}
.card li small {color: #8b9bb4;}
.shop {display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;}
.chip {font-size: .78rem; padding: 4px 9px; border-radius: 999px; background: #1e293b; color: #cbd5e1; border: 1px solid #2a3a52;}
.chip.best {background: #0c2a24; color: #6ee7b7; font-weight: 700; border-color: #134e4a;}
.chip.this {outline: 1px dashed #64748b;}
.chip.off {background: #3f1215; color: #fca5a5; border-color: #7f1d1d;}
.chip.miss {background: transparent; color: #64748b; border-style: dashed;}

/* ---- tracker table ---- */
table.trk {width: 100%; border-collapse: collapse; font-size: .82rem; margin: 4px 0 14px;}
table.trk th {text-align: left; color: #8b9bb4; font-weight: 600; border-bottom: 1px solid #243044; padding: 6px 6px;}
table.trk td {padding: 6px 6px; border-bottom: 1px solid #1a2230; white-space: nowrap; color: #d5deea;}
table.trk tr.flag td {color: #f87171;}
table.trk tr.you td {color: #60a5fa;}
.red {color: #f87171;} .blue {color: #60a5fa;}
.small {font-size: .8rem; color: #8b9bb4;}

/* ---- password gate ---- */
.gate-wrap {max-width: 380px; margin: 12vh auto 0; text-align: center;}
.gate-card {
  background: linear-gradient(180deg, #171e2a 0%, #121826 100%);
  border: 1px solid #243044; border-radius: 20px; padding: 28px 24px 22px;
  box-shadow: 0 1px 0 rgba(255,255,255,.04), 0 24px 48px rgba(0,0,0,.45);
}
.gate-card h1 {font-size: 1.55rem; margin: 0 0 4px; letter-spacing: -.02em;}
.gate-card p {color: #8b9bb4; font-size: .9rem; margin: 0 0 18px;}
.gate-icon {
  width: 48px; height: 48px; margin: 0 auto 14px; border-radius: 14px;
  background: linear-gradient(180deg, #1e3a4f 0%, #0f2740 100%);
  border: 1px solid #2a4a66; display: flex; align-items: center; justify-content: center;
  font-size: 1.35rem; color: #38bdf8;
}

/* ---- section header ---- */
.app-head {display: flex; align-items: center; gap: 10px; margin: 0 0 0.4rem;}
.app-head .mark {
  width: 36px; height: 36px; border-radius: 10px;
  background: linear-gradient(180deg, #1e3a4f 0%, #0f2740 100%);
  border: 1px solid #2a4a66; display: flex; align-items: center; justify-content: center;
  color: #38bdf8; font-size: 1.1rem; flex-shrink: 0;
}
.app-head h1 {font-size: 1.35rem; margin: 0; letter-spacing: -.02em; font-weight: 700;}
.app-head span {color: #8b9bb4; font-size: .82rem;}

/* ---- legend chips ---- */
.legend {display: flex; flex-wrap: wrap; gap: 8px; margin: 2px 0 10px;}
.legend span {
  font-size: .75rem; padding: 3px 10px; border-radius: 999px;
  border: 1px solid #2a3a52; background: #151b24; color: #9aacc4;
}
.legend .you {color: #60a5fa; border-color: #1e3a5f; background: #0f1a2c;}
.legend .flag {color: #f87171; border-color: #5c1d1d; background: #1a1012;}

/* ---- mobile ---- */
@media (max-width: 480px) {
  .block-container {padding-left: 0.85rem; padding-right: 0.85rem;}
  .card {padding: 12px;}
  .card .odds {font-size: 1.35rem;}
  .stTabs [data-baseweb="tab"] {padding: 0.3rem 0.7rem; font-size: .9rem;}
  div[data-testid="stMetric"] {padding: 8px 10px;}
  div[data-testid="stMetricValue"] {font-size: 1.05rem !important;}
  div[data-testid="stMetricLabel"] p {font-size: .7rem !important;}
  div[data-testid="stMetricDelta"] {font-size: .72rem !important;}
}
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
    st.markdown(
        '<div class="gate-wrap"><div class="gate-card">'
        '<div class="gate-icon">🔒</div>'
        "<h1>Parlays</h1>"
        "<p>Private tracker · enter your password to continue</p>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    # nest the form under the visual card by keeping it tight; Streamlit can't put widgets inside raw HTML
    with st.form("login"):
        p = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
        ok = st.form_submit_button("Unlock", type="primary", use_container_width=True)
    if ok:
        if hmac.compare_digest(p.encode("utf-8"), str(pw).encode("utf-8")):
            st.session_state["auth"] = True
            st.rerun()
        n = st.session_state["fails"] = st.session_state.get("fails", 0) + 1
        time.sleep(min(2 * n, 10))  # slow down guessing
        st.error("Wrong password.")
    st.stop()


gate()

# The heavier app modules (builder, grader, slip reader) load only after the password screen, so it paints at once.
import services as S          # noqa: E402
import slip_reader as SR      # noqa: E402
from storage import get_storage, LocalStorage  # noqa: E402


# ---------------- storage ----------------
@st.cache_resource(show_spinner=False)
def storage():
    return get_storage({k: cfg(k) for k in ("GITHUB_TOKEN", "GH_REPO", "GH_DATA_BRANCH", "STORAGE")})


try:
    STORE = storage()
except Exception as _ex:  # a malformed secret must not stop the app from opening
    STORE = LocalStorage()
    st.warning(f"GitHub storage is not set up correctly ({type(_ex).__name__}); using this server's files only.")
if (STORE.kind == "local" and (cfg("STORAGE") or "").lower() != "local"
        and bool(cfg("GITHUB_TOKEN")) != bool(cfg("GH_REPO"))):
    st.warning("GitHub storage needs both GITHUB_TOKEN and GH_REPO in the app's Secrets; only one is set, so bets are saved on "
               "this server only (lost when the app restarts).")


def sync_down(force=False):
    """Pull the ledger from GitHub at most every 5 minutes per session (always before an action). A pull whose branch head
    has not moved costs one API call. A GitHub outage only shows a warning; the app keeps working on the local copy."""
    last = st.session_state.get("pulled_at", 0)
    if force or time.time() - last > 300:
        try:
            if last: STORE.pull()
            else:
                with st.spinner("Loading your saved ledger..."): STORE.pull()  # first load of a session (cold start)
            st.session_state["pulled_at"] = time.time()
        except Exception as ex:
            st.session_state["pulled_at"] = time.time() - 240  # retry in about a minute, not on every rerun
            st.warning(f"Could not load the saved ledger (showing the copy on this server): {ex}")


def sync_up(paths, msg):
    try:
        return STORE.push(paths, msg)
    except Exception as ex:
        st.error(f"Saved on this server only; GitHub save failed: {ex}")
        return None


sync_down()


@st.cache_data(ttl=600, show_spinner=False, max_entries=4)
def tracker_cached(sig):
    """Tracker data, recomputed only when a ledger file changed (sig = mtimes/sizes) or after 10 minutes. Every widget
    click reruns the script; this keeps the tracker tab from re-reading ~1 MB of ledger and regrouping it each time."""
    return S.tracker_data()


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
    if s["flagged"]: badges.append('<span class="badge red">flagged price · may be stale or a boost</span>')
    legs = "".join(
        f'<li>{"● " if l["flagged"] else ""}<b>{e(l["label"])}</b> <span class="small">{fam(l["american"])}</span><br>'
        f'<small>{e(l["event"])} · {e(et(l["start"]))} · fair {l["fair"]*100:.0f}% ({l["n_books_fair"]} books)</small></li>' for l in s["legs"])
    chips = []
    for o in s["shop"]:
        cls = "chip" + (" best" if o["best"] else "") + (" this" if o["this_slip"] else "") + (" off" if o["off_market"] else "")
        tag = (" ★" if o["best"] else "") + (" · this slip" if o["this_slip"] else "") + (" · pick'em" if o["pickem"] else "") + (" · off-market" if o["off_market"] else "")
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
st.markdown(
    '<div class="app-head"><div class="mark">◎</div><div><h1>Parlays</h1>'
    '<span>Build · track · log — private</span></div></div>',
    unsafe_allow_html=True,
)
tab_build, tab_track, tab_log = st.tabs([
    ":material/construction: Build",
    ":material/monitoring: Tracker",
    ":material/edit_note: Log my bet",
])

with tab_build:
    key_present = bool(os.environ.get("ODDS_API_KEY"))
    rem, used, at = balance() if key_present else (None, None, None)
    c1, c2 = st.columns(2)
    c1.metric("Odds API credits left", "-" if rem is None else rem, help="Free call; refreshed every 10 minutes. Free plan = 500 per month.")
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
    try:
        mode = st.segmented_control(
            "Odds",
            options=["Live odds", "Last snapshot (free, no logging)"],
            default="Live odds",
            key="odds_mode",
            label_visibility="collapsed",
        )
    except Exception:
        mode = st.radio("Odds", ["Live odds", "Last snapshot (free, no logging)"], horizontal=True, label_visibility="collapsed")
    if mode is None:
        mode = "Live odds"
    live = mode == "Live odds"
    if st.button("Build parlays", type="primary", use_container_width=True, disabled=not sports):
        if not live and not os.path.exists(S.SNAPSHOT):
            st.error("No saved snapshot yet: run once with live odds.")
        else:
            with st.status("Fetching odds and building slips…", expanded=True) as status:
                st.write("Pulling ledger / reading odds…")
                if live: sync_down(force=True)  # a snapshot replay never logs, so it needs no fresh ledger
                try:
                    res = S.build(sports, flagged=flagged, show_long_multi=long_multi, live=live)
                except Exception as ex:
                    res = None
                    status.update(label="Build failed", state="error")
                    st.error(f"Build failed: {type(ex).__name__}: {ex}")
                if res is not None:
                    m = re.search(r": (\d+) new slips, (\d+) duplicate tags", res.get("ledger") or "")
                    if live and m and int(m.group(1)) + int(m.group(2)) > 0:  # skip the GitHub round trip when nothing was logged
                        st.write("Saving new slips…")
                        res["saved"] = sync_up(["ledger/slips.jsonl"], f"Log parlay run {res['generated']}")
                    st.session_state["res"] = res
                    status.update(label=f"Built {len(res['slips'])} slips", state="complete")
                if live: balance.clear()
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
        if any(s["flagged"] for s in res["slips"]): lists.append(("flagged", "Flagged"))
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
            with st.expander(f":material/warning: Check these prices ({len(res['check_prices'])})"):
                st.markdown(table(["Leg", "Book", "Price", "Others", "Gap"], [("flag", [c["label"], c["book"], fam(c["american"]),
                            ", ".join(f"{k} {fam(v)}" for k, v in c["others"].items()), f"{c['gap_pp']} pp"]) for c in res["check_prices"]]), unsafe_allow_html=True)
        with st.expander(":material/description: Full report / fetch log"):
            st.download_button("Download report (.md)", res["md"] or "", file_name="parlays.md", use_container_width=True)
            st.code("\n".join(res["log"][-60:]))
    st.caption("Not betting advice. Re-check every price in the sportsbook app. Flat 0.5-1% of bankroll per slip.")

with tab_track:
    top = st.columns([3, 2])
    if top[1].button("Grade now", use_container_width=True, help="Settles finished games from ESPN box scores (free, ~10-60 s)."):
        with st.status("Grading from ESPN box scores…", expanded=False) as status:
            sync_down(force=True)
            try:
                out, err = S.grade(), None
            except Exception as ex:
                out, err = "", f"{type(ex).__name__}: {ex}"
            saved = None if err else sync_up(["ledger/grades.json", "ledger/page_contents.tsx.txt"], "Grade slips (app)")
            if err:
                status.update(label="Grading failed", state="error")
                st.error(f"Grading failed (nothing saved): {err}")
            else:
                status.update(label="Graded", state="complete")
                st.success("Graded. " + (saved or ""))
                st.toast("Grading done", icon="✅")
                with st.expander("Grader output"): st.code(out[-3000:])
    d = tracker_cached(S.ledger_signature())
    top[0].caption(f"Last graded: {et(d['graded_at']) if d.get('graded_at') else 'never'} · storage: {STORE.label}")
    o, fl = d["overall"], d["flagged"]
    hr = f"{100*o['hit']/(o['hit']+o['miss']):.1f}%" if o["hit"] + o["miss"] else "-"
    u = d["user"]
    uw, ul = sum(r["wins"] for r in u), sum(r["losses"] for r in u)
    unet = sum(r["net"] for r in u if r.get("net") is not None)
    br, roi = d.get("bankroll"), (d.get("userPays") or {}).get("roi") or {}
    logged_roi = (roi.get("logged") or {})
    roi_val = logged_roi.get("roi")
    roi_n = logged_roi.get("n") or 0
    graded_n = o["hit"] + o["miss"]
    # 2x2 metric grid: never put a signed P&L in a delta_color="inverse" slot, and never put a
    # non-numeric caption in a slot that auto-picks an up/down arrow (that caused green losses).
    r1, r2 = st.columns(2)
    r1.metric("Record", f"{o['hit']}-{o['miss']}",
              delta=f"{o['pending']} pending", delta_color="off", delta_arrow="off",
              help="Generated slips (regular lists). Pending = not yet graded.")
    r2.metric("Hit rate", hr,
              delta=(f"of {graded_n} graded" if graded_n else "no graded slips"),
              delta_color="off", delta_arrow="off")
    r3, r4 = st.columns(2)
    r3.metric("Net units", units(o["profit"]),
              delta=float(o["profit"]), delta_color="normal", delta_arrow="auto",
              delta_description="generated slips · 1u each",
              help="Profit on generated slips at 1 unit each. Not your logged bets.")
    your_net_val = (f"{'+' if unet >= 0 else '-'}${abs(unet):.2f}" if (uw + ul) else "—")
    r4.metric("Your net", your_net_val,
              delta=(float(unet) if (uw + ul) else None),
              delta_color="normal", delta_arrow="auto",
              delta_description=(f"record {uw}-{ul}" if (uw + ul) else "no bets"),
              help="Your logged bets only (blue on the tables). ROI is shown below with its stake basis.")
    st.markdown(
        '<div class="legend">'
        '<span>regular slips</span>'
        '<span class="you">your bets</span>'
        '<span class="flag">flagged price</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="red">Flagged ({", ".join(d["flagKeys"]) or "none"}): {fl["hit"]}-{fl["miss"]} · {units(fl["profit"])} · {fl["pending"]} pending</div>'
        f'<div class="blue">Your bets: {uw}-{ul} · net {"+" if unet >= 0 else "-"}${abs(unet):.2f} · {len({r["date"] for r in u})} days</div>',
        unsafe_allow_html=True,
    )
    pct = lambda r: (f"{r['roi']:+.1f}% ({r['n']} bet{'' if r['n'] == 1 else 's'})" if r and r.get("roi") is not None else "-")
    # Keep the literal "Bankroll $" substring for AppTest smoke checks
    roi_logged_txt = (
        f"ROI on {roi_n} logged stake{'s' if roi_n != 1 else ''} {roi_val:+.1f}%"
        if roi_val is not None else "ROI on logged stakes -"
    )
    st.markdown("<div class='blue'>" + (f"💰 Bankroll ${br['current']:,.2f} · flat 0.5-1% stake ${br['stake_min']:.2f}-${br['stake_max']:.2f}"
                                       if br else "💰 Bankroll not set (open the bankroll panel below)")
                + f" · {roi_logged_txt}"
                + (f" · incl. derived stakes for {roi['all'].get('derived', 0)} older bets {pct(roi.get('all'))}" if roi.get("all") and roi["all"].get("derived") else "")
                + "</div>", unsafe_allow_html=True)
    st.caption("Default = regular slips, red = flagged-price slips, blue = your own bets. Never added together. 1 unit per slip.")
    with st.expander(":material/account_balance_wallet: Bankroll and what pays (your bets)"):
        if br:
            import pandas as pd
            st.markdown(f"<div class='blue'>Started ${br['start']:,.2f} on {br['start_date']}"
                        + (f" · deposits ${br['deposits']:,.2f}" if br["deposits"] else "") + (f" · withdrawals ${br['withdrawals']:,.2f}" if br["withdrawals"] else "")
                        + f" · your bets net {'+' if br['bets_net'] >= 0 else '-'}${abs(br['bets_net']):,.2f} over {br['n_bets']} bets"
                        + (f" · {br['n_no_net']} bets without net $ not counted" if br["n_no_net"] else "") + "</div>", unsafe_allow_html=True)
            if len(br["series"]) > 1:
                df = pd.DataFrame(br["series"], columns=["date", "Bankroll $"])
                df["date"] = pd.to_datetime(df["date"])
                st.line_chart(df.set_index("date"), height=170, color="#38bdf8")
        with st.form("bankroll", clear_on_submit=True):
            k1, k2, k3 = st.columns([3, 2, 2])
            kind = k1.selectbox("Bankroll entry", ["start", "deposit", "withdrawal"],
                                format_func=lambda x: {"start": "Set starting bankroll", "deposit": "Deposit", "withdrawal": "Withdrawal"}[x])
            amt = k2.number_input("Amount $", min_value=0.0, value=None, step=10.0, format="%.2f")
            bdate = k3.date_input("Date", value=datetime.now(S.ET).date(), key="br_date")
            bnote = st.text_input("Note (optional)", key="br_note")
            if st.form_submit_button("Save bankroll entry", type="primary", use_container_width=True):
                try:
                    if amt is None: raise ValueError("enter an amount")
                    sync_down(force=True)
                    S.bankroll_add(kind, amt, bdate.strftime("%Y-%m-%d"), bnote or None)
                    saved = sync_up(["ledger/bankroll.jsonl"], f"Bankroll {kind} {bdate}")
                    st.success(f"Saved: {kind} ${amt:,.2f} on {bdate}. " + (saved or ""))
                    st.toast("Bankroll updated", icon="💰")
                except ValueError as ex:
                    st.error(f"Not saved: {ex}")
        st.caption("A new starting bankroll replaces the old one. Bets dated after its date (and that day's bets logged after you set it) move it; bets without a net $ can't.")
        up_ = d.get("userPays") or {}
        if up_.get("nBets"):
            try:
                dim = st.segmented_control(
                    "What pays, by",
                    options=["sport", "legs", "type", "odds", "book"],
                    format_func=lambda x: {"sport": "Sport", "legs": "Legs", "type": "Bet type", "odds": "Odds", "book": "Book"}[x],
                    default="sport",
                    key="pays_dim",
                )
            except Exception:
                dim = st.radio("What pays, by", ["sport", "legs", "type", "odds", "book"], horizontal=True, key="pays_dim",
                               format_func=lambda x: {"sport": "Sport", "legs": "Legs", "type": "Bet type", "odds": "Odds", "book": "Book"}[x])
            if dim is None:
                dim = "sport"
            rows = []
            for r in up_["dims"].get(dim, []) + [dict(up_["overall"], k="Overall")]:
                rows.append(("you", [r["k"], r["n"], f"{r['w']}-{r['l']}-{r['p']}",
                                     f"${r['staked']:.2f}" + (f" ({r['sn']}/{r['n']})" if r["sn"] < r["n"] else "") if r["sn"] else "-",
                                     f"{'+' if r['net'] >= 0 else '-'}${abs(r['net']):.2f}" if r["netN"] else "-",
                                     f"{100 * r['snet'] / r['staked']:+.0f}%" if r["sn"] and r["staked"] else "-"]))
            st.markdown(table(["", "Bets", "W-L-P", "Staked", "Net $", "ROI"], rows), unsafe_allow_html=True)
            st.caption("Missing: " + "; ".join(up_.get("gaps", [])) + ".")
    strategies = sorted({x["s"] for x in d["facts"]} - set(d["flagKeys"]))
    f1, f2 = st.columns(2)
    strat = f1.selectbox("Strategy", ["all"] + strategies + d["flagKeys"], format_func=lambda x: "All strategies" if x == "all" else ("⚑ " + x if x.endswith("-flagged") else x))
    lst = f2.selectbox("List", ["all", "sgp", "multi", "3leg"], format_func=lambda x: {"all": "All lists", "sgp": "SGP", "multi": "Multi-game", "3leg": "3-leg"}[x])
    st.markdown("**By strategy**")
    rows = [("main", [t["k"], t["n"], f"{t['hit']}-{t['miss']}", t["pending"], f"{100*t['hit']/(t['hit']+t['miss']):.0f}%" if t["hit"] + t["miss"] else "-", units(t["profit"])])
            for t in d["breakdown"]["strategy"]]
    rows += [("flag", ["⚑ " + t["k"], t["n"], f"{t['hit']}-{t['miss']}", t["pending"], f"{100*t['hit']/(t['hit']+t['miss']):.0f}%" if t["hit"] + t["miss"] else "-", units(t["profit"])])
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
    with st.expander(":material/history: Your bets (latest first)"):
        rows = []
        for r in reversed(u[-30:]):
            for b in (r.get("bets") or [None]):
                src = b or r
                typ = " · ".join(x for x in [src.get("type") or "", f"{src['legs']}L" if src.get("legs") else ""] if x) or "-"
                stake = f"{src['stake']:.2f}" if src.get("stake") is not None else "-"
                if b: rows.append(("you", [r["date"], b["result"], b.get("book") or "-", b.get("sport") or "-", fam(b["odds"]) if b.get("odds") else "-",
                                          typ, stake, f"{b['net']:+.2f}" if b.get("net") is not None else "-"]))
                else: rows.append(("you", [r["date"], f"{r['wins']}-{r['losses']}-{r.get('pushes') or 0}", r.get("book") or "-", r.get("sport") or "-",
                                          fam(r["odds"]) if r.get("odds") else "-", typ, stake, f"{r['net']:+.2f}" if r.get("net") is not None else "-"]))
        st.markdown(table(["Date", "Result", "Book", "Sport", "Odds", "Type", "Stake", "Net $"], rows), unsafe_allow_html=True)

FORM_KEYS = ("f_result", "f_book", "f_sport", "f_date", "f_odds", "f_legs", "f_type", "f_stake", "f_net", "f_leglist", "f_note", "f_payout")


def prefill(p):
    """Copy a parsed slip into the bet form's widget state (the user still checks everything before saving)."""
    ss = st.session_state
    ss["f_result"] = p.get("result")
    ss["f_book"] = p["book"] if p.get("book") in S.BOOK_CHOICES else "Other"
    ss["f_sport"] = p.get("sport") or "Other"
    try: ss["f_date"] = datetime.strptime(p["date"], "%Y-%m-%d").date()
    except Exception: ss["f_date"] = datetime.now(S.ET).date()
    ss["f_odds"] = fam(p["odds"]) if p.get("odds") is not None else ""
    ss["f_legs"] = p.get("legs")
    ss["f_type"] = p.get("bet_type") or "-"
    ss["f_stake"] = p.get("stake")
    ss["f_net"] = p.get("net")
    ss["f_payout"] = p.get("payout")
    ss["f_leglist"] = "\n".join(p.get("leg_list") or [])
    ss["f_note"] = "read from a slip" + (f" (book: {p['book']})" if p.get("book") and p["book"] not in S.BOOK_CHOICES else "")


def clear_form():
    for k in FORM_KEYS + ("slip_parsed",): st.session_state.pop(k, None)


with tab_log:
    st.caption("Adds one of YOUR bets (kept apart from the generated slips; shown in blue on the tracker).")
    if st.session_state.get("log_msg"):
        st.success(st.session_state.pop("log_msg"))
        st.toast("Bet saved", icon="✅")
    with st.expander(":material/receipt_long: Read a bet slip (paste the text or upload a screenshot)", expanded=not st.session_state.get("slip_parsed")):
        st.caption("DraftKings, FanDuel, Caesars, theScore Bet, BetMGM, Underdog (others best-effort). Nothing is saved until you press Save below.")
        slip_txt = st.text_area("Bet slip text", key="slip_text", height=140, placeholder="Copy the bet from your sportsbook's bet history and paste it here")
        ocr_ok, ocr_msg = SR.ocr_status()
        shot = st.file_uploader("...or a screenshot", type=["png", "jpg", "jpeg", "webp"], key="slip_img",
                                disabled=not ocr_ok, help=None if ocr_ok else ocr_msg)
        if not ocr_ok: st.caption(ocr_msg)
        if st.button("Read slip", use_container_width=True, disabled=not (slip_txt.strip() or shot)):
            text, err = slip_txt, None
            if shot is not None:
                with st.spinner("Reading the screenshot (free OCR, a few seconds)..."):
                    ocr_text, err = SR.ocr_image(shot.getvalue())
                if ocr_text: text = ocr_text + ("\n" + slip_txt if slip_txt.strip() else "")
            if err and not text.strip():
                st.error(err)
            else:
                if err: st.warning(err + " Using the pasted text.")
                p = SR.parse_slip(text, today=datetime.now(S.ET).date())
                p["ocr"] = shot is not None and not err
                p["raw"] = text
                st.session_state["slip_parsed"] = p
                prefill(p)
                st.toast("Slip read — check the fields", icon="📋")
                st.rerun()
    p = st.session_state.get("slip_parsed")
    if p:
        st.info("Filled in from the slip" + (" (screenshot OCR: double-check every number)" if p.get("ocr") else "")
                + ". Check every field and fix anything wrong, then press **Save bet**.")
        if p.get("notes"): st.caption("Reader notes: " + "; ".join(p["notes"]) + ".")
        if p.get("ocr"):
            with st.expander("Text read from the screenshot"): st.code(p.get("raw", "")[:3000])
    ss = st.session_state
    for k, v in (("f_result", None), ("f_book", S.BOOK_CHOICES[0]), ("f_sport", S.SPORT_CHOICES[0]), ("f_date", datetime.now(S.ET).date()),
                 ("f_odds", ""), ("f_legs", None), ("f_type", "-"), ("f_stake", None), ("f_net", None), ("f_leglist", ""), ("f_note", "")):
        ss.setdefault(k, v)  # defaults live in session state, so prefilled values never clash with widget defaults
    try:
        res_ = st.segmented_control(
            "Result",
            options=["W", "L", "P"],
            format_func=lambda x: {"W": "Won", "L": "Lost", "P": "Push / void"}[x],
            key="f_result",
        )
    except Exception:
        res_ = st.radio("Result", ["W", "L", "P"], horizontal=True, key="f_result",
                        format_func=lambda x: {"W": "Won", "L": "Lost", "P": "Push / void"}[x])
    a, b = st.columns(2)
    book = a.selectbox("Book", S.BOOK_CHOICES, key="f_book")
    sports = S.SPORT_CHOICES + ([ss["f_sport"]] if ss.get("f_sport") and ss["f_sport"] not in S.SPORT_CHOICES else [])
    sport = b.selectbox("Sport", sports, key="f_sport")
    a, b, c = st.columns(3)
    odds = a.text_input("Odds (American)", placeholder="+250", key="f_odds")
    legs = b.number_input("Legs", min_value=1, max_value=25, step=1, key="f_legs", placeholder="e.g. 3")
    btype = c.selectbox("Bet type", ["-"] + S.TYPE_CHOICES, key="f_type", format_func=lambda x: "Not sure" if x == "-" else x)
    a, b = st.columns(2)
    stake = a.number_input("Stake $ (risked)", min_value=0.0, step=1.0, format="%.2f", key="f_stake", placeholder="e.g. 10")
    net = b.number_input("Net $ (+ won / - lost)", step=1.0, format="%.2f", placeholder="e.g. 25 or -10", key="f_net",
                         help="Leave empty to work it out from stake + odds (or leave both empty if unknown).")
    brs = S.bankroll_summary()
    if brs and brs["current"] > 0:
        warn = S.stake_warning(stake, brs) if stake else None
        if warn: st.warning("\u26a0\ufe0f " + warn)
        else: st.caption(f"Your flat 0.5-1% rule on a ${brs['current']:,.2f} bankroll: stake ${brs['stake_min']:.2f} - ${brs['stake_max']:.2f}.")
    date = st.date_input("Date", key="f_date")
    leglist = st.text_area("Legs (one per line, optional)", key="f_leglist", height=90)
    note = st.text_input("Note (optional)", key="f_note")
    a, b = st.columns([3, 1])
    go = a.button("Save bet", type="primary", use_container_width=True)
    if b.button("Clear", use_container_width=True):
        clear_form(); st.rerun()
    if go:
        try:
            if res_ is None: raise ValueError("pick the result (Won, Lost or Push)")
            sync_down(force=True)
            r = S.log_bet(res_, book, sport, odds or None, net, date.strftime("%Y-%m-%d"), note or None, stake=stake, legs=legs,
                          bet_type=None if btype == "-" else btype, leg_list=leglist.splitlines(), payout=ss.get("f_payout") if p else None)
            saved = sync_up(["ledger/user_results.jsonl"], f"Log my bet {r['date']} {res_}")
            bt = r["bets"][0]
            ss["log_msg"] = (f"Logged: {res_} {book} {sport} {odds or ''} " + (f"stake ${bt['stake']:.2f} " if bt.get("stake") is not None else "")
                             + (f"net {bt['net']:+.2f}" + (" (worked out from stake and odds)" if bt.get("net_computed") else "") if bt["net"] is not None else "(net not given)")
                             + f" on {r['date']}. " + (saved or ""))
            clear_form(); ss.pop("slip_text", None)
            st.rerun()
        except ValueError as ex:
            st.error(f"Not logged: {ex}")
