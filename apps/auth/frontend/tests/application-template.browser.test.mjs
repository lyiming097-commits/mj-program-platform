import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium, expect } = browserTools("@playwright/test");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));
const starterRoot = fileURLToPath(new URL("../../../starter-app/frontend/", import.meta.url));
const portalRoot = fileURLToPath(new URL("../../../portal/frontend/", import.meta.url));
const session = { sessionId: "template-entry-test", userId: "template-entry-test", name: "隔离测试", canConfigurePermissions: true, canManagePlatformSettings: true, canManageApp: true };

await test("后台应用模板只保留原模板入口", async (t) => {
  let starterServer, authServer, portalServer;
  let cacheRoot;
  let base = process.env.CHECK_BASE;
  if (!base) {
    cacheRoot = await mkdtemp(fileURLToPath(new URL("../../../../.codex-artifacts/template-entry-vite-", import.meta.url)));
    starterServer = await createServer({ root: starterRoot, cacheDir: path.join(cacheRoot, "starter"), configFile: path.join(starterRoot, "vite.config.ts"), server: { host: "127.0.0.1", port: 0, strictPort: false } });
    await starterServer.listen();
    authServer = await createServer({ root, cacheDir: path.join(cacheRoot, "auth"), configFile: path.join(root, "vite.config.ts"), server: { host: "127.0.0.1", port: 0, strictPort: false, proxy: { "/starter-app/": `http://127.0.0.1:${starterServer.httpServer.address().port}` } } });
    await authServer.listen();
    portalServer = await createServer({ root: portalRoot, cacheDir: path.join(cacheRoot, "portal"), configFile: path.join(portalRoot, "vite.config.ts"), server: { host: "127.0.0.1", port: 0, strictPort: false, proxy: {
      "/auth/": `http://127.0.0.1:${authServer.httpServer.address().port}`,
      "/starter-app/": `http://127.0.0.1:${starterServer.httpServer.address().port}`,
    } } });
    await portalServer.listen();
    base = `http://127.0.0.1:${portalServer.httpServer.address().port}`;
  }
  const browser = await chromium.launch({ headless: true });
  const screenshots = await mkdtemp(path.join(tmpdir(), "mj-template-entry-"));
  async function fixture({ width = 1440, admin = true, messageOnly = false } = {}) {
    const context = await browser.newContext({ viewport: { width, height: 960 } });
    const currentSession = { ...session, canConfigurePermissions: admin, canManagePlatformSettings: admin };
    await context.addInitScript(value => {
      if (["http:", "https:"].includes(location.protocol) && location.pathname.startsWith("/auth/")) {
        sessionStorage.setItem("mj_program_login_session", JSON.stringify(value));
      }
    }, currentSession);
    if (messageOnly) await context.addInitScript(() => {
      if (window === window.parent) document.addEventListener("mj.portal.app.open", event => event.stopImmediatePropagation(), true);
    });
    const requests = [], writes = [], errors = [];
    context.on("page", page => page.on("pageerror", error => errors.push(error.message)));
    await context.route("**/api/**", route => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      requests.push(pathname);
      if (!["GET", "HEAD"].includes(request.method())) writes.push(pathname);
      const data = pathname.includes("/session/") || pathname === "/api/portal/session" ? currentSession
        : pathname.endsWith("/permissions/directory") ? { orgRevision: "1", departments: [], employees: [] }
        : pathname.endsWith("/permissions") ? { revision: "1", orgRevision: "1", items: [], rules: [] }
        : pathname.endsWith("/enabled-departments") ? { departmentIds: [], revision: "1", orgRevision: "1" }
        : { items: [], total: 0, count: 0, totalPages: 1, page: 1, filterOptions: {}, orgRevision: "1" };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
    });
    return { context, page: await context.newPage(), requests, writes, errors };
  }
  try {
    for (const width of [1440, 1024, 800]) {
      await t.test(`${width}px 后台入口打开顶部模板页签，重复打开保留页面`, async () => {
        const { context, page, requests, writes, errors } = await fixture({ width });
        try {
          await page.goto(`${base}/?app=auth-settings`);
          const backend = page.frameLocator("#portal-frame-auth-settings");
          await expect(backend.getByRole("tablist", { name: "组织架构页面" })).toBeVisible({ timeout: 15000 }).catch(async error => {
            console.log(JSON.stringify({ url: page.url(), errors, frames: page.frames().map(frame => frame.url()), body: (await page.locator("body").innerText()).slice(0, 1500) }));
            throw error;
          });
          const sidebar = backend.getByRole("navigation", { name: "主导航" });
          const entry = sidebar.getByRole("link", { name: "应用模板", exact: true });
          await expect(entry).toHaveAttribute("href", "/?app=starter-app");
          assert.deepEqual(await sidebar.getByRole("button").allTextContents(), ["组织架构", "我司主体", "省市区域", "工商信息查询", "机器人群发"]);
          assert.equal(requests.some(url => url.startsWith("/api/starter-app/")), false);
          await expect(page.getByRole("link", { name: "应用模板", exact: true })).toHaveCount(0);
          await entry.click();
          const templateTab = page.getByRole("tab", { name: "应用模板", exact: true });
          await expect(templateTab).toHaveAttribute("aria-selected", "true", { timeout: 15000 });
          const template = page.frameLocator("#portal-frame-starter-app");
          await expect(template.getByRole("tab", { name: "示例表格", exact: true })).toBeVisible({ timeout: 15000 });
          await expect(page).toHaveURL(`${base}/?app=starter-app`);
          assert.equal(context.pages().length, 1);
          await expect(page.locator("#portal-frame-auth-settings")).toHaveAttribute("src", "/auth/settings/organization");
          await template.getByRole("tab", { name: "示例字段", exact: true }).click();
          await expect(template.getByRole("group", { name: "气泡多选", exact: true })).toBeVisible();
          await page.getByRole("tab", { name: "后台管理", exact: true }).click();
          await entry.click();
          await expect(templateTab).toHaveAttribute("aria-selected", "true");
          await expect(page.locator("#portal-frame-starter-app")).toHaveCount(1);
          await expect(template.getByRole("tab", { name: "示例字段", exact: true })).toHaveAttribute("aria-selected", "true");
          await template.getByRole("button", { name: "设置", exact: true }).click();
          await expect(template.getByRole("tab", { name: "权限设置", exact: true })).toBeVisible();
          await template.getByRole("button", { name: "本软件优化建议", exact: true }).click();
          await expect(template.locator(".suggestions-workspace")).toBeVisible();
          await page.screenshot({ path: path.join(screenshots, `workspace-${width}.png`) });
          if (width === 1440) {
            await template.getByRole("button", { name: "示例样式", exact: true }).click();
            await template.getByRole("tab", { name: "示例字段", exact: true }).click();
            const draft = template.getByRole("textbox", { name: "示例字段富文本", exact: true });
            await draft.fill("未保存的模板草稿");
            await page.getByRole("tab", { name: "后台管理", exact: true }).click();
            await entry.click();
            await expect(draft).toHaveText("未保存的模板草稿");
            const close = page.locator('[data-portal-tab-id="starter-app"] .portal-tab-close');
            await close.click();
            const confirm = page.getByRole("alertdialog", { name: "是否放弃修改" });
            await expect(confirm).toBeVisible();
            await confirm.getByRole("button", { name: "继续编辑" }).click();
            await expect(draft).toHaveText("未保存的模板草稿");
            await close.click();
            await confirm.getByRole("button", { name: "确认关闭" }).click();
            await expect(templateTab).toHaveCount(0);
          }
          assert.deepEqual(writes, []);
          assert.deepEqual(errors, []);
        } finally { await context.close(); }
      });
    }
    await t.test("消息通道打开模板，刷新恢复顶部页签", async () => {
      const { context, page, errors } = await fixture({ messageOnly: true });
      try {
        await page.goto(`${base}/?app=auth-settings`);
        const backend = page.frameLocator("#portal-frame-auth-settings");
        await backend.getByRole("link", { name: "应用模板", exact: true }).click();
        await expect(page.getByRole("tab", { name: "应用模板", exact: true })).toHaveAttribute("aria-selected", "true");
        await page.reload();
        await expect(page.getByRole("tab", { name: "应用模板", exact: true })).toHaveAttribute("aria-selected", "true");
        await expect(page.frameLocator("#portal-frame-starter-app").getByRole("tab", { name: "示例表格", exact: true })).toBeVisible();
        assert.equal(context.pages().length, 1);
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    await t.test("只接受后台 frame 请求，并重新验证后台管理能力", async () => {
      const { context, page } = await fixture();
      try {
        await page.goto(`${base}/?app=auth-settings`);
        await expect(page.frameLocator("#portal-frame-auth-settings").getByRole("link", { name: "应用模板", exact: true })).toBeVisible();
        await page.evaluate(() => {
          window.postMessage({ type: "mj.portal.app.open", appId: "starter-app", requestId: "wrong-source" }, location.origin);
          const frame = document.getElementById("portal-frame-auth-settings");
          window.dispatchEvent(new MessageEvent("message", { origin: "https://untrusted.invalid", source: frame.contentWindow,
            data: { type: "mj.portal.app.open", appId: "starter-app", requestId: "wrong-origin" } }));
        });
        await page.getByRole("tab", { name: "首页", exact: true }).click();
        await expect(page.getByRole("tab", { name: "应用模板", exact: true })).toHaveCount(0);
        await expect(page.getByRole("link", { name: "应用模板", exact: true })).toHaveCount(0);
      } finally { await context.close(); }
      const regular = await fixture({ admin: false });
      try {
        await regular.page.goto(`${base}/?app=starter-app`);
        await expect(regular.page.locator(".portal-app-categories")).toBeVisible();
        await expect(regular.page.getByRole("tab", { name: "应用模板", exact: true })).toHaveCount(0);
        await expect(regular.page).not.toHaveURL(/app=starter-app/);
      } finally { await regular.context.close(); }
    });
    await t.test("旧后台模板地址只显示链接，不再请求模板业务数据", async () => {
      const { context, page, requests } = await fixture();
      try {
        await page.goto(`${base}/auth/settings/application-template?templatePage=permissions`);
        await expect(page.getByRole("link", { name: "打开应用模板", exact: true })).toHaveAttribute("href", "/?app=starter-app");
        await expect(page.getByRole("heading", { name: "权限选择", exact: true })).toHaveCount(0);
        assert.equal(requests.some(url => url.startsWith("/api/starter-app/")), false);
        assert.equal(await page.locator("body.auth-application-template").count(), 0);
        const opened = context.waitForEvent("page");
        await page.getByRole("link", { name: "打开应用模板", exact: true }).click();
        const workspace = await opened;
        await expect(workspace.getByRole("tab", { name: "应用模板", exact: true })).toHaveAttribute("aria-selected", "true");
        await expect(workspace.frameLocator("#portal-frame-starter-app").getByRole("tab", { name: "示例表格", exact: true })).toBeVisible();
      } finally { await context.close(); }
    });
    await t.test("普通用户和手机后台不出现模板入口", async () => {
      for (const options of [{ admin: false }, { width: 390 }]) {
        const { context, page } = await fixture(options);
        try {
          await page.goto(`${base}/auth/settings/organization`);
          await expect(page.getByRole("tablist", { name: "组织架构页面" })).toBeVisible({ timeout: 15000 });
          await expect(page.getByRole("link", { name: "应用模板", exact: true })).toHaveCount(0);
        } finally { await context.close(); }
      }
    });
    console.log(`截图：${screenshots}`);
  } finally {
    await browser.close();
    await portalServer?.close();
    await authServer?.close();
    await starterServer?.close();
    if (cacheRoot) await rm(cacheRoot, { recursive: true, force: true });
  }
});
