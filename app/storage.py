"""Pluggable durable storage for the ledger files.

Free hosts (Streamlit Community Cloud, Render free) wipe the disk on every restart, so the app keeps the ledger in a PRIVATE
GitHub repo and commits every change back through the GitHub REST API:

  * LocalStorage  - files on disk only (running on your own computer / this box). pull() and push() do nothing.
  * GitHubStorage - the files live on a data branch (default "ledger-data") of the private repo. pull() downloads them and
                    merges them into the local copies; push() commits the changed files in ONE commit (Git Data API). If the
                    branch moved meanwhile (e.g. the daily grading workflow committed), it re-pulls, merges and retries.

Merging is append-friendly: *.jsonl files are unioned line by line (slips by (run_ts, slip_id), your bets by the whole record),
grades.json / page_contents.tsx.txt keep the newer grading, leg_overrides.json keeps the remote copy unless missing remotely.
Secrets come from environment variables / Streamlit secrets: GITHUB_TOKEN (fine-grained, Contents read+write on the repo),
GH_REPO ("owner/name"), optional GH_DATA_BRANCH (default "ledger-data"). The token is never logged or shown.
"""
import base64, json, os, time, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNC_FILES = ["ledger/slips.jsonl", "ledger/user_results.jsonl", "ledger/grades.json",
              "ledger/page_contents.tsx.txt", "ledger/leg_overrides.json"]


def _read(path):
    p = os.path.join(ROOT, path)
    return open(p, "rb").read() if os.path.exists(p) else None


def _write(path, data):
    p = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "wb") as f: f.write(data)
    os.replace(tmp, p)


def _jsonl(b):
    return [json.loads(x) for x in (b or b"").decode("utf-8").splitlines() if x.strip()]


def merge(path, local, remote):
    """Return merged bytes for one file (local and remote are bytes or None)."""
    if remote is None: return local
    if local is None: return remote
    if local == remote: return local
    if path.endswith("slips.jsonl"):
        rows = {}
        for r in _jsonl(remote) + _jsonl(local):
            k = (r["run_ts"], r["slip_id"])
            if k in rows:  # keep every appearance tag from both copies
                for a in r.get("appearances", []):
                    if a not in rows[k]["appearances"]: rows[k]["appearances"].append(a)
            else:
                rows[k] = r
        out = sorted(rows.values(), key=lambda r: (r["run_ts"], r["first_seen"]["report"], r["first_seen"]["list"],
                                                   r["first_seen"]["target"], r["first_seen"]["slip_no"]))
        return "".join(json.dumps(r) + "\n" for r in out).encode()
    if path.endswith("user_results.jsonl"):
        seen, out = set(), []
        for r in _jsonl(remote) + _jsonl(local):
            k = json.dumps(r, sort_keys=True)
            if k not in seen: seen.add(k); out.append(r)
        out.sort(key=lambda r: r.get("entered_at", ""))
        return "".join(json.dumps(r) + "\n" for r in out).encode()
    if path.endswith("grades.json"):
        try:
            gl, gr = json.loads(local).get("graded_at", ""), json.loads(remote).get("graded_at", "")
            return local if gl >= gr else remote
        except Exception:
            return local
    if path.endswith("page_contents.tsx.txt"):
        return None  # decided together with grades.json (see GitHubStorage.pull)
    return remote  # leg_overrides.json and anything else: the repo copy wins


class LocalStorage:
    kind = "local"
    label = "Local files (this computer)"
    def pull(self): return "local files"
    def push(self, paths, message): return "saved locally"
    def status(self): return {"kind": self.kind, "label": self.label}


class GitHubStorage:
    kind = "github"
    API = "https://api.github.com"

    def __init__(self, token, repo, branch="ledger-data"):
        self._token, self.repo, self.branch = token, repo.strip().strip("/"), branch or "ledger-data"
        self.label = f"GitHub {self.repo} (branch {self.branch})"
        self.last_pull = None

    # -- low-level --
    def _req(self, method, path, body=None, accept="application/vnd.github+json", raw=False):
        url = self.API + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "parlay-app", **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                b = r.read()
                return r.status, (b if raw else (json.loads(b) if b else None))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            return e.code, {"message": msg}

    def _head(self):
        st, d = self._req("GET", f"/repos/{self.repo}/git/ref/heads/{urllib.parse.quote(self.branch)}")
        if st == 200: return d["object"]["sha"]
        if st == 404: return None
        raise RuntimeError(f"GitHub: cannot read branch {self.branch} ({st}: {d.get('message', '')[:120]})")

    def ensure_branch(self):
        """Create the data branch from the default branch if it does not exist yet."""
        sha = self._head()
        if sha: return sha
        st, repo = self._req("GET", f"/repos/{self.repo}")
        if st != 200: raise RuntimeError(f"GitHub: repo {self.repo} not reachable with this token ({st})")
        st, d = self._req("GET", f"/repos/{self.repo}/git/ref/heads/{repo['default_branch']}")
        if st != 200: raise RuntimeError(f"GitHub: default branch not readable ({st})")
        base = d["object"]["sha"]
        st, d = self._req("POST", f"/repos/{self.repo}/git/refs", {"ref": f"refs/heads/{self.branch}", "sha": base})
        if st not in (200, 201): raise RuntimeError(f"GitHub: could not create branch {self.branch} ({st}: {d.get('message', '')[:120]})")
        return base

    def _get_file(self, path):
        st, b = self._req("GET", f"/repos/{self.repo}/contents/{path}?ref={urllib.parse.quote(self.branch)}",
                          accept="application/vnd.github.raw", raw=True)
        if st == 200: return b
        if st == 404: return None
        raise RuntimeError(f"GitHub: cannot read {path} ({st})")

    # -- public --
    def pull(self):
        self.ensure_branch()
        remote = {p: self._get_file(p) for p in SYNC_FILES}
        for p in SYNC_FILES:
            if p.endswith("page_contents.tsx.txt"): continue
            m = merge(p, _read(p), remote[p])
            if m is not None and m != _read(p): _write(p, m)
            if p.endswith("grades.json") and remote[p] is not None and m == remote[p] and remote.get("ledger/page_contents.tsx.txt"):
                _write("ledger/page_contents.tsx.txt", remote["ledger/page_contents.tsx.txt"])
        if _read("ledger/page_contents.tsx.txt") is None and remote.get("ledger/page_contents.tsx.txt"):
            _write("ledger/page_contents.tsx.txt", remote["ledger/page_contents.tsx.txt"])
        self.last_pull = time.time()
        return f"pulled from {self.label}"

    def push(self, paths, message):
        """Commit the given local files to the data branch in one commit. Retries after merging if the branch moved."""
        for attempt in range(3):
            head = self.ensure_branch()
            st, commit = self._req("GET", f"/repos/{self.repo}/git/commits/{head}")
            if st != 200: raise RuntimeError(f"GitHub: cannot read commit ({st})")
            tree = []
            for p in paths:
                b = _read(p)
                if b is None: continue
                rb = self._get_file(p)  # file as of the branch head (may contain another writer's changes since our last pull)
                m = merge(p, b, rb)
                if m is not None and m != b:
                    _write(p, m); b = m
                if b == rb: continue  # unchanged
                st, blob = self._req("POST", f"/repos/{self.repo}/git/blobs", {"content": base64.b64encode(b).decode(), "encoding": "base64"})
                if st not in (200, 201): raise RuntimeError(f"GitHub: blob upload failed for {p} ({st}: {blob.get('message', '')[:120]})")
                tree.append({"path": p, "mode": "100644", "type": "blob", "sha": blob["sha"]})
            if not tree: return "nothing changed"
            st, t = self._req("POST", f"/repos/{self.repo}/git/trees", {"base_tree": commit["tree"]["sha"], "tree": tree})
            if st not in (200, 201): raise RuntimeError(f"GitHub: tree failed ({st})")
            st, c = self._req("POST", f"/repos/{self.repo}/git/commits", {"message": message, "tree": t["sha"], "parents": [head]})
            if st not in (200, 201): raise RuntimeError(f"GitHub: commit failed ({st})")
            st, d = self._req("PATCH", f"/repos/{self.repo}/git/refs/heads/{urllib.parse.quote(self.branch)}", {"sha": c["sha"], "force": False})
            if st == 200: return f"saved to {self.label}: {', '.join(x['path'].split('/')[-1] for x in tree)}"
            if st in (409, 422):  # branch moved: merge the remote copies in and retry
                self.pull(); time.sleep(1); continue
            raise RuntimeError(f"GitHub: update failed ({st}: {d.get('message', '')[:120]})")
        raise RuntimeError("GitHub: branch kept moving; try again")

    def status(self):
        return {"kind": self.kind, "label": self.label, "last_pull": self.last_pull}


def get_storage(cfg):
    """cfg: dict-like with GITHUB_TOKEN, GH_REPO, GH_DATA_BRANCH, STORAGE ('local' forces local files)."""
    if (cfg.get("STORAGE") or "").lower() == "local": return LocalStorage()
    tok, repo = cfg.get("GITHUB_TOKEN"), cfg.get("GH_REPO")
    if tok and repo: return GitHubStorage(tok, repo, cfg.get("GH_DATA_BRANCH") or "ledger-data")
    return LocalStorage()
