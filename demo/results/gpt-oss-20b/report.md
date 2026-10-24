# Gordian run: lb_float1_fp_l1

- backend: `openrouter:openai/gpt-oss-20b`  budget: 600.0s  elapsed: 261s
- line coverage: **13/13 = 100.0%**
- test cases: 11  bombs reached: 0
- LLM usage: {'input_tokens': 1333, 'output_tokens': 23018, 'calls': 1, 'wall_seconds': 241.17}

## Coverage progression

| step | ktests | new lines | covered | t (s) |
|---|---|---|---|---|
| 00_explore | 1 | +12 | 12/13 | 9 |
| 01_partition_1 | 3 | +0 | 12/13 | 254 |
| 01_partition_2 | 3 | +0 | 12/13 | 257 |
| 01_partition_3 | 4 | +1 | 13/13 | 261 |
