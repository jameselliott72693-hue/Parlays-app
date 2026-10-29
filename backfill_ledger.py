#!/usr/bin/env python3
"""Backfill the slip ledger from archived report markdown (reports/archive/*.md). Safe to rerun (idempotent)."""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ledger_lib import parse_report, append_slips, ROOT

for f in sorted(glob.glob(os.path.join(ROOT, "reports", "archive", "*.md"))):
    rtype = "single_book" if "single_book" in os.path.basename(f) else "best_price"
    run_ts, slips = parse_report(open(f).read(), rtype)
    a, t = append_slips(run_ts, slips, "backfill:" + os.path.basename(f))
    print(f"{os.path.basename(f)}: run {run_ts}, {len(slips)} slips displayed -> {a} new, {t} tagged as duplicates")
