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

test("presales mixes local and CRM projects, supports local creation/deletion and keeps CRM fields read-only", { timeout: 90000 }, async () => {
  const server = await createServer({ root, configFile: path.join(root, "vite.config.ts"), server: { host: "127.0.0.1", port: 0 } });
  let browser;
  const project = {
    id: 101, code: "PS101", serviceType: "presales", source: "crm", sourceCrmId: "crm-101",
    name: "分页 CRM 项目", customer: "测试学校", ownerName: "CRM 负责人", ownerUserId: "crm-owner",
    crmStage: "方案渗透", crmStatus: "进行中", crmOrderType: "项目销售",
    status: "in_progress", statusLabel: "进行中", currentNodeKey: "early-plan", summary: "",
    permissions: { canManage: true, canDelete: false, canSettle: true },
    activeNodes: [{ nodeKey: "early-plan", name: "前期方案" }, { nodeKey: "budget-match", name: "预算匹配" }],
    businessData: { projectInfo: { customer: "测试学校", name: "分页 CRM 项目", owner: "CRM 负责人", info: "", reason: "" } },
    nodes: [
      { id: 1011, nodeKey: "early-approval", name: "前期立项", kind: "approval", status: "completed", statusLabel: "已完成", enabled: true, sequence: 1, businessData: { outcome: "approved" } },
      { id: 1012, nodeKey: "early-plan", name: "前期方案", kind: "delivery", status: "active", statusLabel: "进行中", enabled: true, sequence: 2, businessData: {} },
      { id: 1013, nodeKey: "budget-match", name: "预算匹配", kind: "delivery", status: "active", statusLabel: "进行中", enabled: true, sequence: 3, businessData: {} },
    ], assignments: [], events: [],
  };
  for (const node of project.nodes) node.permissions = { canEdit: node.status === "active", canAssign: true };
  const legacy = { ...project, id: 102, code: "PS102", source: "local", sourceCrmId: "",
    permissions: { canManage: true, canDelete: true, canSettle: true },
    name: "之前创建的测试项目", customer: "本地测试学校", ownerName: "当前管理员", ownerUserId: "service-admin" };
  const allProjects = [...Array.from({ length: 100 }, (_, index) => ({ ...project, id: index + 1,
    name: `CRM 项目 ${index + 1}`, crmStage: index === 99 ? "已签合同" : project.crmStage })), project, legacy];
  // UTC is deliberately a different calendar day from the user's Beijing day.
  const now = "2026-10-16T15:59:30Z";
  allProjects[0].crmCreatedAt = "2026-10-15T16:00:00Z";
  allProjects[1].crmCreatedAt = "2026-10-15T15:59:59Z";
  allProjects[1].createdAt = now;
  allProjects[1].updatedAt = now;
  allProjects[2].createdAt = now;
  allProjects[3].crmCreatedAt = "2026-10-16T16:00:00Z";
  const patches = [];
  const creates = [];
  const deletedIds = [];
  const requestedPages = [];
  const pageErrors = [];
  let sourceFailure = false;
  let initialSync = true;
  let delayOldSearch = false;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.clock.install({ time: new Date(now) });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.addInitScript(() => sessionStorage.setItem("mj_program_login_session", JSON.stringify({
      sessionId: "crm-presales-test", userId: "service-admin", name: "当前管理员", loginType: "scan",
    })));
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      const method = route.request().method();
      let body = { items: [] };
      let status = 200;
      if (url.pathname === "/api/auth/session/validate") {
        body = { sessionId: "crm-presales-test", userId: "service-admin", name: "当前管理员", loginType: "scan" };
      } else if (url.pathname === "/api/after-sales/session/") {
        body = { canManageApp: true, canManageSettings: true, appPermission: "admin" };
      } else if (url.pathname === "/api/after-sales/projects" && method === "POST") {
        const payload = route.request().postDataJSON();
        creates.push(payload);
        const created = { ...legacy, id: 103, code: "PS103", name: payload.name, customer: payload.customer,
          currentNodeKey: "early-approval", nodes: project.nodes.map((node, index) => ({ ...node, id: 1031 + index,
            status: index === 0 ? "active" : "pending", statusLabel: index === 0 ? "进行中" : "未开始",
            permissions: { canEdit: index === 0, canAssign: true },
            actualStartAt: index === 0 ? new Date().toISOString() : "", businessData: {} })) };
        allProjects.push(created);
        status = 201;
        body = { ok: true, item: created };
      } else if (url.pathname === "/api/after-sales/projects" && url.searchParams.get("type") === "presales") {
        let number = Number(url.searchParams.get("page") || 1);
        const size = Number(url.searchParams.get("pageSize") || 20);
        requestedPages.push(number);
        const search = url.searchParams.get("nameSearch") || "";
        assert.equal(url.searchParams.has("search"), false, "project-name input must not search internal codes or other columns");
        const customer = url.searchParams.get("customerSearch") || "";
        const owner = url.searchParams.get("ownerSearch") || "";
        const crmStage = url.searchParams.get("crmStage") || "";
        const nodeKey = url.searchParams.get("nodeKey") || "";
        const rows = allProjects.filter((item) => item.name.includes(search) && item.customer.includes(customer) && item.ownerName.includes(owner)
          && (!nodeKey || (nodeKey === "completed" ? item.status === "completed" : item.activeNodes?.some(node => node.nodeKey === nodeKey)))
          && (!crmStage || (crmStage === "__empty__" ? !item.sourceCrmId || !item.crmStage : item.sourceCrmId && item.crmStage === crmStage)));
        const pages = Math.max(1, Math.ceil(rows.length / size));
        number = Math.min(number, pages);
        body = { items: rows.slice((number - 1) * size, number * size), totalPages: pages, total: rows.length, page: number, pageSize: size,
          crmStageOptions: [...new Set(allProjects.filter((item) => item.sourceCrmId && item.crmStage).map((item) => item.crmStage))] };
        if (initialSync) {
          body = { ...body, items: [], total: 0, totalPages: 1, crmSyncing: true };
          initialSync = false;
        }
        if (delayOldSearch && search === "旧搜索") await new Promise((resolve) => setTimeout(resolve, 1000));
        if (sourceFailure) {
          const localRows = rows.filter((item) => item.source === "local");
          body = { items: localRows, total: localRows.length, page: 1, pageSize: size, totalPages: 1,
            crmScopeReady: false, crmSyncing: false, crmSyncError: "CRM 项目暂时无法读取，请稍后重试" };
        }
      } else if (/^\/api\/after-sales\/projects\/\d+$/.test(url.pathname)) {
        const id = Number(url.pathname.split("/").at(-1));
        const target = allProjects.find((item) => item.id === id);
        if (method === "PATCH") {
          const payload = route.request().postDataJSON();
          patches.push(payload);
          if (payload.businessData) target.businessData = payload.businessData;
        } else if (method === "DELETE") {
          assert.equal(target.source, "local", "UI must never delete a CRM project");
          deletedIds.push(id);
          allProjects.splice(allProjects.indexOf(target), 1);
        }
        body = { ok: true, item: target };
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/after-sales/`);
    const navigation = page.getByRole("navigation", { name: "主导航" });
    await navigation.getByRole("button", { name: "售前服务" }).click();
    try {
      await page.getByText("102 个项目 · CRM 同步与本地新增", { exact: true }).waitFor({ timeout: 10000 });
    } catch (reason) {
      throw new Error(JSON.stringify({ body: await page.locator("body").innerText(), requestedPages, pageErrors }), { cause: reason });
    }
    assert.ok(requestedPages.every((number) => number === 1), "must not eagerly load other pages");
    assert.equal(await page.locator(".as-project-data-row").count(), 20);
    const firstRow = page.locator(".as-project-data-row").first();
    await firstRow.getByText("新", { exact: true }).waitFor();
    for (const index of [1, 2, 3]) {
      assert.equal(await page.locator(".as-project-data-row").nth(index).getByText("新", { exact: true }).count(), 0,
        "old CRM projects, local import/edit times, missing CRM dates and future dates cannot mark a project new");
    }
    assert.deepEqual(await page.locator(".as-project-data-row").first().locator(".as-project-stage").allTextContents(), ["前期方案", "预算匹配"]);
    for (const viewport of [{ width: 1440, height: 900 }, { width: 1024, height: 768 }]) {
      await page.setViewportSize(viewport);
      const bounds = await page.getByRole("navigation", { name: "项目分页" }).boundingBox();
      assert.ok(bounds.y + bounds.height <= viewport.height, "pagination must stay visible below the scrolling table");
      const badge = await firstRow.getByText("新", { exact: true }).boundingBox();
      const cell = await firstRow.locator("td").first().boundingBox();
      assert.ok(badge.x >= cell.x && badge.x + badge.width <= cell.x + cell.width,
        "the new badge must stay fully visible beside the project name");
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: path.join(root, "../../../.codex-artifacts/after-sales-crm-new-project.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await firstRow.getByText("新", { exact: true }).isVisible(), false, "desktop-only badge preserves the mobile layout");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.clock.fastForward(61_000);
    await firstRow.getByText("新", { exact: true }).waitFor({ state: "detached" });
    await page.screenshot({ path: path.join(root, "../../../.codex-artifacts/after-sales-crm-pagination.png") });
    assert.equal(await page.getByRole("button", { name: "新增售前项目" }).count(), 1);
    assert.equal(await page.getByRole("button", { name: /^删除CRM 项目/ }).count(), 0);
    const pagination = page.getByRole("navigation", { name: "项目分页" });
    await pagination.getByRole("button", { name: "下一页" }).click();
    await pagination.getByRole("button", { name: "第 2 页", exact: true }).waitFor();
    await page.waitForFunction(() => document.querySelector('[aria-current="page"]')?.textContent === "2");
    assert.equal(requestedPages.at(-1), 2);
    assert.equal(new URL(page.url()).searchParams.get("page"), "2");
    const crmStagePicker = page.getByRole("combobox", { name: "筛选 CRM 阶段", exact: true });
    await crmStagePicker.click();
    await page.getByRole("option", { name: "已签合同", exact: true }).click();
    await page.getByText("1 个项目 · CRM 同步与本地新增", { exact: true }).waitFor();
    await page.locator(".as-project-data-row").filter({ hasText: "CRM 项目 100" }).waitFor();
    assert.equal(requestedPages.at(-1), 1, "stage filtering must reset pagination and search across all pages");
    assert.equal(new URL(page.url()).searchParams.get("crmStage"), "已签合同");
    assert.equal(new URL(page.url()).searchParams.get("page"), null);
    await page.reload();
    await page.locator(".as-project-data-row").filter({ hasText: "CRM 项目 100" }).waitFor();
    assert.equal(await page.locator(".as-project-data-row").count(), 1, "reload must preserve the stage filter");
    await page.screenshot({ path: path.join(root, "../../../.codex-artifacts/after-sales-crm-stage-filter.png") });
    await page.getByRole("searchbox", { name: "搜索客户", exact: true }).fill("不存在的客户");
    await page.getByText("没有符合条件的项目", { exact: true }).waitFor();
    await crmStagePicker.click();
    await page.getByRole("option", { name: "方案渗透", exact: true }).waitFor();
    await page.keyboard.press("Escape");
    await page.getByRole("searchbox", { name: "搜索客户", exact: true }).fill("");
    await page.getByText("1 个项目 · CRM 同步与本地新增", { exact: true }).waitFor();
    await crmStagePicker.click();
    await page.getByRole("option", { name: "无 CRM 阶段", exact: true }).click();
    await page.locator(".as-project-data-row").filter({ hasText: legacy.name }).waitFor();
    assert.equal(await page.locator(".as-project-data-row").count(), 1);
    await crmStagePicker.click();
    await page.getByRole("option", { name: "全部阶段", exact: true }).click();
    await page.getByText("102 个项目 · CRM 同步与本地新增", { exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("crmStage"), null);
    await pagination.getByRole("button", { name: "第 6 页", exact: true }).click();
    await page.locator(".as-project-data-row").filter({ hasText: "分页 CRM 项目" }).waitFor();
    assert.equal(await page.locator(".as-project-data-row").count(), 2);
    await page.locator(".as-project-data-row").filter({ hasText: legacy.name }).waitFor();
    assert.equal(await page.getByRole("button", { name: `删除${project.name}`, exact: true }).count(), 0);
    assert.equal(await page.getByRole("button", { name: `删除${legacy.name}`, exact: true }).count(), 1);
    const nodePicker = page.getByRole("combobox", { name: "筛选节点阶段", exact: true });
    await nodePicker.press("Enter");
    await page.getByRole("option", { name: "预算匹配", exact: true }).click();
    await page.waitForURL(url => url.searchParams.get("stage") === "budget-match");
    await page.locator(".as-project-data-row").first().waitFor();
    assert.equal(await page.locator(".as-project-data-row").count(), 20);
    assert.deepEqual(await page.locator(".as-project-data-row").first().locator(".as-project-stage").allTextContents(), ["前期方案", "预算匹配"]);
    await page.screenshot({ path: path.join(root, "../../../.codex-artifacts/after-sales-parallel-node-list.png") });
    await nodePicker.press("Enter");
    await page.getByRole("option", { name: "全部节点", exact: true }).click();
    await page.waitForURL(url => !url.searchParams.has("stage"));
    await page.screenshot({ path: path.join(root, "../../../.codex-artifacts/after-sales-local-crm-projects.png") });
    await page.getByRole("combobox", { name: "每页项目数" }).selectOption("50");
    await page.waitForFunction(() => document.querySelectorAll('.as-project-data-row').length === 50);
    assert.equal(new URL(page.url()).searchParams.get("page"), null);
    // A late previous search must not replace the newer query's results.
    delayOldSearch = true;
    await page.getByRole("searchbox", { name: "搜索项目名称" }).fill("旧搜索");
    await page.waitForRequest((request) => new URL(request.url()).searchParams.get("nameSearch") === "旧搜索");
    await page.getByRole("searchbox", { name: "搜索项目名称" }).fill("分页 CRM");
    await page.locator(".as-project-data-row").filter({ hasText: "分页 CRM 项目" }).waitFor();
    await page.waitForTimeout(1100);
    assert.equal(await page.locator(".as-project-data-row").count(), 1);
    await page.getByText("1 个项目 · CRM 同步与本地新增", { exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("search"), "分页 CRM", "name-search wording must survive a page reload");
    await page.reload();
    await page.locator(".as-project-data-row").filter({ hasText: "分页 CRM 项目" }).waitFor();
    assert.equal(await page.getByRole("searchbox", { name: "搜索项目名称" }).inputValue(), "分页 CRM");
    assert.equal(await page.locator(".as-project-data-row").count(), 1);
    assert.equal(new URL(page.url()).searchParams.get("page"), null);
    await page.locator(".as-project-data-row").filter({ hasText: "分页 CRM 项目" }).click();
    await page.getByRole("navigation", { name: "售前项目流程" }).getByRole("button", { name: "前期方案，进行中", exact: true }).click();
    assert.equal(await page.getByRole("button", { name: "开始节点", exact: true }).count(), 0);
    assert.ok(await page.getByRole("button", { name: "节点通过", exact: true }).isEnabled());
    await page.getByRole("navigation", { name: "售前项目流程" }).getByRole("button", { name: /^前期立项，/ }).click();
    assert.match(await page.locator(".as-project-drawer-context__meta").innerText(), /当前节点\s*前期方案、预算匹配/);
    await page.getByRole("button", { name: "项目信息", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "项目信息", exact: true });
    for (const label of ["客户单位", "CRM 负责人", "项目名称", "项目信息"]) {
      assert.equal(await dialog.getByRole("textbox", { name: label, exact: true }).getAttribute("readonly"), "");
    }
    assert.equal(await dialog.getByRole("textbox", { name: "CRM 负责人", exact: true }).inputValue(), "CRM 负责人");
    assert.equal(await dialog.getByText(/联系电话/).count(), 0);
    assert.equal(await dialog.getByRole("textbox", { name: "申请理由（选填）" }).getAttribute("readonly"), "");
    assert.equal(await dialog.getByRole("button", { name: "立即保存" }).count(), 0);
    const patchCount = patches.length;
    await dialog.getByLabel("关闭", { exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
    assert.equal(patches.length, patchCount, "closing a completed node must not save its information");
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    await page.getByRole("searchbox", { name: "搜索项目名称" }).fill("");
    await page.getByRole("searchbox", { name: "搜索客户" }).fill("本地测试");
    const legacyRow = page.locator(".as-project-data-row").filter({ hasText: legacy.name });
    await legacyRow.waitFor();
    assert.equal(await page.locator(".as-project-data-row").count(), 1);
    // Cancellation preserves the local row; confirming deletes only that row.
    await legacyRow.getByRole("button", { name: `删除${legacy.name}`, exact: true }).click();
    const deleteDialog = page.getByRole("dialog", { name: "确认删除服务", exact: true });
    await deleteDialog.getByRole("button", { name: "取消", exact: true }).click();
    assert.deepEqual(deletedIds, []);
    await legacyRow.getByRole("button", { name: `删除${legacy.name}`, exact: true }).click();
    await deleteDialog.getByRole("button", { name: "确认删除", exact: true }).click();
    await page.getByText("没有符合条件的项目", { exact: true }).waitFor();
    assert.deepEqual(deletedIds, [102]);
    await page.getByRole("button", { name: "新增售前项目", exact: true }).click();
    const createDialog = page.getByRole("dialog", { name: "新增售前项目", exact: true });
    await createDialog.getByText("在服务中心独立维护，不关联 CRM；创建后进入前期立项流程。", { exact: true }).waitFor();
    await createDialog.getByRole("textbox", { name: "客户单位 *", exact: true }).fill("本地测试客户");
    await createDialog.getByRole("textbox", { name: "项目名称 *", exact: true }).fill("新建独立售前项目");
    assert.equal(await createDialog.getByText(/联系电话/).count(), 0);
    await createDialog.getByRole("button", { name: "确认新增", exact: true }).click();
    await createDialog.waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "项目信息", exact: true }).click();
    for (const label of ["客户单位", "负责人", "项目名称", "项目信息"]) {
      assert.equal(await dialog.getByRole("textbox", { name: label, exact: true }).getAttribute("readonly"), null);
    }
    assert.equal(creates.length, 1);
    assert.equal(creates[0].serviceType, "presales");
    assert.equal(Object.hasOwn(creates[0], "sourceCrmId"), false);
    assert.equal(creates[0].businessData.applicationReason, "");
    await dialog.getByRole("textbox", { name: "申请理由（选填）" }).fill("补充售前说明");
    await dialog.getByRole("button", { name: "立即保存" }).click();
    await dialog.waitFor({ state: "hidden" });
    assert.equal(patches.at(-1).businessData.applicationReason, "补充售前说明");
    await page.getByRole("button", { name: "项目信息", exact: true }).click();
    await dialog.getByRole("textbox", { name: "申请理由（选填）" }).fill("");
    await dialog.getByRole("button", { name: "立即保存" }).click();
    await dialog.waitFor({ state: "hidden" });
    assert.equal(patches.at(-1).businessData.applicationReason, "");
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    sourceFailure = true;
    await navigation.getByRole("button", { name: "总览", exact: true }).click();
    await navigation.getByRole("button", { name: "售前服务", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "本地项目仍可正常使用" }).waitFor();
    await page.locator(".as-project-data-row").filter({ hasText: "新建独立售前项目" }).waitFor();
    sourceFailure = false;
    await navigation.getByRole("button", { name: "售中服务" }).click();
    assert.equal(await crmStagePicker.count(), 0, "CRM stage filtering is specific to presales");
    await page.getByRole("button", { name: "新增售中项目" }).click();
    await page.getByRole("dialog").getByText("申请人联系电话 *", { exact: true }).waitFor();
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});

test("presales reuses a verified page after same-user re-login and isolates changed users and proxies", { timeout: 60000 }, async () => {
  const server = await createServer({ root, cacheDir: path.join(root, "../../../.codex-artifacts/vite-after-sales-crm-fast-list"), configFile: path.join(root, "vite.config.ts"), server: { host: "127.0.0.1", port: 0 } });
  let browser;
  let hold = false;
  let release;
  const heldRequests = [];
  let pending = false;
  let denied = false;
  let currentSession = "fast-presales-1";
  let currentUser = "service-admin";
  let proxying = false;
  const pageErrors = [];
  const requests = [];
  const crm = { id: 1, name: "缓存 CRM 项目", customer: "学校", serviceType: "presales", sourceCrmId: "crm-fast",
    ownerName: "负责人", currentNodeKey: "early-approval", statusLabel: "进行中" };
  const local = { ...crm, id: 2, name: "缓存本地项目", sourceCrmId: "" };
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.clock.install();
    await page.addInitScript(() => {
      if (!sessionStorage.getItem("mj_program_login_session")) sessionStorage.setItem("mj_program_login_session", JSON.stringify({
        sessionId: "fast-presales-1", userId: "service-admin", name: "当前管理员", loginType: "scan",
      }));
    });
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      requests.push(url.pathname + url.search);
      let body = { items: [] };
      if (url.pathname === "/api/auth/session/validate") {
        body = { sessionId: currentSession, userId: currentUser, name: "当前管理员", loginType: "scan", isProxying: proxying,
          actorUserId: proxying ? "actor-admin" : currentUser };
      } else if (url.pathname === "/api/after-sales/session/") {
        body = { canManageApp: true, canManageSettings: true, appPermission: "admin" };
      } else if (url.pathname === "/api/after-sales/projects" && url.searchParams.get("type") === "presales") {
        if (hold) await new Promise((resolve) => {
          heldRequests.push(resolve);
          release = () => heldRequests.splice(0).forEach((finish) => finish());
        });
        const ready = !denied;
        body = { items: ready ? [crm, local] : [local], total: ready ? 2 : 1, totalPages: 1, page: 1,
          crmScopeReady: ready, crmSyncing: pending, crmSyncError: denied ? "当前账号无权读取 CRM 项目" : "",
          crmScopeExpiresAt: ready ? new Date(await page.evaluate(() => Date.now()) + 300_000).toISOString() : "" };
      }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    const address = `http://127.0.0.1:${server.httpServer.address().port}/after-sales/presales/`;
    await page.goto(address);
    const navigation = page.getByRole("navigation", { name: "主导航" });
    await navigation.getByRole("button", { name: "售前服务", exact: true }).click();
    try {
      await page.getByText(crm.name, { exact: true }).waitFor({ timeout: 8000 });
    } catch (reason) {
      throw new Error(JSON.stringify({ body: await page.locator("body").innerText(), requests, pageErrors }), { cause: reason });
    }
    await page.waitForFunction(() => sessionStorage.getItem("mj-after-sales:presales-pages:v2"));
    hold = true;
    await page.reload();
    await navigation.getByRole("button", { name: "售前服务", exact: true }).click();
    await page.waitForFunction(() => document.body.innerText.includes("缓存 CRM 项目"));
    assert.ok(release, "the revalidation request should still be pending while cached rows are already visible");
    assert.equal(await page.getByText("正在加载项目...", { exact: false }).count(), 0);
    hold = false;
    release();
    await page.waitForFunction(() => JSON.parse(sessionStorage.getItem("mj-after-sales:presales-pages:v2")).pages.length > 0);
    await page.screenshot({ path: path.join(root, "../../../.codex-artifacts/after-sales-crm-fast-list.png") });

    // Background refresh keeps the valid page visible and publishes new rows
    // through the existing automatic polling, without a refresh button.
    pending = true;
    assert.equal(await page.getByRole("button", { name: "刷新 CRM 项目", exact: true }).count(), 0);
    await page.clock.fastForward(30_100);
    await page.getByRole("status").filter({ hasText: "正在后台更新" }).waitFor();
    assert.equal(await page.getByText(crm.name, { exact: true }).count(), 1, "valid rows must remain visible during refresh");
    pending = false;
    await page.clock.fastForward(1000);
    await page.getByRole("status").filter({ hasText: "正在后台更新" }).waitFor({ state: "hidden" });

    // With the API temporarily unavailable, the display cache still expires
    // at the verified scope deadline instead of lingering indefinitely.
    hold = true;
    await page.clock.fastForward(300_100);
    await page.getByText(crm.name, { exact: true }).waitFor({ state: "hidden" });
    assert.equal(await page.evaluate(() => sessionStorage.getItem("mj-after-sales:presales-pages:v2")), null);
    hold = false;
    release();
    await page.getByText(crm.name, { exact: true }).waitFor();
    denied = true;
    await page.clock.fastForward(30_100);
    await page.getByRole("alert").filter({ hasText: "无权读取" }).waitFor();
    assert.equal(await page.getByText(crm.name, { exact: true }).count(), 0);
    assert.equal(await page.getByText(local.name, { exact: true }).count(), 1);
    assert.equal(await page.evaluate(() => sessionStorage.getItem("mj-after-sales:presales-pages:v2")), null);

    denied = false;
    await page.clock.fastForward(30_100);
    await page.getByText(crm.name, { exact: true }).waitFor();
    currentSession = "fast-presales-2";
    await page.evaluate((sessionId) => {
      const session = JSON.parse(sessionStorage.getItem("mj_program_login_session"));
      session.sessionId = sessionId;
      sessionStorage.setItem("mj_program_login_session", JSON.stringify(session));
    }, currentSession);
    hold = true;
    await page.reload();
    await navigation.getByRole("button", { name: "售前服务", exact: true }).click();
    await page.getByText(crm.name, { exact: true }).waitFor();
    assert.ok(release, "same-user re-login must show the verified page before revalidation finishes");
    hold = false;
    release();
    await page.getByText(crm.name, { exact: true }).waitFor();
    for (const changed of [{ userId: "another-user", isProxying: false }, { userId: "another-user", isProxying: true }]) {
      currentUser = changed.userId;
      proxying = changed.isProxying;
      currentSession += "-changed";
      await page.evaluate((session) => sessionStorage.setItem("mj_program_login_session", JSON.stringify(session)), {
        sessionId: currentSession, userId: currentUser, name: "当前管理员", loginType: "scan", isProxying: proxying,
        actorUserId: proxying ? "actor-admin" : currentUser,
      });
      hold = true;
      await page.reload();
      await navigation.getByRole("button", { name: "售前服务", exact: true }).click();
      await page.getByText("正在加载项目...", { exact: false }).waitFor();
      assert.equal(await page.getByText(crm.name, { exact: true }).count(), 0, "changed identities cannot reuse the previous scope");
      hold = false;
      release();
      await page.getByText(crm.name, { exact: true }).waitFor();
      await page.waitForFunction(() => JSON.parse(sessionStorage.getItem("mj-after-sales:presales-pages:v2") || "null")?.pages.length > 0);
    }
    assert.deepEqual(pageErrors, []);
  } finally {
    release?.();
    await browser?.close();
    await server.close();
  }
});
