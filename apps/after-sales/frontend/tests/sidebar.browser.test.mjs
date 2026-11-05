import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools(process.env.PLAYWRIGHT_MODULE || "playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));

test("the after-sales sidebar remains available inside the portal frame", { timeout: 60000 }, async () => {
  const server = await createServer({
    root,
    configFile: path.join(root, "vite.config.ts"),
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  await server.listen();
  const base = `http://127.0.0.1:${server.httpServer.address().port}/`;
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addInitScript(() => {
      sessionStorage.setItem("mj_program_login_session", JSON.stringify({
        sessionId: "sidebar-test", userId: "employee", name: "测试人员", loginType: "scan",
      }));
    });
    await context.route("**/api/**", (route) => {
      const url = new URL(route.request().url());
      const body = url.pathname === "/api/auth/session/validate"
        ? { sessionId: "sidebar-test", userId: "employee", name: "测试人员", loginType: "scan" }
        : url.pathname === "/api/after-sales/session/"
          ? { canManageApp: true, canManageSettings: true, appPermission: "admin" }
          : { items: [], projects: [], tasks: [], alerts: [] };
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    await context.route(`${base}sidebar-fixture`, (route) => route.fulfill({
      contentType: "text/html; charset=utf-8",
      body: `<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0"><iframe title="迈杰服务应用" src="${base}after-sales/" data-portal-embed="true" style="display:block;border:0;width:100%;height:850px"></iframe></body></html>`,
    }));
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`${base}sidebar-fixture`);
    await page.locator('iframe[title="迈杰服务应用"]').waitFor();
    const frame = page.frames().find((item) => item.url().endsWith("/after-sales/"));
    assert.ok(frame, "the after-sales frame must load");
    const nav = frame.getByRole("navigation", { name: "主导航" });
    const presales = nav.getByRole("button", { name: "售前服务" });
    try {
      await presales.waitFor();
    } catch (reason) {
      throw new Error(`Sidebar did not load: ${JSON.stringify({ body: await frame.locator("body").innerText().catch(() => "unavailable"), errors })}`, { cause: reason });
    }
    assert.equal(await nav.isVisible(), true);
    assert.equal((await frame.locator(".as-main").boundingBox()).x, 0);
    assert.equal((await frame.locator(".platform-sidebar.is-fixed").boundingBox()).width, 216);
    await presales.click();
    assert.match(await presales.getAttribute("class"), /active/);
    assert.equal(await presales.evaluate(() => location.pathname), "/after-sales/presales/");

    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await frame.locator(".as-app > .platform-sidebar").isVisible(), false);
    await context.close();
  } finally {
    await browser?.close();
    await server.close();
  }
});
