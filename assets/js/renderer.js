"use strict";
// Shared version-1 renderer. Keep pixels identical for human and agent scenes.
(() => {
  const { foods, portraits } = window.FOODFACE_CATALOG;
  const paths = Object.fromEntries(
    Object.entries(window.FOODFACE_PATHS).map(([id, p]) => [
      id,
      { face: new Path2D(p.face), hat: new Path2D(p.hat) },
    ]),
  );
  const assets = new Map();
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
  function dimensions(item, width) {
    const { box } = assets.get(item.id);
    const longest = item.size * width;
    return {
      w: (longest * box.w) / Math.max(box.w, box.h),
      h: (longest * box.h) / Math.max(box.w, box.h),
    };
  }
  function imageToCanvas(g, item, width, height) {
    const a = assets.get(item.id);
    if (!a) return;
    const { w, h } = dimensions(item, width);
    g.save();
    g.translate(item.x * width, item.y * height);
    g.rotate((item.angle * Math.PI) / 180);
    // Reflect around the food's center in its own axes before rotation.
    if (item.flipX || item.flipY) g.scale(item.flipX ? -1 : 1, item.flipY ? -1 : 1);
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
  function drawScene(g, active, items) {
    const { w: width, h: height } = portraits[active];
    g.clearRect(0, 0, width, height);
    // Original pixels preserve all backdrop, clothing, color and registration.
    const original = assets.get(active + "-original");
    g.drawImage(original, 0, 0, width, height);
    // Use generated inpainting only inside the removed face, never on garments.
    g.save();
    g.clip(paths[active].face);
    if (active === "euro") g.filter = "saturate(0.25) brightness(0.8)";
    g.drawImage(
      assets.get(active === "euro" ? "euro-background" : active + "-face-fill"),
      0,
      0,
      width,
      height,
    );
    g.restore();
    for (const item of items) imageToCanvas(g, item, width, height);
    // Only the original hat is in front; food may cover the collar and clothing.
    g.save();
    g.clip(paths[active].hat);
    g.drawImage(original, 0, 0, width, height);
    g.restore();
  }
  async function loadAssets() {
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
  }
  window.FOODFACE_RENDERER = {
    assets, dimensions, drawScene, ready: loadAssets(),
  };
})();
