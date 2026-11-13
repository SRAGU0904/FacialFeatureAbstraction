# OpenAI collage experiment

`scripts/openai_experiment.py` runs one initial layout and two adjustments using the official OpenAI Python SDK and Responses API. Default model: `gpt-6.1-sol`. By default it runs both `zhu` and `euro`, with separate conversation histories and three calls per portrait. Use `--portrait zhu` or `--portrait euro` for a single trial. The existing human editor and manual JSON runner remain available.

## Qwen through Alibaba Cloud Bailian (Beijing)

Use `--provider qwen` with a **Beijing-region Bailian API Key**, not an Alibaba
Cloud AccessKey or Token Plan key. The endpoint is pinned to
`https://dashscope.aliyuncs.com/compatible-mode/v1/responses`; existing OpenAI
and DeepSeek keys/settings are not used. No new dependency is required.

In macOS zsh, paste the key at the hidden input prompt, then run both portraits:

```sh
read -rs 'DASHSCOPE_API_KEY?Bailian Beijing API key: '
export DASHSCOPE_API_KEY
echo
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers \
python scripts/openai_experiment.py \
  --provider qwen --model qwen3.8-max --portrait all \
  --reasoning xhigh --max-output-tokens 65536 --timeout 900
```

Defaults: `qwen3.8-max`, `xhigh` reasoning (the provider's documented default),
65536 output tokens per request **including thinking**, and no automatic retries.
Supported native efforts are `none`, `low`, `medium`, and `xhigh`; the runner
rejects `high`/`max` aliases so experiment names describe the actual setting.
Effort labels do not establish equivalent compute across providers.

The adapter retains server-side history with `store: true` and
`previous_response_id`. The initial request supplies the same three images;
each adjustment supplies one new collage image. The task prompt is unchanged,
and the explanation instruction is added only in round three. Bailian uses a
nested `text.format.json_schema` configuration, so the adapter translates that
container while preserving the layout schema. The undocumented `service_tier`
and image `detail` fields are omitted; image bytes and resizing stay unchanged,
and `imageDetail` is recorded as `auto`. Token usage is printed and saved using
the provider-reported input, output, reasoning, and cache fields.

Live output is automatically organized as
`result-data/ai-results/qwen3.8-max_xhigh_01/` (or the next unused number), with
the two final PNGs at the top level and detailed original records in `records/`.
For an offline mock, add `--dry-run --output /private/tmp/foodface-qwen-dry-run`;
dry runs never read a real API key or enter the formal-results gallery.

Compatibility checked against the official [Responses API reference](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses)
and [structured output guide](https://help.aliyun.com/zh/model-studio/qwen-structured-output)
on 2026-11-13. Offline validation covers request construction and local rendering;
it does not verify a particular account's permissions or a live model response.

## DeepSeek official API

The same runner also supports `--provider deepseek`, using the official
`https://api.deepseek.com/responses` endpoint through the existing SDK. No new
dependency is needed. As checked on 2026-11-13, the latest image-input model is
`deepseek-flash` (DeepSeek-V4.1-Flash-1017); this is a moving API alias, not a pinned
snapshot. See the [official changelog](https://api-docs.deepseek.com/updates/) and
[vision guide](https://api-docs.deepseek.com/guides/vision/).

In macOS zsh, enter the key yourself, then run both portraits:

```sh
read -rs 'DEEPSEEK_API_KEY?DeepSeek API key: '
export DEEPSEEK_API_KEY
echo
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers \
python scripts/openai_experiment.py --provider deepseek --portrait all
```

The key is read only for a live run, from `DEEPSEEK_API_KEY`. OpenAI calls continue
to use `OPENAI_API_KEY`. Dry runs use a placeholder and a mock transport:

```sh
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers \
python scripts/openai_experiment.py --provider deepseek --dry-run
```

DeepSeek defaults: `deepseek-flash`, reasoning `high`, output limit 32768 tokens,
timeout 900 seconds, images at `high` detail, and zero automatic retries. Native
reasoning choices are `none`, `low`, `high`, and `max`. The runner rejects the
`medium`/`xhigh` aliases to avoid silently labeling them as distinct conditions;
[DeepSeek maps both to high](https://api-docs.deepseek.com/guides/thinking_mode/).
These effort labels are not calibrated equivalents of OpenAI effort levels.

The [DeepSeek Responses API](https://api-docs.deepseek.com/guides/responses_api/)
is stateless: each request resends the initial prompt and images, prior assistant
layout JSON, and available collage feedback (3, 4, then 5 images total). The
runner manages this automatically. It sends the unchanged task text as `system`,
because DeepSeek treats `developer` as `user`. Only round 3 adds the existing
final-explanation requirement. Private reasoning is not replayed. Unsupported
`previous_response_id`, `store`, and `service_tier` fields are omitted. Each
portrait has independent history. The original OpenAI conversation chain remains
unchanged. `--from-round-2` also supports DeepSeek; specify `--provider deepseek`
when continuing a DeepSeek portrait.

DeepSeek layouts now apply a deterministic minimum-size rule before rendering:
finite numeric `size` values below `0.03` become `0.03`. Other invalid fields and
sizes above `0.9` still fail validation. This makes no extra model call and does
not change the task prompt. The original `api-response.json` and
`model-output.txt` are preserved; `normalization.json` records each changed uid,
field and before/after value. The rendered `layout.json` and subsequent assistant
history contain the normalized layout so the next observation and JSON agree.

For a previously failed second round with this size issue, first prepare a local
checkpoint with no API client or credential access:

```sh
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers \
python scripts/openai_experiment.py --provider deepseek \
  --repair-round-2 PATH_TO_FAILED_PORTRAIT_DIRECTORY
```

This preserves the source experiment, verifies the first-round render, and saves
a new `Experiment-repaired-...` directory with the corrected second-round image.
Its status is `ready-for-round-3`, not a completed experiment. Token usage in
this checkpoint is inherited from the original calls; repair makes zero calls.
Continue using the printed portrait-directory path:

```sh
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers \
python scripts/openai_experiment.py --provider deepseek \
  --from-round-2 PATH_TO_REPAIRED_PORTRAIT_DIRECTORY
```

Only round 3 is requested, using the original model/effort/output allowance,
normalized second-round JSON and corrected feedback PNG. Its token report covers
the new call; original calls remain separately recorded as inherited calls.

Results default to `result-data/deepseek-experiments/`, using portrait names and
sequential numbers, e.g. `Experiment-live-Zhu-Yuanzhang_Rudolf-II-001`. The same
final PNGs, layout JSON, explanations, raw responses, per-round request records,
and token totals are saved. Provider, endpoint, requested/returned model, effort,
and history mode are recorded. Input/output/reasoning/cached-input tokens are
printed and saved; dry-run counts remain unknown. Mock runs verify local protocol
handling and rendering, not live API acceptance or model quality.

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

Defaults are `--reasoning medium --max-output-tokens 8192 --image-detail high --max-edge 1024 --timeout 900`. All are recorded and configurable. `max-output-tokens` includes reasoning and visible JSON; truncation is treated as a failure, not a valid partial layout. The output limit is not a dollar budget. Standard processing is explicitly requested with `service_tier: default`. No model-side tools or image generation are enabled; food compositing stays local. Use `--headed` to watch rendering.

If an Astra request reports `incomplete_details.reason: max_output_tokens`, a
longer timeout cannot fix it. Increase the output allowance for a new attempt.
For the saved `astra-xhigh` batch `003`, Zhu completed all rounds but Rudolf's
first response was truncated at 8192 output tokens (8063 reasoning tokens).
Batch `002` completed both portraits. To fill only the missing Rudolf trial:

```sh
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers \
python scripts/openai_experiment.py --provider openai --portrait euro \
  --model gpt-6-astra --reasoning xhigh --timeout 900 \
  --max-output-tokens 16384 --output result-data/openai-experiments/astra-xhigh
```

This starts Rudolf at round 1 because the failed first response had no complete
layout. It creates a new numbered directory and leaves all earlier results
intact. The new token limit is recorded; it is a changed experimental parameter,
not a guarantee against truncation. Successful portraits are not rerun.

The client explicitly requests `Accept-Encoding: gzip`. This avoids optional Brotli decoder incompatibilities in existing Conda environments (for example, `httpx2 2.16.0` with `brotlicffi 1.0.9.2` raises `Decompressor.decompress() got an unexpected keyword argument 'output_buffer_limit'`). Only HTTP response compression changes; the model request, images and experiment settings are unchanged. No package reinstall is required for this workaround.

## Conversation and response contract

1. Prepare original portrait, empty portrait, food contact sheet, dimensions, and the complete English catalog prompt.
2. First request: a developer **message** containing the prompt, followed by a user message with the three labeled images. Using a message keeps it in history; the top-level `instructions` parameter is not used because it is not inherited through `previous_response_id`.
3. Require strict Structured Outputs with the full `items` schema and valid catalog IDs. The API schema requires explicit boolean `flipX` and `flipY` on every item, including false. This narrows the existing optional-flag contract without changing rendering semantics.
4. Use the SDK's `with_raw_response` interface to save the HTTP response body before JSON validation. Read the envelope, usage and message text directly from JSON, without SDK typed-model conversion or `model_dump()`. Validate the complete layout (including stable/retired uid rules), and save the full-resolution JSON/PNG pair plus reduced feedback.
5. The second request passes `previous_response_id` and only the previous round's feedback image and short adjustment prompt. The original inputs and previous JSON remain in the server-side response chain.
6. The third request also includes the English developer message from `prompts/agent-final-explanation.txt`. Only this request adds `explanation` to the schema, after the complete `items` array. It replaces the earlier layout-only formatting instruction. The first two requests contain no advance notice of this requirement. Stop after this response (folder `round-2`); no fourth explanation call is made.

The final explanation has only `overall` (the composition and distinctive features) and `choices` (final instance `uids`, facial `feature`, and the visual association in `reason`). It describes shapes, contours or textures, without requesting private reasoning, revision history or a final decision. Layout changes remain optional. The runner saves the full output, validates the explanation's uid references, and passes only `items` to the existing renderer. Use `--no-final-explanation` for the previous layout-only control condition. The human task and initial agent prompt are unchanged.

Putting `items` before `explanation` specifies output order, but does not guarantee that knowing about the explanation leaves the third-round artwork unaffected. Compare outcomes cautiously: a single rerun also includes sampling variability.

`store: true` enables the stored response chain. History is available to the model but is not free: previous input tokens are still billable, and caching depends on actual cache hits. No USD estimate is fabricated; the raw usage and actual returned model are recorded. Each portrait starts a new chain.

The terminal prints input, output, reasoning, cached-input and total tokens immediately after each API response, followed by portrait subtotals and the experiment total. Reasoning is already included in output; total is input + output, without adding reasoning again. `token-usage.json` records the same per-round counts and totals and is updated as the experiment runs, including on failures. It also records how many requests have reported usage. Unknown values (including all dry-run usage) are `null` in JSON and `N/A` in the terminal, not zero. Subtotals after a timeout cover reported usage only.

## Branch from a saved second round

With the key exported in the same terminal, pass the existing **portrait run directory** (older runs use an `Agent-…` name):

```sh
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers \
/private/tmp/foodface-agent-venv/bin/python scripts/openai_experiment.py \
  --from-round-2 result-data/openai-experiments/Experiment-live-a3367c0d-301a-4376-947f-5d9fc38ba278/Agent-zhu-979893e0-bbc4-4473-9b84-9dca06df8d40
```

This creates a new numbered directory such as `Experiment-live-branch-Zhu-Yuanzhang-001` and makes **one new request**, using the saved second response ID as `previous_response_id`. The original third response is not in the new conversation branch. The source's portrait, model, reasoning level and other call settings are inherited; incompatible overrides are rejected. Original files are never modified. Round folders are zero-based: `round-1` is the second round and `round-2` is the third.

Before calling the API, the runner checks source records, browser/version and rendering assets, then re-renders the first two scenes and requires byte-identical full and feedback PNGs. It copies their records as inherited history, keeps the old third rendering in `baseline-round-3/`, and writes `comparison.json` after the new third rendering. Source paths and hashes are recorded for provenance. The initial saved prompt is preserved even if the current initial prompt has changed.

The source must be a real run with two completed rounds, and its stored response ID must still be accessible to the current API project. A missing or expired response causes a failure without retry or automatic history reconstruction. Add `--dry-run` to verify the branch locally: the mock returns the second layout unchanged plus a clearly simulated explanation. This does not test whether the remote response ID remains usable.

The new experiment's token totals count only its new request. Inherited calls are listed separately in `experiment.json`; copying their files does not mean they were called again. The new call can still be billed for its historical context.

## Records and failures

Live results now default to `result-data/ai-results/<model>_<reasoning>_<number>/`.
The folder contains `01-Zhu-Yuanzhang.png`, `02-Rudolf-II.png`, `index.html`, and
`summary.json`. Full records are written directly inside `records/`; the main
`result-data/ai-results/index.html` gallery updates after each attempt stops.
Only completed portraits appear as final images. Failed calls and partial results
remain available under `records/`, without being presented as completed works.

Each invocation reserves a new model/effort number. To finish an existing group,
explicitly pass `--result-group <model>_<reasoning>_<number>` together with the
missing `--portrait` or the relevant `--from-round-2` checkpoint. An existing
completed portrait cannot be overwritten, and unrelated single-portrait runs are
never paired automatically. Dry runs stay separate from the real-results gallery.
An explicit `--output` retains its raw-record location and adds a verified copy
to the gallery; omit it for the simpler default with no duplicate record tree.

Existing stopped batches can be imported offline using
`python scripts/ai_results.py --group <model>_<reasoning>_<number> <batch-directory> ...`.
`--move` removes each source batch only after its preserved copy passes hash
verification. Original API replies, manual-repair records, and token usage are retained.

Inside `records/`, batches retain names such as `Experiment-live-Zhu-Yuanzhang_Rudolf-II-001/`.
Failed attempts keep their number, and existing directories are never overwritten.

To start both portraits from round one, with a key already exported in the current terminal:

```sh
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers \
python scripts/openai_experiment.py --portrait all --model gpt-6.1-sol --reasoning medium
```

This runs three rounds for each portrait (six calls total), with explanations requested only in each third round. For the first named batch, its two run directories are `Zhu-Yuanzhang-001/` and `Rudolf-II-001/`. Each contains easy-to-find final PNG/scene JSON and explanation exports named after the person and batch number. Detailed per-round snapshots retain their internal IDs. Final scene JSON references its matching readable PNG filename.

```text
experiment.json           Settings, status, per-call IDs, actual models, token usage, final paths
token-usage.json          Compact per-round, per-portrait and experiment token totals
error.json                On failure: stage, stack locations, redacted programming errors, runtime versions
<Person>-<number>/
  <Person>-<number>.png                 Final full-resolution collage
  <Person>-<number>.json                Final scene referencing the named PNG
  <Person>-<number>-explanation.txt      Final explanation in readable English
  <Person>-<number>-explanation.json     Final structured explanation
  run.json                Protocol, requested model/settings, browser version, code/asset hashes
  inputs/                 Original/empty/contact-sheet PNGs, manifest, English prompt
  calls/round-0/          Also round-1 and round-2
    request.json          Request parameters; images replaced by local paths, SHA-256, byte counts
    api-response.json     Original HTTP response body, saved before validation
    model-output.txt      Exact completed response text, including any explanation
    layout.json           Layout-only JSON; extracted from the final response when it has an explanation
    explanation.json      Final round only, if requested
  round-0/               Also round-1 and round-2
    response.txt          Accepted layout text
    feedback.png          Image for the next round, except after the final round
    feedback.json        Scene and paths to native-resolution snapshot pair
    next-prompt.txt       Next adjustment instructions, or completion notice
    explanation.json     Final round only: structured artwork description
    explanation.txt      Final round only: readable artwork description
    FoodFace-.../        Native-resolution scene JSON and PNG
```

The request log is not the literal wire body: to reconstruct it, replace each image's `localFile`/`sha256`/`bytes` fields with `image_url: data:image/png;base64,...` using the referenced bytes relative to that Agent directory. Other request parameters are retained. Headers/keys are never logged. Keep the run and referenced source files together; hashes alone cannot reconstruct the renderer.

There are no automatic API retries or model repair calls. A refusal, incomplete response, invalid layout, timeout, HTTP failure, or render failure stops the experiment, marks it failed, and preserves completed rounds and available API records. Invalid layouts do not consume an accepted rendering opportunity, but the attempted API call may still cost money. A timeout can have an unknown server-side outcome. This version does not automatically resume failed experiments; inspect saved records before deliberately starting another paid run. An abrupt process kill may leave a `running` status; it is not evidence that the API request was unbilled.

Failures report their stage and stack locations instead of just an exception class. `error.json` and `experiment.json` include Python/package versions and redacted built-in error messages, including wrapped causes. Request headers, local variables and arbitrary HTTP exception text are excluded. Successful HTTP response bodies are saved before application parsing, so a local validation failure does not discard an already-received model result. Receiving no response still means unknown usage, not zero cost.

## Verification

```sh
/private/tmp/foodface-agent-venv/bin/python -m unittest discover -s scripts -p 'test_*.py'
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers FOODFACE_BROWSER_TEST=1 /private/tmp/foodface-agent-venv/bin/python -m unittest discover -s scripts -p 'test_*.py'
```

The mock tests cover request history, image transport, final-round-only explanations, uid references, isolated branching, unchanged source files, and stopping without retries. Browser tests run all three rounds for both portraits and check snapshots and the final state. No test invokes a paid API.

Official references: [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Responses conversation state](https://developers.openai.com/api/docs/guides/conversation-state), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), and [image inputs](https://developers.openai.com/api/docs/guides/images-vision).
