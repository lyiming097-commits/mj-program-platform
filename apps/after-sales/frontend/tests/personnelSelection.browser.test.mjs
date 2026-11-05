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
const fixtureId = "/__personnel-selection.js";
const fixture = `
import { createApp } from 'vue';
import '/src/styles.css';
import ProjectWorkspace from '/src/components/ProjectWorkspace.vue';
import ProjectCollaborationPanel from '/src/components/ProjectCollaborationPanel.vue';
const serviceType = new URL(location.href).searchParams.get('type');
createApp(serviceType === 'collaboration' ? ProjectCollaborationPanel : ProjectWorkspace,
  { serviceType, session: { userId: 'admin' } }).mount('#app');
`;

test("personnel names are the selection controls across project workspaces and tickets", { timeout: 90000 }, async () => {
  const server = await createServer({
    root, base: "/", configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-personnel"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "personnel-selection-fixture",
      resolveId(id) { if (id === fixtureId) return id; },
      load(id) { if (id === fixtureId) return fixture; },
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (!request.url?.startsWith("/__personnel-selection?")) return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<div id="app"></div><script type="module" src="${fixtureId}"></script>`);
        });
      },
    }],
  });
  const makeNode = (id, key, name, kind, status, sequence) => ({
    id, nodeKey: key, name, kind, status, enabled: true, sequence,
    statusLabel: status === "active" ? "进行中" : "未开始",
    plannedStartAt: "2026-10-14T09:00:00", plannedEndAt: "2026-10-15T18:00:00",
    updatedAt: "2026-10-14T01:00:00+00:00",
    permissions: { canEdit: true, canAssign: true },
    businessData: {},
  });
  const projects = [
    { id: 201, code: "PS201", name: "售前人员测试", serviceType: "presales", sourceCrmId: "crm-project-201", currentNodeKey: "early-approval", ownerName: "销售甲",
      nodes: [makeNode(2011, "early-approval", "前期立项", "approval", "active", 1),
        makeNode(2012, "early-plan", "前期方案", "delivery", "pending", 2),
        makeNode(2013, "budget-match", "预算匹配", "delivery", "pending", 3),
        makeNode(2014, "project-filing", "项目申报", "delivery", "pending", 4)] },
    { id: 202, code: "MS202", name: "售中人员测试", serviceType: "midsales", currentNodeKey: "midsales-project",
      nodes: [makeNode(2021, "midsales-project", "项目立项", "approval", "active", 1),
        makeNode(2022, "construction-work", "工程施工", "delivery", "pending", 2)] },
    { id: 203, code: "AS203", name: "售后人员测试", serviceType: "aftersales", currentNodeKey: "onsite-service",
      nodes: [makeNode(2031, "onsite-service", "上门售后", "delivery", "pending", 1)] },
  ].map(project => ({ status: "in_progress", customer: "测试学校", assignments: [], events: [], businessData: {},
    permissions: { canManage: true, canDelete: true }, ...project }));
  const employees = [
    { userId: "employee-1", name: "张工", pinyin: "zhanggong", pinyinInitials: "zg", departments: [{ deptId: "technical", name: "技术部", pinyin: "jishubu", pinyinInitials: "jsb" }] },
    { userId: "employee-2", name: "李工", pinyin: "ligong", pinyinInitials: "lg", departments: [{ deptId: "sales", name: "业务部", pinyin: "yewubu", pinyinInitials: "ywb" }] },
  ];
  const providers = [
    { id: 501, name: "王师傅", roleLabel: "安装人员", city: "杭州", status: "certified" },
    { id: 502, name: "赵师傅", roleLabel: "维修人员", city: "宁波", status: "certified" },
  ];
  const ticket = { id: 601, code: "TK601", title: "人员分派测试工单", projectId: 203, projectName: "售后人员测试",
    nodeKey: "onsite-service", status: "assigned", ticketType: "issue", priority: "normal",
    ownerUserId: "employee-1", ownerName: "张工", description: "测试处理人原位更换", businessData: {},
    permissions: { canManage: true, canProcess: true, canMessage: true } };
  const nodeWrites = [];
  const assignmentWrites = [];
  let rejectNodeWrite = false;
  let holdPersonnelWrite = null;
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const pageErrors = [];
    const requestErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("requestfailed", request => requestErrors.push(`${request.url()}: ${request.failure()?.errorText}`));
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      const method = route.request().method();
      const payload = ["POST", "PATCH"].includes(method) ? route.request().postDataJSON() : {};
      let body = { items: [] };
      let status = 200;
      if (url.pathname === "/api/after-sales/projects") {
        body = { items: projects.filter(project => project.serviceType === url.searchParams.get("type")), total: 1, totalPages: 1, page: 1 };
      } else if (url.pathname === "/api/crm/opportunities/crm-project-201/solution-products") {
        body = { opportunityId: "crm-project-201", projectDetailUrl: "/maijie-mall/#/opportunity/42/solution/7" };
      } else if (url.pathname === "/api/after-sales/employees/directory") body = { items: employees };
      else if (url.pathname === "/api/after-sales/providers") body = { items: providers };
      else if (/^\/api\/after-sales\/projects\/\d+/.test(url.pathname)) {
        const parts = url.pathname.split("/");
        const project = projects.find(project => String(project.id) === parts[4]);
        body = { item: project };
        if (parts[7] === "rounds" && method === "POST") {
          const node = project.nodes.find(node => node.nodeKey === parts[6]);
          assert.equal(payload.expectedUpdatedAt, node.updatedAt);
          const rounds = node.businessData.schemeRounds;
          if (parts[8] === "prepare-forward") {
            rounds.forEach((round, index) => { round.roundId ||= `personnel-round-${index}`; });
            body = { item: project, roundId: rounds[payload.roundIndex].roundId };
          } else {
            assert.equal(payload.action, "add_round");
            assert.ok(payload.reason.trim());
            rounds.push({ roundId: `personnel-round-${rounds.length}`, reason: payload.reason,
              plannedStartDate: "", plannedEndDate: "", note: "", attachmentIds: [] });
          }
        } else if (parts[5] === "nodes" && method === "PATCH") {
          nodeWrites.push({ projectId: project.id, nodeKey: parts[6], payload });
          if (rejectNodeWrite) {
            rejectNodeWrite = false;
            status = 503;
            body = { ok: false, error: "人员保存失败，请重试" };
          } else {
            const node = project.nodes.find(node => node.nodeKey === parts[6]);
            const { businessData, ...values } = payload;
            if (businessData?.managementAssignment && holdPersonnelWrite) {
              const held = holdPersonnelWrite;
              holdPersonnelWrite = null;
              await held;
            }
            assert.equal(payload.expectedUpdatedAt, node.updatedAt, "node saves use the latest confirmed version");
            Object.assign(node, values);
            node.updatedAt = new Date(Date.parse(node.updatedAt) + 1000).toISOString();
            if (businessData?.projectLeads) {
              businessData.projectLeads = { ...node.businessData.projectLeads, ...businessData.projectLeads };
              project.projectLeads = businessData.projectLeads;
            }
            node.businessData = { ...node.businessData, ...businessData };
          }
        } else if (parts[5] === "assignments" && method === "POST") {
          assignmentWrites.push({ projectId: project.id, payload });
          const assignment = { id: project.id * 10, ...payload, status: "assigned",
            provider: providers.find(provider => provider.id === payload.providerId) };
          project.assignments = [...project.assignments.filter(item => item.nodeKey !== payload.nodeKey), assignment];
          body = { item: assignment };
        }
      } else if (url.pathname === "/api/after-sales/tickets") body = { items: [ticket] };
      else if (url.pathname === "/api/after-sales/tickets/601") {
        if (method === "PATCH") Object.assign(ticket, payload);
        body = { item: ticket };
      }
      for (const project of projects) {
        for (const node of project.nodes) {
          node.permissions = { canEdit: node.status !== "completed", canAssign: node.status !== "completed" };
        }
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    async function openProject(type) {
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const failedBefore = requestErrors.length;
        await page.goto(`${origin}/__personnel-selection?type=${type}`);
        try {
          await page.locator(".as-project-data-row").filter({ hasText: projects.find(project => project.serviceType === type).name }).click({ timeout: 10000 });
          break;
        } catch (error) {
          // Network interface changes on this shared server can interrupt local
          // Chromium module requests. Retry only that explicit transport error.
          if (attempt < 2 && requestErrors.slice(failedBefore).some(message => message.includes("ERR_NETWORK_CHANGED"))) continue;
          await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-personnel-failed.png"), fullPage: true });
          throw new Error(`${error.message}\nPage errors: ${pageErrors.join('; ')}\nRequests: ${requestErrors.join('; ')}\nBody: ${await page.locator('body').innerText()}`);
        }
      }
      await page.locator(".as-node-main").waitFor();
    }
    async function expandSection(title) {
      const summary = page.locator(".as-node-main summary").filter({ hasText: title }).last();
      await summary.evaluate(element => { element.parentElement.open = true; });
    }
    async function choosePerson(trigger, name, management = true) {
      await trigger.click();
      const dialog = page.getByRole("dialog", { name: management ? "选择钉钉项目人员" : "选择服务人员", exact: true });
      if (management) {
        const clear = dialog.getByRole("button", { name: "清空", exact: true });
        if (await clear.isEnabled()) await clear.click();
        await dialog.getByLabel(`选择${name}`, { exact: true }).check();
        await dialog.getByRole("button", { name: "确认选择", exact: true }).click();
      } else await dialog.getByRole("button").filter({ hasText: name }).click();
      await dialog.waitFor({ state: "hidden" });
    }

    await openProject("presales");
    await expandSection("项目人员");
    const projectRow = page.locator(".as-project-data-row").first();
    const projectHeaders = await page.locator(".as-project-table thead tr").first().locator("th").allTextContents();
    for (const title of ["销售负责人", "设计负责人", "方案负责人"]) {
      assert.ok(projectHeaders.includes(title), JSON.stringify(projectHeaders));
    }
    assert.equal(await projectRow.locator("td").count(), 9);
    await choosePerson(page.getByRole("button", { name: "设计负责人：未选择，点击选择", exact: true }), "张工");
    await choosePerson(page.getByRole("button", { name: "方案负责人：未选择，点击选择", exact: true }), "李工");
    assert.deepEqual(projects[0].projectLeads.design.members, [{ userId: "employee-1", name: "张工" }]);
    assert.deepEqual(projects[0].projectLeads.solution.members, [{ userId: "employee-2", name: "李工" }]);
    assert.equal(await projectRow.locator("td").nth(5).innerText(), "销售甲");
    assert.equal(await projectRow.locator("td").nth(6).innerText(), "张工");
    assert.equal(await projectRow.locator("td").nth(7).innerText(), "李工");
    assert.ok(projects[0].nodes.slice(1).every(node => !node.businessData.managementAssignment), "project roles do not assign executors");
    await page.getByRole("button", { name: "设计负责人：张工，点击更换", exact: true }).click();
    const leadDialog = page.getByRole("dialog", { name: "选择钉钉项目人员", exact: true });
    assert.equal(await leadDialog.getByRole("checkbox").count(), 0, "project leads use single-selection controls");
    await leadDialog.getByRole("radio", { name: "选择李工", exact: true }).check();
    assert.equal(await leadDialog.getByRole("radio", { checked: true }).count(), 1);
    assert.equal(await leadDialog.getByRole("radio", { name: "选择张工", exact: true }).isChecked(), false);
    await leadDialog.getByRole("button", { name: "取消", exact: true }).click();
    await leadDialog.waitFor({ state: "hidden" });
    assert.equal(projects[0].projectLeads.design.name, "张工", "cancel does not save temporary choices");
    rejectNodeWrite = true;
    await page.getByRole("button", { name: "设计负责人：张工，点击更换", exact: true }).click();
    await leadDialog.getByRole("radio", { name: "选择李工", exact: true }).check();
    await leadDialog.getByRole("button", { name: "确认选择", exact: true }).click();
    await leadDialog.getByRole("alert").filter({ hasText: "人员保存失败，请重试" }).waitFor();
    assert.equal(projects[0].projectLeads.design.name, "张工", "failed saves preserve saved people");
    assert.equal(await leadDialog.getByRole("radio", { name: "选择张工", exact: true }).isChecked(), false);
    assert.ok(await leadDialog.getByRole("radio", { name: "选择李工", exact: true }).isChecked());
    await leadDialog.getByRole("button", { name: "确认选择", exact: true }).click();
    await leadDialog.waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "设计负责人：李工，点击更换", exact: true }).waitFor();
    assert.deepEqual(projects[0].projectLeads.design.userIds, ["employee-2"]);
    assert.equal(await projectRow.locator("td").nth(6).innerText(), "李工");
    assert.equal(projects[0].projectLeads.solution.name, "李工", "changing one role preserves the other");
    await page.getByRole("button", { name: "设计负责人：李工，点击更换", exact: true }).click();
    await leadDialog.getByRole("button", { name: "清空", exact: true }).click();
    assert.equal(await leadDialog.getByRole("radio", { checked: true }).count(), 0);
    await leadDialog.getByRole("button", { name: "确认选择", exact: true }).click();
    await leadDialog.waitFor({ state: "hidden" });
    assert.deepEqual(projects[0].projectLeads.design.members, []);
    assert.equal(projects[0].projectLeads.solution.name, "李工", "clearing one role preserves the other");
    await choosePerson(page.getByRole("button", { name: "设计负责人：未选择，点击选择", exact: true }), "李工");
    await openProject("presales");
    await expandSection("项目人员");
    await page.getByRole("button", { name: "设计负责人：李工，点击更换", exact: true }).waitFor();
    await page.getByRole("button", { name: "方案负责人：李工，点击更换", exact: true }).waitFor();
    await page.locator(".as-project-drawer-close").click();
    await page.locator(".as-node-main").waitFor({ state: "hidden" });
    await page.getByRole("dialog", { name: "售前服务 · 项目详情", exact: true, includeHidden: true }).waitFor({ state: "hidden" });
    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "the added columns scroll inside the table");
      await page.locator(".as-project-table-scroll").evaluate(element => { element.scrollLeft = element.scrollWidth; });
      const tableBounds = await page.locator(".as-project-table-scroll").boundingBox();
      const actionBounds = await page.locator(".as-project-operation-cell").first().boundingBox();
      assert.ok(actionBounds.x + actionBounds.width <= tableBounds.x + tableBounds.width + 1, "the operation column remains accessible");
      await page.screenshot({ path: path.resolve(root, `../../../.codex-artifacts/after-sales-project-leads-list-${width}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.locator(".as-project-table-scroll").evaluate(element => { element.scrollLeft = 0; });
    await projectRow.click();
    await expandSection("项目人员");
    const rows = page.locator(".as-presales-assignee");
    assert.equal(await rows.locator('input[type="date"]').count(), 0, "presales personnel have no node schedules");
    assert.equal(await page.locator(".as-presales-assignee-head > *").count(), 3);
    const firstRow = rows.filter({ hasText: "前期方案" });
    assert.equal(await firstRow.getByRole("button").count(), 1, "only the displayed person is a personnel action");
    assert.equal(await page.getByRole("button", { name: /^(选择|更换)项目人员$/ }).count(), 0);
    assert.equal(await page.locator(".as-presales-assignee-head").getByText("操作", { exact: true }).count(), 0);
    await choosePerson(firstRow.getByRole("button", { name: "前期方案项目人员：未选择，点击选择" }), "张工");
    const selectedTrigger = () => firstRow.getByRole("button", { name: "前期方案项目人员：张工，点击更换" });
    await selectedTrigger().waitFor();
    assert.equal(projects[0].nodes[1].businessData.managementAssignment.userId, "employee-1");
    await selectedTrigger().click();
    await page.getByRole("dialog", { name: "选择钉钉项目人员" }).getByRole("button", { name: "关闭", exact: true }).click();
    await selectedTrigger().waitFor();
    await selectedTrigger().click();
    const multiDialog = page.getByRole("dialog", { name: "选择钉钉项目人员", exact: true });
    const memberSearch = multiDialog.getByRole("searchbox");
    await memberSearch.fill("Li Gong");
    assert.equal(await multiDialog.getByRole("checkbox").count(), 1);
    await multiDialog.getByRole("checkbox", { name: "选择李工", exact: true }).check();
    await memberSearch.fill("ji-shu-bu");
    assert.equal(await multiDialog.getByRole("checkbox").count(), 1);
    assert.ok(await multiDialog.getByRole("checkbox", { name: "选择张工", exact: true }).isChecked());
    await memberSearch.fill("");
    await multiDialog.getByRole("status").filter({ hasText: "已选择 2 人" }).waitFor();
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-personnel-multiple.png") });
    await multiDialog.getByRole("button", { name: "确认选择", exact: true }).click();
    await multiDialog.waitFor({ state: "hidden" });
    const multipleTrigger = firstRow.getByRole("button", { name: "前期方案项目人员：张工，点击更换" });
    await firstRow.getByRole("button", { name: "前期方案项目人员：李工，点击更换" }).waitFor();
    assert.equal(await firstRow.locator(".as-presales-personnel-row").count(), 2, "each selected person gets a separate row");
    assert.deepEqual(projects[0].nodes[1].businessData.managementAssignment.userIds, ["employee-1", "employee-2"]);
    let releasePersonnelWrite;
    holdPersonnelWrite = new Promise(resolve => { releasePersonnelWrite = resolve; });
    const firstNote = firstRow.getByRole("textbox", { name: "前期方案张工的工作说明", exact: true });
    const secondNote = firstRow.getByRole("textbox", { name: "前期方案李工的工作说明", exact: true });
    const firstSaveStarted = page.waitForRequest(request => request.method() === "PATCH" && request.postDataJSON()?.businessData?.managementAssignment?.members?.[0]?.note === "张工负责设计");
    await firstNote.fill("张工负责设计");
    await firstNote.blur();
    await firstSaveStarted;
    await secondNote.fill("李工负责预算");
    const bothSaved = page.waitForResponse(response => response.request().method() === "PATCH"
      && response.request().postDataJSON()?.businessData?.managementAssignment?.members?.[1]?.note === "李工负责预算");
    releasePersonnelWrite();
    await secondNote.blur();
    await bothSaved;
    assert.deepEqual(projects[0].nodes[1].businessData.managementAssignment.members.map(member => member.note), ["张工负责设计", "李工负责预算"]);
    assert.equal(await firstNote.inputValue(), "张工负责设计");
    assert.equal(await secondNote.inputValue(), "李工负责预算", "another person's in-flight save does not reset the current input");
    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      const personRows = firstRow.locator(".as-presales-personnel-row");
      const bounds = await personRows.evaluateAll(elements => elements.map(element => {
        const member = element.querySelector(".as-personnel-picker").getBoundingClientRect();
        const note = element.querySelector("input").getBoundingClientRect();
        return { memberX: member.x, memberWidth: member.width, memberHeight: member.height, memberBottom: member.bottom, noteX: note.x, noteWidth: note.width, noteBottom: note.bottom, top: element.getBoundingClientRect().top };
      }));
      assert.equal(bounds[0].memberX, bounds[1].memberX);
      assert.equal(bounds[0].noteX, bounds[1].noteX);
      assert.ok(bounds[1].top >= bounds[0].memberBottom);
      assert.ok(bounds.every(row => row.memberWidth <= 180 && row.memberHeight === 36), "desktop personnel controls remain compact");
      assert.ok(bounds.every(row => row.noteWidth > row.memberWidth), "work notes have more room than the personnel column");
      const leadWidths = await page.locator(".as-presales-project-leads .as-personnel-picker").evaluateAll(elements => elements.map(element => element.getBoundingClientRect().width));
      assert.ok(leadWidths.length === 2 && leadWidths.every(width => width <= 200), "project lead buttons do not stretch across the panel");
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: path.resolve(root, `../../../.codex-artifacts/after-sales-personnel-individual-rows-${width}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "mobile personnel editor does not overflow");
    assert.deepEqual(await firstRow.locator(".as-personnel-picker").first().evaluate(element => ({
      minHeight: getComputedStyle(element).minHeight,
      maxWidth: getComputedStyle(element).maxWidth,
      detailDisplay: getComputedStyle(element.querySelector("small")).display,
    })), { minHeight: "42px", maxWidth: "none", detailDisplay: "block" }, "desktop styling leaves the mobile picker unchanged");
    await page.setViewportSize({ width: 1440, height: 900 });
    await openProject("presales");
    await expandSection("项目人员");
    assert.equal(await firstNote.inputValue(), "张工负责设计");
    assert.equal(await secondNote.inputValue(), "李工负责预算");
    await multipleTrigger.click();
    assert.ok(await multiDialog.getByRole("checkbox", { name: "选择张工", exact: true }).isChecked());
    assert.ok(await multiDialog.getByRole("checkbox", { name: "选择李工", exact: true }).isChecked());
    await multiDialog.getByRole("button", { name: "移除张工", exact: true }).click();
    await multiDialog.getByRole("button", { name: "确认选择", exact: true }).click();
    await multiDialog.waitFor({ state: "hidden" });
    await firstRow.getByRole("button", { name: "前期方案项目人员：李工，点击更换" }).waitFor();
    assert.equal(projects[0].nodes[1].businessData.managementAssignment.userId, "employee-2");
    assert.equal(projects[0].nodes[1].businessData.managementAssignment.members[0].note, "李工负责预算", "removing another person preserves this person's work note");
    for (const viewport of [{ width: 1440, height: 900 }, { width: 1024, height: 768 }]) {
      await page.setViewportSize(viewport);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "no page overflow");
      const cells = await firstRow.evaluate(element => Array.from(element.children, child => child.getBoundingClientRect().width));
      assert.equal(cells.length, 2);
      assert.ok(cells.every(width => width > 0));
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: path.join(root, "../../../.codex-artifacts/after-sales-personnel-selection.png") });

    // Delivery-node reselection must preserve all planned/actual times and assignment notes.
    projects[0].currentNodeKey = "early-plan";
    projects[0].nodes[0].status = "completed";
    projects[0].nodes[1].status = "active";
    projects[0].nodes[1].actualStartAt = "2026-10-14T10:30:00";
    projects[0].nodes[1].businessData.managementAssignment = { userId: "employee-2", name: "李工", note: "原工作说明" };
    projects[0].nodes[1].businessData.schemeRounds = [{ designDate: "2000-01-02", note: "原轮次备注", attachmentIds: [] }];
    const times = [projects[0].nodes[1].plannedStartAt, projects[0].nodes[1].plannedEndAt, projects[0].nodes[1].actualStartAt];
    await openProject("presales");
    await expandSection("项目人员");
    assert.equal(await page.getByRole("textbox", { name: "前期方案李工的工作说明", exact: true }).inputValue(), "原工作说明", "legacy notes remain visible on the person's row");
    await choosePerson(page.getByRole("button", { name: "前期方案项目人员：李工，点击更换" }), "张工");
    await page.getByRole("button", { name: "前期方案项目人员：张工，点击更换" }).waitFor();
    assert.deepEqual([projects[0].nodes[1].plannedStartAt, projects[0].nodes[1].plannedEndAt, projects[0].nodes[1].actualStartAt], times);
    assert.equal(projects[0].nodes[1].businessData.managementAssignment.members[0].note, "", "a different person starts with their own blank work note");
    assert.deepEqual(Object.keys(nodeWrites.at(-1).payload).sort(), ["businessData", "expectedUpdatedAt"]);
    rejectNodeWrite = true;
    await page.getByRole("button", { name: "前期方案项目人员：张工，点击更换" }).click();
    const failedDialog = page.getByRole("dialog", { name: "选择钉钉项目人员" });
    await failedDialog.getByRole("checkbox", { name: "选择张工", exact: true }).uncheck();
    await failedDialog.getByRole("checkbox", { name: "选择李工", exact: true }).check();
    await failedDialog.getByRole("button", { name: "确认选择", exact: true }).click();
    await page.getByText("人员保存失败，请重试", { exact: true }).first().waitFor();
    assert.equal(projects[0].nodes[1].businessData.managementAssignment.userId, "employee-1");
    await failedDialog.getByRole("button", { name: "确认选择", exact: true }).click();
    await failedDialog.waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "前期方案项目人员：李工，点击更换" }).waitFor();

    const directNote = page.getByRole("textbox", { name: "前期方案李工的工作说明", exact: true });
    rejectNodeWrite = true;
    const failedNoteSave = page.waitForResponse(response => response.status() === 503 && response.url().includes("/nodes/early-plan"));
    await directNote.fill("负责方案与预算复核");
    await directNote.blur();
    await failedNoteSave;
    await page.getByText("人员保存失败，请重试", { exact: true }).first().waitFor();
    assert.equal(await directNote.inputValue(), "负责方案与预算复核", "a failed save retains the person's note draft");
    assert.equal(projects[0].nodes[1].businessData.managementAssignment.members[0].note, "");
    const retriedNoteSave = page.waitForResponse(response => response.ok() && response.request().method() === "PATCH"
      && response.request().postDataJSON()?.businessData?.managementAssignment?.members?.[0]?.note === "负责方案与预算复核");
    await page.getByRole("button", { name: "重试保存", exact: true }).click();
    await retriedNoteSave;

    // Round schedules persist through the actual workspace autosave flow.
    await expandSection("前期方案推进");
    const roundField = (number, label) => page.getByLabel(`第 ${number} 次前期方案设计${label}`, { exact: true });
    async function fillRound(number, label, value) {
      const field = roundField(number, label);
      await field.waitFor();
      await page.waitForFunction(label => !document.querySelector(`input[aria-label="${label}"]`)?.disabled,
        `第 ${number} 次前期方案设计${label}`);
      const written = page.waitForResponse(response => response.request().method() === "PATCH" && response.url().includes("/nodes/early-plan"));
      await field.fill(value);
      await written;
    }
    assert.equal(await roundField(1, "实际完成时间").count(), 0);
    await fillRound(1, "计划开始时间", "2000-01-01");
    await fillRound(1, "预计完成时间", "2000-01-03");
    await page.locator(".as-presales-task-status").filter({ hasText: /^已延期 \d+ 天$/ }).waitFor();
    await page.getByRole("button", { name: "新增一轮", exact: true }).click();
    const roundReason = page.getByRole("dialog", { name: "新增一轮", exact: true });
    await roundReason.getByLabel(/新增原因/).fill("补充客户反馈的要求");
    await roundReason.getByRole("button", { name: "确认新增", exact: true }).click();
    const newSubmission = page.getByRole("dialog", { name: "第 2 次提交", exact: true });
    await newSubmission.getByRole("button", { name: "保存并关闭", exact: true }).click();
    await roundField(2, "计划开始时间").waitFor();
    await fillRound(2, "预计完成时间", "2099-10-20");
    assert.equal(await roundField(1, "预计完成时间").getAttribute("readonly"), "");
    assert.equal(await roundField(1, "预计完成时间").inputValue(), "2000-01-03");
    await page.getByText("未超时", { exact: true }).first().waitFor();
    assert.equal(await roundField(2, "预计完成时间").inputValue(), "2099-10-20");
    assert.equal(await roundField(2, "计划开始时间").inputValue(), "");
    assert.equal(await roundField(2, "实际完成时间").count(), 0);
    await openProject("presales");
    await expandSection("前期方案推进");
    await roundField(1, "预计完成时间").waitFor();
    assert.equal(await roundField(1, "预计完成时间").inputValue(), "2000-01-03");
    assert.equal(await roundField(1, "实际完成时间").count(), 0);
    assert.equal(projects[0].nodes[1].businessData.schemeRounds[0].designDate, "2000-01-02", "history is preserved");
    assert.equal(projects[0].nodes[1].businessData.managementAssignment.members[0].note, "负责方案与预算复核", "round autosave preserves personal instructions");
    assert.equal(await roundField(2, "预计完成时间").inputValue(), "2099-10-20");
    const roundWrites = nodeWrites.filter(write => write.projectId === 201 && write.payload.businessData?.schemeRounds);
    assert.ok(roundWrites.some(write => write.payload.businessData.schemeRounds.length === 2));
    assert.ok(roundWrites.every(write => !("plannedStartAt" in write.payload) && !("plannedEndAt" in write.payload)));
    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      const dates = await page.locator(".as-presales-task-dates").first().boundingBox();
      const card = await page.locator(".as-presales-round--scheduled").first().boundingBox();
      assert.ok(dates.x >= card.x && dates.x + dates.width <= card.x + card.width + 1,
        JSON.stringify({ viewport: width, dates, card }));
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
      await page.screenshot({ path: path.resolve(root, `../../../.codex-artifacts/after-sales-round-schedules-${width}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 1440, height: 900 });

    await page.getByRole("button", { name: "第 1 次提交：查看附件和备注" }).click();
    const submission = page.getByRole("dialog", { name: "第 1 次提交", exact: true });
    const mallLink = submission.getByRole("link", { name: "打开商城方案" });
    await mallLink.waitFor();
    assert.equal(await mallLink.getAttribute("href"), `${origin}/maijie-mall/#/opportunity/42/solution/7`);
    assert.equal(await submission.getByLabel("备注", { exact: true }).getAttribute("readonly"), "");
    await submission.getByRole("button", { name: "关闭", exact: true }).last().click();
    await submission.waitFor({ state: "hidden" });

    // Returning to a completed approval must not expose personnel or info edits.
    await page.getByRole("button", { name: /^前期立项，/ }).click();
    await expandSection("项目人员");
    const oldPersonnel = page.locator(".as-presales-assignee");
    for (const role of ["设计负责人", "方案负责人"]) {
      assert.ok(await page.getByRole("button", { name: `${role}：李工，点击更换`, exact: true }).isDisabled());
    }
    for (const button of await oldPersonnel.getByRole("button").all()) assert.ok(await button.isDisabled());
    for (const input of await oldPersonnel.locator("input").all()) assert.ok(await input.isDisabled());
    await page.getByRole("button", { name: "项目信息", exact: true }).click();
    const historicalInfo = page.getByRole("dialog", { name: "项目信息", exact: true });
    assert.equal(await historicalInfo.getByLabel("申请理由（选填）").getAttribute("readonly"), "");
    assert.equal(await historicalInfo.getByRole("button", { name: "立即保存", exact: true }).count(), 0);
    assert.equal(await historicalInfo.locator('input[type="file"]').count(), 0);
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-history-readonly.png") });
    await historicalInfo.getByRole("button", { name: "关闭", exact: true }).last().click();

    await openProject("midsales");
    await expandSection("项目人员");
    await choosePerson(page.getByRole("button", { name: "工程施工服务人员：未选择，点击选择" }), "王师傅", false);
    await page.getByRole("button", { name: "工程施工服务人员：王师傅，点击更换" }).waitFor();
    await choosePerson(page.getByRole("button", { name: "工程施工服务人员：王师傅，点击更换" }), "赵师傅", false);
    await page.getByRole("button", { name: "工程施工服务人员：赵师傅，点击更换" }).waitFor();
    assert.equal(projects[1].assignments[0].providerId, 502);
    projects[1].currentNodeKey = "construction-work";
    projects[1].nodes[0].status = "completed";
    projects[1].nodes[1].status = "active";
    await openProject("midsales");
    await expandSection("交付时间");
    await choosePerson(page.getByRole("button", { name: "工程施工服务人员：赵师傅，点击更换" }), "王师傅", false);
    await page.getByRole("button", { name: "工程施工服务人员：王师傅，点击更换" }).waitFor();

    await openProject("aftersales");
    await expandSection("交付时间");
    await choosePerson(page.getByRole("button", { name: "上门售后项目人员：未选择，点击选择" }), "王师傅", false);
    await page.getByRole("button", { name: "上门售后项目人员：王师傅，点击更换" }).waitFor();
    await choosePerson(page.getByRole("button", { name: "上门售后项目人员：王师傅，点击更换" }), "赵师傅", false);
    await page.getByRole("button", { name: "上门售后项目人员：赵师傅，点击更换" }).waitFor();
    assert.equal(projects[2].assignments[0].providerId, 502);
    assert.equal(await page.getByRole("textbox", { name: "项目人员", exact: true }).count(), 0);
    projects[2].nodes[0].status = "completed";
    projects[2].status = "completed";
    await openProject("aftersales");
    await expandSection("交付时间");
    assert.ok(await page.getByRole("button", { name: "上门售后项目人员：赵师傅，点击更换" }).isDisabled());
    assert.ok(assignmentWrites.every(write => write.projectId !== 201), "presales never uses the WeChat provider assignments");

    await page.goto(`${origin}/__personnel-selection?type=collaboration`);
    await page.getByRole("row").filter({ hasText: "人员分派测试工单" }).click();
    const owner = page.getByRole("combobox", { name: "分派处理人" });
    assert.equal(await owner.count(), 1);
    assert.ok(await owner.evaluate(element => Boolean(element.closest(".as-collaboration-facts"))));
    await owner.click();
    await page.getByRole("option", { name: /李工/ }).click();
    await page.getByText("工单已分派", { exact: true }).waitFor();
    assert.equal(ticket.ownerUserId, "employee-2");
    assert.equal(ticket.ownerName, "李工");
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});
