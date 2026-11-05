"""Bet slip reader: turn a sportsbook bet slip (pasted text, or a screenshot read by free OCR) into the fields of a logged bet.

Pure Python, no Streamlit and no AI/LLM API. Everything is best-effort: the app always shows the parsed fields in an editable form
and the user confirms before anything is saved.

    parse_slip(text, today=date(2026, 11, 1)) -> {"book", "sport", "date", "odds", "legs", "bet_type", "leg_list", "stake",
        "payout", "to_win", "result", "net", "notes"}   (None for anything not found)
    ocr_image(image_bytes) -> (text, None) or ("", "why OCR is unavailable / failed")

Books: DraftKings, FanDuel, Caesars, theScore Bet (ESPN BET), BetMGM, Underdog; best-effort for Fanatics, bet365, BetRivers,
Hard Rock, PrizePicks. Payout means the total return (stake included); to_win is the profit.
"""
import io, os, re, shutil
from datetime import date as Date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

BOOKS = [  # (canonical name as stored in user_results, pattern)
    ("DraftKings", r"draft\s?kings|\bDK\s?(?:sportsbook|\d{6,})|^DK\b|\bDK\s+Sportsbook"),
    ("FanDuel", r"fan\s?duel|\bO/\d{5,}/\d+"),
    ("Caesars", r"caesars|william\s?hill"),
    ("theScore Bet", r"the\s?score(?:\s?bet)?|espn\s?bet"),
    ("BetMGM", r"bet\s?mgm|\bMGM\b"),
    ("Underdog", r"underdog|power\s+play|flex\s+play|\bpick'?em\b"),
    ("Fanatics", r"fanatics"), ("bet365", r"bet\s?365"), ("BetRivers", r"bet\s?rivers"), ("Hard Rock", r"hard\s?rock"),
    ("PrizePicks", r"prize\s?picks"),
]

SPORT_WORDS = [("NCAAF", r"\bNCAAF\b|college\s+football|\bCFB\b|NCAA\s*football|football\s*[-·]?\s*NCAA\b"),
               ("NCAAB", r"\bNCAAB\b|\bNCAAM\b|college\s+basketball|\bCBB\b|NCAA\s*basketball|basketball\s*[-·]?\s*NCAA\b"),
               ("NFL", r"\bNFL\b"), ("NBA", r"\bNBA\b"), ("NHL", r"\bNHL\b"), ("MLB", r"\bMLB\b")]
# full names first for nicknames two leagues share (Panthers, Kings, Jets, Hurricanes, Cardinals ...)
FULL_TEAMS = {"carolina panthers": "NFL", "florida panthers": "NHL", "sacramento kings": "NBA", "los angeles kings": "NHL",
              "la kings": "NHL", "new york jets": "NFL", "winnipeg jets": "NHL", "carolina hurricanes": "NHL",
              "arizona cardinals": "NFL", "new york giants": "NFL", "new york rangers": "NHL", "utah jazz": "NBA",
              "utah hockey club": "NHL", "utah mammoth": "NHL"}
AMBIGUOUS = {"panthers", "kings", "jets", "hurricanes", "cardinals", "giants", "rangers"}
NICKS = {
    "NFL": "falcons ravens bills bears bengals browns cowboys broncos lions packers texans colts jaguars chiefs raiders chargers rams "
           "dolphins vikings patriots saints eagles steelers 49ers niners seahawks buccaneers bucs titans commanders",
    "NBA": "hawks celtics nets hornets bulls cavaliers cavs mavericks mavs nuggets pistons warriors rockets pacers clippers lakers "
           "grizzlies heat bucks timberwolves wolves pelicans knicks thunder magic 76ers sixers suns blazers spurs raptors jazz wizards",
    "NHL": "ducks bruins sabres flames blackhawks avalanche stars oilers wild canadiens predators devils islanders senators flyers "
           "penguins sharks kraken blues lightning canucks capitals mammoth",
}
NICKS2 = {"NHL": ["blue jackets", "red wings", "maple leafs", "golden knights"], "NBA": ["trail blazers"]}
STAT_SPORT = [("NHL", r"shots on goal|\bSOG\b|puck line|\bsaves\b|goal\s?scorer|power\s?play points"),
              ("NFL", r"passing|rushing|receiving|receptions|touchdown|\bTDs?\b|interceptions"),
              ("NBA", r"rebounds|assists|threes|3-pointers|\bPRA\b|pts\s*\+\s*reb")]  # weak signal, used only without teams

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

MONEY = r"(?:\$|(?<![A-Za-z])S(?=\d))\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
LABELS = re.compile(r"(?P<to_win>to\s+win|potential\s+win(?:nings)?|winnings|profit)"
                    r"|(?P<payout>to\s+pay|potential\s+payout|total\s+payout|payout|paid|returned|to\s+return|total\s+return|returns?|cash(?:ed)?\s*out(?:\s+amount)?)"
                    r"|(?P<stake>total\s+wager|total\s+stake|wager(?:ed)?|stake|risk(?:ed)?|entry(?:\s+fee)?|bet\s+amount|amount\s+wagered)", re.I)
ODDS = re.compile(r"(?<![\w.$/:])([+-]\d{3,5})(?![\w.%])|(?<![\w])(EVEN|EV)(?![\w])")
SEL = re.compile(r"\b(?:over|under|higher|lower)\s*\d+(?:\.\d+)?|(?:^|\s)\d+(?:\.5)?\+(?=\s|$)|\b(?:moneyline|money\s+line|ML)\b"
                 r"|(?:^|\s)[+-]\d{1,2}(?:\.5|\.0)?(?![\d.])|\banytime\b|\bto\s+score\b|\b[OU]\s?\d+\.5\b", re.I)
SEL_AT_START = re.compile(r"^(?:over|under|higher|lower|moneyline|money\s+line|ML|[OU]\s?\d|\d+(?:\.5)?\+|[+-]\d{1,2}(?:\.5|\.0)?(?![\d.]))", re.I)
MARKET_VOCAB = set("""points point rebounds assists spread puck run line moneyline total totals goals goal passing receiving rushing yards yds
    tds td touchdowns touchdown receptions reception shots on saves threes 3-pointers pointers made pts reb ast rebs asts + alt alternate
    player game 1st 2nd half quarter period blocks steals combined longest completions attempts interceptions anytime scorer sog
    pass rush rec and o/u""".split())
HEADER = re.compile(r"\b(parlay|sgp\w?|same\s+game|legs?|picks?|selections?|straight|single|wager|odds|bet\s+id|placed|payout|entry|"
                    r"power\s+play|flex\s+play|sportsbook|settled|stake|paid|returned)\b", re.I)
RESULT = re.compile(r"^(?:settled\s*[-:]\s*|bet\s+|status:?\s*|result:?\s*)?(won|win|winner|lost|loss|lose|push|pushed|void|voided|"
                    r"refund(?:ed)?|cashed\s*out|open|pending|unsettled)\b", re.I)


SPLIT_BEFORE = re.compile(r"\s+(?=(?:wager|stake|risk|entry|to\s+pay|to\s+win|payout|paid|returned|to\s+return|won|lost|push|"
                          r"cashed\s*out|placed|bet\s+id)\b)", re.I)


# Sportsbook apps (and OCR) often print minus signs as U+2212 or an en / em dash: "−110", "Duke –3.5". Treat a dash
# directly before a digit as an ASCII minus so odds and spreads are read (and not stripped as a bullet).
DASH_MINUS = re.compile(r"[\u2212\u2013\u2014\u2012\ufe63\uff0d](?=\d)")
NBSP = re.compile(r"[\u00a0\u2007\u202f]")


def normalize_text(text):
    t = NBSP.sub(" ", (text or "").replace("\r\n", "\n").replace("\r", "\n"))
    return DASH_MINUS.sub("-", t)


def _lines(text):
    t = normalize_text(text)
    if t.count("\n") <= 1 and len(t) > 60 and not re.search(r"[|•·]", t):  # one long pasted line: split at the field labels
        t = SPLIT_BEFORE.sub("\n", t)
        t = re.sub(r",\s+", "\n", t)
    out = []
    for raw in t.split("\n"):
        for part in re.split(r"\s*(?:\||•|·)\s*", raw):
            p = re.sub(r"^[\s✓✔✗✘×●○◦▪\-–—*>]+(?=\S)", "", part).strip() if not re.match(r"^[+-]\d", part.strip()) else part.strip()
            if p: out.append(p)
    return out


def am_to_dec(a): return 1 + (a / 100 if a > 0 else 100 / -a)


def dec_to_am(d):
    if d is None or d <= 1: return None
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def _odds_tokens(line):
    out = []
    for m in ODDS.finditer(line):
        if m.group(2): out.append(100)
        else:
            v = int(m.group(1))
            if abs(v) >= 100: out.append(v)
    return out


def _strip_head(line):
    """Drop a leading book name / bet-type phrase ("Caesars 2 leg parlay Lakers -4.5" -> "Lakers -4.5")."""
    for _, bpat in BOOKS:
        line = re.sub(r"^(?:" + bpat + r")\s*", "", line, flags=re.I)
    line = re.sub(r"^(?:(?:straight|single|parlay|sgp|\d+\s*[- ]?\s*(?:leg|pick)s?)\b[:\s]*)+", "", line, flags=re.I).strip()
    return re.sub(r"^[\u2013\u2014:\-]+\s+(?=\S)", "", line).strip()  # "parlay – Bruins ML" -> "Bruins ML"


def _is_odds_line(line): return bool(re.fullmatch(r"\s*(?:[+-]\d{3,5}|EVEN|EV)\s*", line, re.I))


def _is_event(line): return bool(re.search(r"\s(?:@|at|vs\.?|v)\s", line)) and not SEL.search(line)


def _is_market(line):
    words = re.sub(r"[(),:]", " ", line.lower()).split()
    return bool(words) and all(w in MARKET_VOCAB for w in words)


def _is_name(line):
    s = ODDS.sub("", line).strip()
    if not s or "$" in s or _is_event(s) or HEADER.search(s) or RESULT.match(s) or _is_market(s) or SEL.search(s): return False
    if _parse_date_in(s, Date(2000, 1, 1)): return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z.'\- ]{1,40}", s)) and len(s.split()) <= 5


def _safe_date(y, m, d):
    try: return Date(y, m, d)
    except ValueError: return None


def _parse_date_in(line, today):
    """First date in a line -> date, or None. Dates without a year take the year that puts them closest before ~2 months ahead."""
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", line)
    if m:
        try: return Date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError: return None
    m = re.search(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{2,4})(?![\d/])", line)
    if m:
        y = int(m.group(3)); y = y + 2000 if y < 100 else y
        try: return Date(y, int(m.group(1)), int(m.group(2)))
        except ValueError: return None
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", line, re.I)
    if m:
        mo, d = MONTHS[m.group(1).lower()[:3]], int(m.group(2))
        try:
            if m.group(3): return Date(int(m.group(3)), mo, d)
            cands = [c for c in (_safe_date(y, mo, d) for y in (today.year - 1, today.year, today.year + 1))
                     if c and c <= today + timedelta(days=60)]
            return max(cands) if cands else None
        except ValueError:
            return None
    return None


def _money(lines):
    """{'stake', 'payout', 'to_win'} from label/amount pairs, same line or neighbouring lines (either order)."""
    found, pend_label, pend_amount = {}, None, None
    for i, raw in enumerate(lines):
        line = re.sub(r"(?<![A-Za-z])S(?=\d+(?:\.\d{2})\b)", "$", raw) if LABELS.search(raw) or re.fullmatch(r"S\d+(?:\.\d{2})", raw.strip()) else raw
        labels = [(m.start(), next(k for k, v in m.groupdict().items() if v)) for m in LABELS.finditer(line)]
        if re.match(r"^\s*bet\s+id", line, re.I): labels = []
        amounts = [(m.start(), float(m.group(1).replace(",", ""))) for m in re.finditer(MONEY, line)]
        if labels:
            for j, (pos, kind) in enumerate(labels):
                nxt = labels[j + 1][0] if j + 1 < len(labels) else len(line) + 1
                a = next((v for p, v in amounts if pos < p < nxt), None)
                if a is None and j == 0 and amounts and amounts[0][0] < pos: a = amounts[0][1]  # "$10.00 BET" style
                if a is not None: found.setdefault(kind, a)
                elif pend_amount and i - pend_amount[0] <= 2: found.setdefault(kind, pend_amount[1]); pend_amount = None
                else: pend_label = (i, kind)
            continue
        if amounts and re.fullmatch(r"\s*" + MONEY + r"\s*", line):
            if pend_label and i - pend_label[0] <= 2: found.setdefault(pend_label[1], amounts[0][1]); pend_label = None
            else: pend_amount = (i, amounts[0][1])
    return found


def _sport(text, legs_text):
    low = text.lower()
    sports = set()
    for sp, pat in SPORT_WORDS:
        if re.search(pat, text, re.I): sports.add(sp)
    if sports: return sports, "label"
    found = set()
    masked = low
    for name, sp in FULL_TEAMS.items():
        if re.search(r"\b" + re.escape(name) + r"\b", masked): found.add(sp); masked = masked.replace(name, " ")
    for sp, names in NICKS2.items():
        for n in names:
            if n in masked: found.add(sp); masked = masked.replace(n, " ")
    for sp, names in NICKS.items():
        for n in names.split():
            if n not in AMBIGUOUS and re.search(r"\b" + re.escape(n) + r"\b", masked): found.add(sp)
    if found: return found, "teams"
    for sp, pat in STAT_SPORT:
        if re.search(pat, legs_text, re.I): return {sp}, "stats"
    if re.search(r"\bpoints\b", legs_text, re.I) and not re.search(r"total\s+points", legs_text, re.I): return {"NBA"}, "stats"
    return set(), None


def parse_slip(text, today=None):
    today = today or datetime.now(ET).date()
    lines = _lines(text)
    full = "\n".join(lines)
    out = {"book": None, "sport": None, "date": None, "odds": None, "legs": None, "bet_type": None, "leg_list": [], "leg_odds": [],
           "stake": None, "payout": None, "to_win": None, "result": None, "net": None, "notes": []}
    if not lines:
        out["notes"].append("no text to read"); return out
    for name, pat in BOOKS:
        if re.search(pat, full, re.I | re.M): out["book"] = name; break
    # ---- legs ----
    legs, used, first_leg = [], set(), None
    for i, line in enumerate(lines):
        if i in used or "$" in line or not SEL.search(line) or _is_event(line) or RESULT.match(line): continue
        if HEADER.search(line) and not re.search(r"\b(?:over|under|higher|lower|ML|moneyline)\b", line, re.I):
            core = _strip_head(line)
            if core == line or not SEL.search(core) or HEADER.search(core): continue
        start, parts, lodds = i, [], _odds_tokens(line)
        if SEL_AT_START.match(line) and i > 0 and i - 1 not in used and _is_name(lines[i - 1]):
            start = i - 1; parts.append(ODDS.sub("", lines[i - 1]).strip()); lodds = lodds or _odds_tokens(lines[i - 1]); used.add(i - 1)
        sel = ODDS.sub("", line).strip() if not re.fullmatch(r"\s*[+-]\d{1,2}(?:\.5|\.0)?\s*", line) else line.strip()
        sel = _strip_head(sel)
        parts.append(re.sub(r"\s{2,}", " ", sel))
        used.add(i)
        j = i + 1
        while j < len(lines) and _is_odds_line(lines[j]):
            lodds = lodds or _odds_tokens(lines[j]); used.add(j); j += 1
        if j < len(lines) and j not in used and _is_market(lines[j]) and lines[j].lower() not in " ".join(parts).lower():
            parts.append(lines[j]); used.add(j)
        legs.append(" ".join(p for p in parts if p))
        out["leg_odds"].append(lodds[-1] if lodds else None)
        if first_leg is None: first_leg = start
    out["leg_list"] = legs
    # ---- leg count / bet type ----
    m = re.search(r"(?<![\d.])(\d{1,2})\s*[- ]?\s*(?:legs?|picks?|selections?|team)\b", full, re.I) or re.search(r"\((\d{1,2})\s+(?:legs?|picks?)\)", full, re.I)
    n_explicit = int(m.group(1)) if m else None
    straight = re.search(r"\b(straight|single)\b", full, re.I)
    n = n_explicit or (1 if straight else None) or (len(legs) or None)
    if n_explicit and legs and n_explicit != len(legs):
        out["notes"].append(f"the slip says {n_explicit} legs but {len(legs)} leg lines were read; check the leg list")
    out["legs"] = n
    events = {re.sub(r"\s+", " ", l.lower()) for l in lines if _is_event(l)}
    if re.search(r"\bSGP ?(?:\+|x)(?![\w\d])|same[ \t]+game[ \t]+parlay[ \t]*(?:\+(?!\d)|plus)|multi[- ]game[ \t]+sgp", full, re.I): out["bet_type"] = "Multi-game"
    elif re.search(r"\bSGP\b|same\s+game", full, re.I): out["bet_type"] = "SGP"
    elif n == 1: out["bet_type"] = "Straight"
    elif (n or 0) >= 2 or re.search(r"parlay|power\s+play|flex\s+play", full, re.I):
        out["bet_type"] = "SGP" if len(events) == 1 and (n or 0) >= 2 and re.search(r"same", full, re.I) else "Multi-game"
    # ---- money ----
    mo = _money(lines)
    out["stake"], out["payout"], out["to_win"] = mo.get("stake"), mo.get("payout"), mo.get("to_win")
    if out["payout"] is None and out["stake"] is not None and out["to_win"] is not None:
        out["payout"] = round(out["stake"] + out["to_win"], 2)
    # ---- odds ----
    head = lines[:first_leg] if first_leg is not None else lines
    cands = [o for l in head for o in _odds_tokens(l)]
    lab = re.search(r"\bodds\b[:\s]*([+-]\d{3,5}|EVEN)", full, re.I)
    odds = (100 if lab.group(1).upper() == "EVEN" else int(lab.group(1))) if lab else (cands[0] if cands else None)
    if odds is None and n == 1 and out["leg_odds"] and out["leg_odds"][0]: odds = out["leg_odds"][0]
    mult = re.search(r"(?<![\w.])(\d{1,3}(?:\.\d{1,2})?)\s?x\b", full, re.I)
    if odds is None and mult and float(mult.group(1)) > 1: odds = dec_to_am(float(mult.group(1)))
    s, p = out["stake"], out["payout"]
    if s and p and p > 0:
        implied = p / s
        if odds is None: odds = dec_to_am(implied); out["notes"].append("odds worked out from payout / stake")
        elif abs(am_to_dec(odds) - implied) / implied > 0.02 and p > s:
            out["notes"].append(f"payout / stake implies {dec_to_am(implied):+d} but the slip shows {odds:+d} (boost, cash-out or misread?)")
    if odds is None and len([o for o in out["leg_odds"] if o]) >= 2 and len(out["leg_odds"]) == n:
        d = 1.0
        for o in out["leg_odds"]: d *= am_to_dec(o)
        odds = dec_to_am(d); out["notes"].append("odds multiplied from the leg prices (a same-game parlay pays less)")
    out["odds"] = odds
    # ---- result / net ----
    res = None
    for l in lines:
        mm = RESULT.match(l)
        if mm and len(l) <= 30:
            w = mm.group(1).lower()
            if w in ("won", "win", "winner"): res = "W"
            elif w in ("lost", "loss", "lose"): res = "L"
            elif w in ("push", "pushed"): res = "P"
            elif w.startswith("void") or w.startswith("refund"): res = "P"; out["notes"].append("void / refunded: logged as a push (stake back)")
            elif w.replace(" ", "").startswith("cashedout"):
                res = "CASH"
            else: res = "OPEN"
            break
        if re.search(r"\bwon\s+on\s+\w+", l, re.I): res = "W"; break
    if res is None:  # a result word anywhere (not "to win" / "potential win")
        mm = re.search(r"(?<!to )(?<!potential )\b(won|lost|pushed|voided|cashed\s*out)\b", full, re.I)
        if mm:
            w = mm.group(1).lower()
            res = {"won": "W", "lost": "L", "pushed": "P", "voided": "P"}.get(w, "CASH")
    if res == "CASH":
        if s is not None and p is not None:
            res = "W" if p > s else "L" if p < s else "P"; out["notes"].append(f"cashed out for ${p:.2f}")
        else: res = None; out["notes"].append("cashed out: enter the result and net $ yourself")
    if res == "OPEN":
        res = None; out["notes"].append("this bet is not settled yet: pick the result once it settles")
    out["result"] = res
    if res == "W":
        if s is not None and p is not None and p >= s: out["net"] = round(p - s, 2)
        elif out["to_win"] is not None: out["net"] = round(out["to_win"], 2)
        elif s is not None and odds: out["net"] = round(s * (am_to_dec(odds) - 1), 2)
    elif res == "L" and s is not None: out["net"] = round(-s, 2)
    elif res == "P" and s is not None: out["net"] = 0.0
    # ---- sport ----
    sports, how = _sport(full, " ".join(legs))
    if sports:
        out["sport"] = sorted(sports)[0] if len(sports) == 1 else "Mixed (" + " + ".join(sorted(sports)) + ")"
        if how == "stats": out["notes"].append(f"sport guessed from the stat names ({out['sport']}); check it")
    # ---- date (game / settle date first, then the placed date, else today) ----
    dated = [(i, _parse_date_in(l, today)) for i, l in enumerate(lines)]
    dated = [(i, d) for i, d in dated if d]
    game = [d for i, d in dated if not re.search(r"placed", lines[i], re.I)]
    placed = [d for i, d in dated if re.search(r"placed", lines[i], re.I)]
    d = (game or placed or [None])[0]
    if d is None: out["notes"].append("no date on the slip: today (ET) is used")
    out["date"] = (d or today).strftime("%Y-%m-%d")
    for k, label in (("book", "sportsbook"), ("stake", "stake"), ("odds", "odds")):
        if out[k] is None: out["notes"].append(f"{label} not found")
    return out


# ---------------- OCR (screenshots) ----------------
_OCR_STATUS = None


def ocr_status(refresh=False):
    """(available, message). Uses pytesseract + the tesseract binary (Streamlit Cloud: packages.txt `tesseract-ocr`).
    Checked once per process (the app reruns on every click) and never raises, so a missing binary can't break the app."""
    global _OCR_STATUS
    if _OCR_STATUS is None or refresh:
        try: _OCR_STATUS = _ocr_status()
        except Exception as ex: _OCR_STATUS = (False, f"Screenshot reading is unavailable ({type(ex).__name__}). Paste the slip text instead.")
    return _OCR_STATUS


def _ocr_status():
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False, "Screenshot reading is not installed here (Python package pytesseract missing). Paste the slip text instead."
    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not cmd:
        return False, "Screenshot reading is not available on this server (the free Tesseract OCR program is missing). Paste the slip text instead."
    return True, cmd


def _prep(img):
    from PIL import ImageOps
    img = ImageOps.exif_transpose(img).convert("L")
    if img.width < 1400:  # phone screenshots are small for OCR: upscale
        f = 1400 / img.width
        img = img.resize((int(img.width * f), int(img.height * f)))
    if sum(img.resize((64, 64)).getdata()) / 4096 < 110:  # dark mode: invert to dark text on light
        img = ImageOps.invert(img)
    return ImageOps.autocontrast(img)


def ocr_image(data):
    ok, info = ocr_status()
    if not ok: return "", info
    try:
        import pytesseract
        from PIL import Image
        pytesseract.pytesseract.tesseract_cmd = info
        img = _prep(Image.open(io.BytesIO(data)))
        text = pytesseract.image_to_string(img, config="--psm 4")
        if not text.strip(): return "", "No text found in the screenshot. Try a sharper / uncropped screenshot or paste the text."
        return text, None
    except Exception as ex:
        return "", f"Could not read the screenshot ({type(ex).__name__}). Paste the slip text instead."
