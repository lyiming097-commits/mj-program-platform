import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));

async function fixture(run) {
  const server = await createServer({ root, configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-statistics"),
    server: { host: "127.0.0.1", port: 0 } });
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const pdfPage = await browser.newPage();
    await pdfPage.setContent("<p>Read-only requirement document</p>");
    const pdf = await pdfPage.pdf({ format: "A4" });
    await pdfPage.close();
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    await page.clock.install();
    const requests = [], writes = [], errors = [];
    const state = { fail: false, syncing: false, releaseOld: null };
    const projects = Array.from({ length: 45 }, (_, index) => ({
      id: index + 1, name: `统计项目${index + 1}`, customer: "统计客户", serviceType: "presales",
      ownerUserId: index % 2 ? "sales-b" : "sales-a", ownerName: index % 2 ? "销售乙" : "销售甲",
      status: "in_progress", statusLabel: "进行中", currentNodeKey: "early-plan", latestStage: "前期方案、预算匹配",
      crmStage: "方案渗透", natures: [index % 2 ? "家具" : "设备"], amount: index ? null : "0.00",
      designOwners: [{ userId: "design-a", name: "设计甲" }], solutionOwners: [], participants: [],
      startedAt: "2026-10-19", totalArea: null, designArea: null, description: "完整的项目说明，供统计分析查看。",
      note: "项目补充备注", taskCount: 1, completedTaskCount: 0, requirementCount: 1, requirementNodeId: 11,
      tasks: [{ nodeKey: "early-plan", roundNumber: 1, name: "前期方案 · 第 1 轮",
        plannedStartDate: "2026-10-19", plannedEndDate: "2026-10-22", isCompleted: false, actualEndDate: null }],
      earlyTasks: [], filingTasks: [], tenderBaseTasks: [], bidTasks: [], constructionTasks: [],
      nodes: [{ id: 11, nodeKey: "early-plan", name: "前期方案", status: "active", enabled: true,
        kind: "delivery", sequence: 2, businessData: { schemeRounds: [{}] }, permissions: { canEdit: true } }],
      assignments: [], events: [], businessData: {}, permissions: { canManage: true, canDelete: true },
    }));
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => sessionStorage.setItem("mj_program_login_session", JSON.stringify({
      sessionId: "statistics-browser", userId: "statistics-admin", name: "统计用户", loginType: "scan",
    })));
    await page.route("**/api/**", async route => {
      const request = route.request(), url = new URL(request.url());
      requests.push(url.pathname + url.search);
      if (!["GET", "HEAD"].includes(request.method())) writes.push(url.pathname);
      if (url.pathname === "/api/after-sales/attachments/501/download") {
        await route.fulfill({ contentType: "application/pdf", body: pdf });
        return;
      }
      let body = { items: [] }, status = 200;
      if (url.pathname === "/api/auth/session/validate") body = { sessionId: "statistics-browser", userId: "statistics-admin", name: "统计用户", loginType: "scan" };
      else if (url.pathname === "/api/after-sales/session/") body = { canManageApp: true, canManageSettings: true, appPermission: "admin" };
      else if (url.pathname === "/api/after-sales/projects") body = { items: projects.slice(0, 20), total: 45, page: 1, totalPages: 3, crmScopeReady: true };
      else if (/\/projects\/\d+$/.test(url.pathname)) body = { item: projects.find(row => row.id === Number(url.pathname.split("/").at(-1))) };
      else if (url.pathname === "/api/after-sales/attachments") body = { items: [
        { id: 501, category: "general", originalName: "原始需求.pdf", size: pdf.length, contentType: "application/pdf", downloadUrl: "/api/after-sales/attachments/501/download" },
        { id: 502, category: "fee_estimated", originalName: "费用清单.xlsx", size: 20 },
      ] };
      else if (url.pathname === "/api/after-sales/presales/statistics") {
        if (url.searchParams.get("search") === "旧查询") await new Promise(resolve => { state.releaseOld = resolve; });
        if (state.fail) { status = 503; body = { error: "统计暂时无法读取" }; }
        else {
          const view = url.searchParams.get("groupBy") || "all", search = url.searchParams.get("search") || "";
          const rows = projects.filter(row => [row.name, row.customer, row.ownerName].some(value => value.includes(search)));
          const groups = new Map();
          for (const row of rows) {
            const entry = view === "nature" ? [`nature:${row.natures[0]}`, row.natures[0]]
              : view === "sales" ? [`sales:${row.ownerUserId}`, row.ownerName]
                : view === "stage" ? [`stage:${row.crmStage}`, row.crmStage] : ["design:design-a", "设计甲"];
            if (view !== "all") { const group = groups.get(entry[0]) || { key: entry[0], label: entry[1], count: 0, amount: null, activeCount: 0, completedCount: 0, knownAmountCount: 0 };
              group.count++; group.activeCount++; groups.set(entry[0], group); }
          }
          const key = url.searchParams.get("groupKey");
          const selected = key ? rows.filter(row => key === `nature:${row.natures[0]}` || key === `sales:${row.ownerUserId}` || key === `stage:${row.crmStage}` || key === "design:design-a") : rows;
          const size = Number(url.searchParams.get("pageSize") || 20), pages = Math.max(1, Math.ceil(selected.length / size));
          const current = Math.min(pages, Number(url.searchParams.get("page") || 1));
          body = { summary: { count: rows.length }, groupMembershipCount: rows.length, groups: [...groups.values()],
            groupBy: view, items: selected.slice((current - 1) * size, current * size), total: selected.length,
            page: current, pageSize: size, totalPages: pages, crmScopeReady: true,
            crmScopeExpiresAt: new Date(Date.now() + 600000).toISOString() };
          if (state.syncing) { state.syncing = false; body = { ...body, items: [], groups: [], crmSyncing: true, crmScopeReady: false }; }
        }
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    await run({ page, projects, state, requests, writes, base: `http://127.0.0.1:${server.httpServer.address().port}/after-sales/presales/` });
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, [], "statistics must not write business data");
  } finally { await browser?.close(); await server.close(); }
}

test("presales statistics groups authorized results, pages details, reuses the drawer and preserves list context", { timeout: 120000 }, async () => {
  await fixture(async ({ page, requests, base }) => {
    await page.goto(base + "?search=原有筛选");
    const tabs = page.getByRole("tablist", { name: "售前服务视图" });
    const statisticsTab = tabs.getByRole("tab", { name: "统计分析" });
    assert.equal(requests.filter(url => url.includes("presales/statistics")).length, 0);
    await tabs.getByRole("tab", { name: "项目列表" }).press("End");
    const panel = page.getByRole("tabpanel", { name: "统计分析" });
    const table = panel.getByRole("table", { name: "售前统计项目明细", exact: true });
    await table.getByRole("button", { name: "查看项目 统计项目1", exact: true }).waitFor();
    assert.equal(await statisticsTab.getAttribute("aria-selected"), "true");
    assert.equal(await statisticsTab.evaluate(el => el === document.activeElement), true);
    assert.equal(await table.locator("tbody tr").count(), 20);
    async function assertStageColumns() {
      const headings = await table.getByRole("columnheader").allTextContents();
      assert.equal(headings.includes("备注"), false, "no statistics view includes the removed remarks column");
      const nodeIndex = headings.indexOf("项目最新阶段");
      assert.ok(nodeIndex >= 0);
      assert.equal(headings[nodeIndex + 1], "CRM阶段", "CRM stage immediately follows current nodes in each view");
      const cells = table.locator("tbody tr").first().getByRole("cell");
      assert.equal(await cells.nth(nodeIndex).innerText(), "前期方案、预算匹配");
      assert.equal(await cells.nth(nodeIndex + 1).innerText(), "方案渗透");
    }
    await assertStageColumns();
    await table.getByText("￥0", { exact: true }).waitFor();
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-presales-statistics-1440.png"), fullPage: true });
    for (const label of ["按项目性质", "按项目阶段分", "按销售分", "按设计负责人"]) {
      await panel.getByRole("button", { name: label, exact: true }).click();
      const groups = panel.getByRole("table", { name: "售前分组统计", exact: true });
      await groups.locator("tbody button").first().waitFor();
      const selectedName = await groups.locator("tbody button").first().innerText();
      const collapse = panel.getByRole("button", { name: "收起分组统计", exact: true });
      assert.equal(await collapse.getAttribute("aria-expanded"), "true", "each category starts expanded");
      const grouped = page.waitForResponse(response => response.url().includes("presales/statistics") && new URL(response.url()).searchParams.has("groupKey"));
      await groups.locator("tbody button").first().click();
      await grouped;
      await groups.getByRole("button", { name: selectedName, exact: true, pressed: true }).waitFor();
      await assertStageColumns();
      const detail = panel.getByRole("region", { name: "售前统计项目明细", exact: true });
      const before = await detail.boundingBox();
      const filteredUrl = page.url();
      await collapse.focus();
      await collapse.press("Enter");
      await groups.waitFor({ state: "hidden" });
      const expand = panel.getByRole("button", { name: "展开分组统计", exact: true });
      assert.equal(await expand.getAttribute("aria-expanded"), "false");
      assert.ok((await detail.boundingBox()).y < before.y, "collapsing frees space for the project details");
      assert.equal(page.url(), filteredUrl, "collapsing preserves the selected group and pagination");
      await panel.getByText(`当前分组：${selectedName}`, { exact: true }).waitFor();
      if (label === "按项目性质") await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-statistics-groups-collapsed.png"), animations: "disabled" });
      await expand.press("Space");
      await groups.getByRole("button", { name: selectedName, exact: true, pressed: true }).waitFor();
      await collapse.click();
    }
    await panel.getByRole("button", { name: "按项目性质", exact: true }).click();
    await panel.getByRole("button", { name: "展开分组统计", exact: true }).waitFor();
    await panel.getByRole("button", { name: "全部项目", exact: true }).click();
    await panel.getByRole("button", { name: "按项目性质", exact: true }).click();
    await panel.getByRole("button", { name: "展开分组统计", exact: true }).click();
    await panel.getByRole("table", { name: "售前分组统计", exact: true }).waitFor();
    await panel.getByRole("button", { name: "全部项目", exact: true }).click();
    const pagination = panel.getByRole("navigation", { name: "售前统计明细分页" });
    await pagination.getByRole("button", { name: "下一页", exact: true }).click();
    await table.getByRole("button", { name: "查看项目 统计项目21", exact: true }).waitFor();
    await panel.getByRole("combobox", { name: "每页条数", exact: true }).selectOption("50");
    await table.getByRole("button", { name: "查看项目 统计项目45", exact: true }).waitFor();
    const firstRow = table.locator("tbody tr").first();
    await firstRow.getByRole("button", { name: "1 项任务", exact: true }).click();
    const tasks = page.getByRole("dialog", { name: "关联任务", exact: true });
    await tasks.getByRole("cell", { name: "未完成", exact: true }).waitFor();
    await tasks.press("Escape");
    await firstRow.getByRole("button", { name: "1 个文档", exact: true }).click();
    const attachments = page.getByRole("dialog", { name: "项目需求文档", exact: true });
    await attachments.getByText("原始需求.pdf", { exact: true }).waitFor();
    assert.ok(requests.some(request => {
      const url = new URL(request, "http://localhost");
      return url.pathname === "/api/after-sales/attachments" && url.searchParams.get("targetType") === "presales_project"
        && url.searchParams.get("targetId") === "1";
    }), "statistics reads requirement documents by project rather than the early approval node");
    assert.equal(await attachments.getByText("费用清单.xlsx", { exact: true }).count(), 0);
    assert.equal(await attachments.getByRole("button", { name: /上传|删除/ }).count(), 0);
    await attachments.getByRole("button", { name: "预览：原始需求.pdf", exact: true }).first().click();
    const preview = page.getByRole("dialog", { name: "原始需求.pdf", exact: true });
    await preview.waitFor();
    await preview.locator("canvas").first().waitFor();
    await preview.press("Escape");
    await attachments.waitFor();
    await attachments.press("Escape");
    await firstRow.getByRole("button", { name: "完整的项目说明，供统计分析查看。", exact: true }).click();
    const description = page.getByRole("dialog", { name: "项目说明", exact: true });
    await description.getByText("完整的项目说明，供统计分析查看。", { exact: true }).waitFor();
    await description.press("Escape");
    await firstRow.getByRole("button", { name: "查看项目 统计项目1", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "售前服务 · 项目详情", exact: true });
    await drawer.waitFor();
    await drawer.getByRole("heading", { name: "统计项目1", exact: true }).waitFor();
    const refreshed = page.waitForResponse(response => response.url().includes("presales/statistics"));
    await drawer.getByRole("button", { name: "关闭", exact: true }).first().click();
    await refreshed;
    assert.equal(await statisticsTab.getAttribute("aria-selected"), "true");
    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 960 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      const region = panel.getByRole("region", { name: "售前统计项目表格，可横向滚动" });
      const bounds = await region.evaluate(el => { el.scrollLeft = el.scrollWidth; return { scroll: el.scrollLeft,
        first: el.querySelector("tbody td").getBoundingClientRect().left, left: el.getBoundingClientRect().left }; });
      assert.ok(bounds.scroll > 0);
      assert.ok(Math.abs(bounds.first - bounds.left) <= 1, "project name stays visible during horizontal scrolling");
    }
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-presales-statistics-1024.png"), fullPage: true });
    await page.reload();
    await page.getByRole("tabpanel", { name: "统计分析" }).getByRole("button", { name: "查看项目 统计项目45", exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("statPageSize"), "50");
    await tabs.getByRole("tab", { name: "项目列表" }).click();
    assert.equal(await page.getByLabel("搜索项目名称", { exact: true }).inputValue(), "原有筛选");
    const before = requests.filter(url => url.includes("presales/statistics")).length;
    await page.clock.fastForward(31000);
    assert.equal(requests.filter(url => url.includes("presales/statistics")).length, before, "hidden statistics stop polling");
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await tabs.count(), 0, "desktop tabs do not change the phone view");
    await page.getByLabel("搜索项目名称", { exact: true }).waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  });
});

test("statistics recover from source sync and errors, and discard late search responses", { timeout: 60000 }, async () => {
  await fixture(async ({ page, state, base }) => {
    state.syncing = true;
    await page.goto(base + "?tab=statistics");
    await page.getByRole("status").filter({ hasText: "CRM 项目正在同步" }).waitFor();
    await page.clock.fastForward(1100);
    const panel = page.getByRole("tabpanel", { name: "统计分析" });
    const table = panel.getByRole("table", { name: "售前统计项目明细", exact: true });
    await table.getByRole("button", { name: "查看项目 统计项目1", exact: true }).waitFor();
    state.fail = true;
    await page.clock.fastForward(30100);
    await page.getByRole("alert").filter({ hasText: "统计暂时无法读取" }).waitFor();
    assert.equal(await table.getByRole("button", { name: /^查看项目/ }).count(), 0);
    state.fail = false;
    await panel.getByRole("button", { name: "重试", exact: true }).click();
    await table.getByRole("button", { name: "查看项目 统计项目1", exact: true }).waitFor();
    const search = panel.getByRole("searchbox", { name: "搜索售前统计项目", exact: true });
    const oldRequest = page.waitForRequest(request => request.url().includes("presales/statistics") && new URL(request.url()).searchParams.get("search") === "旧查询");
    await search.fill("旧查询"); await page.clock.fastForward(400); await oldRequest;
    await search.fill("统计项目45"); await page.clock.fastForward(400);
    await table.getByRole("button", { name: "查看项目 统计项目45", exact: true }).waitFor();
    const oldResponse = page.waitForResponse(response => response.url().includes("presales/statistics") && new URL(response.url()).searchParams.get("search") === "旧查询");
    state.releaseOld();
    await oldResponse;
    assert.equal(await table.getByRole("button", { name: "查看项目 统计项目45", exact: true }).count(), 1);
    assert.equal(new URL(page.url()).searchParams.get("statSearch"), "统计项目45");
  });
});

test("statistics allow page scrolling without squeezing tables and reuse the project list table theme", { timeout: 120000 }, async () => {
  await fixture(async ({ page, projects, base }) => {
    for (const [index, project] of projects.entries()) project.natures = [`项目性质${index + 1}`];
    projects[1].name = "YX-202609-0013浙江科技大学小和山校区-地板及多媒体教学设备更新项目";
    projects[2].name = "MJ-2026-10-0003-ABCDEFGHIJKLMNOPQRSTUVWXYZ-跨区域智慧教育设备更新项目";
    projects[2].crmCreatedAt = new Date().toISOString();
    await page.goto(base);
    const tabs = page.getByRole("tablist", { name: "售前服务视图" });
    const list = page.getByRole("tabpanel", { name: "项目列表" }).getByRole("table");
    await list.locator("tbody tr").first().waitFor();
    const theme = table => table.evaluate(element => {
      const values = selector => {
        const style = getComputedStyle(element.querySelector(selector));
        return Object.fromEntries(["padding", "color", "fontSize", "fontWeight", "textAlign",
          "borderBottom", "borderRight", "backgroundColor", "backgroundImage"].map(key => [key, style[key]]));
      };
      return { heading: values("thead th:nth-child(2)"), cell: values("tbody td:nth-child(2)"),
        alternate: getComputedStyle(element.querySelector("tbody tr:nth-child(2) td:nth-child(2)")).backgroundColor };
    });
    const listTheme = await theme(list);
    await tabs.getByRole("tab", { name: "统计分析" }).click();
    const panel = page.getByRole("tabpanel", { name: "统计分析" });
    const table = panel.getByRole("table", { name: "售前统计项目明细", exact: true });
    const region = panel.getByRole("region", { name: "售前统计项目表格，可横向滚动" });
    const pagination = panel.getByRole("navigation", { name: "售前统计明细分页" });
    await table.getByRole("button", { name: "查看项目 统计项目1", exact: true }).waitFor();
    assert.deepEqual(await theme(table), listTheme, "detail rows, borders, alignment, header and stripes match the project list");

    async function assertNamesContained() {
      for (const project of projects.slice(1, 3)) {
        const name = table.getByRole("button", { name: `查看项目 ${project.name}`, exact: true });
        const bounds = await name.evaluate(element => {
          const cell = element.closest("td").getBoundingClientRect();
          const text = element.querySelector("[title]");
          const icon = element.querySelector("svg").getBoundingClientRect();
          const badge = element.querySelector(".as-project-name__new")?.getBoundingClientRect();
          return { left: cell.left, right: cell.right, button: element.getBoundingClientRect().right,
            textRight: text.getBoundingClientRect().right, iconRight: icon.right, iconLeft: icon.left,
            iconWidth: icon.width, badgeRight: badge?.right, badgeWidth: badge?.width,
            truncated: text.scrollWidth > text.clientWidth, title: text.title };
        });
        assert.ok(bounds.button <= bounds.right && bounds.textRight <= bounds.right && bounds.iconRight <= bounds.right,
          `long names stay inside their column: ${JSON.stringify(bounds)}`);
        assert.ok(bounds.truncated, "long names are truncated instead of overlapping the next column");
        assert.ok(bounds.iconLeft >= bounds.left && bounds.iconWidth > 0, "the open-project icon remains visible");
        if (project.crmCreatedAt) assert.ok(bounds.badgeWidth > 0 && bounds.badgeRight <= bounds.right, "the new-project badge remains visible");
        assert.equal(bounds.title, project.name, "the full name is available on hover");
      }
    }

    async function assertReadable() {
      await page.evaluate(() => window.scrollTo(0, 0));
      await assertNamesContained();
      const footer = await pagination.locator("..").boundingBox();
      const scroll = await region.boundingBox();
      assert.ok(scroll.height >= 400 && scroll.y + scroll.height <= footer.y + 1,
        `the detail table has a readable height and pagination follows it: ${JSON.stringify({ scroll, footer })}`);
      assert.ok(await page.evaluate(() => document.documentElement.scrollHeight > innerHeight), "the page can scroll to fit readable tables");
      assert.ok(await region.evaluate(element => element.scrollHeight > element.clientHeight), "many rows scroll within the table");
      const before = await pagination.boundingBox();
      await region.evaluate(element => { element.scrollTop = element.scrollHeight; });
      assert.deepEqual(await pagination.boundingBox(), before, "scrolling rows does not move pagination");
      const heading = await table.locator("thead th").first().boundingBox();
      assert.ok(Math.abs(heading.y - scroll.y) <= 2, "the table header stays visible while scrolling rows");
      await region.evaluate(element => { element.scrollTop = 0; });
      await pagination.scrollIntoViewIfNeeded();
      const visibleFooter = await pagination.boundingBox();
      assert.ok(visibleFooter.y >= 0 && visibleFooter.y + visibleFooter.height <= page.viewportSize().height,
        "pagination is reachable by scrolling the page");
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "wide tables do not widen the page");
      await page.evaluate(() => window.scrollTo(0, 0));
    }

    for (const viewport of [{ width: 1440, height: 960 }, { width: 1024, height: 768 }]) {
      await page.setViewportSize(viewport);
      for (const size of [20, 50, 100]) {
        await panel.getByRole("combobox", { name: "每页条数", exact: true }).selectOption(String(size));
        await page.waitForFunction(expected => document.querySelector(".as-stat-details tbody").children.length === expected, Math.min(size, projects.length));
        await assertReadable();
      }
      await panel.getByRole("button", { name: "按项目性质", exact: true }).click();
      const groups = panel.getByRole("table", { name: "售前分组统计", exact: true });
      await groups.getByRole("button", { name: "项目性质45", exact: true }).waitFor({ state: "attached" });
      assert.deepEqual(await theme(groups), listTheme, "group tables use the same theme as the project list");
      const groupRegion = panel.getByRole("region", { name: "售前分组表格，可滚动查看" });
      assert.ok(await groupRegion.evaluate(element => element.scrollHeight > element.clientHeight), "many groups scroll independently");
      assert.ok((await groupRegion.boundingBox()).height >= 240, "the group table shows several rows instead of sharing a cramped viewport");
      await assertReadable();
      await region.evaluate(element => { element.scrollLeft = element.scrollWidth; });
      await assertNamesContained();
      await region.evaluate(element => { element.scrollLeft = 0; });
      await page.waitForFunction(() => document.querySelector(".as-stat-details")?.getAttribute("aria-busy") === "false"
        && document.querySelector(".as-stat-details tbody")?.children.length === 45);
      await page.screenshot({ path: path.resolve(root, `../../../.codex-artifacts/after-sales-statistics-layout-${viewport.width}.png`), animations: "disabled" });
      await panel.getByRole("button", { name: "全部项目", exact: true }).click();
    }
    await table.getByRole("button", { name: "查看项目 统计项目1", exact: true }).waitFor();
    await table.locator("tbody tr").first().getByRole("button", { name: "1 项任务", exact: true }).click();
    const tasks = page.getByRole("dialog", { name: "关联任务", exact: true }).getByRole("table", { name: "售前任务排期", exact: true });
    const taskTheme = await tasks.locator("thead th").first().evaluate(element => {
      const style = getComputedStyle(element);
      return { background: style.backgroundImage, fontSize: style.fontSize, textAlign: style.textAlign };
    });
    assert.deepEqual(taskTheme, { background: listTheme.heading.backgroundImage, fontSize: listTheme.heading.fontSize, textAlign: "center" });
    await page.getByRole("dialog", { name: "关联任务", exact: true }).getByLabel("关闭", { exact: true }).click();
    await tabs.getByRole("tab", { name: "项目列表", exact: true }).click();
    const listFooter = await page.getByRole("navigation", { name: "项目分页", exact: true }).boundingBox();
    assert.ok(listFooter.y >= 0 && listFooter.y + listFooter.height <= page.viewportSize().height,
      "the original project list still keeps pagination in the viewport");
  });
});
