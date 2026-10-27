
Demonistration of Gordian:
- https://bouras.online/gordian/
- https://github.com/msv-lab/gordian

---

Our demonstration consisted of two stages:

### Stage 1

An sample end-to-end run of gordian method. This exists in `demo/main` branch. You may wish to read `DEMO-TUTORIAL.md` which details how to recreate the demo. The key steps are (1) get a docker image of KLEE (2) set up python environment (3) set api key (we use OpenRouter but you can easily replace it with any openai interface) (4) run the demo

To run the 3 demo steps, first ensure the KLEE docker is running, then the steps below. The input to KLEE is in

```
DEMO_NAME="choose-a-name-here"

# Step 1 (Klee fails)
python -m gordian.demo baseline \
  --name "${DEMO_NAME}-baseline"

# Step 2 (Generate ghost-code)
python -m gordian.demo generate \
  --from-run "runs/${DEMO_NAME}-baseline" \
  --name "${DEMO_NAME}-ghost" \
  --provider openrouter \
  --model deepseek/deepseek-v4.1-flash

# Step 3 (Run modified code on KLEE)
python -m gordian.demo assisted \
  --from-run "runs/${DEMO_NAME}-ghost" \
  --name "${DEMO_NAME}-assisted"
```

### Stage 2

We ran Gordian with a variety of models to see how it performs on the benchmark `lb_float1_fp_l1`. The results of the runs are in `demo/results/`. The models `mistral_nemo`, `gpt-oss-20b` and `deepseek-v4.1` were run using OpenRouter (which uses an OpenAi completions interface); and the Claude and GPT models were run through the interface provided by Gordian that works with Anthropic and OpenAI subscriptions for their respective agentic harnesses Claude and Codex. Therefore, token-usage may not be directly comparable, especially noting how the Antropic models consumed many orders of magnitude more tokens than the others.

While `mistral-nemo`, the worst model, failed, even weak models such as `gpt-oss-20b` succeeded, potentially indicating the method presented in the paper is strong (not brittle) and works with most models. An alternative explanation is the sample is easy.

An LLM-generated analysis of the summary page is available at `./Gordian Float Bomb Showdown.html`

This part also explained a bit of how Gordian works, with prompt splitting creation of ghost-code into three steps (stages or "harnesses").
