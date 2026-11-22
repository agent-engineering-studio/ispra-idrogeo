# Agent eval: Claude on idrogeo-mcp

## baseline

- **correct: 5/5 = 100%** (95% CI 57%-100%)
- cites ISPRA: 5/5
- not scored: 0 (truncated or refused), errors: 0
- models: claude-sonnet-5-5
- latency per case: median 8.8 s, max 9.9 s
- tool calls per case: mean 1.8, max 2
- cost: $0.23 in all, $0.024 median per case (range $0.019-$0.139)

| kind | correct |
|---|---|
| area-risk | 1/1 |
| iffi | 1/1 |
| monitoring | 1/1 |
| point | 1/1 |
| rank | 1/1 |

| case | rep | ok | why | tools | trace |
|---|---|---|---|---|---|
| `risk-bari-flood-p2` | 0 | ✓ | 4037 vs 4037 | 2 | [baseline/traces/risk-bari-flood-p2_rep0.json](baseline/traces/risk-bari-flood-p2_rep0.json) |
| `iffi-trivento` | 0 | ✓ | 921 vs 921 | 2 | [baseline/traces/iffi-trivento_rep0.json](baseline/traces/iffi-trivento_rep0.json) |
| `sites-lombardy-active` | 0 | ✓ | 48 vs 48 | 2 | [baseline/traces/sites-lombardy-active_rep0.json](baseline/traces/sites-lombardy-active_rep0.json) |
| `point-venice-flood` | 0 | ✓ | 'P3' vs 'P3' | 1 | [baseline/traces/point-venice-flood_rep0.json](baseline/traces/point-venice-flood_rep0.json) |
| `rank-bari-province` | 0 | ✓ | 'Polignano a Mare' vs ['Polignano a Mare'] | 2 | [baseline/traces/rank-bari-province_rep0.json](baseline/traces/rank-bari-province_rep0.json) |
