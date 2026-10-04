#!/usr/bin/env python3
"""Refresh global achievement completion rates for 1/7 of the games per day.

Runs on GitHub Actions (stdlib only). Source: Steam's public keyless
ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2. The display names /
descriptions / icons need a Web API key (GetSchemaForGame) and almost never
change, so they are NOT fetched here: the builder fills them in for achievement
names it hasn't seen before.

    collect_achievements.py --shard 0/2 [--date YYYY-MM-DD] [--out DIR]

Games: tiers/achievements.json (exported by the builder = all games with a page),
today's slice = appid % 7 == date.toordinal() % 7 (every game refreshed weekly),
then split again by position for the CI matrix.

Output: out/ach_<date>_s<i>.jsonl.gz, one line per game asked:
  {"appid", "status", "fetched_at", "pcts": {apiname: percent}}
status 200 with empty pcts = the game has no achievements (an answer).
Network errors are not written; they go to the meta file's "failed".
"""
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/"
PAUSE = 0.3           # same as the laptop
SHARDS_PER_WEEK = 7


def fetch(appid: int) -> tuple[int, dict]:
    q = urllib.parse.urlencode({"gameid": appid})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "steamcozy-collect"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
            return 200, {a["name"]: float(a["percent"]) for a in
                         d.get("achievementpercentages", {}).get("achievements", [])}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            if e.code in (400, 403, 404):
                return e.code, {}      # the laptop also records these as "no achievements"
            raise
    raise RuntimeError("retries exhausted")


def main() -> int:
    args = sys.argv[1:]
    i, n = map(int, args[args.index("--shard") + 1].split("/")) if "--shard" in args else (0, 1)
    day = date.fromisoformat(args[args.index("--date") + 1]) if "--date" in args \
        else datetime.now(timezone.utc).date()
    out_dir = Path(args[args.index("--out") + 1]) if "--out" in args else HERE / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    allids = json.loads((HERE / "tiers" / "achievements.json").read_text())
    k = day.toordinal() % SHARDS_PER_WEEK
    today = [a for a in allids if a % SHARDS_PER_WEEK == k]
    mine = today[i::n]
    print(f"{day} slice {k}/{SHARDS_PER_WEEK}: {len(today):,} games, shard {i}/{n}: {len(mine):,}", flush=True)
    stem = out_dir / f"ach_{day}_s{i}"
    t0 = time.time()
    with_ach = none = 0
    bad: list[int] = []
    with gzip.open(f"{stem}.jsonl.gz", "wt", encoding="utf-8") as f:
        for j, a in enumerate(mine, 1):
            try:
                st, pcts = fetch(a)
                f.write(json.dumps({"appid": a, "status": st, "pcts": pcts,
                                    "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}) + "\n")
                with_ach += bool(pcts)
                none += not pcts
            except Exception:
                bad.append(a)
            if j % 500 == 0:
                print(f"  {j:,}/{len(mine):,} with={with_ach} none={none} fail={len(bad)}", flush=True)
            time.sleep(PAUSE)
    meta = {"date": str(day), "slice": f"{k}/{SHARDS_PER_WEEK}", "shard": f"{i}/{n}", "asked": len(mine),
            "with": with_ach, "none": none, "failed": bad, "seconds": round(time.time() - t0),
            "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
    Path(f"{stem}.meta.json").write_text(json.dumps(meta))
    print(json.dumps({k2: v for k2, v in meta.items() if k2 != "failed"} | {"failed": len(bad)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
