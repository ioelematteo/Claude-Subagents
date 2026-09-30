# Eval results

8 tasks with hidden tests x 3 repetitions, run 2026-09-30. Tier rows = pass@1 (one attempt, no feedback). Ladder = the profile's escalation ladder with the hidden tests as `verify`, so a failing attempt gets the test output and escalates to the next tier.

| Config | Pass | Hidden tests passed | Avg cost / run | Cost / passing run | Avg latency | Escalated |
|---|---|---|---|---|---|---|
| flash-fast | 19/24 (79%) | 98.6% | $0.0007 | $0.0009 | 1.8s | 0 |
| flash-low | 24/24 (100%) | 100.0% | $0.0024 | $0.0024 | 7.8s | 0 |
| flash-high | 22/24 (92%) | 99.5% | $0.0067 | $0.0073 | 22.1s | 0 |
| flash-max | 21/24 (88%) | 99.3% | $0.0088 | $0.0100 | 29.6s | 0 |
| pro-high | 23/24 (96%) | 94.6% | $0.0164 | $0.0171 | 39.8s | 0 |
| ladder | 24/24 (100%) | 100.0% | $0.0053 | $0.0053 | 18.9s | 1 |

| Task | flash-fast | flash-low | flash-high | flash-max | pro-high | ladder |
|---|---|---|---|---|---|---|
| flatten_json | ⚠️ 2/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| lru_cache | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| merge_intervals | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| parse_duration | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| roman | ❌ 0/3 | ✅ 3/3 | ✅ 3/3 | ⚠️ 2/3 | ✅ 3/3 | ✅ 3/3 |
| semver | ⚠️ 2/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ⚠️ 2/3 | ✅ 3/3 |
| slugify | ✅ 3/3 | ✅ 3/3 | ⚠️ 1/3 | ⚠️ 1/3 | ✅ 3/3 | ✅ 3/3 |
| token_bucket | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |

Total eval cost: $0.9690
