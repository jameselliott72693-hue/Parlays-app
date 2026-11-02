"""Tests for the bet slip reader, stake / legs / bet type on your bets, and bankroll tracking (no network, no Odds API credits).

    python3 -m unittest discover -s tests -v
OCR tests run only where the free Tesseract program is installed (TESSERACT_CMD or `tesseract` on PATH); otherwise skipped.
"""
import io, json, os, shutil, subprocess, sys, tempfile, unittest
from datetime import date
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "app")]
import slip_reader as sr          # noqa: E402
import bankroll_lib as bl         # noqa: E402
import storage                    # noqa: E402
import grade_slips as gs          # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "slips")
TODAY = date(2026, 11, 1)
EXPECTED = json.load(open(os.path.join(FIX, "expected.json")))


class SlipReaderFixtures(unittest.TestCase):
    def test_every_fixture(self):
        for name, exp in EXPECTED.items():
            with self.subTest(slip=name):
                got = sr.parse_slip(open(os.path.join(FIX, name)).read(), today=TODAY)
                for k, v in exp.items():
                    self.assertEqual(got[k], v, f"{name}: {k}")

    def test_all_supported_books_covered(self):
        books = {e["book"] for e in EXPECTED.values()}
        self.assertTrue({"DraftKings", "FanDuel", "Caesars", "theScore Bet", "BetMGM", "Underdog"} <= books)


class SlipReaderEdges(unittest.TestCase):
    def p(self, t, today=TODAY): return sr.parse_slip(t, today=today)

    def test_empty_and_junk(self):
        self.assertIn("no text to read", self.p("")["notes"])
        r = self.p("hello there, nothing useful")
        self.assertIsNone(r["book"]); self.assertIsNone(r["odds"]); self.assertIsNone(r["result"])
        self.assertEqual(r["date"], "2026-11-01")  # falls back to today ET, with a note
        self.assertTrue(any("today" in n for n in r["notes"]))

    def test_one_long_line_with_commas(self):
        r = self.p("Caesars 2 leg parlay Lakers -4.5 -110, Celtics ML -200 Wager $10 To Win $17.27 Lost Nov 2")
        self.assertEqual((r["book"], r["legs"], r["bet_type"], r["result"], r["net"], r["date"]), ("Caesars", 2, "Multi-game", "L", -10.0, "2026-11-02"))
        self.assertEqual(r["leg_list"], ["Lakers -4.5", "Celtics ML"])
        self.assertEqual(r["payout"], 27.27); self.assertEqual(r["odds"], 173)  # from stake + to win

    def test_cash_out_and_open_bets(self):
        r = self.p("DraftKings Straight Buffalo Bills ML -150 Wager $15.00 To Pay $25.00 Cashed out")
        self.assertEqual((r["result"], r["net"]), ("W", 10.0))
        r = self.p("BetMGM\nStraight\nBuffalo Bills ML\n-150\nStake $15.00\nPotential Payout $25.00\nOpen")
        self.assertIsNone(r["result"]); self.assertIsNone(r["net"])
        self.assertTrue(any("not settled" in n for n in r["notes"]))

    def test_void_is_a_push(self):
        r = self.p("FanDuel\nStraight\nJosh Allen Over 1.5 Passing TDs\n-130\n$10.00\nWAGER\n$10.00\nRETURNED\nVOID")
        self.assertEqual((r["result"], r["net"]), ("P", 0.0))

    def test_sgp_plus_is_multi_game(self):
        self.assertEqual(self.p("FanDuel SGP+ 4 legs +900 Wager $5 Payout $50 Won")["bet_type"], "Multi-game")

    def test_year_inference_near_new_year(self):
        self.assertEqual(self.p("DraftKings Dec 30 Wager $5", today=date(2027, 1, 2))["date"], "2026-12-30")
        self.assertEqual(self.p("DraftKings Jan 2 Wager $5", today=date(2026, 12, 30))["date"], "2027-01-02")

    def test_payout_disagreeing_with_odds_is_noted(self):
        r = self.p("DraftKings\nStraight\nBills ML\n+150\nWager: $10.00\nTo Pay: $30.00\nWon")
        self.assertEqual(r["odds"], 150); self.assertEqual(r["net"], 20.0)
        self.assertTrue(any("boost" in n for n in r["notes"]))

    def test_even_money_and_ambiguous_nicknames(self):
        r = self.p("theScore Bet\nStraight\nCarolina Panthers ML\nEVEN\nWager $10.00\nPaid $20.00\nWon")
        self.assertEqual((r["odds"], r["sport"]), (100, "NFL"))
        self.assertEqual(self.p("DraftKings Florida Panthers ML -120 Wager $12 Lost")["sport"], "NHL")

    def test_odds_math(self):
        self.assertEqual(sr.dec_to_am(2.0), 100); self.assertEqual(sr.dec_to_am(1.909), -110); self.assertEqual(sr.dec_to_am(6.0), 500)
        self.assertIsNone(sr.dec_to_am(1.0))


def tesseract_cmd():
    return os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")


class OcrTests(unittest.TestCase):
    def test_missing_ocr_degrades_with_a_clear_message(self):
        with mock.patch.dict(os.environ, {"TESSERACT_CMD": ""}), mock.patch("shutil.which", return_value=None):
            ok, msg = sr.ocr_status()
            text, err = sr.ocr_image(b"not an image")
        self.assertFalse(ok); self.assertEqual(text, ""); self.assertIn("Paste the slip text", err)

    def test_bad_image_bytes(self):
        if not sr.ocr_status()[0]: self.skipTest("tesseract not installed")
        text, err = sr.ocr_image(b"definitely not an image")
        self.assertEqual(text, ""); self.assertIn("Paste the slip text", err)

    def test_screenshot_round_trip(self):
        if not sr.ocr_status()[0]: self.skipTest("tesseract not installed")
        from PIL import Image, ImageDraw, ImageFont
        fonts = [p for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",) if os.path.exists(p)]
        font = ImageFont.truetype(fonts[0], 30) if fonts else ImageFont.load_default()
        for name in ("draftkings_sgp_won.txt", "fanduel_sgp_lost.txt", "underdog_powerplay_won.txt"):
            for dark in (False, True):
                with self.subTest(slip=name, dark=dark):
                    lines = open(os.path.join(FIX, name)).read().splitlines()
                    img = Image.new("RGB", (750, 50 * len(lines) + 40), (20, 20, 24) if dark else "white")
                    d = ImageDraw.Draw(img)
                    for i, l in enumerate(lines): d.text((30, 20 + 50 * i), l, fill="white" if dark else "black", font=font)
                    b = io.BytesIO(); img.save(b, "PNG")
                    text, err = sr.ocr_image(b.getvalue())
                    self.assertIsNone(err)
                    got = sr.parse_slip(text, today=TODAY)
                    for k in ("book", "odds", "legs", "bet_type", "stake", "result", "net"):
                        self.assertEqual(got[k], EXPECTED[name][k], f"{name} {k}")


def bet(date_, net, entered, stake=None):
    b = {"result": "W" if (net or 0) > 0 else "L", "net": net}
    if stake: b["stake"] = stake
    return {"date": date_, "wins": int((net or 0) > 0), "losses": int((net or 0) <= 0), "net": net, "entered_at": entered, "bets": [b]}


class BankrollTests(unittest.TestCase):
    def test_summary(self):
        entries = [{"kind": "start", "amount": 500, "date": "2026-11-01", "entered_at": "2026-11-01T20:00:00+00:00"},
                   {"kind": "deposit", "amount": 100, "date": "2026-11-03", "entered_at": "2026-11-03T12:00:00+00:00"},
                   {"kind": "withdrawal", "amount": 50, "date": "2026-11-04", "entered_at": "2026-11-04T12:00:00+00:00"}]
        user = [bet("2026-10-31", -20, "2026-10-31T22:00:00+00:00"),       # before the start: not counted
                bet("2026-11-01", -59.9, "2026-11-01T19:00:00+00:00"),     # same day, logged before the start was set: in the start amount
                bet("2026-11-01", 30, "2026-11-01T21:00:00+00:00", 10),    # same day, logged after: counted
                bet("2026-11-02", -10, "2026-11-02T21:00:00+00:00", 10),
                bet("2026-11-02", None, "2026-11-02T22:00:00+00:00")]      # no net $: not counted, reported
        s = bl.summary(entries, user)
        self.assertEqual(s["current"], 570.0)
        self.assertEqual((s["deposits"], s["withdrawals"], s["bets_net"], s["n_bets"], s["n_no_net"]), (100.0, 50.0, 20.0, 2, 1))
        self.assertEqual(s["series"], [("2026-11-01", 530.0), ("2026-11-02", 520.0), ("2026-11-03", 620.0), ("2026-11-04", 570.0)])
        self.assertEqual((s["stake_min"], s["stake_max"]), (2.85, 5.7))
        self.assertIsNone(bl.summary([], user))

    def test_latest_start_resets(self):
        entries = [{"kind": "start", "amount": 500, "date": "2026-11-01", "entered_at": "a"},
                   {"kind": "start", "amount": 800, "date": "2026-11-05", "entered_at": "b"}]
        self.assertEqual(bl.summary(entries, [bet("2026-11-02", 50, "x")])["current"], 800.0)

    def test_stake_rule(self):
        self.assertIsNone(bl.stake_check(10, 1000))
        w = bl.stake_check(25, 1000)
        self.assertIn("2.5%", w); self.assertIn("$5.00 - $10.00", w)
        self.assertIsNone(bl.stake_check(25, None))

    def test_entries_validated_and_saved(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "b.jsonl")
            with self.assertRaises(ValueError): bl.add("bonus", 10, "2026-11-01", path=p)
            with self.assertRaises(ValueError): bl.add("deposit", -5, "2026-11-01", path=p)
            with self.assertRaises(ValueError): bl.add("deposit", 5, "11/01/2026", path=p)
            bl.add("start", 250, "2026-11-01", "first", path=p)
            self.assertEqual(bl.load(p)[0]["amount"], 250.0)
        finally:
            shutil.rmtree(tmp)

    def test_bankroll_file_syncs(self):
        self.assertIn("ledger/bankroll.jsonl", storage.SYNC_FILES)
        a = {"kind": "start", "amount": 500.0, "date": "2026-11-01", "entered_at": "t1"}
        b = {"kind": "deposit", "amount": 50.0, "date": "2026-11-02", "entered_at": "t2"}
        j = lambda rows: "".join(json.dumps(r) + "\n" for r in rows).encode()
        out = [json.loads(x) for x in storage.merge("ledger/bankroll.jsonl", j([a, b]), j([a])).decode().splitlines()]
        self.assertEqual(out, [a, b])
        self.assertEqual(storage.merge("ledger/bankroll.jsonl", j([a]), None), j([a]))


class LogBetTests(unittest.TestCase):
    def setUp(self):
        import services, add_user_result
        self.S, self.aur = services, add_user_result
        self.tmp = tempfile.mkdtemp()
        self.p = mock.patch.object(add_user_result, "LEDGER", os.path.join(self.tmp, "u.jsonl")); self.p.start()
    def tearDown(self):
        self.p.stop(); shutil.rmtree(self.tmp)

    def test_new_fields_saved_and_net_computed(self):
        r = self.S.log_bet("W", "DraftKings", "NBA", "+485", None, "2026-11-01", stake=10, legs=3, bet_type="SGP",
                           leg_list=["Jayson Tatum 25+ Points", "", "Boston Celtics Moneyline"], payout=58.5)
        b = r["bets"][0]
        self.assertEqual((b["stake"], b["legs"], b["type"], b["net"], b["payout"]), (10.0, 3, "SGP", 48.5, 58.5))
        self.assertTrue(b["net_computed"]); self.assertEqual(b["leg_list"], ["Jayson Tatum 25+ Points", "Boston Celtics Moneyline"])
        self.assertEqual(self.S.log_bet("L", "FanDuel", "NFL", None, None, "2026-11-01", stake=12)["net"], -12.0)
        self.assertEqual(self.S.log_bet("P", "FanDuel", "NFL", None, None, "2026-11-01", stake=12)["net"], 0.0)
        old_style = self.S.log_bet("L", "FanDuel", "NFL", "-110", -10, "2026-11-01")["bets"][0]
        self.assertFalse({"stake", "legs", "type"} & set(old_style))  # nothing new unless given

    def test_validation(self):
        with self.assertRaises(ValueError): self.S.log_bet("W", "FanDuel", "NBA", None, 5, "2026-11-01", bet_type="teaser")
        with self.assertRaises(ValueError): self.S.log_bet("W", "FanDuel", "NBA", None, 5, "2026-11-01", legs=0)
        with self.assertRaises(ValueError): self.S.log_bet("L", "FanDuel", "NBA", None, -50, "2026-11-01", stake=10)
        with self.assertRaises(ValueError): self.S.log_bet(None, "FanDuel", "NBA", None, 5, "2026-11-01")


class WhatPaysTests(unittest.TestCase):
    def test_logged_and_derived_stakes_and_labels(self):
        user = [{"date": "2026-10-24", "wins": 0, "losses": 1, "net": -14.52, "entered_at": "a",
                 "bets": [{"result": "L", "book": "FanDuel", "sport": "NBA", "odds": -104, "net": -14.52}]},           # old: derived stake
                {"date": "2026-11-01", "wins": 1, "losses": 0, "net": 48.5, "entered_at": "b",
                 "bets": [{"result": "W", "book": "DraftKings", "sport": "NBA", "odds": 485, "net": 48.5, "stake": 10.0, "legs": 3, "type": "SGP"}]},
                {"date": "2026-11-01", "wins": 0, "losses": 1, "net": -10.0, "entered_at": "c",
                 "bets": [{"result": "L", "book": "FanDuel", "sport": "NFL", "odds": -110, "net": -10.0, "stake": 10.0, "legs": 1, "type": "Straight"}]},
                {"date": "2026-11-02", "wins": 0, "losses": 1, "net": -5.0, "entered_at": "d", "stake": 5.0, "legs": 12, "type": "multi"}]  # whole entry
        r = gs.user_what_pays(user)
        self.assertEqual(r["roi"]["logged"], {"n": 3, "staked": 25.0, "net": 33.5, "roi": 134.0})
        self.assertEqual(r["roi"]["all"]["derived"], 1)
        self.assertEqual([x["k"] for x in r["dims"]["legs"]], ["1 leg", "3 legs", "12 legs", gs.UNK])
        self.assertEqual({x["k"] for x in r["dims"]["type"]}, {"SGP", "Straight", "Multi-game", gs.UNK})
        self.assertTrue(any("stake logged for 3 of 4 bets" in g for g in r["gaps"]))

    def test_page_data_has_bankroll(self):
        with mock.patch.object(gs, "USER", "/nonexistent"), mock.patch.object(bl, "BANKROLL", "/nonexistent"):
            d = gs.build_page_data([], [])
        self.assertIn("bankroll", d); self.assertIsNone(d["bankroll"])
        self.assertIn("roi", d["userPays"])

    def test_template_uses_the_new_fields(self):
        t = open(os.path.join(ROOT, "ledger", "page_template.tsx.txt")).read()
        self.assertIn("DATA.bankroll", t); self.assertIn("userPays.roi", t); self.assertIn("/*__DATA__*/null", t)


class CliTests(unittest.TestCase):
    def test_add_user_result_new_options(self):
        tmp = tempfile.mkdtemp()
        try:
            for f in ("add_user_result.py", "bankroll_lib.py"): shutil.copy(os.path.join(ROOT, f), tmp)
            run = lambda *a: subprocess.run([sys.executable, os.path.join(tmp, "add_user_result.py"), *a], capture_output=True, text=True)
            r = run("--date", "2026-11-01", "--bet", "W FanDuel NBA +250 25 stake=10 legs=3 type=sgp", "--bet", "L DraftKings NFL -110 -11 stake=11")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run("--date", "2026-11-01", "--bet", "L Caesars NHL +120 -10", "--stake", "10", "--legs", "2", "--type", "Multi-game")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotEqual(run("--bet", "W a b +100 1", "--bet", "W a b +100 1", "--stake", "5").returncode, 0)
            self.assertNotEqual(run("--bet", "W FanDuel NBA +100 5 type=teaser").returncode, 0)
            rows = [json.loads(x) for x in open(os.path.join(tmp, "ledger", "user_results.jsonl"))]
            self.assertEqual(rows[0]["bets"][0]["type"], "SGP"); self.assertEqual(rows[0]["bets"][1]["stake"], 11.0)
            self.assertEqual((rows[1]["bets"][0]["legs"], rows[1]["bets"][0]["type"]), (2, "Multi-game"))
            r = run("--bankroll-start", "1000", "--date", "2026-10-31")
            self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("bankroll $1,004.00", r.stdout)  # +25 -11 -10 dated after the start
            r = run("--deposit", "100", "--date", "2026-11-02")
            self.assertIn("bankroll $1,104.00", r.stdout)
        finally:
            shutil.rmtree(tmp)


class AppLogTabSmokeTest(unittest.TestCase):
    """Headless app: paste a slip, check the prefilled form, set a bankroll, see the stake warning, save the bet."""
    def test_read_slip_and_save(self):
        try:
            from streamlit.testing.v1 import AppTest
        except Exception as ex:
            self.skipTest(f"streamlit not installed: {ex}")
        tmp = tempfile.mkdtemp()
        mods = ("services", "storage", "parlay_builder", "grade_slips", "add_user_result", "ledger_lib", "bankroll_lib", "slip_reader")
        try:
            dst = os.path.join(tmp, "repo")
            shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "espn_cache", "cache"))
            env = {"APP_PASSWORD": "pw-test", "STORAGE": "local", "ODDS_API_KEY": "", "GITHUB_TOKEN": "", "GH_REPO": ""}
            with mock.patch.dict(os.environ, env):
                for m in mods: sys.modules.pop(m, None)
                saved_path = list(sys.path)
                try:
                    at = AppTest.from_file(os.path.join(dst, "app", "streamlit_app.py"), default_timeout=120).run()
                    at.text_input[0].input("pw-test"); at.button[0].click().run()
                    self.assertFalse(at.exception, at.exception)
                    nb = sum(1 for _ in open(os.path.join(dst, "ledger", "user_results.jsonl")))
                    # saving without a result is refused (never a silent default)
                    next(b for b in at.button if b.label == "Save bet").click().run()
                    self.assertTrue(any("pick the result" in e.value for e in at.error))
                    next(t for t in at.text_area if t.label == "Bet slip text").input(open(os.path.join(FIX, "caesars_parlay_won.txt")).read()).run()
                    next(b for b in at.button if b.label == "Read slip").click().run()
                    self.assertFalse(at.exception, at.exception)
                    ss = at.session_state
                    self.assertEqual((ss["f_result"], ss["f_book"], ss["f_sport"], ss["f_odds"], ss["f_legs"], ss["f_type"], ss["f_stake"], ss["f_net"]),
                                     ("W", "Caesars", "NHL", "+264", 2, "Multi-game", 25.0, 66.0))
                    self.assertEqual(nb, sum(1 for _ in open(os.path.join(dst, "ledger", "user_results.jsonl"))))  # not auto-saved
                    next(n for n in at.number_input if n.label == "Amount $").set_value(1000.0)
                    next(b for b in at.button if b.label == "Save bankroll entry").click().run()
                    self.assertTrue(os.path.exists(os.path.join(dst, "ledger", "bankroll.jsonl")))
                    self.assertTrue(any("above your flat 0.5-1% rule" in w.value for w in at.warning))
                    next(n for n in at.number_input if n.label == "Net $ (+ won / - lost)").set_value(60.0).run()  # the user edits a field
                    next(b for b in at.button if b.label == "Save bet").click().run()
                    self.assertFalse(at.exception, at.exception)
                    rows = [json.loads(x) for x in open(os.path.join(dst, "ledger", "user_results.jsonl"))]
                    self.assertEqual(len(rows), nb + 1)
                    b = rows[-1]["bets"][0]
                    self.assertEqual((b["book"], b["stake"], b["legs"], b["type"], b["net"]), ("Caesars", 25.0, 2, "Multi-game", 60.0))
                    self.assertTrue(any("Logged" in s_.value for s_ in at.success))
                    self.assertTrue(any("Bankroll $" in m.value for m in at.markdown))
                finally:
                    sys.path[:] = saved_path
                    for m in mods: sys.modules.pop(m, None)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
