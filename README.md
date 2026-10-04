# steamcozy-collect

Data collectors for [steamcozy.com](https://steamcozy.com) that only need network,
run on GitHub Actions so the site's build machine doesn't have to.
Sister repos: [steamcozy-prices](https://github.com/scos-lab/steamcozy-prices),
[steamcozy-ccu](https://github.com/scos-lab/steamcozy-ccu).

## news (`collect_news.py`, `.github/workflows/news.yml`)

Steam's public keyless `ISteamNews/GetNewsForApp/v2`, latest 10 items per game,
full text. Which games are asked on a given day is decided on the build machine
(it needs the news history and price data) and shipped in as `tiers/news_*.json`:

| tier | asked | file |
|---|---|---|
| hot  | every day | `tiers/news_hot.json` |
| warm | Sundays (UTC) | `tiers/news_warm.json` |
| cold | 1/7 of the list per day (`appid % 7 == date.toordinal() % 7`) | `tiers/news_cold.json` |

Output is a workflow **artifact** (`news-<run_id>-s<shard>`: one `.jsonl.gz` + one
`.meta.json` per shard), not a commit — full article text would grow the repo by
gigabytes a year. Artifacts are kept 30 days; the builder imports them daily with
`INSERT OR IGNORE` on the news `gid`, so a missed day is simply picked up by the
next run (the API always returns the latest 10 items).

Politeness: 0.25 s between requests, 429/5xx retried with backoff, one retry pass
for failures after the sweep, no retry at all if more than 500 failed (that's an
outage, not jitter — the failures are reported in the meta file instead).

## achievements (`collect_achievements.py`, `.github/workflows/achievements.yml`)

Steam's public keyless `ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2`.
Every game with a steamcozy page (`tiers/achievements.json`, exported by the builder)
is refreshed once a week: 1/7 per day (`appid % 7 == date.toordinal() % 7`).
Only completion rates are collected here — display names, descriptions and icons
need a Web API key (`GetSchemaForGame`), almost never change, and are filled in by
the builder for achievement names it hasn't seen before.
Output: artifact `ach-<run_id>-s<shard>` (`.jsonl.gz` + `.meta.json`), kept 30 days.
