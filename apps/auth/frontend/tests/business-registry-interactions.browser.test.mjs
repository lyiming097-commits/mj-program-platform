import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));
const artifacts = fileURLToPath(new URL("../../../../.codex-artifacts/business-registry/", import.meta.url));
const api = "/api/org/business-registry";
const session = { sessionId: "registry-audit-session", userId: "registry-audit-admin", name: "测试管理员",
  canUseSystemAdmin: true, isFullAccessUser: true, canConfigurePermissions: true, canManagePlatformSettings: true };

test("enterprise field interaction edge cases", async (t) => {
  const server = await createServer({ root, server: { host: "127.0.0.1", port: 0, strictPort: false } });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  await mkdir(artifacts, { recursive: true });
  async function setup({ holdSearch = false, longNames = false } = {}) {
    const context = await browser.newContext({ viewport: { width: 1024, height: 768 }, locale: "zh-CN" });
    const page = await context.newPage();
    page.setDefaultTimeout(8000);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await context.addInitScript((value) => sessionStorage.setItem("mj_program_login_session", JSON.stringify(value)), session);
    const posts = [];
    let release;
    const gate = holdSearch ? new Promise((resolve) => { release = resolve; }) : Promise.resolve();
    await context.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let body = path === "/api/auth/session/validate" ? session : { items: [], orgRevision: 1 };
      if ([`${api}/companies`, `${api}/queries`].includes(path)) body = { configured: true, items: [], total: 0 };
      if (path === `${api}/search`) {
        const request = route.request().postDataJSON();
        posts.push(request);
        if (request.keyword === "延迟查询") await gate;
        const companies = Array.from({ length: 20 }, (_, index) => {
          const number = (request.pageNum - 1) * 20 + index + 1;
          return { companyName: `测试企业 ${number}${longNames ? "（长名称用于测试气泡换行和字段滚动）".repeat(4) : ""}`,
            creditNo: `AUDIT${String(number).padStart(13, "0")}`, companyCode: "", legalPerson: "测试法人", establishDate: "20260101" };
        });
        body = { ...request, id: posts.length, status: "succeeded", companies, resultCount: 20, totalRecords: 60 };
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/auth/settings/business-registry`);
    await page.getByRole("button", { name: "查询企业", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "企业工商查询", exact: true });
    const single = drawer.getByRole("region", { name: "单选企业", exact: true });
    const multi = drawer.getByRole("region", { name: "多选企业", exact: true });
    const singleInput = single.getByRole("combobox");
    const multiInput = multi.getByRole("combobox");
    const singleResults = page.getByRole("listbox", { name: "查询结果，单选企业", exact: true });
    const multiResults = page.getByRole("listbox", { name: "查询结果，多选企业", exact: true });
    const singleRegion = page.getByRole("region", { name: "企业查询结果", exact: true });
    const multiRegion = page.getByRole("region", { name: "多选企业查询结果", exact: true });
    return { context, page, errors, posts, release, drawer, single, multi, singleInput, multiInput, singleResults, multiResults, singleRegion, multiRegion };
  }
  try {
    await t.test("a delayed result does not steal focus from the other field", async () => {
      const f = await setup({ holdSearch: true });
      try {
        await f.singleInput.fill("延迟查询");
        await f.singleInput.press("Enter");
        await f.single.getByRole("button", { name: "查询中…", exact: true }).waitFor();
        await f.multiInput.fill("正在输入第二家企业");
        f.release();
        await f.single.getByRole("button", { name: "查询中…", exact: true }).waitFor({ state: "hidden" });
        assert.equal(await f.multiInput.evaluate((element) => element === document.activeElement), true, "a completed background query must not move the typing cursor");
        assert.equal(await f.singleResults.isVisible(), false);
        await f.singleInput.click();
        await f.singleResults.waitFor();
        assert.equal(f.posts.length, 1);
        assert.deepEqual(f.errors, []);
      } finally { f.release(); await f.context.close(); }
    });

    await t.test("many long enterprise chips leave usable results next to the trailing input", async () => {
      const f = await setup({ longNames: true });
      try {
        await f.page.setViewportSize({ width: 800, height: 600 });
        await f.multiInput.fill("长名称");
        await f.multiInput.press("Enter");
        for (let index = 0; index < 14; index++) {
          if (index) await f.multiInput.click();
          await f.multiResults.getByRole("option").nth(index).click();
          await f.multiResults.waitFor({ state: "hidden" });
        }
        await f.multiInput.click();
        const bounds = await f.multiRegion.boundingBox();
        await f.page.screenshot({ path: `${artifacts}/many-chips-results-800.png` });
        assert.ok(bounds && bounds.height >= 100 && bounds.y >= 0 && bounds.y + bounds.height <= 600, "the results remain visible after the chip container grows beyond the drawer height");
        assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        assert.deepEqual(f.errors, []);
      } finally { await f.context.close(); }
    });

    await t.test("Escape from the pagination action closes results before the drawer", async () => {
      const f = await setup();
      try {
        await f.singleInput.fill("键盘分页");
        await f.singleInput.press("Enter");
        const more = f.singleRegion.getByRole("button", { name: "加载更多", exact: true });
        await f.singleResults.waitFor();
        await f.singleInput.press("Tab");
        await f.page.keyboard.press("Tab");
        assert.equal(await more.evaluate((element) => element === document.activeElement), true, "the pagination action is reachable by keyboard");
        await f.page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        assert.equal(f.posts.length, 1, "focusing the pagination action must not buy a page before activation");
        await more.press("Escape");
        await f.singleResults.waitFor({ state: "hidden" });
        assert.equal(await f.drawer.isVisible(), true, "Escape inside the teleported menu must not close its drawer");
        assert.equal(await f.singleResults.isVisible(), false);
        assert.equal(await f.singleInput.evaluate((element) => element === document.activeElement), true);
        await f.singleInput.click();
        await f.singleInput.press("Tab");
        await f.page.keyboard.press("Tab");
        await more.press("Enter");
        await f.singleResults.getByRole("option").nth(20).waitFor();
        assert.equal(f.posts.length, 2, "explicit keyboard activation loads exactly one page");
        assert.equal(f.posts.at(-1).pageNum, 2);
        assert.equal(await f.singleResults.getByRole("option").count(), 40);
        assert.equal(await f.singleInput.evaluate((element) => element === document.activeElement), true, "keyboard paging keeps focus in the company picker when its footer is replaced");
      } finally { await f.context.close(); }
    });

    await t.test("reopening the last selected option does not automatically buy the next page", async () => {
      const f = await setup();
      try {
        await f.singleInput.fill("选择末行");
        await f.singleInput.press("Enter");
        await f.singleResults.getByRole("option").last().click();
        assert.equal(f.posts.length, 1);
        await f.singleInput.click();
        await f.page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        assert.equal(f.posts.length, 1);
        await f.singleInput.dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true, bubbles: true, cancelable: true });
        assert.equal(await f.singleResults.isVisible(), true, "IME confirmation does not select a result");
        assert.equal(f.posts.length, 1);
        assert.deepEqual(f.errors, []);
      } finally { await f.context.close(); }
    });

    await t.test("multi-select pagination remains keyboard accessible with an empty trailing input", async () => {
      const f = await setup();
      try {
        await f.multiInput.fill("多选键盘");
        await f.multiInput.press("Enter");
        await f.multiResults.getByRole("option").first().click();
        await f.multiInput.click();
        await f.multiInput.press("Tab");
        const more = f.multiRegion.getByRole("button", { name: "加载更多", exact: true });
        assert.equal(await more.evaluate((element) => element === document.activeElement), true);
        await f.page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        assert.equal(f.posts.length, 1);
        await more.press("Shift+Tab");
        assert.equal(await f.multiInput.evaluate((element) => element === document.activeElement), true);
        assert.equal(await f.multiResults.isVisible(), false);
        assert.equal(await f.multi.getByRole("listitem").count(), 1);
        assert.deepEqual(f.errors, []);
      } finally { await f.context.close(); }
    });
  } finally { await browser.close(); await server.close(); }
});
