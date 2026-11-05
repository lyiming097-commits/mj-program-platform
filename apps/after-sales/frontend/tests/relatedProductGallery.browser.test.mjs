import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));
const fixtureId = "/__related-product-gallery.js";
const mockDrawer = path.join(root, "src/components/ProjectDetailDrawer.vue");

test("related product gallery switches images and preserves the narrow-screen single image", { timeout: 60000 }, async () => {
  const server = await createServer({
    root,
    base: "/",
    configFile: path.join(root, "vite.config.ts"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "related-product-gallery-test",
      enforce: "pre",
      resolveId(id) { if (id === fixtureId) return id; },
      load(id) {
        if (id === mockDrawer) return '<template><div class="test-drawer"><slot /></div></template>';
        if (id !== fixtureId) return;
        return `
          import { createApp, h } from 'vue';
          import '/src/styles.css';
          import RelatedProductDetailDrawer from '/src/components/RelatedProductDetailDrawer.vue';
          function photo(index) {
            const canvas = document.createElement('canvas');
            canvas.width = 1100; canvas.height = 825;
            const context = canvas.getContext('2d');
            context.fillStyle = '#f8fafc'; context.fillRect(0, 0, canvas.width, canvas.height);
            context.fillStyle = ['#2563eb', '#047857', '#b45309', '#be185d', '#475569', '#0891b2'][index % 6];
            context.fillRect(170, 120, 760, 585);
            context.fillStyle = '#fff'; context.font = 'bold 180px sans-serif';
            context.fillText(String(index + 1), 480, 475);
            return canvas.toDataURL('image/png');
          }
          const sources = Array.from({ length: 17 }, (_, index) => photo(index));
          const product = {
            productId: 901, name: '多功能电子讲台', productPreview: sources[0],
            productImages: sources.map((source, index) => ({ slot: 'detail-' + index, thumbnail: source, preview: source })),
            parameterRows: [], manuals: [],
          };
          createApp({ setup: () => () => h(RelatedProductDetailDrawer, { open: true, product }) }).mount('#app');
        `;
      },
      configureServer(vite) {
        vite.middlewares.use((req, res, next) => {
          if (req.url !== "/__related-product-gallery") return next();
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
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/__related-product-gallery`);
    const gallery = page.getByRole("region", { name: "多功能电子讲台产品图片" });
    await gallery.getByRole("button", { name: "显示第1张图片" }).waitFor();
    assert.equal(await gallery.getByRole("button", { name: "显示第1张图片" }).getAttribute("aria-pressed"), "true");
    await gallery.getByRole("button", { name: "下一张图片" }).click();
    assert.equal(await gallery.getByRole("button", { name: "显示第2张图片" }).getAttribute("aria-pressed"), "true");
    await gallery.getByRole("button", { name: /显示第5张图片，其余13张/ }).click();
    await gallery.getByRole("img", { name: "多功能电子讲台第5张图片" }).waitFor();
    await gallery.getByRole("button", { name: "下一张图片" }).click();
    await gallery.getByRole("img", { name: "多功能电子讲台第6张图片" }).waitFor();
    const mainBounds = await gallery.locator(".as-product-gallery-main").boundingBox();
    const imageBounds = await gallery.getByRole("img", { name: "多功能电子讲台第6张图片" }).boundingBox();
    assert.ok(imageBounds.x >= mainBounds.x && imageBounds.y >= mainBounds.y);
    assert.ok(imageBounds.x + imageBounds.width <= mainBounds.x + mainBounds.width + 1);
    assert.ok(imageBounds.y + imageBounds.height <= mainBounds.y + mainBounds.height + 1);
    await gallery.getByRole("button", { name: "查看多功能电子讲台第6张大图" }).click();
    const dialog = page.getByRole("dialog", { name: "多功能电子讲台图片预览" });
    await dialog.waitFor();
    assert.equal(await dialog.locator(".as-image-preview-count").innerText(), "6 / 17");
    assert.equal(await dialog.locator(".as-image-preview-strip").evaluate((element) => element.scrollWidth > element.clientWidth), true);
    await dialog.getByRole("button", { name: "查看第17张图片" }).click();
    assert.equal(await dialog.locator(".as-image-preview-count").innerText(), "17 / 17");
    await dialog.getByRole("button", { name: "下一张图片" }).click();
    assert.equal(await dialog.locator(".as-image-preview-count").innerText(), "1 / 17");
    await dialog.getByRole("button", { name: "查看第3张图片" }).click();
    assert.equal(await dialog.locator(".as-image-preview-count").innerText(), "3 / 17");
    assert.equal(await dialog.getByRole("button", { name: "查看第3张图片" }).getAttribute("aria-current"), "true");
    await page.keyboard.press("ArrowRight");
    assert.equal(await dialog.locator(".as-image-preview-count").innerText(), "4 / 17");
    const previewBounds = await dialog.boundingBox();
    assert.ok(previewBounds.x >= 0 && previewBounds.y >= 0 && previewBounds.x + previewBounds.width <= 1441 && previewBounds.y + previewBounds.height <= 961);
    assert.equal(await dialog.evaluate((element) => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1), false);
    await page.setViewportSize({ width: 1024, height: 768 });
    const mediumBounds = await dialog.boundingBox();
    assert.ok(mediumBounds.x >= 0 && mediumBounds.y >= 0 && mediumBounds.x + mediumBounds.width <= 1025 && mediumBounds.y + mediumBounds.height <= 769);
    assert.equal(await dialog.evaluate((element) => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1), false);
    await page.setViewportSize({ width: 1440, height: 960 });
    if (process.env.MJ_PREVIEW_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.MJ_PREVIEW_SCREENSHOT_DIR, "after-sales-product-gallery-preview.png") });
    }
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "hidden" });
    assert.equal(await gallery.getByRole("button", { name: "查看多功能电子讲台第6张大图" }).evaluate((element) => element === document.activeElement), true);
    if (process.env.MJ_PREVIEW_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.MJ_PREVIEW_SCREENSHOT_DIR, "after-sales-product-gallery-desktop.png") });
    }

    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await gallery.isVisible(), false);
    const singleImage = page.locator(".product-gallery-mobile");
    assert.equal(await singleImage.isVisible(), true);
    assert.equal(await singleImage.getByRole("img", { name: "多功能电子讲台" }).count(), 1);
    assert.ok((await page.locator(".product-archive-content").boundingBox()).width <= 390);
    if (process.env.MJ_PREVIEW_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.MJ_PREVIEW_SCREENSHOT_DIR, "after-sales-product-gallery-mobile.png") });
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});
