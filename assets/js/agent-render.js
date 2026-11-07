"use strict";
(() => {
  const renderer = window.FOODFACE_RENDERER;
  const { foods, portraits } = window.FOODFACE_CATALOG;

  function canvas(width, height) {
    const c = document.createElement("canvas");
    c.width = width;
    c.height = height;
    return c;
  }

  function encode(source, maxEdge = null) {
    const scale = maxEdge ? Math.min(1, maxEdge / Math.max(source.width, source.height)) : 1;
    if (scale === 1) {
      return { png: source.toDataURL("image/png").split(",")[1], width: source.width, height: source.height };
    }
    const c = canvas(Math.round(source.width * scale), Math.round(source.height * scale));
    c.getContext("2d").drawImage(source, 0, 0, c.width, c.height);
    return { png: c.toDataURL("image/png").split(",")[1], width: c.width, height: c.height };
  }

  async function render({ scene, maxEdge = 1024 }) {
    await renderer.ready;
    const p = portraits[scene.portraitId];
    // Match the studio export's fresh, detached full-resolution canvas.
    const c = canvas(p.w, p.h);
    renderer.drawScene(c.getContext("2d"), scene.portraitId, scene.items);
    const preview = document.getElementById("result");
    preview.width = p.w;
    preview.height = p.h;
    preview.getContext("2d").drawImage(c, 0, 0);
    return { full: encode(c), feedback: encode(c, maxEdge) };
  }

  async function inputs({ portraitId, maxEdge = 1024 }) {
    await renderer.ready;
    const p = portraits[portraitId];
    const original = canvas(p.w, p.h);
    original.getContext("2d").drawImage(renderer.assets.get(portraitId + "-original"), 0, 0);
    const empty = canvas(p.w, p.h);
    renderer.drawScene(empty.getContext("2d"), portraitId, []);
    // A geometric reference only, not a face landmark detector or placement restriction.
    const mask = canvas(p.w, p.h);
    const maskContext = mask.getContext("2d");
    maskContext.fill(new Path2D(window.FOODFACE_PATHS[portraitId].face));
    const pixels = maskContext.getImageData(0, 0, p.w, p.h).data;
    let left = p.w, top = p.h, right = 0, bottom = 0;
    for (let y = 0; y < p.h; y++) {
      for (let x = 0; x < p.w; x++) {
        if (pixels[(y * p.w + x) * 4 + 3] > 0) {
          left = Math.min(left, x); top = Math.min(top, y);
          right = Math.max(right, x + 1); bottom = Math.max(bottom, y + 1);
        }
      }
    }
    const faceBounds = Object.fromEntries(Object.entries({
      left: left / p.w, top: top / p.h, right: right / p.w, bottom: bottom / p.h,
    }).map(([key, value]) => [key, Number(value.toFixed(4))]));
    // Each tile keeps the exact source orientation and aspect ratio used by the renderer.
    const sheet = canvas(1024, Math.ceil(foods.length / 4) * 256);
    const g = sheet.getContext("2d");
    g.fillStyle = "#f5f3ec";
    g.fillRect(0, 0, sheet.width, sheet.height);
    const catalog = foods.map((food, index) => {
      const { image, box } = renderer.assets.get(food.id);
      const x = (index % 4) * 256, y = Math.floor(index / 4) * 256;
      const scale = Math.min(216 / box.w, 192 / box.h);
      const w = box.w * scale, h = box.h * scale;
      g.drawImage(image, box.x, box.y, box.w, box.h, x + (256 - w) / 2, y + 8 + (192 - h) / 2, w, h);
      g.fillStyle = "#1b291d";
      g.textAlign = "center";
      g.font = "bold 17px sans-serif";
      g.fillText(food.id, x + 128, y + 220);
      g.font = "14px sans-serif";
      g.fillText(`${box.w} × ${box.h} px`, x + 128, y + 242);
      return {
        id: food.id,
        source: `assets/foods/${food.id}.png`,
        sourceWidth: image.naturalWidth,
        sourceHeight: image.naturalHeight,
        crop: box,
      };
    });
    return {
      canvas: { width: p.w, height: p.h },
      faceBounds,
      original: encode(original, maxEdge),
      empty: encode(empty, maxEdge),
      foods: encode(sheet),
      catalog,
    };
  }

  window.FOODFACE_AGENT = { render, inputs };
})();
