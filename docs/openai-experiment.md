# OpenAI collage experiment

`scripts/openai_experiment.py` runs one initial layout and two adjustments using the official OpenAI Python SDK and Responses API. Default model: `gpt-6.1-sol`. By default it runs both `zhu` and `euro`, with separate conversation histories and three calls per portrait. Use `--portrait zhu` or `--portrait euro` for a single trial. The existing human editor and manual JSON runner remain available.

## Install

From the repository root, use the existing agent environment or create it:

```sh
python3 -m venv /private/tmp/foodface-agent-venv
/private/tmp/foodface-agent-venv/bin/python -m pip install -r scripts/requirements-openai.txt
export PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers
/private/tmp/foodface-agent-venv/bin/python -m playwright install chromium
```

Temporary dependencies can be recreated if `/private/tmp` is cleared. The runner starts its own loopback server and Chromium renderer; you do not need to run the studio separately.

## Offline dry run

```sh
export PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers
/private/tmp/foodface-agent-venv/bin/python scripts/openai_experiment.py --dry-run
```

No key is required. Even if a real key exists in the environment, dry-run mode uses a placeholder and an in-memory HTTP mock. The real SDK serializes requests and parses fabricated Responses API envelopes; no request reaches OpenAI. Images are still prepared, base64-encoded as image inputs, validated by the mock, and rendered by the real Chromium pipeline. Fixture outputs under `examples/openai-dry-run/` exercise duplicated assets, stable uids, position/size/angle, local-axis flips, additions, omissions, and layering.

Dry runs are explicitly labeled `simulated: true` with `actualModel: null` and `usage: null`. They verify local plumbing, not credentials, remote API acceptance, image understanding, model quality, token counts, or actual cost.

## Live run with a terminal-only key

For macOS zsh, read the key without echoing it or placing its literal value in shell history:

```sh
read -rs 'OPENAI_API_KEY?OpenAI API key: '
export OPENAI_API_KEY
export PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers
/private/tmp/foodface-agent-venv/bin/python scripts/openai_experiment.py --portrait zhu
unset OPENAI_API_KEY
```

For bash, replace the first line with `read -r -s -p 'OpenAI API key: ' OPENAI_API_KEY`. Remove `--portrait zhu` to run both portraits (six API calls in total). The key is not a command-line argument, is not stored in the repository, and is not included in result files. The adapter pins `https://api.openai.com/v1` even if `OPENAI_BASE_URL` is set elsewhere. Normal OpenAI project/organization environment settings still apply.

Defaults are `--reasoning medium --max-output-tokens 8192 --image-detail high --max-edge 1024 --timeout 180`. All are recorded and configurable. `max-output-tokens` includes reasoning and visible JSON; truncation is treated as a failure, not a valid partial layout. The output limit is not a dollar budget. Standard processing is explicitly requested with `service_tier: default`. No model-side tools or image generation are enabled; food compositing stays local. Use `--headed` to watch rendering.

## Conversation and response contract

1. Prepare original portrait, empty portrait, food contact sheet, dimensions, and the complete English catalog prompt.
2. First request: a developer **message** containing the prompt, followed by a user message with the three labeled images. Using a message keeps it in history; the top-level `instructions` parameter is not used because it is not inherited through `previous_response_id`.
3. Require strict Structured Outputs with the full `items` schema and valid catalog IDs. The API schema requires explicit boolean `flipX` and `flipY` on every item, including false. This narrows the existing optional-flag contract without changing rendering semantics.
4. Save the raw API response, validate the complete layout (including stable/retired uid rules), and save the full-resolution JSON/PNG pair plus reduced feedback.
5. The next request passes `previous_response_id` and only the previous round's feedback image and short adjustment prompt. The original inputs and previous JSON remain in the server-side response chain. Repeat once more, then stop after round 2. No fourth evaluation call is made.

`store: true` enables the stored response chain. History is available to the model but is not free: previous input tokens are still billable, and caching depends on actual cache hits. No USD estimate is fabricated; the raw usage and actual returned model are recorded. Each portrait starts a new chain.

The terminal prints input, output, reasoning, cached-input and total tokens immediately after each API response, followed by portrait subtotals and the experiment total. Reasoning is already included in output; total is input + output, without adding reasoning again. `token-usage.json` records the same per-round counts and totals and is updated as the experiment runs, including on failures. It also records how many requests have reported usage. Unknown values (including all dry-run usage) are `null` in JSON and `N/A` in the terminal, not zero. Subtotals after a timeout cover reported usage only.

## Records and failures

Output root: `result-data/openai-experiments/Experiment-<live|dry-run>-<UUID>/`.

```text
experiment.json           Settings, status, per-call IDs, actual models, token usage, final paths
token-usage.json          Compact per-round, per-portrait and experiment token totals
Agent-<portrait>-<UUID>/
  run.json                Protocol, requested model/settings, browser version, code/asset hashes
  inputs/                 Original/empty/contact-sheet PNGs, manifest, English prompt
  calls/round-0/          Also round-1 and round-2
    request.json          Request parameters; images replaced by local paths, SHA-256, byte counts
    api-response.json     SDK response including output, status, usage, and any refusal
    layout.json           Exact returned layout text when the response completed
  round-0/               Also round-1 and round-2
    response.txt          Accepted layout text
    feedback.png          Image for the next round, except after the final round
    feedback.json        Scene and paths to native-resolution snapshot pair
    next-prompt.txt       Next adjustment instructions, or completion notice
    FoodFace-.../        Native-resolution scene JSON and PNG
```

The request log is not the literal wire body: to reconstruct it, replace each image's `localFile`/`sha256`/`bytes` fields with `image_url: data:image/png;base64,...` using the referenced bytes relative to that Agent directory. Other request parameters are retained. Headers/keys are never logged. Keep the run and referenced source files together; hashes alone cannot reconstruct the renderer.

There are no automatic API retries or model repair calls. A refusal, incomplete response, invalid layout, timeout, HTTP failure, or render failure stops the experiment, marks it failed, and preserves completed rounds and available API records. Invalid layouts do not consume an accepted rendering opportunity, but the attempted API call may still cost money. A timeout can have an unknown server-side outcome. This version does not automatically resume failed experiments; inspect saved records before deliberately starting another paid run. An abrupt process kill may leave a `running` status; it is not evidence that the API request was unbilled.

## Verification

```sh
/private/tmp/foodface-agent-venv/bin/python -m unittest discover -s scripts -p 'test_*.py'
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers FOODFACE_BROWSER_TEST=1 /private/tmp/foodface-agent-venv/bin/python -m unittest discover -s scripts -p 'test_*.py'
```

The mock tests cover request history, image transport, incomplete/refused/invalid responses, and stopping without retries. Browser tests run all three rounds for both portraits and check snapshots and the final state. No test invokes a paid API.

Official references: [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Responses conversation state](https://developers.openai.com/api/docs/guides/conversation-state), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), and [image inputs](https://developers.openai.com/api/docs/guides/images-vision).
