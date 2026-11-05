import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));
const fixtureId = "/__pdf-preview-regression.js";
const mockApiId = "\0pdf-preview-mock-api";
const mockServiceId = "\0pdf-preview-mock-service";
const filename = "系统演示.pdf";

test("attachment PDF opens in-place, renders pages and reports invalid documents", { timeout: 60000 }, async () => {
  const server = await createServer({
    root,
    base: "/",
    configFile: path.join(root, "vite.config.ts"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "pdf-preview-regression",
      enforce: "pre",
      resolveId(id) {
        if (id === fixtureId) return id;
        if (id === "@/api") return mockApiId;
        if (id === "@/serviceApi") return mockServiceId;
      },
      load(id) {
        if (id === fixtureId) return `
          import { createApp, h, ref } from 'vue';
          import '/src/styles.css';
          import AttachmentPanel from '/src/components/AttachmentPanel.vue';
          const error = ref('');
          createApp({ setup: () => () => [
            h(AttachmentPanel, { targetType: 'ticket', targetId: 1, onError: (message) => { error.value = message; } }),
            h('p', { role: 'alert' }, error.value),
          ] }).mount('#app');
        `;
        if (id === mockApiId || id === path.join(root, "src/api.js")) return `
          export async function apiFetchRaw() {
            return { blob: async () => new Blob([new Uint8Array(window.testPdfBytes)], { type: 'application/pdf' }) };
          }
        `;
        if (id === mockServiceId || id === path.join(root, "src/serviceApi.js")) return `
          export const collectionRows = (response) => response.items;
          export const normalizeDatabaseId = (id) => String(id);
          export const serviceApi = { listAttachments: async () => ({ items: [{
            id: 1, category: 'general', originalName: '${filename}', mimeType: 'application/pdf',
            downloadUrl: '/api/after-sales/attachments/1/download', size: 1200,
          }] }) };
        `;
      },
      configureServer(vite) {
        vite.middlewares.use((req, res, next) => {
          if (req.url !== "/__pdf-preview-regression") return next();
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
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const pdfPage = await browser.newPage();
    await pdfPage.setContent('<style>.page { height: 250mm; break-after: page; font-size: 40px; }</style><div class="page">First PDF page</div><div>Second PDF page</div>');
    const pdf = await pdfPage.pdf({ format: "A4", printBackground: true });
    await pdfPage.close();

    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/__pdf-preview-regression`);
    await page.evaluate((bytes) => { window.testPdfBytes = bytes; }, [...pdf]);
    await page.getByRole("button", { name: `预览：${filename}` }).last().waitFor({ timeout: 10000 }).catch(async (reason) => {
      const code = await page.evaluate(async () => (await fetch('/src/components/AttachmentPanel.vue')).text());
      throw new Error(`${reason.message}\npage errors: ${JSON.stringify(errors)}\nservice imports: ${JSON.stringify(code.match(/.*serviceApi.*/g)?.slice(0, 4))}\nbody: ${await page.locator("body").innerText()}`);
    });
    await page.getByRole("button", { name: `预览：${filename}` }).last().click();
    const dialog = page.getByRole("dialog", { name: filename });
    await dialog.waitFor();
    await dialog.getByRole("img", { name: `${filename} 第 1 页` }).waitFor();
    await dialog.getByText("1 / 2").waitFor();
    const renderedPixels = await dialog.locator("canvas").evaluate((canvas) => {
      const { data } = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
      let nonWhite = 0;
      for (let i = 0; i < data.length; i += 4) {
        if (data[i + 3] && (data[i] < 220 || data[i + 1] < 220 || data[i + 2] < 220)) nonWhite += 1;
      }
      return nonWhite;
    });
    assert.ok(renderedPixels > 100, `PDF canvas was blank (${renderedPixels} non-white pixels)`);
    const bounds = await dialog.boundingBox();
    assert.ok(bounds.width < 900 && bounds.height <= 900, JSON.stringify(bounds));
    assert.deepEqual(await dialog.evaluate((element) => ({
      horizontal: element.scrollWidth > element.clientWidth + 1,
      vertical: element.scrollHeight > element.clientHeight + 1,
    })), { horizontal: false, vertical: false });
    await page.setViewportSize({ width: 390, height: 844 });
    await dialog.getByRole("img", { name: `${filename} 第 1 页` }).waitFor();
    const mobileDialog = await dialog.boundingBox();
    const mobileCanvas = await dialog.locator("canvas").boundingBox();
    assert.ok(mobileDialog.x >= 0 && mobileDialog.y >= 0);
    assert.ok(mobileDialog.x + mobileDialog.width <= 391 && mobileDialog.y + mobileDialog.height <= 845);
    assert.ok(mobileCanvas.x >= mobileDialog.x && mobileCanvas.x + mobileCanvas.width <= mobileDialog.x + mobileDialog.width);
    assert.deepEqual(await dialog.evaluate((element) => ({
      horizontal: element.scrollWidth > element.clientWidth + 1,
      vertical: element.scrollHeight > element.clientHeight + 1,
    })), { horizontal: false, vertical: false });
    if (process.env.MJ_PREVIEW_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.MJ_PREVIEW_SCREENSHOT_DIR, "after-sales-preview-pdf-mobile.png") });
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await dialog.getByRole("button", { name: "下一页" }).click();
    await dialog.getByRole("img", { name: `${filename} 第 2 页` }).waitFor();
    await dialog.getByRole("button", { name: "上一页" }).click();
    await dialog.getByRole("img", { name: `${filename} 第 1 页` }).waitFor();
    if (process.env.MJ_PREVIEW_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.MJ_PREVIEW_SCREENSHOT_DIR, "after-sales-preview-pdf.png") });
    }
    await dialog.getByRole("button", { name: "关闭预览" }).click();
    await dialog.waitFor({ state: "hidden" });

    await page.evaluate(() => { window.testPdfBytes = [1, 2, 3]; });
    await page.getByRole("button", { name: `预览：${filename}` }).last().click();
    await dialog.getByRole("alert").waitFor();
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});
