# Parlay builder prototype
**Current strategy: v3 (2026-10-29)** - see *Strategy v3* below. Web app for the phone: `app/` (see *Web app* below and `DEPLOY.md`).
Backup of the pre-v3 folder: `/workspace/parlays_backup_20261029`.
- `parlay_builder.py` - run `python3 parlay_builder.py` (live, keyless: FanDuel + Underdog; default sports NFL, NBA, NHL, NCAAF, NCAAB). Report -> `reports/parlays_<ts>.md` (or `--out`).
- Targets: +100, +200, +300, +400; up to 3 slips each; SGP list (estimated prices) first, then the multi-game list, then the 3-leg list (see below).
- `ODDS_API_KEY=...` adds DraftKings / BetMGM / theScore Bet (`espnbet`) / Caesars (`williamhill_us`, paid plans only) via The Odds API. Odds API props are on by default but frugal: per sport nfl 1, nba 1, nhl 2, ncaaf 0 (v3), ncaab 1 game(s), only games starting within 48 h (see *Odds API credits (v3)* below; hard cap 40/run, reserve 50). `--oddsapi-prop-events N` (same N for every sport), `--oddsapi-max-credits N`, `--no-oddsapi-props` adjust.
- `--no-dfs-legs`, `--sports nfl,nba,nhl,ncaaf,ncaab,mlb` (default `nfl,nba,nhl,ncaaf,ncaab`; MLB is available but off by default), `--save-snapshot/--from-file`, `--no-ledger`, `--flagged` (show flagged-price slips; off by default since v3; `--no-flagged` still accepted), `--no-3leg`, `--flagged-only-ledger`,
  `--v2-props` (v2 prop rules, tagged v2), `--no-cache`, `--cache-ttl-min N`, `--gameline-window-h N`, `--log-gap-min N`.
- `probe/` holds raw JSON captured during the feasibility test.

## Strategy v3 (default since 2026-10-29)
Built from the settled v2 results (64 slips, 34.4% hit vs 33.4% predicted, -5.88u; leg hit rates ML 31/46, spread 3/5, total 7/9,
props 31/63; v2-flagged 1-for-10, -6.08u, flagged prop legs 4/16). Every v2 rule still applies, plus:
1. **Props need a deep, agreeing market.** A player-prop leg is used only when >= 4 books quote that exact line (Underdog counts
   once; its market price and pick'em payout are the same book) AND the books' no-vig fair probabilities are within 4 pp of each other
   (max - min, `PROP_MIN_BOOKS` / `PROP_MAX_FAIR_SPREAD`). Game lines (ML / spread / total) are unchanged. Fewer slips are shown rather
   than relaxing. On the 2026-10-29 18:10 UTC data: eligible prop leg x book pairs 893 (v2) -> 531 (v3); distinct prop outcomes 266 -> 120
   (of 4072 quoted); prop legs in the displayed slips 22 of 66 (v2 replay) -> 9 of 66; still 28 slips (game lines fill the gap).
   The report's "Leg checks" line counts props rejected for < 4 books and for books disagreeing.
2. **Price shopping.** Under every slip: `Price shop (same legs at each book): 🏆 **DraftKings +215** · FanDuel +200 (this slip) · ...
   · not offered at: ...` = what each book that offers ALL the slip's legs would pay (product of its leg prices; for SGP / SGP-3 it is an
   estimate, books price correlation). The 🏆 best book is the highest payout among books with no off-market leg (off-market prices are
   shown with "off-market", never best); Underdog is marked pick'em. Every slip stays placeable at one book (the one named, or the 🏆 book).
   Ledger rows get optional `shop` ({book: american}), `best_book`, `best_american` (+ `shop_off_market`); older rows simply lack them.
   First v3 run: another book paid more on 4 of 28 slips (+3.1% payout on average).
3. **Flagged-price slips OFF by default** (`--flagged` shows and logs them, tag `v3-flagged`). The 🔴 *Check these prices* list stays.
   v2-flagged history stays in the ledger and on the tracker; any strategy ending in `-flagged` is tracked apart (red).
4. Ledger tag `"strategy": "v3"`; the tracker's strategy filter shows v1 / v2 / v3 (+ red flagged tags) and the Strategy breakdown splits them.
5. **Closing-line value per strategy** on the tracker (Page and app): legs with a same-line ESPN/DraftKings close, average CLV in pp, %
   of legs that beat the close, and the average split by ML / spread / total (`clv[].mkt` in the Page data). No per-leg lists.
   As of 2026-10-29: v1 +1.06 pp (65% beat, 51 legs), v2 +0.86 pp (73%, 44 legs).

## Odds API credits (v3, 2026-10-29)
- **Cache:** every paid Odds API response is saved in `reports/cache/oddsapi/` (key = URL without the API key and the moving
  `commenceTimeFrom`); a response younger than 15 minutes is reused for 0 credits (`--cache-ttl-min`, `--no-cache`). Started games are
  dropped from a cached copy. The report header and log show credits used, cache hits and credits saved.
- **Skip empty sports:** before any paid call, the free `/v4/sports/{sport}/events` list (0 credits, verified) is read for the next 48 h;
  if it shows no game AND FanDuel / Underdog list none either, the sport's game-line and prop calls are skipped (`--gameline-window-h 48`;
  0 = never skip). Out-of-season sports are still skipped via the free `/sports` list. Trade-off: on days with no game in the next 48 h
  for a sport (e.g. NFL on a Tuesday) its far-off games get no Odds API books, so no slips for that sport that day (their lines are the
  least settled anyway).
- **NCAAF props off** (`OA_PROP_EVENTS["ncaaf"] = 0`): Odds API college props come from 2 books at most and can never pass the v3 4-book rule.
- **Credits per run, before -> after:** worst case 35 -> 31 (nfl 7, nba 8, nhl 7, ncaaf 3, ncaab 6); the last v2 run cost 32; the first v3
  run (2026-10-29 18:10 UTC, same slate) cost **25** (NCAAB skipped: no game until 2026-11-02; NCAAF props off); a re-run within 15 minutes
  costs **0** (verified: 8 cached responses, ~25 credits saved). Free plan 500/month -> about 20 fresh runs a month.
- The free `/sports` call also refreshes `reports/cache/oddsapi_balance.json` (last known balance, no key inside) for the app.

## Sports and Odds API credits (updated 2026-10-27; credit numbers superseded by the v3 section above)
- Default sports: NFL, NBA, NHL, NCAAF, NCAAB (ledger / tracker labels `NFL`, `NBA`, `NHL`, `NCAAF`, `NCAAB`; mixed slips `Mixed (NBA + NHL)` etc.,
  labels sorted alphabetically). Sources per sport: FanDuel page ids `nfl nba nhl ncaaf ncaab`; Underdog sport codes `NFL NBA NHL CFB CBB`;
  Odds API keys `americanfootball_nfl basketball_nba icehockey_nhl americanfootball_ncaaf basketball_ncaab` (`baseball_mlb` for MLB).
- Odds API props markets: NFL pass/rush/reception yds + receptions (4); NBA points/rebounds/assists/threes/PRA (5); NHL points + shots on goal (2);
  NCAAF pass + rush yds (2); NCAAB points/rebounds/assists (3). **Cost = markets x events** (odds call = 3 credits per sport).
- **Default run: 15 credits for the 5 odds calls + props for 1 NFL, 1 NBA, 2 NHL, 2 NCAAF, 1 NCAAB event = 4+5+4+4+3 = 20 -> at most 35 credits**
  (cap 40). Typical 20-30: props are only pulled for games that start within 48 h (otherwise 0 credits for that sport), events with no props posted
  cost 0-1, and an out-of-season sport is skipped for 0 credits. The first 5-sport test run cost 25. A 2-sport (NFL+NBA, 2 events each) run was ~24.
- Out-of-season / empty sports are skipped automatically: the Odds API `/sports` list (free) says which keys are `active`; FanDuel pages with no games and Underdog
  sports with no lines just return no quotes. The report header shows `Sports coverage (quotes)` with `NO DATA` for any requested sport that returned nothing.
  (NCAAB season starts 2026-11-02: until then only a few DraftKings opening lines exist, so no NCAAB slips can pass the 3-books rule.)
- College team names differ per book (FanDuel `Miami Florida`, Odds API `Miami Hurricanes`); the builder rewrites every college team to ESPN's displayName
  (index built from ESPN's free scoreboards for the next ~2 weeks, plus a small alias table `TEAM_ALIASES`). Unmatched names are logged under `[names]`
  and left as given (those games then can't be cross-confirmed, so they are never used: safe).
- Player props reality check: FanDuel's NHL shots/points/assists markets are one-sided "2+" ladders (no under, can't be de-vigged); only "Total Goals" O/U is
  parsed. NHL props therefore come from Underdog (shots, points, assists, goals) and the Odds API (points, shots on goal). College props usually have
  FanDuel + Underdog only until game day, which fails the "3+ books behind the fair price" rule, so most college slips are game lines (ML/spread/total).

## Strategy v2 (default since 2026-10-23)
Built from the first 105 settled v1 slips (see the tracker). Every rule is on by default:
1. **Off-market prices rejected.** A leg priced >= 5 pp of implied probability better than the median of the *other
   sportsbooks* (Underdog left out of that median) is never used; it is listed under **Check these prices** instead.
2. **Confirmation.** >= 3 books behind the leg's no-vig fair price, and >= 2 sportsbooks quoting it (another
   sportsbook within 3 pp of the price used). Underdog's pick'em payout stays out of the fair price (as before; Underdog's
   market price still counts). An Underdog pick'em leg is allowed when >= 3 books other than Underdog are behind the fair
   price and >= 2 sportsbooks quote it.
3. **Ranking by fair hit probability** (consensus no-vig, legs independent), closest tolerance tier first (6%, 12%, 20%
   of the target's decimal odds; v2 never goes wider). Est. EV is shown for information only.
4. **Placeable slips only.** SGP and multi-game slips are each at one book. The default report is therefore the
   single-book report; `--single-book` is accepted but a no-op in v2.
5. **SGP first; multi-game +300/+400 hidden** unless `--show-long-multi`.
6. **Leg reuse cap:** a leg (outcome) appears in at most 2 displayed slips per run; no shared leg within a target and
   no identical slip at two targets.
7. **Max 2 legs** per slip in the SGP and multi-game lists (`--max-legs` is capped at 2 unless `--legacy`). The separate 3-leg list is the one user-approved exception.
8. **Unders-first test:** ties in fair probability (to 0.5 pp) go to the slip with more prop unders, and every slip line
   carries `props: U<n>/O<n>`; the ledger stores `prop_sides` and the Page has a "Prop sides" breakdown.
9. **Staking note** in every report: flat 0.5-1% of bankroll per slip (no Kelly while the measured edge is <= 0).
10. **Closing prices:** `grade_slips.py` stores, for moneyline/spread/total legs on final games, the DraftKings line ESPN
    shows in its game summary (keyless, no Odds API credits) and the CLV in pp. Player props have no free closing
    source; Odds API historical odds would cost credits (paid plans), so that is not done.
- Pool selection: per book, an equal share of legs from each price bucket (1.2-1.6, 1.6-2.0, 2.0-2.6, 2.6-4.0 decimal),
  lowest vig first within a bucket, so every target is reachable.
- If the rules leave fewer than 3 slips at a target, fewer are shown and the report says so ("Targets short of 3 slips").
- `--legacy` reproduces v1 exactly (best price per leg across books, EV ranking, up to 4 legs, no leg filters;
  add `--single-book` for the old single-book companion report).
- Ledger rows are tagged `"strategy": "v2"` (rows without the field are v1); the Page splits v1 vs v2 (and v3 since 2026-10-29).

### 3-leg parlays list (added 2026-10-27; on by default, `--no-3leg` hides it)
User-requested third list after the SGP and multi-game lists (before the flagged section). Same targets (+100/+200/+300/+400), up to 3 slips each,
**+300/+400 are not hidden**. Exactly 3 legs, whole slip at ONE book, either all in one game (**SGP-3**, price is an estimate: books apply correlation pricing) or one leg
in each of 3 different games (**Multi-game-3**); each slip line says which. All the other v2 rules still apply: off-market legs rejected, 3+ books behind the fair price,
a second sportsbook within 3 pp, rank by fair hit probability (unders first on ties), each leg in at most 2 slips *of this list*, within +-20% of the target odds,
no identical slip at two targets, fewer slips shown rather than relaxing a rule. (Three legs at -150 or shorter multiply to about +100, so +100 is often short.)
Flagged-price slips stay max 2 legs. Ledger: strategy `v2`, list `3leg` (plus `kind` SGP-3 / Multi-game-3); the Page's list filter gets a "3-leg" option
(and "All lists") and the List breakdown shows "3-leg" separately. `--no-3leg` hides the list and skips logging it.

### Flagged-price slips (added 2026-10-24; OFF by default since v3 2026-10-29: `--flagged` to show)
The user asked to see the slips the off-market rule removes, highlighted in red. After the regular lists the report has a
**🔴 Flagged-price slips** section (SGP +100..+400, multi-game +100/+200, `--show-long-multi` for +300/+400), up to 3 slips per target.
- Every slip has >= 1 *flagged leg* (price >= 5 pp of implied probability better than the other sportsbooks' median, the same
  legs listed under **🔴 Check these prices**). Only the off-market rejection (and the "second sportsbook within 3 pp"
  confirmation, which a stale price cannot meet) is relaxed. Still enforced: max 2 legs, one book per slip, leg reuse <= 2 within the
  flagged section (own counter), the other leg(s) pass every regular v2 check at the same book, +-20% of target odds, closest tier first.
- >= 3 books behind a flagged leg's fair price; if the section would be short, 2 is allowed as a labeled fallback ("Fewer than 3 books
  ...") and those slips rank last. A flagged leg's **fair probability excludes the flagged book's own price** (it is the outlier).
- Markup: 🔴 on the slip line, a warning line under every slip ("price is far off the other books; may be stale or a boost, check in
  app"), 🔴 on the flagged leg, and a Flag column with the gap (pp better than the others' median, median implied vs price implied);
  the Other books column lists what the other books offer. The report is markdown only; the Page uses red.
- Off by default since v3; `--flagged` shows and logs the section. Ledger tag: `"strategy": "v2-flagged"` (v3 runs: `v3-flagged`), appearance report type `flagged`.
  `grade_slips.py` keeps them out of every regular total (overall, strategy/list/report/props breakdown, records tables, by run):
  the Page shows them as separate red lines/rows and a red `v2-flagged` option in the strategy filter.
- Backfill a run whose regular slips are already logged (no Odds API credits):
  `python3 parlay_builder.py --from-file reports/snapshot_latest.json --no-ledger --flagged --out reports/latest_flagged_replay.md` (review), then
  `python3 parlay_builder.py --from-file reports/snapshot_latest.json --flagged-only-ledger --out reports/latest_flagged_replay.md`
  (logs only the `v2-flagged` slips; idempotent; refuses if the live run is not in the ledger).
  A normal live run logs regular and flagged slips together.

### Run command (v2/v3, unchanged)
```
cd /workspace/parlays && python3 parlay_builder.py --out reports/latest.md --save-snapshot reports/snapshot_latest.json
```
The old two-step command still works: the `--from-file reports/snapshot_latest.json --single-book --out reports/latest_single_book.md`
replay produces the same v2 slips and is not logged again (the live run already logged the run's single-book report).
Test without credits or logging: `python3 parlay_builder.py --from-file reports/snapshot_latest.json --no-ledger --out /tmp/test.md`.

## Slip tracker (ledger + grading + Page)
- Page: **Parlay Tracker**, canvas id `888feb17-cd3c-492e-8d44-46b8d6fac722`
  (https://cursor.com/canvas/store-12ff3b9c-b466-4407-b7e9-358e9163af93/888feb17-cd3c-492e-8d44-46b8d6fac722)
- `ledger/slips.jsonl` - every displayed slip, one record per unique slip per run (run_ts, list, odds, books, est. EV,
  structured legs: sport, teams, commence, market, player, stat, line, side) with `appearances` tags
  (report best_price/single_book, list, target, slip_no), `strategy` (v2; absent = v1) and `prop_sides`.
  Identical slips across both reports are stored once.
- Logging is automatic: a live `parlay_builder.py` run logs its report (v2: as the run's single_book report; `--legacy`:
  best_price); a `--from-file ... --single-book` companion replay is logged only if that report type is not yet logged
  for the run (other replays are not logged). `--no-ledger` disables.
  Flagged-price slips (strategy `v2-flagged`) are logged with the run unless `--no-flagged`.
  Each logged report is also archived to `reports/archive/<run>_<type>.md`.
- `backfill_ledger.py` - re-import `reports/archive/*.md` (idempotent).
- `grade_slips.py` - grades NFL, NBA, NHL, NCAAF and NCAAB (see *Grading by sport*) from ESPN public JSON (site.api.espn.com, keyless, no Odds API credits), writes
  `ledger/grades.json` (including ESPN closing prices for game-line legs), and regenerates the Page source at `ledger/page_contents.tsx.txt` from
  `ledger/page_template.tsx.txt` (template has a `/*__DATA__*/null` placeholder).
- Update the Page: `cd /workspace/parlays && python3 grade_slips.py`, then WriteCanvas with
  canvas_id `888feb17-cd3c-492e-8d44-46b8d6fac722` and the full contents of `ledger/page_contents.tsx.txt`.
- "Records by sportsbook, odds and sport" section: three tables of graded slips (by book, with v1 split-book slips as
  "Mixed books"; by odds target +100/+200/+300/+400 with average actual odds; by sport: NBA, NFL, NHL, NCAAF, NCAAB and `Mixed (...)` labels such as "Mixed (NBA + NFL)", "Mixed (NBA + NHL)").
  Each row: W-L record (+ voids/ungraded if any), pending, hit rate, units and ROI at 1u per slip. Filters: strategy
  (All / v1 / v2, only strategies present in the ledger), SGP vs multi-game; sort by default order, units, hit rate, slips.
  A slip counts once, at the target where it first appeared. Built client-side from `facts` in the Page data.
  Red rows = flagged-price slips (from `fFacts`; never added into regular rows). Legend on the Page: red = flagged-price slips,
  blue = your bets, default = regular slips.

## Grading by sport (ESPN box scores, keyless)
- Games are found on ESPN's scoreboard by sport (`football/nfl`, `basketball/nba`, `hockey/nhl`, `football/college-football`, `basketball/mens-college-basketball`) by team + date.
  College teams must match ESPN's displayName (the builder standardizes names); a college mascot alone never matches.
- Game lines: moneyline, spread/puck line, total (NHL shootout: ESPN adds a goal to the winner; totals are graded without it). Closing line = ESPN's DraftKings pickcenter.
- Player props supported: NBA and NCAAB `points rebounds assists steals blocks three_points_made` + PRA combos (DNP = void); NFL and NCAAF `passing_yds passing_tds rushing_yds
  receiving_yds receiving_rec rush_rec_yds` (a player missing from the relevant table = ungraded, never a miss); NHL `goals assists points shots (SOG) blocked_shots saves`.
- Anything else (unknown stat, player not in the box score, e.g. an NHL scratch who is simply not listed) is `ungraded`/`pending`, never a false loss: ask the user, then use `leg_overrides.json`.
- Stat names: `shots` = shots on goal, `points` (NHL) = goals + assists.

## Your own results (separate from graded slips)
- `python3 add_user_result.py --wins 3 --losses 2 [--pushes 0] [--net 45.50] [--units 1.2] [--date 2026-10-22] [--note "..."]`
- Optional whole-entry tags: `--book FanDuel --sport NBA --odds +250` (`--odds` takes American odds or a target such as +200).
- Several bets in a day: log each bet with a repeatable `--bet "RESULT BOOK SPORT ODDS NET"` (RESULT = W, L or P; `-` for
  an unknown field; quote multi-word books inside the string). Wins/losses/pushes and net $ are then computed from the bets:
  `python3 add_user_result.py --date 2026-10-23 --bet "W FanDuel NBA +250 25" --bet "L 'theScore Bet' NFL -110 -11"`
  `--bet` and the whole-entry tags can't be combined in one entry.
- Sports: NBA, NFL, NHL, NCAAF (also `college football`, `CFB`), NCAAB (also `college basketball`, `CBB`, `NCAAM`), MLB; `hockey` -> NHL. Quote multi-word names inside `--bet`, e.g. `--bet "W FanDuel 'college football' +300 20"`. A mixed parlay takes `Mixed` (= `Mixed (NBA + NFL)`), `NBA/NHL`, `NHL+NBA` or `NBA & NCAAF` and is
  stored with sorted labels, e.g. `Mixed (NBA + NHL)`, the same label the slip tables use, so it lands in that row. Older entries are unchanged.
- Odds buckets: under +150 (incl. minus odds) = +100, +150..+249 = +200, +250..+349 = +300, +350 and longer = +400.
- On the Page your bets are shown in blue: a line under the overall slip metrics, a blue "You" row under the matching row of each
  record table (unmatched keys, incl. `Untagged`, at the bottom), and the blue per-day log. Never added into the slip totals.
- `python3 add_user_result.py --list` / `python3 add_user_result.py --undo` (removes the last entry)
- Stored in `ledger/user_results.jsonl`; shown in the Page's "Your reported results" section after the next
  `python3 grade_slips.py` + Page update. Never merged into the graded tally.

## Manual leg overrides (`ledger/leg_overrides.json`)
- When a leg can't be graded automatically (typically `UNGRADED ... player not in ESPN box score`), **ask the user**; never assume a void.
  Once he confirms, add an entry to `ledger/leg_overrides.json` and re-run `python3 grade_slips.py`. `slips.jsonl` is never edited.
- Format: `{"overrides": [{"player": "Olamide Zaccheaus", "event": "San Francisco 49ers @ Atlanta Falcons", "date": "2026-10-25",
  "stat": "receiving_rec", "side": "under", "line": 1.5, "result": "void", "reason": "DNP/inactive; confirmed by user 2026-10-26", "note": "..."}]}`
  - Match on `player` (or an exact `label`) plus optional `event`, `date` (ET game date), `market`, `stat`, `side`, `line`; use `event` + `date` so it
    hits only that game. An override applies to EVERY slip containing the leg (all runs, regular and flagged).
  - `result` is `void`, `push`, `win` or `loss`; void/push legs are removed and the slip's odds recomputed (a slip with only void legs is void).
  - The grade records `override: true`, the reason and any note; if it replaces an already-decided result the grader prints a WARNING and keeps the
    original as `auto_result`. Duplicate an entry only by mistake: check the file first.
- Current overrides: Olamide Zaccheaus Under 1.5 receptions (49ers @ Falcons, 2026-10-25) = void (5 slips contain it).

## Web app (phone) - `app/` (added 2026-10-29)
- `app/streamlit_app.py` (Streamlit UI), `app/services.py` (in-process wrappers: build, grade, log bet, tracker data), `app/storage.py`
  (pluggable storage). Config: `requirements.txt`, `.streamlit/config.toml` (mobile theme), `.streamlit/secrets.toml.example`,
  `.gitignore`, `.github/workflows/grade.yml` (daily grading). Deployment guide: `DEPLOY.md`. Deployable copy: `/workspace/parlays_app_repo`
  (refresh with `bash app/export_repo.sh`).
- Run locally: `cd /workspace/parlays && APP_PASSWORD=... python3 -m streamlit run app/streamlit_app.py` (uses `ODDS_API_KEY` from the env).
- Features: password gate (`APP_PASSWORD` secret, constant-time compare, slow-down after wrong tries; the app refuses to open without it),
  **Build** tab (sport toggles, "Show flagged slips", "Multi-game +300/+400", live odds or the last snapshot for free, Odds API credits left +
  cost of a fresh run + cache status, the three lists as cards with price-shop chips and the 🏆 best book, Check these prices, report download),
  **Tracker** tab (records by strategy / book / odds target / sport / list with strategy + list filters, flagged rows red, your bets blue,
  CLV summary, price-shop summary, your recent bets, **Grade now**), **Log my bet** (W/L/P, book, sport, odds, net $, date, note -> appended to
  `ledger/user_results.jsonl` exactly like `add_user_result.py --bet`).
- Live builds from the app pass `--log-gap-min 15`: a run within 15 minutes of an already-logged run is shown but not logged (cached odds
  would otherwise double-count the same slips). Optional secret `ODDS_MAX_CREDITS_PER_RUN` lowers the 40-credit cap.
- Storage: `STORAGE=local` or no GitHub secrets -> files on disk. With `GITHUB_TOKEN` + `GH_REPO`, ledger files
  (`slips.jsonl`, `user_results.jsonl`, `grades.json`, `page_contents.tsx.txt`, `leg_overrides.json`) live on the `ledger-data` branch
  (`GH_DATA_BRANCH`) of the private repo: pulled/merged on start and before every action, committed after every change (one commit via the
  Git Data API; *.jsonl are union-merged, so concurrent writers never lose rows; an `--undo` done elsewhere is not propagated). The daily
  workflow grades at 13:00 UTC (9 AM EDT / 8 AM EST) and commits to the same branch. Using a separate branch means saving data never
  redeploys the app.
- To update the Grok tracker Page from cloud data: download `ledger/page_contents.tsx.txt` from the `ledger-data` branch (or run
  `grade_slips.py` here) and WriteCanvas as before.
