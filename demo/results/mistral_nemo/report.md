# Gordian run: lb_float1_fp_l1

- backend: `openrouter:mistralai/mistral-nemo`  budget: 600.0s  elapsed: 144s
- line coverage: **12/13 = 92.3%**
- test cases: 10  bombs reached: 0
- LLM usage: {'input_tokens': 5720, 'output_tokens': 1659, 'calls': 4, 'wall_seconds': 127.17}

## Coverage progression

| step | ktests | new lines | covered | t (s) |
|---|---|---|---|---|
| 00_explore | 1 | +12 | 12/13 | 6 |
| 01_partition_1 | 3 | +0 | 12/13 | 72 |
| 01_partition_2 | 3 | +0 | 12/13 | 74 |
| 01_partition_3 | 3 | +0 | 12/13 | 77 |
| 02_model_float1_fp_l1_klee | - | build failed | - | 116 |
| 02_model_float1_fp_l1_klee_fixed | - | build failed | - | 144 |

## Triage of uncovered regions

| file | lines | technique | score | reason |
|---|---|---|---|---|
| benchmarks/logic_bombs_src/floating_point/float1_fp_l1_klee.c | 13-13 | model | 0.8 | Floating point comparison (a - b == 0) is solver-hostile. |
