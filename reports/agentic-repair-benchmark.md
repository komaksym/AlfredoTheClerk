# Synthetic Agentic Repair Benchmark

- Corpus: `agentic-repair-hard-v1`
- Corpus SHA-256: `9b8510bdc8f34cc7a2d5b2d5fa6d11d749e5a12a5b7c0ca38b1ae0e7dd4b7d06`
- Model: `deepseek:deepseek-v4-flash`
- Repeated runs: `3`

## Results

| Metric | Value |
| --- | ---: |
| Evaluated cases | 30 |
| Case-runs | 90 |
| Known defects | 147 |
| Agent-eligible fields | 96 |
| Correct automated repairs | 84 |
| Human corrections remaining | 63 |
| Manual-correction reduction | 57.1% |
| Candidate-selection accuracy | 87.5% |
| Safe-escalation rate | 100.0% |
| Straight-through rate | 48.9% |
| Errored attempts | 0 |
| Median latency | 2731.1 ms |
| P95 latency | 5213.3 ms |

## Methodology

The agent-disabled baseline requires one human correction for every persisted known defect. Only a candidate selection that exactly matches ground truth counts as removed human work. Incorrect, missing, or errored actions remain human corrections.

## Limitations

This controlled synthetic benchmark does not establish production generalization, accountant speed, cost savings, or end-to-end accounts-payable cycle-time improvement.
