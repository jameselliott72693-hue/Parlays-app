"""Small regression suite (stdlib unittest; no network, no Odds API credits, never touches ledger-data on GitHub).

    python3 -m unittest discover -s tests -v
Optional: PARLAYS_TEST_SNAPSHOT=/path/to/snapshot_latest.json also runs a free snapshot-replay build inside the app smoke test.
"""
import json, os, shutil, sys, tempfile, unittest
from datetime import datetime, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "app")]
import storage                      # noqa: E402
import grade_slips as gs            # noqa: E402


def jl(rows): return "".join(json.dumps(r) + "\n" for r in rows).encode()
def unjl(b): return [json.loads(x) for x in b.decode().splitlines() if x.strip()]


class MergeTests(unittest.TestCase):
    OV = {"player": "Jonnu Smith", "event": "Carolina Panthers @ Green Bay Packers", "date": "2026-10-29",
          "stat": "receiving_rec", "side": "over", "line": 0.5, "result": "void", "reason": "DNP"}

    def test_overrides_union_keeps_new_local_override(self):
        remote = json.dumps({"overrides": [{"player": "A", "result": "void"}]}).encode()
        local = json.dumps({"overrides": [{"player": "A", "result": "void"}, self.OV]}).encode()
        out = json.loads(storage.merge("ledger/leg_overrides.json", local, remote))["overrides"]
        self.assertEqual([o["player"] for o in out], ["A", "Jonnu Smith"])  # the local-only void is not dropped

    def test_overrides_same_leg_not_duplicated(self):
        edited = dict(self.OV, result="loss", reason="played, 0 rec", updated_at="2026-11-01T20:00:00+00:00")
        out = json.loads(storage.merge("ledger/leg_overrides.json",
                                       json.dumps({"overrides": [edited]}).encode(), json.dumps({"overrides": [self.OV]}).encode()))["overrides"]
        self.assertEqual(len(out), 1); self.assertEqual(out[0]["result"], "loss")  # later updated_at wins
        tie = dict(self.OV, result="loss")
        out = json.loads(storage.merge("ledger/leg_overrides.json",
                                       json.dumps({"overrides": [tie]}).encode(), json.dumps({"overrides": [self.OV]}).encode()))["overrides"]
        self.assertEqual(len(out), 1); self.assertEqual(out[0]["result"], "void")  # no stamp: the repo copy wins

    def test_overrides_bad_json_falls_back_to_remote(self):
        remote = json.dumps({"overrides": [self.OV]}).encode()
        self.assertEqual(storage.merge("ledger/leg_overrides.json", b"{not json", remote), remote)

    def test_user_results_edit_replaces_instead_of_double_counting(self):
        a = {"date": "2026-11-01", "wins": 0, "losses": 1, "net": -10.0, "entered_at": "2026-11-01T21:00:00+00:00"}
        b = {"date": "2026-11-01", "wins": 1, "losses": 0, "net": 25.0, "entered_at": "2026-11-01T22:00:00+00:00"}
        a_edit = dict(a, net=-59.9, edited_at="2026-11-01T23:00:00+00:00")
        out = unjl(storage.merge("ledger/user_results.jsonl", jl([a_edit, b]), jl([a])))
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["net"], -59.9)
        # the app's stale copy (no edited_at) never overrides an edit already on the repo
        out = unjl(storage.merge("ledger/user_results.jsonl", jl([a]), jl([a_edit])))
        self.assertEqual(len(out), 1); self.assertEqual(out[0]["net"], -59.9)
        # a new bet logged locally is kept, sorted by entered_at
        out = unjl(storage.merge("ledger/user_results.jsonl", jl([a, b]), jl([a])))
        self.assertEqual([r["entered_at"] for r in out], [a["entered_at"], b["entered_at"]])

    def test_slips_union_keeps_all_appearance_tags(self):
        fs = {"report": "single_book", "list": "sgp", "target": 100, "slip_no": 1}
        r1 = {"run_ts": "t", "slip_id": "x", "first_seen": fs, "appearances": [fs]}
        r2 = dict(r1, appearances=[fs, dict(fs, target=200)])
        r3 = {"run_ts": "t", "slip_id": "y", "first_seen": dict(fs, slip_no=2), "appearances": [dict(fs, slip_no=2)]}
        out = unjl(storage.merge("ledger/slips.jsonl", jl([r2, r3]), jl([r1])))
        self.assertEqual(len(out), 2); self.assertEqual(len(out[0]["appearances"]), 2)


class FakeGitHub(storage.GitHubStorage):
    """GitHubStorage with the HTTP layer replaced by a dict of files (no network)."""
    def __init__(self, files, head="h1"):
        super().__init__("tok", "o/r"); self.files, self.head, self.calls = files, head, []
    def _req(self, method, path, body=None, accept=None, raw=False):
        self.calls.append((method, path))
        if "/git/ref/heads/" in path: return 200, {"object": {"sha": self.head}}
        if "/contents/" in path:
            p = path.split("/contents/")[1].split("?")[0]
            return (200, self.files[p]) if p in self.files else (404, {"message": "Not Found"})
        raise AssertionError(path)


class PullTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self._root = storage.ROOT; storage.ROOT = self.tmp
    def tearDown(self):
        storage.ROOT = self._root; shutil.rmtree(self.tmp)

    def test_pull_skips_downloads_when_head_unchanged(self):
        s = FakeGitHub({"ledger/slips.jsonl": b"", "ledger/user_results.jsonl": jl([{"date": "d", "entered_at": "e"}])})
        s.pull(); n = len(s.calls)
        self.assertGreater(n, 2)
        s.pull()
        self.assertEqual(len(s.calls) - n, 1)  # only the branch-head read
        s.head = "h2"; s.pull()
        self.assertGreater(len(s.calls) - n, 2)  # branch moved: downloads again
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "ledger/user_results.jsonl")))

    def test_network_error_is_a_clean_runtime_error_without_token(self):
        import urllib.error
        s = storage.GitHubStorage("secret-token-123", "o/r")
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("secret-token-123 down")):
            with self.assertRaises(RuntimeError) as cm: s.pull()
        self.assertNotIn("secret-token-123", str(cm.exception))


def comp(name, side, score, location=None, short=None, nick=None):
    return {"homeAway": side, "score": str(score),
            "team": {"displayName": name, "location": location or name.rsplit(" ", 1)[0],
                     "shortDisplayName": short or name.rsplit(" ", 1)[0], "name": nick or name.rsplit(" ", 1)[1]}}


def event(eid, date, home, away, neutral=False, final=True):
    return {"id": eid, "date": date, "status": {"type": {"name": "STATUS_FINAL" if final else "STATUS_SCHEDULED", "completed": final}},
            "competitions": [{"neutralSite": neutral, "competitors": [home, away]}]}


class GraderTests(unittest.TestCase):
    def setUp(self):
        gs._sb.clear(); gs._sum.clear()
        self.p = mock.patch.object(gs, "closing_price", return_value=None); self.p.start()
    def tearDown(self):
        self.p.stop(); gs._sb.clear(); gs._sum.clear()

    def test_neutral_site_listed_the_other_way_round(self):
        # ESPN: Notre Dame (away) 74 at Villanova (home) 72, neutral site; the books listed "Villanova @ Notre Dame"
        ev = event("1", "2026-11-01T14:30Z", comp("Villanova Wildcats", "home", 72, "Villanova", "Villanova", "Wildcats"),
                   comp("Notre Dame Fighting Irish", "away", 74, "Notre Dame", "Notre Dame", "Fighting Irish"), neutral=True)
        sb = {("ncaab", "20261101"): [ev]}
        with mock.patch.object(gs, "scoreboard", side_effect=lambda sp, d: sb.get((sp, d), [])):
            base = {"sport": "ncaab", "event": "Villanova Wildcats @ Notre Dame Fighting Irish",
                    "away": "Villanova Wildcats", "home": "Notre Dame Fighting Irish", "american": -110}
            g = gs.grade_leg(dict(base, market="ml", team="Villanova Wildcats", line=None), "2026-11-01T13:54:00+00:00")
            self.assertEqual(g["result"], "loss")
            g = gs.grade_leg(dict(base, market="ml", team="Notre Dame Fighting Irish", line=None), "2026-11-01T13:54:00+00:00")
            self.assertEqual(g["result"], "win")
            g = gs.grade_leg(dict(base, market="spread", team="Villanova Wildcats", line=2.5), "2026-11-01T13:54:00+00:00")
            self.assertEqual(g["result"], "win")   # lost by 2, +2.5 covers
            g = gs.grade_leg(dict(base, market="total", side="over", line=145.5, team=None), "2026-11-01T13:54:00+00:00")
            self.assertEqual(g["result"], "win")

    def test_swapped_teams_not_matched_at_a_true_home_game(self):
        ev = event("2", "2026-11-01T23:00Z", comp("Boston Celtics", "home", 100), comp("Orlando Magic", "away", 90))
        sb = {("nba", "20261101"): [ev]}
        with mock.patch.object(gs, "scoreboard", side_effect=lambda sp, d: sb.get((sp, d), [])):
            sp, e = gs.find_event({"sport": "nba", "home": "Orlando Magic", "away": "Boston Celtics"}, "2026-11-01T13:00:00+00:00")
        self.assertIsNone(e)

    def test_late_evening_run_uses_the_eastern_date(self):
        # run at 01:00 UTC Nov 2 = 9:00 PM ET Nov 1; the 10:30 PM ET game is on ESPN's Nov 1 scoreboard
        ev = event("3", "2026-11-02T03:30Z", comp("Los Angeles Lakers", "home", 110), comp("Toronto Raptors", "away", 100))
        sb = {("nba", "20261101"): [ev]}
        with mock.patch.object(gs, "scoreboard", side_effect=lambda sp, d: sb.get((sp, d), [])):
            sp, e = gs.find_event({"sport": "nba", "home": "Los Angeles Lakers", "away": "Toronto Raptors"}, "2026-11-02T01:00:00+00:00")
        self.assertIsNotNone(e); self.assertEqual(e["id"], "3")

    def test_void_leg_recomputes_payout(self):
        slip = {"decimal": 2.0 * 1.5, "legs": [{"american": 100}, {"american": -200}]}
        res, dec, profit = gs.grade_slip(slip, [{"result": "win"}, {"result": "void"}])
        self.assertEqual(res, "hit"); self.assertAlmostEqual(dec, 2.0); self.assertAlmostEqual(profit, 1.0)
        self.assertEqual(gs.grade_slip(slip, [{"result": "loss"}, {"result": "pending"}])[0], "miss")
        self.assertEqual(gs.grade_slip(slip, [{"result": "void"}, {"result": "push"}])[:3:2], ("void", 0.0))

    def test_v3_flagged_slips_stay_out_of_the_regular_records(self):
        def slip(sid, strat):
            fs = {"report": "flagged" if "flag" in strat else "single_book", "list": "sgp", "target": 100, "slip_no": 1}
            return {"slip_id": sid, "run_ts": "2026-11-01T13:54:00+00:00", "strategy": strat, "list": "sgp", "decimal": 2.0, "books": ["fanduel"],
                    "legs": [{"label": "X ML", "event": "A @ B", "book": "fanduel", "american": 100, "sport": "nba", "market": "ml"}],
                    "appearances": [fs], "first_seen": fs}
        slips = [slip("a", "v3"), slip("b", "v3-flagged"), slip("c", "v2-flagged")]
        graded = [{"result": "hit", "profit": 1.0, "legs": [{"result": "win"}]}] * 3
        with mock.patch.object(gs, "USER", "/nonexistent"):
            d = gs.build_page_data(slips, graded)
        self.assertEqual({x["s"] for x in d["facts"]}, {"v3"})
        self.assertEqual({x["s"] for x in d["fFacts"]}, {"v2-flagged", "v3-flagged"})
        self.assertEqual(d["overall"]["n"], 1)


class ServicesTests(unittest.TestCase):
    def test_log_bet_rejects_sign_mismatch_and_accepts_unknown_net(self):
        import services as S, add_user_result as aur
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.object(aur, "LEDGER", os.path.join(tmp, "u.jsonl")):
                with self.assertRaises(ValueError): S.log_bet("W", "FanDuel", "NBA", "+250", -10, "2026-11-01")
                with self.assertRaises(ValueError): S.log_bet("L", "FanDuel", "NBA", "+250", 10, "2026-11-01")
                with self.assertRaises(ValueError): S.log_bet("W", "FanDuel", "NBA", "+50", 10, "2026-11-01")
                r = S.log_bet("L", "FanDuel", "NBA", "-110", None, "2026-11-01")
                self.assertIsNone(r["net"]); self.assertEqual(r["bets"][0]["bucket"], "+100")
                r = S.log_bet("W", "theScore Bet", "NFL", " +250 ", 25, "2026-11-01")
                self.assertEqual(r["bets"][0]["odds"], 250)
                self.assertEqual(len(aur.load()), 2)
        finally:
            shutil.rmtree(tmp)

    def test_ledger_signature_changes_when_a_file_changes(self):
        import services as S
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "slips.jsonl"); open(p, "w").write("")
            with mock.patch.object(S, "TRACKER_FILES", (p,)):
                a = S.ledger_signature(); open(p, "w").write("{}\n"); b = S.ledger_signature()
            self.assertNotEqual(a, b)
        finally:
            shutil.rmtree(tmp)


class AppSmokeTest(unittest.TestCase):
    """Runs the Streamlit app headlessly (AppTest) on a throw-away copy of the repo with local storage."""
    def test_app_renders_and_tracker_works(self):
        try:
            from streamlit.testing.v1 import AppTest
        except Exception as ex:
            self.skipTest(f"streamlit not installed: {ex}")
        tmp = tempfile.mkdtemp()
        try:
            dst = os.path.join(tmp, "repo")
            shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "espn_cache", "cache"))
            snap = os.environ.get("PARLAYS_TEST_SNAPSHOT")
            if snap: os.makedirs(os.path.join(dst, "reports"), exist_ok=True); shutil.copy(snap, os.path.join(dst, "reports", "snapshot_latest.json"))
            env = {"APP_PASSWORD": "pw-test", "STORAGE": "local", "ODDS_API_KEY": "", "ODDS_API_KEY_NEW": "", "GITHUB_TOKEN": "", "GH_REPO": ""}
            with mock.patch.dict(os.environ, env):
                for m in ("services", "storage", "parlay_builder", "grade_slips", "add_user_result", "ledger_lib"): sys.modules.pop(m, None)
                saved_path = list(sys.path)
                try:
                    at = AppTest.from_file(os.path.join(dst, "app", "streamlit_app.py"), default_timeout=120).run()
                    self.assertFalse(at.exception, at.exception)
                    at.text_input[0].input("wrong"); at.button[0].click().run()
                    self.assertTrue(any("Wrong password" in e.value for e in at.error))
                    at.text_input[0].input("pw-test"); at.button[0].click().run()
                    self.assertFalse(at.exception, at.exception)
                    self.assertGreaterEqual(len(at.tabs), 3)
                    md = " ".join(m.value for m in at.markdown)
                    self.assertIn("By sportsbook", md); self.assertIn("By odds target", md)
                    next(x for x in at.selectbox if x.label == "List").select("sgp").run()  # a filter change reruns the script (tracker data now cached)
                    self.assertFalse(at.exception, at.exception)
                    if snap:
                        odds_w = next((x for x in at.segmented_control if "Last snapshot (free, no logging)" in getattr(x, "options", [])), None)
                        if odds_w is not None:
                            odds_w.set_value("Last snapshot (free, no logging)").run()
                        else:
                            at.radio[0].set_value("Last snapshot (free, no logging)").run()
                        b = next(x for x in at.button if x.label == "Build parlays"); b.click().run()
                        self.assertFalse(at.exception, at.exception)
                        self.assertFalse([e.value for e in at.error if "Build failed" in e.value])
                        cap = " ".join(c.value for c in at.caption)
                        self.assertIn("SNAPSHOT replay", cap)
                finally:
                    sys.path[:] = saved_path
                    for m in ("services", "storage", "parlay_builder", "grade_slips", "add_user_result", "ledger_lib"): sys.modules.pop(m, None)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
