# Token-economics KPIs

Datasets: `cost_and_usage` 12 rows, `telemetry` 2206 rows, `task` 1923 rows, `outcome` 1920 rows, `value` 2953 rows

## Phases
| phase | note |
|---|---|
| baseline | prefix-cache-scorer weight 3 |
| incident | prefix-cache-scorer weight 0 |

## 4.1 Infrastructure (per phase and workload)
| phase | workload | requests | input tok | output tok | KV cache hit | prefill GPU-s | decode GPU-s | allocated cost | cost / 1M tok |
|---|---|---|---|---|---|---|---|---|---|
| baseline | UNLINKED | 128 | 4,871 | 7,794 | 0.0% | 19.2 | 448.0 | $0.0463 | $3.654 |
| baseline | support_bot | 1,122 | 4,396,754 | 42,641 | 50.2% | 361.3 | 2,234.5 | $0.2964 | $0.067 |
| baseline | triage_bot | 479 | 114,527 | 5,334 | 26.7% | 79.8 | 318.3 | $0.0448 | $0.373 |
| incident | UNLINKED | 110 | 4,189 | 6,662 | 0.0% | 18.6 | 425.3 | $0.0444 | $4.096 |
| incident | support_bot | 944 | 3,698,982 | 35,694 | 25.5% | 440.2 | 2,162.2 | $0.2972 | $0.080 |
| incident | triage_bot | 408 | 97,407 | 4,619 | 26.8% | 78.2 | 321.8 | $0.0544 | $0.534 |

## 4.2-4.4 Yield, outcomes and cost to value (per phase and workload)
| phase | workload | tasks | task yield | CPQT | outcomes | SLA survival | CPQO | GPU-s / QO | net outcome | est. value | spend / $1 value |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | support_bot | 561 | 100.0% | $0.00053 | 561 | 36.4% | $0.00145 | 12.724 | 204.0 deflected_tickets | $-6,375.00 | n/a (value <= 0) |
| baseline | triage_bot | 479 | 98.5% | $0.00009 | 479 | 53.7% | $0.00017 | 1.549 | 1,252.0 minutes | $1,878.00 | $0.000024 |
| incident | support_bot | 472 | 100.0% | $0.00063 | 472 | 35.6% | $0.00177 | 15.490 | 168.0 deflected_tickets | $-5,460.00 | n/a (value <= 0) |
| incident | triage_bot | 408 | 98.8% | $0.00014 | 408 | 58.3% | $0.00023 | 1.680 | 1,348.5 minutes | $2,022.75 | $0.000027 |

## Portfolio (per phase)
| phase | total cost | IDLE | UNLINKED | failed-task cost | scrap rate | of which UNLINKED | qualified outcomes |
|---|---|---|---|---|---|---|---|
| baseline | $0.3875 | $0.0000 | $0.0463 | $0.0007 | 12.1% | 11.9% | 461 |
| incident | $0.3961 | $0.0000 | $0.0444 | $0.0005 | 11.3% | 11.2% | 406 |
