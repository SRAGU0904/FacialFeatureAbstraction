# Local agent workflow

The manual runner (`scripts/agent.py`) accepts JSON responses from files and returns rendered images without model calls or API keys. For automatic model calls, see the [OpenAI experiment workflow](openai-experiment.md), which reuses this renderer and protocol and also provides a fully offline dry run. The initial layout and two adjustments are a provisional protocol, not a validated study design. The examples are hand-written plumbing tests, not AI results or recommended compositions.

## Setup and demo

The normal human editor still requires only Python 3. The agent runner additionally uses Playwright and Chromium. From the repository root:

```sh
python3 -m venv /private/tmp/foodface-agent-venv
/private/tmp/foodface-agent-venv/bin/python -m pip install -r scripts/requirements-agent.txt
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers /private/tmp/foodface-agent-venv/bin/python -m playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers /private/tmp/foodface-agent-venv/bin/python scripts/agent.py demo --portrait zhu
```

The runner starts and stops its own local server on an available port and uses an isolated browser. No separate studio server is needed. Replace `zhu` with `euro` for the second portrait. Add `--headed` before the command to watch the browser. The terminal prints the run directory and final feedback image path. Temporary dependencies can be recreated if `/private/tmp` is cleared; use a persistent virtual environment outside the repository if preferred.

## Supply your own responses

Using the same Python environment and `PLAYWRIGHT_BROWSERS_PATH` as above:

```sh
python scripts/agent.py start --portrait zhu
python scripts/agent.py apply /absolute/path/to/Agent-zhu-RUN_ID examples/agent/initial.json
python scripts/agent.py apply /absolute/path/to/Agent-zhu-RUN_ID examples/agent/adjust-1.json
python scripts/agent.py apply /absolute/path/to/Agent-zhu-RUN_ID examples/agent/adjust-2.json
```

Substitute the actual printed run directory and your own response file paths. `start` prepares the input package without consuming an attempt. Each `apply` renders and commits exactly one response. There are three accepted responses: round 0 (initial), round 1, round 2. The fourth is rejected. Invalid responses leave the scene unchanged, are recorded as `rejected-*.json`, and do not consume an opportunity. A failed render or disk write also does not publish a round. The separate OpenAI adapter stops on invalid responses or API failures and performs no automatic retries.

All three responses use the same complete-layout format:

```json
{"items":[{"uid":"f1","id":"<asset_id>","x":0.5,"y":0.5,"size":0.2,"angle":0,"flipX":false,"flipY":false}]}
```

`<asset_id>` is a documentation placeholder, not a valid ID; choose from the supplied catalog. The model-facing prompt describes field types without a named-food example. The runnable demo fixtures use real assets to exercise rendering; they are never included in model input packages.

Every response replaces the complete item list, including unchanged instances. Keep the same uid and asset id for retained instances. Include new instances with fresh uids; omit instances to remove them. Change array order to change food layers: later entries cover earlier entries. Use a fresh uid when replacing an instance with a different asset. A removed uid cannot be reused later in the run. Return the identical complete layout to leave the scene unchanged; `{"items":[]}` clears it, while `{}` is invalid. All items need the six core fields on every round; `flipX` and `flipY` are optional booleans. Omitted flip flags mean false, even if they were true in the previous response. Include each true flag again to retain it. Partial-operation fields (`update`, `add`, `remove`, `order`) are not accepted.

Invalid fields, duplicate keys/uids, reused retired uids and out-of-range values are rejected without changing the previous scene. This is response protocol version 2; start a new run instead of continuing a version-1 incremental-response run. Scene/snapshot schema version 1 is unchanged. See `prompts/agent-layout.txt` for the full English contract.

## Images and geometry

`inputs/` contains:

- `original.png`: original full-frame portrait, reduced only for observation.
- `empty.png`: full-frame portrait with the face cleared using the same renderer as the human editor. This is not the raw fill asset: clothing and hat remain correctly composited.
- `foods.png`: a 4 by 4 contact sheet with the stable string IDs, original orientations, and alpha-cropped pixel dimensions. The IDs serve as selection codes; there is no second numeric-to-name mapping.
- `manifest.json`: logical canvas dimensions, observation dimensions, exact source paths and crop rectangles, and the normalized bounding box of the existing face-removal mask.
- `prompt.txt`: the English instructions with the selected portrait's dimensions, face bounds, and food sizes filled in.

Coordinates are normalized against the full portrait, so downsampling does not change their meaning. Position is the center of the cropped food rectangle; size is the longest unrotated side divided by **canvas width**. Crop aspect ratio fixes the other side. The face bounding box is a geometric aid derived from the existing mask, not facial landmarks or a placement restriction. Neither the empty image nor these coordinates guarantee that a model can locate facial features accurately; that remains to be tested.

`flipX` reverses left/right along the food's own local X direction; `flipY` reverses up/down along its local Y direction. These directions follow the original contact-sheet orientation, not screen axes after rotation. Both flips act around the cropped food's center before `angle` rotation. In local coordinates, they negate X and Y respectively. Uniform size scaling preserves this meaning; the center is then placed at `(x * W, y * H)`. Flipping leaves position, size and angle values unchanged. The JSON describes final state, not the chronological order of editing gestures. Both flags may be true, and non-boolean values are rejected.

Observation images default to a longest edge of 1024 pixels (`start --max-edge 1024`); the contact sheet is 1024 by 1024. These are configurable engineering defaults, not a claim of optimal image-token cost or sufficient visual detail for every model. Individual full-resolution food files remain in `assets/foods/`. The saved scene PNG always has the portrait's original resolution.

## Feedback and local records

Runs are saved under `result-data/agent-runs/Agent-<portrait>-<UUID>/`:

```text
run.json                 Protocol settings, timestamps, browser version, code/asset hashes
inputs/                  Initial images, manifest and instantiated English prompt
round-0/                 Initial layout
round-1/                 First adjustment
round-2/                 Second adjustment (final)
  response.txt           Exact submitted response text
  feedback.png           Reduced image to return to the model
  feedback.json          Full resulting scene, dimensions, remaining adjustments, snapshot paths
  next-prompt.txt         Short full-layout request; final round marks completion
  FoodFace-.../          Original-resolution JSON + PNG pair in the existing snapshot format
```

Every accepted round uses the same `schemaVersion`, `assetVersion`, `rendererVersion`, item constraints, draw order, and paired-snapshot writer as human work. Manual runs store `model: null` and `modelParameters: null`; the OpenAI adapter fills these fields and separately records returned model IDs, requests, settings, token usage and failures. This does not guarantee model reproducibility. Runs record exact code and asset hashes and reject continuing after they change. Retain referenced source files with the run; hashes alone cannot reconstruct them. A crashed process can leave `.lock`; remove it only after verifying no writer is running.

`feedback.json` is a local record, not a requirement to send all metadata to a model. For an API integration, send the initial prompt and three images, then append the latest `feedback.png` and `next-prompt.txt` after rounds 0 and 1. No fourth model call is needed after the final image. Keep the original/reference information and previous complete JSON responses available in the conversation. The next-round prompt does not repeat the previous item list; `feedback.json` retains it locally. Avoid manually appending duplicate copies of prior images or responses. Prior images may still be billed when retained in request history; savings and caching depend on the chosen API. Sending base64 as an image transport is different from placing the base64 string in a text prompt.

A contact sheet reduces separate attachments and redundant padding, but may lose small details. Inspect the images for the chosen model before fixing an experimental condition. Full-layout JSON simplifies the response contract and eliminates patch merging, but repeats unchanged items in model output. It is not guaranteed to use fewer tokens than incremental responses. No separate explanation or duplicate current-state block is requested. Future face crops or coordinate grids should be explicit observation conditions, not silently introduced midway through a run.

## Verification

```sh
python -m unittest discover -s scripts -p 'test_*.py'
FOODFACE_BROWSER_TEST=1 python -m unittest discover -s scripts -p 'test_*.py'
```

The second command needs the agent environment/browser above and permission to bind a loopback port. It exercises both portraits, all three rounds, invalid-response rollback, failed writes, source-version changes, human editing, and exact equality between human-editor exports and agent PNGs. Unit tests cover repeated assets, stable uids, full-state replacement, omissions, layers, and invalid responses.

`agent-render.html` and `window.FOODFACE_AGENT` are the internal browser bridge used after Python validation. They are not a public HTTP layout endpoint. The OpenAI adapter keeps one `BrowserRenderer` open and calls `start_run` and `submit_response`; the existing `/api/snapshots` continues accepting already-rendered scene/PNG pairs. The general-purpose historical JSON-to-PNG regeneration tool remains deferred.
