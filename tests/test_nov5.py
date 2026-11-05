"""Round-2 fixes (2026-11-05): Unicode minus signs on slips, odds parsing, sport labels in 'what pays', odds buckets,
parallel GitHub reads, OCR status that can never break the app. No network, no Odds API credits."""
import json, os, shutil, sys, tempfile, threading, time, unittest
from datetime import date
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "app")]
import slip_reader as sr          # noqa: E402
import storage                    # noqa: E402
import grade_slips as gs          # noqa: E402
import add_user_result as aur     # noqa: E402

TODAY = date(2026, 11, 5)


class UnicodeMinus(unittest.TestCase):
    def test_unicode_minus_odds_on_its_own_line(self):
        p = sr.parse_slip("DraftKings\nNBA\nLakers Moneyline\n\u2212150\nWager $15.00\nTo Pay $25.00\nWon\nNov 4, 2026", today=TODAY)
        self.assertEqual(p["odds"], -150)
        self.assertEqual(p["leg_odds"], [-150])
        self.assertNotIn("odds worked out from payout / stake", p["notes"])
        self.assertEqual(p["net"], 10.0)

    def test_en_dash_spread_and_bullet(self):
        p = sr.parse_slip("FanDuel 2 leg parlay \u2013 Bruins ML +120, Duke \u20133.5 \u2212110, wager $10 to win $31.00 lost Nov 3", today=TODAY)
        self.assertEqual(p["leg_list"], ["Bruins ML", "Duke -3.5"])
        self.assertEqual(p["leg_odds"], [120, -110])
        self.assertEqual((p["result"], p["net"], p["date"]), ("L", -10.0, "2026-11-03"))

    def test_nbsp_and_sgp_plus_untouched(self):
        p = sr.parse_slip("FanDuel SGP+ 4 legs +900 Wager\u00a0$5 Payout $50 Won", today=TODAY)
        self.assertEqual((p["bet_type"], p["odds"], p["stake"]), ("Multi-game", 900, 5.0))


class OddsParsing(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(aur.parse_odds("\u2212110"), (-110, "+100"))
        self.assertEqual(aur.parse_odds("EVEN"), (100, "+100"))
        self.assertEqual(aur.parse_odds("+250.0"), (250, "+300"))
        self.assertEqual(aur.parse_odds(" "), (None, None))
        with self.assertRaises(ValueError) as cm: aur.parse_odds("abc")
        self.assertIn("bad American odds", str(cm.exception))
        with self.assertRaises(ValueError): aur.parse_odds("+50")

    def test_log_bet_accepts_unicode_minus(self):
        import services as S
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.object(S.aur, "LEDGER", os.path.join(tmp, "u.jsonl")):  # the module services really uses
                r = S.log_bet("W", "DraftKings", "NBA", "\u2212150", None, "2026-11-04", stake=15)
            self.assertEqual((r["bets"][0]["odds"], r["bets"][0]["net"]), (-150, 10.0))
        finally:
            shutil.rmtree(tmp)


class SportLabels(unittest.TestCase):
    USER = [
        {"date": "2026-11-01", "wins": 0, "losses": 1, "net": -10, "bets": [{"result": "L", "sport": "NCAAM", "odds": 200, "net": -10, "stake": 10}]},
        {"date": "2026-11-02", "wins": 1, "losses": 0, "net": 20, "bets": [{"result": "W", "sport": "NCAAB", "odds": 200, "net": 20, "stake": 10}]},
        {"date": "2026-11-03", "wins": 0, "losses": 1, "net": -5, "bets": [{"result": "L", "sport": "NHL+NCAAB", "odds": 300, "net": -5}]},
        {"date": "2026-11-04", "wins": 0, "losses": 1, "net": -5, "bets": [{"result": "L", "sport": "Mixed (NCAAB + NHL)", "odds": 300, "net": -5}]},
    ]

    def test_labels(self):
        self.assertEqual(gs.sport_label("NCAAM"), "NCAAB")
        self.assertEqual(gs.sport_label("NHL+NCAAB"), "Mixed (NCAAB + NHL)")
        self.assertEqual(gs.sport_label("nba / ncaam"), "Mixed (NBA + NCAAB)")
        self.assertIsNone(gs.sport_label(None))

    def test_what_pays_groups_aliases_and_multi_sport(self):
        up = gs.user_what_pays(self.USER)
        sp = {r["k"]: r for r in up["dims"]["sport"]}
        self.assertEqual(set(sp), {"NCAAB", "Mixed (NCAAB + NHL)"})
        self.assertEqual((sp["NCAAB"]["n"], sp["NCAAB"]["w"], sp["NCAAB"]["net"]), (2, 1, 10.0))
        self.assertEqual(sp["Mixed (NCAAB + NHL)"]["n"], 2)
        ty = {r["k"]: r["n"] for r in up["dims"]["type"]}
        self.assertEqual(ty.get("Multi-game (cross-sport)"), 2)  # both spellings of the cross-sport parlay

    def test_tracker_user_breakdown_and_bucket_fallback(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "u.jsonl")
            open(p, "w").write("".join(json.dumps(r) + "\n" for r in self.USER))
            with mock.patch.object(gs, "USER", p):
                d = gs.build_page_data([], [])
            sp = {r["k"]: r for r in d["userBreak"]["sport"]}
            self.assertEqual(set(sp), {"NCAAB", "Mixed (NCAAB + NHL)"})
            odds = {r["k"] for r in d["userBreak"]["odds"]}
            self.assertEqual(odds, {"+200", "+300"})  # no stored bucket: derived from the odds, not "Untagged"
        finally:
            shutil.rmtree(tmp)


class SlowGitHub(storage.GitHubStorage):
    """Fake GitHub with 0.2 s per request, to measure first-load pull time (no network)."""
    def __init__(self, files):
        super().__init__("tok", "o/r"); self.files, self.refs, self.lock = files, [], threading.Lock()
    def _req(self, method, path, body=None, accept=None, raw=False):
        time.sleep(0.2)
        if "/git/ref/heads/" in path: return 200, {"object": {"sha": "abc123"}}
        if "/contents/" in path:
            p, q = path.split("/contents/")[1].split("?")
            with self.lock: self.refs.append(q)
            return (200, self.files[p]) if p in self.files else (404, {"message": "Not Found"})
        raise AssertionError(path)


class ParallelPull(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self._root = storage.ROOT; storage.ROOT = self.tmp
    def tearDown(self):
        storage.ROOT = self._root; shutil.rmtree(self.tmp)

    def test_first_pull_downloads_in_parallel_at_the_pulled_head(self):
        s = SlowGitHub({"ledger/user_results.jsonl": b'{"date": "d", "entered_at": "e"}\n', "ledger/slips.jsonl": b""})
        t = time.perf_counter(); s.pull(); dt = time.perf_counter() - t
        self.assertLess(dt, 0.9)  # head + 6 files: ~1.4 s one after another, ~0.4 s in parallel
        self.assertEqual(len(s.refs), len(storage.SYNC_FILES))
        self.assertTrue(all(q == "ref=abc123" for q in s.refs))  # files read at the head recorded as pulled
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "ledger/user_results.jsonl")))


class OcrStatus(unittest.TestCase):
    def test_never_raises_and_is_cached(self):
        with mock.patch.object(sr, "_ocr_status", side_effect=OSError("boom")):
            ok, msg = sr.ocr_status(refresh=True)
        self.assertFalse(ok); self.assertIn("Paste the slip text", msg)
        with mock.patch.object(sr, "_ocr_status", return_value=(False, "missing")) as m:
            sr.ocr_status(refresh=True); sr.ocr_status(); sr.ocr_status()
            self.assertEqual(m.call_count, 1)
        sr.ocr_status(refresh=True)

    def test_missing_binary_message(self):
        with mock.patch("shutil.which", return_value=None), mock.patch.dict(os.environ, {"TESSERACT_CMD": ""}):
            ok, msg = sr.ocr_status(refresh=True)
        self.assertFalse(ok); self.assertIn("Paste the slip text", msg)
        sr.ocr_status(refresh=True)


if __name__ == "__main__":
    unittest.main()
