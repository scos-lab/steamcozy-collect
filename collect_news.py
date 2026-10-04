#!/usr/bin/env python3
"""Fetch Steam news for one day's tier set and write one gzipped JSONL per shard.

Runs on GitHub Actions (stdlib only). Source: Steam's public keyless
ISteamNews/GetNewsForApp/v2 (count=10, maxlength=0 = full text).

    collect_news.py --shard 0/2 [--date YYYY-MM-DD] [--out DIR]

Which games are asked today (same rules the laptop used, docs in the main repo
pipeline/fetch_news.py):
  hot   every day                 tiers/news_hot.json
  warm  Sundays (UTC) — feeds the builder's Monday-morning (Australia) run   tiers/news_warm.json
  cold  1/7 per day, by appid % 7 == date.toordinal() % 7   tiers/news_cold.json
The union is split again by --shard i/n (every n-th game by position) so CI runs it as a matrix.

Output: out/news_<date>_s<i>.jsonl.gz, one line per news item:
  {"appid", "gid", "title", "url", "date", "feedlabel", "feed_type", "contents"}
plus out/news_<date>_s<i>.meta.json with counts and the appids that failed.
This is NOT committed to git (full article text would grow the repo by ~GB/year);
the workflow uploads it as an artifact and the builder downloads and imports it
(`pipeline/fetch_news.py --sync-cloud`). Artifacts live 30 days; the builder
syncs daily, and anything it missed is re-fetched next time anyway (the API
always returns the latest 10 items, imports are INSERT OR IGNORE).
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
API = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
PAUSE = 0.25          # same politeness as the laptop
RETRY_CAP = 500       # more failures than this = systemic, don't retry one by one


def todays_appids(day: date) -> tuple[list[int], dict]:
    def load(name):
        p = HERE / "tiers" / f"news_{name}.json"
        return [int(a) for a in json.loads(p.read_text())] if p.exists() else []
    hot, warm, cold = load("hot"), load("warm"), load("cold")
    k = day.toordinal() % 7
    picked = {"hot": hot,
              "warm": warm if day.weekday() == 6 else [],   # Sun UTC = before Mon 09:00 AEST/AEDT
              "cold": [a for a in cold if a % 7 == k]}
    seen, out = set(), []
    for name in ("hot", "warm", "cold"):
        for a in picked[name]:
            if a not in seen:
                seen.add(a)
                out.append(a)
    return out, {n: len(v) for n, v in picked.items()}


def fetch(appid: int) -> list[dict]:
    q = urllib.parse.urlencode({"appid": appid, "count": 10, "maxlength": 0})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "steamcozy-collect"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
            return [{"appid": appid, "gid": it["gid"], "title": it.get("title", ""),
                     "url": it.get("url", ""), "date": it.get("date", 0),
                     "feedlabel": it.get("feedlabel", ""), "feed_type": it.get("feed_type", 0),
                     "contents": it.get("contents", "")}
                    for it in d.get("appnews", {}).get("newsitems", [])]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            if e.code in (400, 403, 404):
                return []      # no news endpoint for this app — an answer, not a failure
            raise
    return []


def main() -> int:
    args = sys.argv[1:]
    i, n = map(int, args[args.index("--shard") + 1].split("/")) if "--shard" in args else (0, 1)
    day = date.fromisoformat(args[args.index("--date") + 1]) if "--date" in args \
        else datetime.now(timezone.utc).date()
    out_dir = Path(args[args.index("--out") + 1]) if "--out" in args else HERE / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    appids, sizes = todays_appids(day)
    # Split by position, not by appid: Steam appids are almost all multiples of 10, so
    # `appid % 2` put 20,293 of 20,314 games in shard 0 on the first run (2026-10-04).
    mine = appids[i::n]
    print(f"{day} shard {i}/{n}: {len(mine):,} of {len(appids):,} appids  {sizes}", flush=True)
    stem = out_dir / f"news_{day}_s{i}"
    t0 = time.time()
    items = failed = 0
    bad: list[int] = []
    with gzip.open(f"{stem}.jsonl.gz", "wt", encoding="utf-8") as f:
        def one(a):
            nonlocal items
            for row in fetch(a):
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                items += 1
        for k, a in enumerate(mine, 1):
            try:
                one(a)
            except Exception:
                bad.append(a)
            if k % 500 == 0:
                print(f"  {k:,}/{len(mine):,}  items={items:,} fail={len(bad)}", flush=True)
            time.sleep(PAUSE)
        if bad and len(bad) <= RETRY_CAP:     # one retry pass after the sweep (jitter, not outage)
            pending, bad = bad, []
            for a in pending:
                try:
                    one(a)
                except Exception:
                    bad.append(a)
                time.sleep(PAUSE)
    meta = {"date": str(day), "shard": f"{i}/{n}", "asked": len(mine), "items": items,
            "failed": bad, "tier_sizes": sizes, "seconds": round(time.time() - t0),
            "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
    Path(f"{stem}.meta.json").write_text(json.dumps(meta))
    print(json.dumps({k: v for k, v in meta.items() if k != "failed"} | {"failed": len(bad)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
