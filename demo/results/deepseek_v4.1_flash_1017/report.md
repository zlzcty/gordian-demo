# Gordian run: lb_float1_fp_l1

- backend: `openrouter:deepseek/deepseek-v4.1-flash-1017`  budget: 600.0s  elapsed: 43s
- line coverage: **13/13 = 100.0%**
- test cases: 20  bombs reached: 0
- LLM usage: {'input_tokens': 1353, 'output_tokens': 8128, 'calls': 1, 'wall_seconds': 19.79}

## Coverage progression

| step | ktests | new lines | covered | t (s) |
|---|---|---|---|---|
| 00_explore | 1 | +12 | 12/13 | 5 |
| 01_partition_1 | 4 | +1 | 13/13 | 32 |
| 01_partition_2 | 7 | +0 | 13/13 | 37 |
| 01_partition_3 | 8 | +0 | 13/13 | 43 |
