import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));
const fixtureId = "/__image-preview-regression.js";
const fileName = "tmp_c5b7e70ead95edcfdbbb10a0f63e44dd_very_long_uploaded_image_filename.png";
const fixture = `
import { createApp, h, ref } from 'vue';
import '/src/styles.css';
import ImagePreviewDialog from '/src/components/ImagePreviewDialog.vue';
const open = ref(true);
const src = ref('');
const title = ref('${fileName}');
window.setPreviewImage = (value) => { src.value = value; open.value = true; };
createApp({ setup: () => () => h(ImagePreviewDialog, {
  open: open.value, src: src.value, title: title.value,
  onClose: () => { open.value = false; },
}) }).mount('#app');
`;

test("attachment image preview fits the original ratio within the viewport", { timeout: 60000 }, async () => {
  const server = await createServer({
    root,
    base: "/",
    configFile: path.join(root, "vite.config.ts"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "image-preview-regression",
      resolveId(id) { if (id === fixtureId) return id; },
      load(id) { if (id === fixtureId) return fixture; },
      configureServer(vite) {
        vite.middlewares.use((req, res, next) => {
          if (req.url !== "/__image-preview-regression") return next();
          res.setHeader("Content-Type", "text/html; charset=utf-8");
          res.end(`<div id="app"></div><script type="module" src="${fixtureId}"></script>`);
        });
      },
    }],
  });
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/__image-preview-regression`);

    for (const sample of [
      { name: "portrait", viewport: { width: 1580, height: 890 }, image: { width: 700, height: 1540 } },
      { name: "landscape", viewport: { width: 1280, height: 800 }, image: { width: 1800, height: 500 } },
      { name: "mobile", viewport: { width: 390, height: 844 }, image: { width: 700, height: 1540 } },
    ]) {
      await page.setViewportSize(sample.viewport);
      await page.evaluate(({ width, height }) => {
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        context.fillStyle = "#f8fafc";
        context.fillRect(0, 0, width, height);
        context.fillStyle = "#2563eb";
        context.fillRect(0, 0, width, height / 5);
        window.setPreviewImage(canvas.toDataURL("image/png"));
      }, sample.image);
      const dialog = page.getByRole("dialog", { name: fileName });
      const image = dialog.getByRole("img", { name: fileName });
      await image.evaluate((element) => new Promise((resolve) => {
        if (element.complete && element.naturalWidth) resolve();
        else element.addEventListener("load", resolve, { once: true });
      }));
      const bounds = await dialog.boundingBox();
      const imageBounds = await image.boundingBox();
      const stageBounds = await dialog.locator(".as-image-preview-stage").boundingBox();
      assert.ok(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= sample.viewport.width + 1);
      assert.ok(bounds.y + bounds.height <= sample.viewport.height + 1);
      assert.ok(imageBounds.x >= stageBounds.x - 1 && imageBounds.y >= stageBounds.y - 1);
      assert.ok(imageBounds.x + imageBounds.width <= stageBounds.x + stageBounds.width + 1);
      assert.ok(imageBounds.y + imageBounds.height <= stageBounds.y + stageBounds.height + 1,
        JSON.stringify({ name: sample.name, dialog: bounds, stage: stageBounds, image: imageBounds }));
      assert.deepEqual(await dialog.evaluate((element) => ({
        horizontal: element.scrollWidth > element.clientWidth + 1,
        vertical: element.scrollHeight > element.clientHeight + 1,
      })), { horizontal: false, vertical: false });
      if (sample.name !== "mobile") {
        assert.ok(Math.abs(imageBounds.width / imageBounds.height - sample.image.width / sample.image.height) < 0.01);
        assert.ok(bounds.width <= imageBounds.width + 40, `${sample.name} dialog leaves excess width`);
      }
      if (process.env.MJ_PREVIEW_SCREENSHOT_DIR) {
        await page.screenshot({ path: path.join(process.env.MJ_PREVIEW_SCREENSHOT_DIR, `after-sales-preview-${sample.name}.png`) });
      }
    }
    assert.deepEqual(errors, []);
    await page.getByRole("button", { name: "关闭大图" }).click();
    await page.getByRole("dialog", { name: fileName }).waitFor({ state: "hidden" });
  } finally {
    await browser?.close();
    await server.close();
  }
});
