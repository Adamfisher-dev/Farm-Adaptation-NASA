"""appeears.py - small client for NASA AppEEARS point extractions (SMAP, HLS).

AppEEARS (LP DAAC) samples NASA products at points on NASA's servers and returns
small CSVs, so we never download whole SMAP or HLS granules.
API docs: https://appeears.earthdatacloud.nasa.gov/api/

Used only by scripts/prefetch_field_data.py; the app never calls external services.

Login: NASA Earthdata username + password, taken from (in order)
  1. ~/.netrc (or ~/_netrc) entry for urs.earthdata.nasa.gov  (earthaccess writes this)
  2. environment variables EARTHDATA_USERNAME / EARTHDATA_PASSWORD
  3. a prompt
Credentials are sent only to AppEEARS and never written to the repo.

No Streamlit calls in this file (project rule).
AI use: drafted with Claude (Anthropic); reviewed by the team.
"""

from __future__ import annotations

import getpass
import json
import netrc
import os
import time
from pathlib import Path

import requests

from fieldshift import config

API = config.APPEEARS_URL
EARTHDATA_HOST = "urs.earthdata.nasa.gov"


# --- Credentials and login --------------------------------------------------------
def earthdata_credentials():
    for name in (".netrc", "_netrc"):
        path = Path.home() / name
        if path.exists():
            try:
                auth = netrc.netrc(str(path)).authenticators(EARTHDATA_HOST)
            except (netrc.NetrcParseError, OSError):
                auth = None
            if auth:
                return auth[0], auth[2]
    user, pw = os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD")
    if user and pw:
        return user, pw
    user = input("NASA Earthdata username: ").strip()
    return user, getpass.getpass("NASA Earthdata password: ")


def _request(method, url, tries=4, timeout=120, **kw):
    """requests call with retries: AppEEARS (and the Earthdata check behind its login)
    sometimes stalls or returns 5xx for a minute or two."""
    for attempt in range(1, tries + 1):
        try:
            r = requests.request(method, url, timeout=timeout, **kw)
            if r.status_code < 500:
                return r
            problem = f"HTTP {r.status_code}"
        except (requests.Timeout, requests.ConnectionError) as err:
            problem = type(err).__name__
        if attempt == tries:
            raise RuntimeError(f"AppEEARS not responding ({problem}) after {tries} tries: {url}. "
                               "Try again later; status: https://appeears.earthdatacloud.nasa.gov")
        wait = 15 * attempt
        print(f"  AppEEARS {problem}; retrying in {wait} s ({attempt}/{tries - 1})")
        time.sleep(wait)


# Token cache (data/raw is gitignored). The token gives access to your AppEEARS
# requests until it expires; it is not your password.
TOKEN_FILE = config.APPEEARS_DIR / "token.json"


def login(credentials=None) -> str:
    """Bearer token (valid about 48 h), reused from TOKEN_FILE while it has > 1 h left."""
    if credentials is None and TOKEN_FILE.exists():
        try:
            cached = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            if time.time() < cached["expires_at"] - 3600:
                return cached["token"]
        except (ValueError, KeyError):
            pass
    user, pw = credentials or earthdata_credentials()
    print("  logging in to AppEEARS (the Earthdata check can take a minute)...")
    r = _request("POST", f"{API}/login", auth=(user, pw), timeout=180)
    if r.status_code == 401:
        raise RuntimeError("AppEEARS rejected the Earthdata username/password (401). Check them at "
                           "https://urs.earthdata.nasa.gov, and fix ~/.netrc if it holds an old one.")
    if r.status_code != 200:
        raise RuntimeError(f"AppEEARS login failed ({r.status_code}): {r.text[:200]}")
    token = r.json()["token"]
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"token": token, "expires_at": time.time() + 47 * 3600}),
                          encoding="utf-8")
    return token


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


# --- Products (no login needed) ---------------------------------------------------
def product_info(product_id: str) -> dict:
    """Entry from GET /product for one ProductAndVersion, e.g. 'SPL3SMP_E.006'."""
    r = _request("GET", f"{API}/product", params={"limit": 1000})
    r.raise_for_status()
    for p in r.json():
        if p["ProductAndVersion"] == product_id:
            return p
    newer = [p["ProductAndVersion"] for p in r.json()
             if p["Product"] == product_id.split(".")[0]]
    raise ValueError(f"{product_id} not in AppEEARS. Available versions: {newer or 'none'}. "
                     "Update config.py.")


def check_layers(product_id: str, layers) -> None:
    """Fail before submitting if a layer name in config.py is not in the product."""
    r = _request("GET", f"{API}/product/{product_id}")
    r.raise_for_status()
    missing = [lyr for lyr in layers if lyr not in r.json()]
    if missing:
        raise ValueError(f"{product_id}: layers {missing} not found. "
                         f"Available: {sorted(r.json())}")


# --- Tasks ------------------------------------------------------------------------
def _mdy(iso_date: str) -> str:
    y, m, d = iso_date[:10].split("-")
    return f"{m}-{d}-{y}"


def point_task_body(name, layers, points, start, end) -> dict:
    """layers: [(product_id, layer)]; points: [(id, category, lat, lon)]; dates ISO."""
    return {
        "task_type": "point",
        "task_name": name,
        "params": {
            "dates": [{"startDate": _mdy(start), "endDate": _mdy(end)}],
            "layers": [{"product": p, "layer": lyr} for p, lyr in layers],
            "coordinates": [{"id": pid, "category": cat, "latitude": lat, "longitude": lon}
                            for pid, cat, lat, lon in points],
        },
    }


def submit(token, body) -> str:
    r = _request("POST", f"{API}/task", json=body, headers=_headers(token))
    if r.status_code not in (200, 202):
        raise RuntimeError(f"AppEEARS rejected task {body['task_name']!r} "
                           f"({r.status_code}): {r.text[:300]}")
    return r.json()["task_id"]


def status(token, task_id) -> str:
    """'pending' | 'processing' | 'done' | 'error'."""
    r = _request("GET", f"{API}/task/{task_id}", headers=_headers(token))
    r.raise_for_status()
    return r.json().get("status", "unknown")


def download(token, task_id, folder: Path) -> list[Path]:
    """Download every CSV in the task's bundle into folder; returns the paths."""
    folder.mkdir(parents=True, exist_ok=True)
    r = _request("GET", f"{API}/bundle/{task_id}", headers=_headers(token))
    r.raise_for_status()
    paths = []
    for f in r.json()["files"]:
        if not f["file_name"].lower().endswith(".csv"):
            continue
        path = folder / Path(f["file_name"]).name
        resp = _request("GET", f"{API}/bundle/{task_id}/{f['file_id']}", headers=_headers(token),
                        timeout=600, allow_redirects=True)
        resp.raise_for_status()
        path.write_bytes(resp.content)
        paths.append(path)
    return paths


# --- Reading result CSVs ------------------------------------------------------------
def find_column(df, name: str, required=True):
    """Column for a layer (AppEEARS prefixes layer columns with product and version)
    or a plain column like 'Date' / 'ID', matched case-insensitively. The exact
    prefix format is not documented, so only the layer-name ending is relied on."""
    low = {c.lower(): c for c in df.columns}
    if name.lower() in low:
        return low[name.lower()]
    hits = [c for c in df.columns if c.lower().endswith("_" + name.lower())]
    if len(hits) == 1:
        return hits[0]
    if required:
        raise KeyError(f"No unique column for {name!r} in AppEEARS CSV. Columns: {list(df.columns)}")
    return None


# --- Remembering submitted tasks between runs (the queue can take hours) ----------
TASKS_FILE = config.APPEEARS_DIR / "tasks.json"


def load_tasks() -> dict:
    return json.loads(TASKS_FILE.read_text(encoding="utf-8")) if TASKS_FILE.exists() else {}


def save_tasks(tasks: dict) -> None:
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


def run_all(token, jobs, wait_minutes=10, poll_s=30) -> dict:
    """Submit every job not yet submitted, then poll them together and download each
    one as it finishes. Safe to rerun: submitted tasks are remembered in tasks.json.

    jobs: [(name, body, folder)]. Returns {name: 'downloaded' | 'pending' | 'processing' | 'error'}.
    """
    tasks = load_tasks()
    for name, body, _ in jobs:                       # 1. submit everything first
        if name not in tasks:
            tasks[name] = {"task_id": submit(token, body), "downloaded": False}
            save_tasks(tasks)
            print(f"  {name}: submitted (task {tasks[name]['task_id']})")
        elif not tasks[name]["downloaded"]:
            print(f"  {name}: already submitted (task {tasks[name]['task_id']})")

    state = {name: "downloaded" for name, _, _ in jobs if tasks[name]["downloaded"]}
    deadline = time.time() + wait_minutes * 60
    while True:                                      # 2. poll all, download when done
        for name, _, folder in jobs:
            if name in state and state[name] in ("downloaded", "error"):
                continue
            st = status(token, tasks[name]["task_id"])
            if st == "done":
                paths = download(token, tasks[name]["task_id"], folder)
                tasks[name]["downloaded"] = True
                save_tasks(tasks)
                print(f"  {name}: downloaded {len(paths)} CSV file(s) to {folder}")
                st = "downloaded"
            elif st == "error":
                print(f"  {name}: FAILED on the AppEEARS side; it will be resubmitted next run")
                del tasks[name]
                save_tasks(tasks)
            state[name] = st
        waiting = [n for n, st in state.items() if st not in ("downloaded", "error")]
        if not waiting:
            return state
        if time.time() >= deadline:
            print(f"  still queued: {', '.join(f'{n} ({state[n]})' for n in waiting)}")
            print("  AppEEARS can take hours. Run the same command later to download them.")
            return state
        time.sleep(poll_s)
