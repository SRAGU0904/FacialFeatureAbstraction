"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const canvas = $("collage"),
    ctx = canvas.getContext("2d");
  const { foods, portraits } = window.FOODFACE_CATALOG;
  const i18n = window.FOODFACE_I18N;
  const mobileLayout = window.matchMedia("(max-width: 560px)");
  const t = (key, values) => i18n.t(key, values);
  const foodName = (id) => t("food." + id);
  const portraitName = (id) => t("portrait." + id);
  const foodById = Object.fromEntries(foods.map((f) => [f.id, f]));
  const renderer = window.FOODFACE_RENDERER,
    assets = renderer.assets,
    states = {
      zhu: { items: [], undo: [], redo: [], submitted: false, result: null },
      euro: { items: [], undo: [], redo: [], submitted: false, result: null },
    };
  let active = "zhu",
    selected = null,
    ready = false,
    gesture = null,
    libraryDrag = null,
    toastTimer;
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const state = () => states[active];
  const selectedItem = () => state().items.find((i) => i.uid === selected);
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
  const normalizeAngle = (n) => ((((n + 180) % 360) + 360) % 360) - 180;
  const uid = () =>
    globalThis.crypto?.randomUUID?.() ||
    "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = Math.floor(Math.random() * 16);
      return (c === "x" ? r : (r & 3) | 8).toString(16);
    });

  // Feedback
  function toast(message) {
    $("toast").textContent = message;
    $("toast").classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $("toast").classList.remove("visible"), 2400);
  }
  // Every page load starts an independent anonymous session. No draft restoration.
  const sessionId = uid();
  const editable = () => ready && !state().submitted;
  function updateProgress() {
    const count = Object.values(states).filter((s) => s.submitted).length;
    $("experimentProgress").textContent =
      count === 2 ? t("completed") : t("progress", { count });
    $("saveStatus").textContent = state().submitted
      ? t("submittedStatus")
      : t("draftStatus");
    document.querySelectorAll("[data-portrait]").forEach((b) => {
      b.querySelector("span").textContent =
        portraitName(b.dataset.portrait) +
        (states[b.dataset.portrait].submitted ? " ✓" : "");
    });
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
    updateProgress();
    updateSubmission();
  }

  // Asset loading and canvas rendering
  function dimensions(item) {
    return renderer.dimensions(item, canvas.width);
  }
  function drawScene(g) {
    if (ready) renderer.drawScene(g, active, state().items);
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
  function updateSelectionHandles(item) {
    for (const id of [
      "deleteHandle",
      "flipHorizontalHandle",
      "flipVerticalHandle",
    ]) {
      $(id).hidden = !item || !editable();
    }
  }
  function positionHandle(id, item, x, y, u) {
    const angle = (item.angle * Math.PI) / 180;
    const px =
      item.x * canvas.width + x * Math.cos(angle) - y * Math.sin(angle);
    const py =
      item.y * canvas.height + x * Math.sin(angle) + y * Math.cos(angle);
    $(id).style.left =
      (clamp(px, 14 * u, canvas.width - 14 * u) / canvas.width) * 100 + "%";
    $(id).style.top =
      (clamp(py, 14 * u, canvas.height - 14 * u) / canvas.height) * 100 + "%";
  }
  function draw() {
    if (!ready) return;
    drawScene(ctx);
    const item = selectedItem();
    updateSelectionHandles(item);
    if (item) {
      const { w, h, u } = selectionGeometry(item);
      positionHandle("deleteHandle", item, w / 2, -h / 2, u);
      positionHandle("flipHorizontalHandle", item, -w / 2, -h / 2, u);
      positionHandle("flipVerticalHandle", item, -w / 2, h / 2, u);
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
    $("objectCount").textContent = t(
      state().items.length === 1 ? "itemOne" : "itemMany",
      { count: state().items.length },
    );
  }

  // Selection and portrait controls
  function updateControls() {
    const i = selectedItem();
    $("transformControls").disabled = !i || !editable();
    $("selectedName").textContent = i ? foodName(i.id) : t("noSelection");
    $("flipHorizontal").setAttribute("aria-pressed", String(!!i?.flipX));
    $("flipHorizontalHandle").setAttribute("aria-pressed", String(!!i?.flipX));
    $("flipVertical").setAttribute("aria-pressed", String(!!i?.flipY));
    $("flipVerticalHandle").setAttribute("aria-pressed", String(!!i?.flipY));
    if (i) {
      $("size").value = i.size * 100;
      $("sizeValue").textContent = `${Math.round(i.size * 100)}%`;
      $("rotation").value = Math.round(i.angle);
      $("rotationValue").textContent = `${Math.round(i.angle)}°`;
    }
    $("undo").disabled = !editable() || !state().undo.length;
    $("redo").disabled = !editable() || !state().redo.length;
    $("clear").disabled = !editable() || !state().items.length;
    $("export").disabled = !editable();
    $("export").textContent = state().submitted ? t("submitted") : t("submit");
    document
      .querySelectorAll(".food-card")
      .forEach((b) => (b.disabled = !editable()));
    updateSelectionHandles(i);
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
      b.textContent = `${foodName(i.id)} ${index + 1}`;
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
    if (!editable()) return;
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
      flipX: false,
      flipY: false,
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
    $("original").alt = t("originalAlt", { name: portraitName(active) });
    $("portraitName").textContent =
      portraitName(active) + (p.artist ? ` · ${t("artist." + active)}` : "");
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
      // Invert the image reflection after undoing its rotation.
      sx = Math.min(
        a.box.x + a.box.w - 1,
        Math.floor(a.box.x + ((item.flipX ? -q.x : q.x) / w + 0.5) * a.box.w),
      ),
      sy = Math.min(
        a.box.y + a.box.h - 1,
        Math.floor(a.box.y + ((item.flipY ? -q.y : q.y) / h + 0.5) * a.box.h),
      );
    return !a.pixels || a.pixels[(sy * a.sourceWidth + sx) * 4 + 3] > 35;
  }
  canvas.addEventListener("pointerdown", (e) => {
    if (!editable() || e.button !== 0) return;
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
    if (!editable()) return;
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
      b.setAttribute("aria-label", t("addFood", { name: foodName(f.id) }));
      b.disabled = true;
      const im = document.createElement("img");
      im.src = `assets/foods/${f.id}.png`;
      im.alt = "";
      im.draggable = false;
      const label = document.createElement("span");
      label.textContent = foodName(f.id);
      b.append(im, label);
      b.addEventListener("pointerdown", (e) => {
        // On narrow screens, native scrolling browses foods; a click adds one.
        if (mobileLayout.matches || e.button !== 0 || !editable()) return;
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
    if (!editable()) return;
    if (!selectedItem()) return;
    checkpoint();
    state().items = state().items.filter((i) => i.uid !== selected);
    selected = null;
    commit();
  }
  function duplicate() {
    if (!editable()) return;
    const item = selectedItem();
    if (!item) return;
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
  function flip(axis) {
    if (!editable()) return;
    const item = selectedItem();
    if (!item) return;
    checkpoint();
    item[axis] = !item[axis];
    commit();
  }
  function reorder(direction) {
    if (!editable()) return;
    const i = state().items.findIndex((i) => i.uid === selected),
      j = i + direction;
    if (i < 0 || j < 0 || j >= state().items.length) return;
    checkpoint();
    [state().items[i], state().items[j]] = [state().items[j], state().items[i]];
    commit();
  }
  function undo() {
    if (!editable()) return;
    if (!state().undo.length) return;
    state().redo.push(clone(state().items));
    state().items = state().undo.pop();
    selected = null;
    commit();
  }
  function redo() {
    if (!editable()) return;
    if (!state().redo.length) return;
    state().undo.push(clone(state().items));
    state().items = state().redo.pop();
    selected = null;
    commit();
  }
  for (const id of ["size", "rotation"]) {
    let editing = false;
    $(id).addEventListener("input", () => {
      if (!editable()) return;
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
  $("flipHorizontal").addEventListener("click", () => flip("flipX"));
  $("flipHorizontalHandle").addEventListener("click", () => flip("flipX"));
  $("flipVertical").addEventListener("click", () => flip("flipY"));
  $("flipVerticalHandle").addEventListener("click", () => flip("flipY"));
  $("forward").addEventListener("click", () => reorder(1));
  $("backward").addEventListener("click", () => reorder(-1));
  $("undo").addEventListener("click", undo);
  $("redo").addEventListener("click", redo);
  $("clear").addEventListener("click", () => {
    if (!editable()) return;
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
    if (!editable()) return;
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
    }
  });

  // Results stay in this page until the participant copies and shares them.
  function updateSubmission() {
    const result = state().result;
    $("jsonResult").hidden = !result;
    $("resultJson").value = result || "";
    $("copyStatus").textContent = "";
  }
  function readParticipant() {
    // The shared form retains its values; read current edits for each submission.
    $("nationality").value = $("nationality").value.trim();
    for (const id of ["gender", "age", "nationality"]) {
      const field = $(id);
      field.setCustomValidity("");
      if (!field.validity.valid) field.setCustomValidity(t(id + "Required"));
    }
    if (!$("participantForm").reportValidity()) return null;
    return {
      gender: $("gender").value,
      age: Number($("age").value),
      nationality: $("nationality").value,
      feedback: $("feedback").value.trim(),
    };
  }
  for (const id of ["gender", "age", "nationality"]) {
    $(id).addEventListener("input", () => $(id).setCustomValidity(""));
  }
  $("participantForm").addEventListener("submit", (event) =>
    event.preventDefault(),
  );
  $("export").addEventListener("click", () => {
    if (editable() && readParticipant()) $("submitDialog").showModal();
  });
  $("cancelSubmission").addEventListener("click", () =>
    $("submitDialog").close(),
  );
  $("confirmSubmission").addEventListener("click", () => {
    $("submitDialog").close();
    submitPortrait();
  });
  function submitPortrait() {
    if (!editable()) return;
    const details = readParticipant();
    if (!details) return;
    const result = {
      schemaVersion: 1,
      assetVersion: "1",
      rendererVersion: "1",
      portraitId: active,
      canvas: { width: canvas.width, height: canvas.height },
      items: clone(state().items),
      demographics: {
        gender: details.gender,
        age: details.age,
        nationality: details.nationality,
      },
      feedback: details.feedback,
      experiment: {
        actorType: "human",
        sessionId,
        trialId: uid(),
        status: "submitted",
        submittedAt: new Date().toISOString(),
        interfaceLanguage: i18n.language,
      },
      researchNotice: i18n.t("notice", {}, "en"),
    };
    // Scene fields are identical to agent snapshots; metadata does not affect pixels.
    state().result = JSON.stringify(result, null, 2);
    state().submitted = true;
    state().undo = [];
    state().redo = [];
    selected = null;
    gesture = null;
    libraryDrag = null;
    $("dragGhost").hidden = true;
    $("canvasFrame").classList.remove("drop-active");
    commit();
    $("jsonResult").scrollIntoView({ block: "nearest" });
    toast(t("jsonReady"));
  }
  $("copyJson").addEventListener("click", async () => {
    const result = state().result;
    if (!result) return;
    const portrait = active;
    try {
      await navigator.clipboard.writeText(result);
      if (active === portrait) $("copyStatus").textContent = t("copied");
    } catch {
      // Clipboard permissions vary; keep the complete JSON available for manual copying.
      if (active !== portrait) return;
      $("resultJson").focus();
      $("resultJson").select();
      let copied = false;
      try {
        copied = document.execCommand("copy");
      } catch {
        /* Use manual copy below. */
      }
      $("copyStatus").textContent = copied ? t("copied") : t("manualCopy");
    }
  });

  function changeLanguage(language) {
    i18n.apply(language);
    $("toast").classList.remove("visible");
    for (const id of ["gender", "age", "nationality"])
      $(id).setCustomValidity("");
    $("original").alt = t("originalAlt", { name: portraitName(active) });
    $("portraitName").textContent =
      portraitName(active) +
      (portraits[active].artist ? ` · ${t("artist." + active)}` : "");
    document.querySelectorAll("[data-food]").forEach((button) => {
      const name = foodName(button.dataset.food);
      button.querySelector("span").textContent = name;
      button.setAttribute("aria-label", t("addFood", { name }));
    });
    commit();
  }
  document.querySelectorAll("[data-language]").forEach((button) => {
    button.addEventListener("click", () =>
      changeLanguage(button.dataset.language),
    );
  });

  // Layout and initialization
  const library = document.querySelector(".library");
  function updateLibraryLayout() {
    if (libraryDrag)
      endLibraryDrag({ pointerId: libraryDrag.pointer, type: "pointercancel" });
    if (mobileLayout.matches)
      document.querySelector(".canvas-actions").after(library);
    else document.querySelector(".studio").append(library);
    updateLibraryHeight();
  }
  function updateLibraryHeight() {
    const h = $("canvasFrame").getBoundingClientRect().height;
    $("foodGrid").style.maxHeight =
      mobileLayout.matches ? "none" : Math.max(220, h - 34) + "px";
  }
  mobileLayout.addEventListener("change", updateLibraryLayout);
  updateLibraryLayout();
  new ResizeObserver(() => {
    if (ready) draw();
    updateLibraryHeight();
  }).observe($("canvasFrame"));
  async function init() {
    i18n.apply("en");
    buildLibrary();
    selectPortrait(active);
    try {
      await renderer.ready;
      ready = true;
      $("loading").hidden = true;
      document
        .querySelectorAll(".food-card")
        .forEach((b) => (b.disabled = false));
      commit();
    } catch (error) {
      $("loading").textContent = t("loadError");
      toast(t("loadError"));
      console.error(error);
    }
  }
  init();
})();
