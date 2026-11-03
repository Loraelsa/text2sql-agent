# Benchmark results

30 questions, groq, model: openai/gpt-oss-120b, 2026-11-03

| Mode | Accuracy | Valid SQL | Avg attempts | Avg latency (s) |
|---|---|---|---|---|
| baseline | 96.7% (29/30) | 100.0% | 1.00 | 1.17 |
| self_correct | 96.7% (29/30) | 100.0% | 1.00 | 2.96 |
| full | 96.7% (29/30) | 100.0% | 1.00 | 2.91 |

| Mode | easy | hard | medium |
|---|---|---|---|
| baseline | 100.0% | 100.0% | 90.9% |
| self_correct | 100.0% | 100.0% | 90.9% |
| full | 100.0% | 100.0% | 90.9% |
