"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const canvas = $("collage"),
    ctx = canvas.getContext("2d");
  const { foods, portraits } = window.FOODFACE_CATALOG;
  const foodById = Object.fromEntries(foods.map((f) => [f.id, f]));
  const paths = Object.fromEntries(
    Object.entries(window.FOODFACE_PATHS).map(([id, p]) => [
      id,
      { face: new Path2D(p.face), hat: new Path2D(p.hat) },
    ]),
  );
  const assets = new Map(),
    states = {
      zhu: { items: [], undo: [], redo: [] },
      euro: { items: [], undo: [], redo: [] },
    };
  const storageKey = "foodface-studio-v1";
  let active = "zhu",
    selected = null,
    ready = false,
    savingSnapshot = false,
    gesture = null,
    libraryDrag = null,
    toastTimer,
    saveTimer;
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const state = () => states[active];
  const selectedItem = () => state().items.find((i) => i.uid === selected);
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
  const normalizeAngle = (n) => ((((n + 180) % 360) + 360) % 360) - 180;
  const uid = () =>
    globalThis.crypto?.randomUUID?.() ||
    `food-${Date.now()}-${Math.random().toString(36).slice(2)}`;

  // Feedback and local storage
  function toast(message) {
    $("toast").textContent = message;
    $("toast").classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $("toast").classList.remove("visible"), 2400);
  }
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try {
        localStorage.setItem(
          storageKey,
          JSON.stringify({
            active,
            scenes: Object.fromEntries(
              Object.entries(states).map(([k, s]) => [k, s.items]),
            ),
          }),
        );
        $("saveStatus").textContent = "Draft saved in browser";
      } catch {
        $("saveStatus").textContent =
          "Browser autosave unavailable. Use Save JSON + PNG to keep your work.";
      }
    }, 180);
  }
  function restore() {
    try {
      const data = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (!data) return;
      if (portraits[data.active]) active = data.active;
      for (const key of Object.keys(states)) {
        if (!Array.isArray(data.scenes?.[key])) continue;
        const restoredIds = new Set();
        states[key].items = data.scenes[key]
          .filter(
            (i) =>
              foodById[i.id] &&
              [i.x, i.y, i.size, i.angle].every(Number.isFinite),
          )
          .slice(0, 150)
          .map((i) => {
            const itemUid = typeof i.uid === "string" && i.uid.length > 0 &&
              i.uid.length <= 128 && !restoredIds.has(i.uid) ? i.uid : uid();
            restoredIds.add(itemUid);
            return {
              uid: itemUid,
              id: i.id,
              x: clamp(i.x, 0, 1),
              y: clamp(i.y, 0, 1),
              size: clamp(i.size, 0.03, 0.9),
              angle: normalizeAngle(i.angle),
            };
          });
      }
    } catch {
      /* Ignore invalid or inaccessible browser storage. */
    }
  }

  // History
  function checkpoint() {
    state().undo.push(clone(state().items));
    if (state().undo.length > 60) state().undo.shift();
    state().redo = [];
  }
  function commit() {
    draw();
    updateControls();
    updateLayers();
    save();
  }

  // Asset loading and canvas rendering
  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const im = new Image();
      im.onload = () => resolve(im);
      im.onerror = () => reject(new Error(`Could not load ${url}`));
      im.src = url;
    });
  }
  function analyzeImage(image) {
    const c = document.createElement("canvas");
    c.width = image.naturalWidth;
    c.height = image.naturalHeight;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(image, 0, 0);
    const pixels = g.getImageData(0, 0, c.width, c.height).data;
    let minX = c.width,
      minY = c.height,
      maxX = 0,
      maxY = 0;
    for (let y = 0; y < c.height; y++)
      for (let x = 0; x < c.width; x++)
        if (pixels[(y * c.width + x) * 4 + 3] > 64) {
          minX = Math.min(minX, x);
          maxX = Math.max(maxX, x);
          minY = Math.min(minY, y);
          maxY = Math.max(maxY, y);
        }
    const box = {
      x: Math.max(0, minX - 2),
      y: Math.max(0, minY - 2),
      w: Math.min(c.width, maxX + 3) - Math.max(0, minX - 2),
      h: Math.min(c.height, maxY + 3) - Math.max(0, minY - 2),
    };
    return { image, box, pixels, sourceWidth: c.width };
  }
  function dimensions(item) {
    const { box } = assets.get(item.id);
    const longest = item.size * canvas.width;
    return {
      w: (longest * box.w) / Math.max(box.w, box.h),
      h: (longest * box.h) / Math.max(box.w, box.h),
    };
  }
  function imageToCanvas(g, item) {
    const a = assets.get(item.id);
    if (!a) return;
    const { w, h } = dimensions(item);
    g.save();
    g.translate(item.x * canvas.width, item.y * canvas.height);
    g.rotate((item.angle * Math.PI) / 180);
    g.drawImage(
      a.image,
      a.box.x,
      a.box.y,
      a.box.w,
      a.box.h,
      -w / 2,
      -h / 2,
      w,
      h,
    );
    g.restore();
  }
  function drawScene(g) {
    if (!ready) return;
    g.clearRect(0, 0, canvas.width, canvas.height);
    // Original pixels preserve all backdrop, clothing, color and registration.
    const original = assets.get(active + "-original");
    g.drawImage(original, 0, 0, canvas.width, canvas.height);
    // Use generated inpainting only inside the removed face, never on garments.
    g.save();
    g.clip(paths[active].face);
    if (active === "euro") g.filter = "saturate(0.25) brightness(0.8)";
    g.drawImage(
      assets.get(active === "euro" ? "euro-background" : active + "-face-fill"),
      0,
      0,
      canvas.width,
      canvas.height,
    );
    g.restore();
    for (const item of state().items) imageToCanvas(g, item);
    // Only the original hat is in front; food may cover the collar and clothing.
    g.save();
    g.clip(paths[active].hat);
    g.drawImage(original, 0, 0, canvas.width, canvas.height);
    g.restore();
  }
  function screenUnit() {
    return canvas.width / Math.max(1, canvas.getBoundingClientRect().width);
  }
  function selectionGeometry(item) {
    const d = dimensions(item),
      u = screenUnit(),
      pad = 6 * u;
    return { w: d.w + pad * 2, h: d.h + pad * 2, u };
  }
  function draw() {
    if (!ready) return;
    drawScene(ctx);
    const item = selectedItem();
    $("deleteHandle").hidden = !item;
    if (item) {
      const { w, h, u } = selectionGeometry(item);
      const angle = (item.angle * Math.PI) / 180;
      const cornerX =
        item.x * canvas.width +
        (w / 2) * Math.cos(angle) +
        (h / 2) * Math.sin(angle);
      const cornerY =
        item.y * canvas.height +
        (w / 2) * Math.sin(angle) -
        (h / 2) * Math.cos(angle);
      $("deleteHandle").style.left =
        (clamp(cornerX, 14 * u, canvas.width - 14 * u) / canvas.width) * 100 +
        "%";
      $("deleteHandle").style.top =
        (clamp(cornerY, 14 * u, canvas.height - 14 * u) / canvas.height) * 100 +
        "%";
      ctx.save();
      ctx.translate(item.x * canvas.width, item.y * canvas.height);
      ctx.rotate((item.angle * Math.PI) / 180);
      ctx.strokeStyle = "#f9fff0";
      ctx.lineWidth = 1.3 * u;
      ctx.shadowColor = "#24391a90";
      ctx.shadowBlur = 3 * u;
      ctx.setLineDash([4 * u, 3 * u]);
      ctx.strokeRect(-w / 2, -h / 2, w, h);
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(0, -h / 2);
      ctx.lineTo(0, -h / 2 - 24 * u);
      ctx.stroke();
      ctx.fillStyle = "#f8fff2";
      ctx.strokeStyle = "#48633c";
      ctx.lineWidth = 1.5 * u;
      ctx.beginPath();
      ctx.arc(0, -h / 2 - 24 * u, 6 * u, 0, 2 * Math.PI);
      ctx.fill();
      ctx.stroke();
      ctx.fillRect(w / 2 - 5 * u, h / 2 - 5 * u, 10 * u, 10 * u);
      ctx.strokeRect(w / 2 - 5 * u, h / 2 - 5 * u, 10 * u, 10 * u);
      ctx.restore();
    }
    $("objectCount").textContent =
      `${state().items.length} ${state().items.length === 1 ? "item" : "items"}`;
  }

  // Selection and portrait controls
  function updateControls() {
    const i = selectedItem();
    $("transformControls").disabled = !i;
    $("selectedName").textContent = i ? foodById[i.id].name : "No selection";
    if (i) {
      $("size").value = i.size * 100;
      $("sizeValue").textContent = `${Math.round(i.size * 100)}%`;
      $("rotation").value = Math.round(i.angle);
      $("rotationValue").textContent = `${Math.round(i.angle)}°`;
    }
    $("undo").disabled = !state().undo.length;
    $("redo").disabled = !state().redo.length;
    $("clear").disabled = !state().items.length;
    $("export").disabled = !ready || savingSnapshot;
    if (i) {
      const index = state().items.indexOf(i);
      $("backward").disabled = index === 0;
      $("forward").disabled = index === state().items.length - 1;
    }
  }
  function updateLayers() {
    const list = $("layerList");
    list.replaceChildren();
    if (!state().items.length) return;
    state().items.forEach((i, index) => {
      const b = document.createElement("button");
      b.className = "layer-chip" + (i.uid === selected ? " active" : "");
      b.textContent = `${foodById[i.id].name} ${index + 1}`;
      b.setAttribute("aria-pressed", String(i.uid === selected));
      b.addEventListener("click", () => {
        selected = i.uid;
        draw();
        updateControls();
        updateLayers();
      });
      list.append(b);
    });
  }
  function addFood(id, point) {
    if (!ready) {
      toast("Assets are still loading.");
      return;
    }
    if (state().items.length >= 150) {
      toast("Maximum 150 items per canvas.");
      return;
    }
    const f = foodById[id];
    checkpoint();
    const [x, y] = point || portraits[active].center;
    const item = {
      uid: uid(),
      id,
      x: clamp(x, 0, 1),
      y: clamp(y, 0, 1),
      size: f.size,
      angle: 0,
    };
    state().items.push(item);
    selected = item.uid;
    commit();
  }
  function selectPortrait(id) {
    if (!portraits[id]) return;
    active = id;
    selected = null;
    gesture = null;
    const p = portraits[id];
    canvas.width = p.w;
    canvas.height = p.h;
    document.documentElement.style.setProperty("--ratio", `${p.w}/${p.h}`);
    $("original").src = `assets/portraits/${id}-original.png`;
    $("original").alt = p.name + " — original";
    $("portraitName").textContent = p.name;
    document.querySelectorAll("[data-portrait]").forEach((b) => {
      b.classList.toggle("active", b.dataset.portrait === id);
      b.setAttribute("aria-pressed", String(b.dataset.portrait === id));
    });
    commit();
  }

  // Canvas gestures
  function point(e) {
    const r = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - r.left) / r.width) * canvas.width,
      y: ((e.clientY - r.top) / r.height) * canvas.height,
    };
  }
  function localPoint(p, item) {
    const dx = p.x - item.x * canvas.width,
      dy = p.y - item.y * canvas.height,
      a = (-item.angle * Math.PI) / 180;
    return {
      x: dx * Math.cos(a) - dy * Math.sin(a),
      y: dx * Math.sin(a) + dy * Math.cos(a),
    };
  }
  function handleAt(p, item) {
    if (!item) return null;
    const q = localPoint(p, item),
      { w, h, u } = selectionGeometry(item),
      radius = 14 * u;
    if (Math.hypot(q.x, q.y + h / 2 + 24 * u) < radius) return "rotate";
    if (Math.hypot(q.x - w / 2, q.y - h / 2) < radius) return "scale";
    return null;
  }
  function hitTest(p, item) {
    const q = localPoint(p, item),
      { w, h } = dimensions(item);
    if (Math.abs(q.x) > w / 2 || Math.abs(q.y) > h / 2) return false;
    const a = assets.get(item.id),
      sx = Math.floor(a.box.x + (q.x / w + 0.5) * a.box.w),
      sy = Math.floor(a.box.y + (q.y / h + 0.5) * a.box.h);
    return !a.pixels || a.pixels[(sy * a.sourceWidth + sx) * 4 + 3] > 35;
  }
  canvas.addEventListener("pointerdown", (e) => {
    if (!ready || e.button !== 0) return;
    e.preventDefault();
    canvas.focus();
    const p = point(e);
    let item = selectedItem(),
      mode = handleAt(p, item);
    if (!mode) {
      item = [...state().items].reverse().find((i) => hitTest(p, i));
      mode = "move";
    }
    if (!item) {
      selected = null;
      draw();
      updateControls();
      updateLayers();
      return;
    }
    selected = item.uid;
    const dx = p.x - item.x * canvas.width,
      dy = p.y - item.y * canvas.height;
    gesture = {
      pointer: e.pointerId,
      mode,
      uid: item.uid,
      start: p,
      before: clone(item),
      distance: Math.hypot(dx, dy),
      angle: Math.atan2(dy, dx),
      changed: false,
    };
    canvas.setPointerCapture(e.pointerId);
    draw();
    updateControls();
    updateLayers();
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!ready) return;
    const p = point(e);
    if (!gesture) {
      const m = handleAt(p, selectedItem());
      canvas.style.cursor =
        m === "rotate"
          ? "crosshair"
          : m === "scale"
            ? "nwse-resize"
            : state().items.some((i) => hitTest(p, i))
              ? "grab"
              : "default";
      return;
    }
    if (e.pointerId !== gesture.pointer) return;
    const item = state().items.find((i) => i.uid === gesture.uid);
    if (!item) return;
    if (!gesture.changed) {
      if (
        Math.hypot(p.x - gesture.start.x, p.y - gesture.start.y) <
        2 * screenUnit()
      )
        return;
      checkpoint();
      gesture.changed = true;
    }
    if (gesture.mode === "move") {
      item.x = clamp(
        gesture.before.x + (p.x - gesture.start.x) / canvas.width,
        0,
        1,
      );
      item.y = clamp(
        gesture.before.y + (p.y - gesture.start.y) / canvas.height,
        0,
        1,
      );
      canvas.style.cursor = "grabbing";
    } else if (gesture.mode === "scale") {
      const distance = Math.hypot(
        p.x - item.x * canvas.width,
        p.y - item.y * canvas.height,
      );
      item.size = clamp(
        (gesture.before.size * distance) / Math.max(1, gesture.distance),
        0.03,
        0.9,
      );
    } else {
      const angle = Math.atan2(
        p.y - item.y * canvas.height,
        p.x - item.x * canvas.width,
      );
      item.angle = normalizeAngle(
        gesture.before.angle + ((angle - gesture.angle) * 180) / Math.PI,
      );
      if (e.shiftKey) item.angle = Math.round(item.angle / 15) * 15;
    }
    draw();
    updateControls();
  });
  function endGesture(e) {
    if (!gesture || e.pointerId !== gesture.pointer) return;
    gesture = null;
    canvas.style.cursor = "grab";
    commit();
  }
  canvas.addEventListener("pointerup", endGesture);
  canvas.addEventListener("pointercancel", endGesture);
  canvas.addEventListener("lostpointercapture", endGesture);

  // Food library and drag-and-drop
  function withinCanvas(e) {
    const r = canvas.getBoundingClientRect();
    return (
      e.clientX >= r.left &&
      e.clientX <= r.right &&
      e.clientY >= r.top &&
      e.clientY <= r.bottom
    );
  }
  function buildLibrary() {
    foods.forEach((f) => {
      const b = document.createElement("button");
      b.className = "food-card";
      b.dataset.food = f.id;
      b.setAttribute("aria-label", "Add " + f.name);
      b.disabled = true;
      const im = document.createElement("img");
      im.src = `assets/foods/${f.id}.png`;
      im.alt = "";
      im.draggable = false;
      const label = document.createElement("span");
      label.textContent = f.name;
      b.append(im, label);
      b.addEventListener("pointerdown", (e) => {
        if (e.button !== 0 || !ready) return;
        libraryDrag = {
          id: f.id,
          pointer: e.pointerId,
          x: e.clientX,
          y: e.clientY,
          dragging: false,
          touch: e.pointerType === "touch",
        };
      });
      b.addEventListener("click", (e) => {
        if (b.dataset.ignoreClick === "yes") {
          delete b.dataset.ignoreClick;
          return;
        }
        if (!libraryDrag) addFood(f.id);
      });
      $("foodGrid").append(b);
    });
  }
  document.addEventListener(
    "pointermove",
    (e) => {
      if (!libraryDrag || e.pointerId !== libraryDrag.pointer) return;
      const dx = e.clientX - libraryDrag.x,
        dy = e.clientY - libraryDrag.y;
      if (!libraryDrag.dragging && Math.hypot(dx, dy) > 6) {
        // A vertical touch gesture scrolls the food palette; tap still adds an item.
        if (libraryDrag.touch && Math.abs(dy) > Math.abs(dx) * 1.5) {
          libraryDrag = null;
          return;
        }
        libraryDrag.dragging = true;
        const ghost = $("dragGhost");
        const im = document.createElement("img");
        im.src = `assets/foods/${libraryDrag.id}.png`;
        im.alt = "";
        ghost.replaceChildren(im);
        ghost.hidden = false;
      }
      if (libraryDrag.dragging) {
        e.preventDefault();
        $("dragGhost").style.left = e.clientX + "px";
        $("dragGhost").style.top = e.clientY + "px";
        $("canvasFrame").classList.toggle("drop-active", withinCanvas(e));
      }
    },
    { passive: false },
  );
  function endLibraryDrag(e) {
    if (!libraryDrag || libraryDrag.pointer !== e.pointerId) return;
    const d = libraryDrag;
    libraryDrag = null;
    $("dragGhost").hidden = true;
    $("canvasFrame").classList.remove("drop-active");
    if (d.dragging) {
      const button = document.querySelector(`[data-food="${d.id}"]`);
      button.dataset.ignoreClick = "yes";
      setTimeout(() => delete button.dataset.ignoreClick, 100);
      if (e.type !== "pointercancel" && withinCanvas(e)) {
        const p = point(e);
        addFood(d.id, [p.x / canvas.width, p.y / canvas.height]);
      }
    }
  }
  document.addEventListener("pointerup", endLibraryDrag);
  document.addEventListener("pointercancel", endLibraryDrag);

  // Editing actions and keyboard shortcuts
  function remove() {
    if (!selectedItem()) return;
    checkpoint();
    state().items = state().items.filter((i) => i.uid !== selected);
    selected = null;
    commit();
  }
  function duplicate() {
    const item = selectedItem();
    if (!item || state().items.length >= 150) return;
    checkpoint();
    const copy = {
      ...item,
      uid: uid(),
      x: clamp(item.x + 0.025, 0, 1),
      y: clamp(item.y + 0.025, 0, 1),
    };
    state().items.push(copy);
    selected = copy.uid;
    commit();
  }
  function reorder(direction) {
    const i = state().items.findIndex((i) => i.uid === selected),
      j = i + direction;
    if (i < 0 || j < 0 || j >= state().items.length) return;
    checkpoint();
    [state().items[i], state().items[j]] = [state().items[j], state().items[i]];
    commit();
  }
  function undo() {
    if (!state().undo.length) return;
    state().redo.push(clone(state().items));
    state().items = state().undo.pop();
    selected = null;
    commit();
  }
  function redo() {
    if (!state().redo.length) return;
    state().undo.push(clone(state().items));
    state().items = state().redo.pop();
    selected = null;
    commit();
  }
  for (const id of ["size", "rotation"]) {
    let editing = false;
    $(id).addEventListener("input", () => {
      const i = selectedItem();
      if (!i) return;
      if (!editing) {
        checkpoint();
        editing = true;
      }
      if (id === "size") i.size = Number($(id).value) / 100;
      else i.angle = Number($(id).value);
      draw();
      updateControls();
      save();
    });
    $(id).addEventListener("change", () => {
      editing = false;
      commit();
    });
    $(id).addEventListener("blur", () => (editing = false));
  }
  $("delete").addEventListener("click", remove);
  $("deleteHandle").addEventListener("click", remove);
  $("duplicate").addEventListener("click", duplicate);
  $("forward").addEventListener("click", () => reorder(1));
  $("backward").addEventListener("click", () => reorder(-1));
  $("undo").addEventListener("click", undo);
  $("redo").addEventListener("click", redo);
  $("clear").addEventListener("click", () => {
    if (!state().items.length) return;
    checkpoint();
    state().items = [];
    selected = null;
    commit();
  });
  document
    .querySelectorAll("[data-portrait]")
    .forEach((b) =>
      b.addEventListener("click", () => selectPortrait(b.dataset.portrait)),
    );
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input,textarea,select")) return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      e.shiftKey ? redo() : undo();
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "y") {
      e.preventDefault();
      redo();
      return;
    }
    if (
      (e.metaKey || e.ctrlKey) &&
      e.key.toLowerCase() === "d" &&
      selectedItem()
    ) {
      e.preventDefault();
      duplicate();
      return;
    }
    if (e.key === "Escape") {
      selected = null;
      draw();
      updateControls();
      updateLayers();
      return;
    }
    if (!selectedItem()) return;
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      remove();
      return;
    }
    const dirs = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    if (dirs[e.key]) {
      e.preventDefault();
      if (!e.repeat) checkpoint();
      const i = selectedItem(),
        step = (e.shiftKey ? 10 : 1) * screenUnit();
      i.x = clamp(i.x + (dirs[e.key][0] * step) / canvas.width, 0, 1);
      i.y = clamp(i.y + (dirs[e.key][1] * step) / canvas.height, 0, 1);
      draw();
      updateControls();
      save();
    }
  });

  // Capture JSON and pixels synchronously before the asynchronous save request.
  $("export").addEventListener("click", async () => {
    if (!ready || savingSnapshot) return;
    if (location.protocol === "file:") {
      toast("Open Start FoodFace.command to save JSON + PNG.");
      return;
    }
    savingSnapshot = true;
    $("export").textContent = "Saving…";
    updateControls();
    const status = $("snapshotStatus");
    status.hidden = false;
    status.textContent = "Saving JSON + PNG to this computer…";
    const output = document.createElement("canvas");
    output.width = canvas.width;
    output.height = canvas.height;
    try {
      const scene = {
        schemaVersion: 1,
        assetVersion: "1",
        rendererVersion: "1",
        portraitId: active,
        canvas: { width: canvas.width, height: canvas.height },
        items: clone(state().items),
      };
      drawScene(output.getContext("2d"));
      const png = output.toDataURL("image/png").split(",")[1];
      const response = await fetch("/api/snapshots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scene, png }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Save failed.");
      status.replaceChildren(document.createTextNode(`Saved in ${result.directory} · `));
      for (const [label, path] of [["JSON", result.json], ["PNG", result.png]]) {
        const link = document.createElement("a");
        link.textContent = label;
        link.href = path;
        link.download = path.split("/").pop();
        status.append(link, document.createTextNode(" "));
      }
      toast("JSON + PNG saved");
    } catch (error) {
      status.textContent = `Save failed. ${error.message} If needed, restart Start FoodFace.command and try again.`;
      toast("Save failed. Your browser draft is still available if autosave succeeded.");
    } finally {
      savingSnapshot = false;
      $("export").textContent = "Save JSON + PNG";
      updateControls();
    }
  });

  // Layout and initialization
  new ResizeObserver(() => {
    if (ready) draw();
    const h = $("canvasFrame").getBoundingClientRect().height;
    $("foodGrid").style.maxHeight =
      window.innerWidth <= 560 ? "210px" : Math.max(220, h - 34) + "px";
  }).observe($("canvasFrame"));
  async function init() {
    buildLibrary();
    restore();
    selectPortrait(active);
    try {
      await Promise.all([
        ...foods.map(async (f) => {
          const im = await loadImage(`assets/foods/${f.id}.png`);
          try {
            assets.set(f.id, analyzeImage(im));
          } catch {
            assets.set(f.id, {
              image: im,
              box: { x: 0, y: 0, w: im.naturalWidth, h: im.naturalHeight },
              pixels: null,
              sourceWidth: im.naturalWidth,
            });
          }
        }),
        ...Object.keys(portraits).map(async (id) =>
          assets.set(
            id + "-original",
            await loadImage(`assets/portraits/${id}-original.png`),
          ),
        ),
        loadImage("assets/portraits/zhu-face-fill.png").then((im) =>
          assets.set("zhu-face-fill", im),
        ),
        loadImage("assets/portraits/euro-background.png").then((im) =>
          assets.set("euro-background", im),
        ),
      ]);
      ready = true;
      $("loading").hidden = true;
      document
        .querySelectorAll(".food-card")
        .forEach((b) => (b.disabled = false));
      commit();
      if (location.protocol === "file:")
        toast("Open Start FoodFace.command to save and export your work.");
    } catch (error) {
      $("loading").textContent =
        "Could not load assets. Open Start FoodFace.command and try again.";
      toast(error.message);
      console.error(error);
    }
  }
  init();
})();
