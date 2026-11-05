import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const artifacts = fileURLToPath(new URL("../../../../.codex-artifacts/settings-feedback/", import.meta.url));
const session = {
  sessionId: "settings-feedback-fixture", userId: "admin-1", actorUserId: "admin-1", name: "测试管理员",
  canManagePlatformSettings: true, canConfigurePermissions: true, canSyncContacts: true,
  canManageEmployeeAccountStatus: true, canAccessInactiveEmployees: true,
};
const department = { deptId: "1", name: "测试部门", children: [] };

await test("desktop management uses the template's floating action feedback", async (t) => {
  const externalBase = process.env.SETTINGS_FEEDBACK_BASE_URL;
  const server = externalBase ? null : await createServer({
    root: fileURLToPath(new URL("../", import.meta.url)),
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  if (server) await server.listen();
  const base = externalBase || `http://127.0.0.1:${server.httpServer.address().port}`;
  const browser = await chromium.launch({ headless: true });
  await mkdir(artifacts, { recursive: true });

  async function fixture(path = "notifications", width = 1440) {
    const context = await browser.newContext({ viewport: { width, height: 960 }, reducedMotion: "reduce" });
    await context.addInitScript((login) => sessionStorage.setItem("mj_program_login_session", JSON.stringify(login)), session);
    const state = { categories: [{ id: "1", name: "测试分类" }], failCategory: false, failLoad: false, conflict: false, failCompany: false, categoryWrites: 0, enabledIds: [], companyItems: [] };
    await context.route("**/api/**", async (route) => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      const reply = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
      if (path === "/api/auth/session/validate") return reply(session);
      if (path === "/api/org/notices/capabilities") return reply({ canManage: true, canPublish: true });
      if (path === "/api/org/notices/categories") {
        if (request.method() === "POST") {
          state.categoryWrites++;
          if (state.failCategory) return reply({ error: "分类名称已存在" }, 400);
          state.categories.push({ id: String(state.categories.length + 1), ...request.postDataJSON() });
        }
        if (state.failLoad) return reply({ error: "分类加载失败，请重试" }, 503);
        return reply({ items: state.categories });
      }
      if (/^\/api\/org\/notices\/categories\/\d+$/.test(path)) {
        state.categoryWrites++;
        if (state.failCategory) return reply({ error: "分类名称已存在" }, 400);
        if (request.method() === "DELETE") state.categories = state.categories.filter(item => item.id !== path.split("/").at(-1));
        else state.categories.find(item => item.id === path.split("/").at(-1)).name = request.postDataJSON().name;
        return reply({});
      }
      if (path === "/api/org/departments/tree") return reply({ items: [department], orgRevision: "1" });
      if (path === "/api/org/enabled-departments") {
        if (request.method() === "PUT") state.enabledIds = request.postDataJSON().departmentIds;
        return reply({ departmentIds: state.enabledIds, revision: "1", orgRevision: "1" });
      }
      if (path === "/api/org/employees" || path.endsWith("/employees")) return reply({ items: [], orgRevision: "1" });
      if (path === "/api/org/departments/1") return reply({ ...department, orgRevision: "1" });
      if (/\/permissions(?:\/(?:admin|publisher))?$/.test(path)) {
        if (request.method() === "PUT" && state.conflict) return reply({ error: "权限已更新" }, 409);
        return reply({ rules: request.method() === "PUT" ? request.postDataJSON().rules : [], revision: "1", orgRevision: "1" });
      }
      if (path === "/api/directory/company-entities") {
        if (request.method() === "POST") {
          if (state.failCompany) return reply({ error: "测试保存失败，请重试" }, 503);
          const item = { id: 1, revision: "1", ...request.postDataJSON() };
          state.companyItems.push(item);
          return reply({ item });
        }
        return reply({ items: state.companyItems, total: state.companyItems.length, count: state.companyItems.length, directoryRevision: "1" });
      }
      return reply({ items: [], total: 0, rules: [], departmentIds: [], revision: "1", orgRevision: "1" });
    });
    const page = await context.newPage(), errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "warning" && message.text().includes("Vue warn")) errors.push(message.text()); });
    await page.goto(`${base}/auth/settings/${path}`);
    return { context, page, state, errors };
  }

  try {
    for (const width of [1440, 1024]) {
      await t.test(`${width}px category actions float without moving content; repeated feedback resets and closes`, async () => {
        const { context, page, state, errors } = await fixture("notifications", width);
        try {
          await page.getByRole("tab", { name: "分类管理", exact: true }).click();
          await page.getByRole("button", { name: "编辑分类测试分类" }).waitFor();
          await page.clock.install();
          const input = page.getByLabel("分类名称", { exact: true });
          const initialBounds = await input.boundingBox();
          const rename = async name => {
            await page.getByRole("button", { name: /^编辑分类/ }).first().click();
            await input.fill(name);
            await page.getByRole("button", { name: "保存修改", exact: true }).click();
            await page.getByRole("status").filter({ hasText: "通知分类已改名" }).waitFor();
          };
          await rename("测试分类甲");
          await page.clock.runFor(250);
          const toast = page.getByRole("status").filter({ hasText: "通知分类已改名" });
          const toastBounds = await toast.boundingBox();
          assert.equal(toastBounds.y, 16);
          assert.equal(toastBounds.width, 420);
          assert.equal(toastBounds.x, (width - 420) / 2);
          assert.equal(await toast.evaluate(node => getComputedStyle(node.parentElement).position), "fixed");
          assert.deepEqual(await input.boundingBox(), initialBounds, "feedback does not push down the form");
          assert.equal(await toast.evaluate(node => node.contains(document.activeElement)), false, "feedback does not take focus");
          await page.screenshot({ path: `${artifacts}${externalBase ? "deployed-" : ""}category-${width}.png` });
          await page.clock.runFor(1800);
          await rename("测试分类乙");
          await page.clock.runFor(1200);
          assert.equal(await toast.isVisible(), true, "the previous timer cannot close a repeated message");
          assert.equal(await page.getByRole("button", { name: "关闭提示", exact: true }).count(), 1);
          await page.clock.runFor(2050);
          await toast.waitFor({ state: "detached" });
          await rename("测试分类丙");
          await page.getByRole("button", { name: "关闭提示", exact: true }).click();
          await page.clock.runFor(250);
          assert.equal(await toast.count(), 0);

          state.failCategory = true;
          await input.fill("重复分类");
          await page.getByRole("button", { name: "添加分类", exact: true }).click();
          const failure = page.getByRole("alert").filter({ hasText: "分类名称已存在" });
          await failure.waitFor();
          assert.equal(await failure.getAttribute("aria-live"), "assertive");
          assert.equal(await input.inputValue(), "重复分类", "a failed operation retains input for retry");
          assert.deepEqual(await input.boundingBox(), initialBounds);
          state.failCategory = false;
          await page.getByRole("button", { name: "添加分类", exact: true }).click();
          await page.getByRole("status").filter({ hasText: "通知分类已添加" }).waitFor();
          assert.equal(await page.getByRole("button", { name: "关闭提示", exact: true }).count(), 1, "new feedback replaces the old one");
          await page.clock.runFor(3250);
          assert.equal(await page.getByRole("button", { name: "关闭提示", exact: true }).count(), 0);
          assert.equal(state.categoryWrites, 5);
          assert.deepEqual(errors, []);
        } finally { await context.close(); }
      });
    }

    await t.test("normal motion shows the template progress bar and expires after three seconds", async () => {
      const { context, page, errors } = await fixture();
      try {
        await page.emulateMedia({ reducedMotion: "no-preference" });
        await page.getByRole("tab", { name: "分类管理", exact: true }).click();
        await page.getByRole("button", { name: "编辑分类测试分类" }).click();
        await page.getByLabel("分类名称", { exact: true }).fill("测试分类改名");
        await page.getByRole("button", { name: "保存修改", exact: true }).click();
        const toast = page.getByRole("status").filter({ hasText: "通知分类已改名" });
        await toast.waitFor();
        await page.waitForFunction(() => {
          const bar = document.querySelector(".platform-action-toast-progress");
          if (!bar) return false;
          const scale = new DOMMatrix(getComputedStyle(bar).transform).a;
          return scale > 0.15 && scale < 0.9;
        });
        assert.equal((await toast.boundingBox()).y, 16);
        await page.screenshot({ path: `${artifacts}${externalBase ? "deployed-" : ""}category-motion.png` });
        await toast.waitFor({ state: "detached", timeout: 5000 });
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });

    await t.test("permissions save uses the same host; conflicts and load errors remain actionable", async () => {
      const { context, page, state, errors } = await fixture();
      try {
        state.enabledIds = ["1"];
        await page.getByRole("tab", { name: "权限管理", exact: true }).click();
        await page.getByRole("button", { name: "添加部门通知管理员" }).click();
        await page.getByRole("checkbox", { name: "测试部门部门", exact: true }).check();
        await page.getByRole("button", { name: "关闭", exact: true }).click();
        await page.getByRole("button", { name: "保存", exact: true }).click();
        await page.getByRole("status").filter({ hasText: "通知管理员权限已保存" }).waitFor();
        assert.equal(await page.getByRole("button", { name: "关闭提示", exact: true }).count(), 1);
        await page.getByRole("button", { name: "关闭提示", exact: true }).click();
        await page.getByRole("button", { name: "移除测试部门" }).click();
        state.conflict = true;
        await page.getByRole("button", { name: "保存", exact: true }).click();
        await page.getByRole("alert").filter({ hasText: "当前修改尚未提交" }).waitFor();
        await page.clock.install();
        await page.clock.runFor(6000);
        assert.equal(await page.getByRole("alert").filter({ hasText: "当前修改尚未提交" }).isVisible(), true);
        assert.equal(await page.getByRole("button", { name: "重新加载", exact: true }).isVisible(), true);
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
      const loaded = await fixture();
      try {
        loaded.state.failLoad = true;
        await loaded.page.reload();
        const error = loaded.page.getByRole("alert").filter({ hasText: "分类加载失败，请重试" });
        await error.waitFor();
        await loaded.page.clock.install();
        await loaded.page.clock.runFor(6000);
        assert.equal(await error.isVisible(), true);
        loaded.state.failLoad = false;
        await error.getByRole("button", { name: "重新加载", exact: true }).click();
        await error.waitFor({ state: "detached" });
        assert.deepEqual(loaded.errors, []);
      } finally { await loaded.context.close(); }
    });

    await t.test("company save feedback stays above the drawer; form failures keep the draft", async () => {
      const { context, page, state, errors } = await fixture("company-entities");
      try {
        await page.getByRole("button", { name: "新增", exact: true }).click();
        const drawer = page.getByRole("dialog", { name: "新增我司主体", exact: true });
        await drawer.getByLabel("公司名称").fill("测试主体有限公司");
        for (const [label, value] of Object.entries({ 税号: "TEST913301", 开户银行: "测试银行", 账号: "10002000", 地址: "测试地址", 电话: "0571-12345678" })) {
          await drawer.getByLabel(label).fill(value);
        }
        state.failCompany = true;
        await drawer.getByRole("button", { name: "保存", exact: true }).click();
        await drawer.getByRole("alert").filter({ hasText: "测试保存失败，请重试" }).waitFor();
        await page.clock.install();
        await page.clock.runFor(6000);
        assert.equal(await drawer.getByRole("alert").isVisible(), true);
        assert.equal(await drawer.getByLabel("公司名称").inputValue(), "测试主体有限公司");
        state.failCompany = false;
        await drawer.getByRole("button", { name: "保存", exact: true }).click();
        const toast = page.getByRole("status").filter({ hasText: "已保存我司主体“测试主体有限公司”" });
        await toast.waitFor();
        await page.clock.runFor(250);
        assert.equal(await toast.evaluate(node => {
          const box = node.getBoundingClientRect();
          return node.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
        }), true, "the drawer cannot obscure feedback");
        await page.screenshot({ path: `${artifacts}${externalBase ? "deployed-" : ""}company-drawer.png` });
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });

    await t.test("enabled departments save floats; switching to mobile unmounts desktop feedback", async () => {
      const { context, page, errors } = await fixture("organization");
      try {
        await page.getByRole("button", { name: "启用范围", exact: true }).click();
        await page.getByRole("checkbox", { name: "启用测试部门", exact: true }).check();
        await page.getByRole("button", { name: "保存", exact: true }).click();
        await page.getByRole("status").filter({ hasText: "启用部门设置已保存" }).waitFor();
        await page.setViewportSize({ width: 390, height: 844 });
        await page.getByRole("button", { name: "关闭提示", exact: true }).waitFor({ state: "detached" });
        assert.equal(await page.locator(".platform-action-toast-host").count(), 0);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        await page.screenshot({ path: `${artifacts}${externalBase ? "deployed-" : ""}phone-unchanged.png` });
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
  } finally {
    await browser.close();
    if (server) await server.close();
  }
});
