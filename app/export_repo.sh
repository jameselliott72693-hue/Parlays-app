#!/usr/bin/env bash
# Copy the deployable app (code + current ledger data, no secrets / caches / snapshots) to /workspace/parlays_app_repo and commit.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="${1:-/workspace/parlays_app_repo}"
mkdir -p "$DST"
# clear the old copy (keep its git history and screenshots), then copy without secrets / caches / snapshots
find "$DST" -mindepth 1 -maxdepth 1 ! -name '.git' ! -name 'screenshot_*.png' -exec rm -rf {} +
tar -C "$SRC" \
  --exclude='./.git' --exclude='./screenshot_*.png' \
  --exclude='./.parlayapi_key' --exclude='./.streamlit/secrets.toml' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='./reports/cache' --exclude='./reports/snapshot_*.json' --exclude='./reports/*.md' --exclude='./reports/*.log' \
  --exclude='./ledger/espn_cache' --exclude='./ledger/*.tmp' --exclude='./probe' \
  -cf - . | tar -C "$DST" -xf -
mkdir -p "$DST/reports/archive" "$DST/ledger"
cd "$DST"
[ -d .git ] || git init -q -b main
git add -A
if git diff --cached --quiet; then echo "nothing to commit"; else
  git -c user.name="Parlay App" -c user.email="parlay-app@users.noreply.github.com" commit -q -m "${2:-Parlay app: code + ledger data}"
  git log --oneline -1
fi
