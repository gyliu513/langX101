# Token-economics KPIs

Datasets: `cost_and_usage` 135 rows, `telemetry` 2280 rows, `task` 1905 rows, `outcome` 1902 rows, `value` 2924 rows

## Phases
| phase | note |
|---|---|
| baseline | prefix-cache-scorer weight 3 |
| incident | prefix-cache-scorer weight 0 |

## 4.1 Infrastructure (per phase and workload)
| phase | workload | requests | input tok | output tok | KV cache hit | prefill GPU-s | decode GPU-s | allocated cost | cost / 1M tok |
|---|---|---|---|---|---|---|---|---|---|
| baseline | IDLE | 0 | 0 | 0 | - | 0.0 | 0.0 | $0.2317 | - |
| baseline | OVERHEAD | 0 | 0 | 0 | - | 0.0 | 0.0 | $0.0034 | - |
| baseline | UNLINKED | 124 | 4,721 | 7,518 | 0.0% | 21.7 | 417.9 | $0.0235 | $1.919 |
| baseline | support_bot | 1,099 | 4,309,122 | 42,753 | 49.5% | 358.0 | 2,272.7 | $0.1640 | $0.038 |
| baseline | triage_bot | 469 | 113,036 | 5,223 | 26.6% | 83.0 | 290.5 | $0.0231 | $0.195 |
| incident | IDLE | 0 | 0 | 0 | - | 0.0 | 0.0 | $0.2309 | - |
| incident | OVERHEAD | 0 | 0 | 0 | - | 0.0 | 0.0 | $0.0037 | - |
| incident | UNLINKED | 107 | 4,075 | 6,434 | 0.0% | 19.7 | 396.8 | $0.0225 | $2.145 |
| incident | support_bot | 944 | 3,702,059 | 37,454 | 28.4% | 411.6 | 2,217.2 | $0.1634 | $0.044 |
| incident | triage_bot | 411 | 99,530 | 4,632 | 26.4% | 78.8 | 304.5 | $0.0237 | $0.227 |

## 4.2-4.4 Yield, outcomes and cost to value (per phase and workload)
| phase | workload | tasks | task yield | CPQT | outcomes | SLA survival | CPQO | GPU-s / QO | net outcome | est. value | spend / $1 value |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | support_bot | 550 | 100.0% | $0.00030 | 550 | 32.5% | $0.00092 | 14.697 | 179.0 deflected_tickets | $-6,806.50 | n/a (value <= 0) |
| baseline | triage_bot | 469 | 97.0% | $0.00005 | 469 | 55.7% | $0.00009 | 1.431 | 1,398.5 minutes | $2,097.75 | $0.000011 |
| incident | support_bot | 472 | 100.0% | $0.00035 | 472 | 34.3% | $0.00101 | 16.228 | 162.0 deflected_tickets | $-5,619.00 | n/a (value <= 0) |
| incident | triage_bot | 411 | 96.6% | $0.00006 | 411 | 56.2% | $0.00010 | 1.660 | 1,267.5 minutes | $1,901.25 | $0.000012 |

## Portfolio (per phase)
| phase | total cost | IDLE | UNLINKED | failed-task cost | scrap rate | of which UNLINKED | qualified outcomes |
|---|---|---|---|---|---|---|---|
| baseline | $0.4457 | $0.2317 | $0.0235 | $0.0006 | 11.4% | 11.2% | 440 |
| incident | $0.4441 | $0.2309 | $0.0225 | $0.0008 | 11.1% | 10.8% | 393 |
