# Eval results

8 tasks with hidden tests x 3 repetitions, run 2026-09-30. Tier rows = pass@1 (one attempt, no feedback). Ladder = the profile's escalation ladder with the hidden tests as `verify`, so a failing attempt gets the test output and escalates to the next tier.

| Config | Pass | Hidden tests passed | Avg cost / run | Cost / passing run | Avg latency | Escalated |
|---|---|---|---|---|---|---|
| ladder | 23/24 (96%) | 96.8% | $0.0034 | $0.0035 | 13.0s | 4 |

| Task | ladder |
|---|---|
| flatten_json | ✅ 3/3 |
| lru_cache | ✅ 3/3 |
| merge_intervals | ✅ 3/3 |
| parse_duration | ✅ 3/3 |
| roman | ✅ 3/3 |
| semver | ✅ 3/3 |
| slugify | ⚠️ 2/3 |
| token_bucket | ✅ 3/3 |

Total eval cost: $0.0813
