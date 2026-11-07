# FoodFace

A local portrait collage studio for facial feature abstraction. Arrange 16 food cutouts on either of two portraits, then save the collage as paired JSON and PNG files on this computer.

## Run

Requires Python 3. No frontend dependencies or build step.

```sh
python3 scripts/server.py
```

On macOS, you can also double-click `Start FoodFace.command`. Keep the terminal open; press `Control+C` to stop. The default address is `http://127.0.0.1:8765`. If the port is occupied, the server prints an available address.

Use `--port 9000` to choose a port or `--no-browser` to skip opening the browser. The browser sends saved snapshots only to the local Python service; nothing is uploaded to a remote server.

## Create a collage

1. Choose a portrait. Each portrait keeps a separate collage.
2. Click a food item to add it, or drag it onto the canvas.
3. Drag to move, use the lower-right handle to resize, or the top handle to rotate. Use the sliders for precise adjustments.
4. Use **Backward**, **Forward**, **Duplicate**, or **Delete** to edit the selection. Select covered items in **Layers**.
5. Select **Save JSON + PNG** to save the active portrait's editable scene data and full-resolution image without selection controls. The confirmation shows the saved location and links to both files.

The original hat stays in front of the food. Food can cover the collar and clothing. **Clear** removes all food from the active portrait and can be undone.

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

## Saving

Working drafts save automatically in browser storage. Use the same browser, host, and port to restore them. Clearing site data removes these drafts. This browser autosave is separate from saving files.

**Save JSON + PNG** writes a new snapshot into `result-data/FoodFace-<portrait>-<snapshot UUID>/` in the project directory. Inside, the `.json` and `.png` files have the same base name. Each click preserves a separate snapshot; earlier saves are never overwritten. The pair is published together after both files have been written. Original images are never modified. `result-data/` is excluded from Git; back up this directory separately. Start or restart the Python service after updating the code to enable the save endpoint.

Saved JSON contains `schemaVersion`, `assetVersion`, `rendererVersion`, `snapshotId`, `savedAt` (UTC), `portraitId`, `canvas`, and `items`. It also records the PNG filename and SHA-256 checksum. `savedAt` is the snapshot time, not the start of the editing session. Each item contains a stable instance `uid`, food asset `id`, center coordinates `x` and `y` (fractions of canvas width and height), `size` (the longest side of the alpha-cropped food image divided by canvas width), and `angle` (clockwise degrees). Array order runs from the lowest food layer to the highest. Undo/redo history is not included.

Version 1 uses the bundled assets, alpha-bound calculation and rendering rules in `app.js`, catalog settings, and face/hat paths. JSON references shared assets; it does not embed them. Retain these assets and rendering rules with your backups, and increment/archive their versions before changing them if old snapshots must render identically. A JSON import or regeneration tool is not included yet.

## Deferred work / project reminder

- **Agreed 2026-11-07:** save JSON and PNG together during the initial stage. Later, add a local tool to regenerate individual or batches of PNGs from JSON and the matching shared assets. When discussing growing image storage or switching to JSON-only saves, remind the user about this tool before removing stored PNGs. Validate it against the paired PNGs saved during this stage. No reminder date has been set.

## Repository structure

```text
index.html                    Studio page
assets/
  css/styles.css              Layout and styles
  js/
    app.js                    Canvas, editing, storage, and export
    catalog.js                Food names, sizes, and portrait settings
    portrait-paths.js         Face and hat clipping paths
  foods/                      16 transparent PNG cutouts and manifest.json
  portraits/                  Original portraits and active face fills
    drafts/                   Unused generated layers
    generation-notes.json     Generation prompts and rendering notes
scripts/server.py             Local static server and snapshot save API
result-data/                  Saved JSON + PNG pairs (not tracked by Git)
Start FoodFace.command        macOS launcher
```

Food cutouts are 1254 × 1254 transparent PNGs; walnut uses the revised version. [The food manifest](assets/foods/manifest.json) records names, reference sources, and generation prompts.

The renderer draws the original portrait, fills the clipped face region, adds food, then restores the clipped original hat. Active fills are `zhu-face-fill.png` and `euro-background.png`. [Generation notes](assets/portraits/generation-notes.json) document the fills and retained drafts. Drafts are not loaded by the studio.
