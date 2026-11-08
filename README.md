# FoodFace

A bilingual portrait collage studio for facial feature abstraction. Arrange 16 food cutouts on two portraits, then copy each result as JSON for manual sharing with the researcher.

## Run

Requires Python 3. No frontend dependencies or build step.

```sh
python3 scripts/server.py
```

On macOS, you can also double-click `Start FoodFace.command`. Keep the terminal open; press `Control+C` to stop. The default address is `http://127.0.0.1:8765`. If the port is occupied, the server prints an available address.

Use `--port 9000` to choose a port or `--no-browser` to skip opening the browser. The human page generates results entirely in the browser. It does not upload submissions or demographic information and can run on static hosting, including GitHub Pages. Use English or 中文 in the upper-right corner to switch the interface without resetting work.

## Human experiment

Create food collages that resemble each person and emphasize their distinctive facial features. Complete both portraits in any order; there is no practice trial or time limit. Any food can be reused, with no item count limit. Preserve natural food shapes: move, rotate, flip and resize proportionally.

1. Choose Zhu Yuanzhang or Rudolf II. Switch freely between unfinished portraits.
2. Click a food to add it, or drag it onto the canvas.
3. Drag to move, use the lower-right handle to resize, or the top handle to rotate. Sliders allow precise adjustments.
4. Use **Flip horizontal** or **Flip vertical** to mirror selected food; click again to undo that flip. Use **Backward**, **Forward**, **Duplicate**, **Delete**, **Clear**, undo and redo while editing. Select covered items in **Layers**.
5. Read the research notice below the submission button and enter gender, age, and nationality. The form retains these details when switching portraits, so they only need to be entered once. You can update them before submitting the second portrait; each result keeps the details recorded at its own submission time.
6. Select **Submit portrait** and confirm. The portrait is locked and its complete result JSON appears below the form. Use **Copy JSON**, then send it to the website developer yourself.
7. Complete the other portrait and copy its result too. You can switch back to either submitted portrait to copy its JSON again.

Refreshing or reopening starts a new session and clears both collages, participant details, and generated JSON. Nothing is saved automatically; copy and send both results before leaving. The notice explains that copying and sending a result to the developer indicates agreement to research use. Generating or copying JSON alone does not transmit it or prove it was sent. No names, contact details, timer, or operation log are requested.

The original hat stays in front of the food. Food can cover the collar and clothing.

The second portrait is **Rudolf II**, by **Hans von Aachen**, 1606–1608, Kunsthistorisches Museum, Vienna ([artwork reference](https://www.wga.hu/html_m/a/aachen/rudolf2.html)). The existing `euro` asset ID and filenames remain stable so saved scenes and agent inputs stay compatible.

## Keyboard shortcuts

| Shortcut                         | Action                       |
| -------------------------------- | ---------------------------- |
| Arrow keys / Shift + Arrow keys  | Move / move faster           |
| Delete or Backspace              | Delete selection             |
| Escape                           | Deselect                     |
| Cmd/Ctrl + Z                     | Undo                         |
| Cmd/Ctrl + Shift + Z or Ctrl + Y | Redo                         |
| Cmd/Ctrl + D                     | Duplicate selection          |
| Shift while rotating             | Snap to 15-degree increments |

## Result JSON and image reproduction

Each result uses the same complete scene fields as agent snapshots: `schemaVersion`, `assetVersion`, `rendererVersion`, `portraitId`, `canvas`, and `items`. Each item includes its instance `uid`, asset `id`, normalized center `x`/`y`, proportional `size`, clockwise `angle`, and optional `flipX`/`flipY`. Array order runs from the lowest food layer to the highest.

Human metadata is separate: `demographics` contains `gender`, integer `age`, and the entered `nationality`; `experiment` records `actorType`, the shared random `sessionId`, unique `trialId`, `status`, `submittedAt` (UTC), and `interfaceLanguage` (`en` or `zh`). `feedback` contains optional suggestions or comments (an empty string when left blank). `researchNotice` retains the English wording corresponding to the bilingual notice. Field names and gender codes remain English in both interfaces; nationality preserves the participant's input. Session IDs group portraits but do not establish distinct participants. JSON does not include pixels or editing history.

Save a received JSON message as a UTF-8 file, then render it using the existing [agent environment](docs/agent-workflow.md):

```sh
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers \
  /private/tmp/foodface-agent-venv/bin/python scripts/render_scene.py \
  /absolute/path/result.json --output /absolute/path/result.png
```

`render_scene.py` validates the scene and calls the existing `agent.BrowserRenderer`, which uses `agent-render.html` and the shared `renderer.js`. Demographics do not affect rendering. Output is the original portrait resolution; existing output files are never overwritten. The same command accepts full agent scene snapshots. Raw agent responses containing only `items` also need the portrait and version fields supplied by the agent runner.

For manual participant folders, save `euro.json` and `zhu.json` under
`result-data/human/0001/` (then `0002/`, etc.). Pass the folder to render
both images beside their source JSONs:

```sh
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/foodface-agent-browsers \
  /private/tmp/foodface-agent-venv/bin/python scripts/render_scene.py \
  result-data/human/0001
```

Folder mode validates every immediate `.json` file and checks for existing PNGs
before rendering; it does not recurse. Single-file mode also defaults to a PNG
beside the JSON when `--output` is omitted. See the [manual data workflow](docs/human-data.md#numbered-participant-folders-manual-workflow).

Keep received JSON in private storage outside the public site. The existing local snapshot/submission APIs and previously saved PNGs remain available for earlier integrations; the human page no longer calls those APIs. `result-data/` remains ignored by Git. Keep the matching assets, renderer, and browser version with research results for reproducibility; do not replace shared assets without archiving/versioning them.

For optional automatic intake, use `scripts/human_results.py` to import one received JSON from
the macOS clipboard or a file, preserve the original, group results by session,
and render automatically. Choose `--collection formal` or `--collection self-test`
explicitly. Duplicate imports do not overwrite records; re-renders keep separate
versions. See [Human data intake and management](docs/human-data.md) for commands,
completeness checks, and private backups.

## Agent prototype

The local Python runner accepts three complete JSON layouts (an initial attempt and two adjustments), renders each with the same renderer as the human editor, and returns an image plus the resulting scene. It also prepares an English prompt, original/empty portraits, and a labeled food contact sheet. See [Agent workflow](docs/agent-workflow.md) for the manual JSON demo and protocol. The [OpenAI experiment runner](docs/openai-experiment.md) adds GPT-6.1 Sol via Responses API with terminal-supplied credentials, separate three-round histories for both portraits, and an offline dry run using fabricated responses.

## Deferred work

Single-scene and single-folder JSON-to-PNG rendering are implemented with the existing agent renderer. Cross-folder batch regeneration remains deferred. Previously saved JSON + PNG pairs remain intact for comparison.

## Repository structure

```text
index.html                    Studio page
assets/
  css/styles.css              Layout and styles
  js/
    app.js                    Editing, demographics, and copyable result JSON
    i18n.js                   English and Chinese interface strings
    renderer.js               Shared human/agent asset loading and rendering
    agent-render.js           Agent image preparation and browser bridge
    catalog.js                Food names, sizes, and portrait settings
    portrait-paths.js         Face and hat clipping paths
  foods/                      16 transparent PNG cutouts and manifest.json
  portraits/                  Original portraits and active face fills
    drafts/                   Unused generated layers
    generation-notes.json     Generation prompts and rendering notes
scripts/server.py             Local static server and snapshot save API
scripts/agent.py              JSON-to-image agent loop (manual responses)
scripts/render_scene.py       Render received human or agent scene JSON to PNG
scripts/human_results.py      Archive, list and re-render received human results
scripts/openai_experiment.py   OpenAI experiment and offline HTTP-mocked dry run
agent-render.html             Isolated browser rendering surface
prompts/agent-layout.txt       English agent instructions
examples/agent/               Hand-written initial and adjustment responses
docs/agent-workflow.md         Agent setup, protocol and verification
result-data/                  Saved JSON + PNG pairs (not tracked by Git)
Start FoodFace.command        macOS launcher
```

Food cutouts are 1254 × 1254 transparent PNGs; walnut uses the revised version. [The food manifest](assets/foods/manifest.json) records names, reference sources, and generation prompts.

The renderer draws the original portrait, fills the clipped face region, adds food, then restores the clipped original hat. Active fills are `zhu-face-fill.png` and `euro-background.png`. [Generation notes](assets/portraits/generation-notes.json) document the fills and retained drafts. Drafts are not loaded by the studio.
