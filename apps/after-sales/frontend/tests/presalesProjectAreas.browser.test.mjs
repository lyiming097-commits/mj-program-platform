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
const fixtureId = "/__presales-project-areas.js";
const fixture = `
import { createApp } from 'vue';
import '/src/styles.css';
import ProjectWorkspace from '/src/components/ProjectWorkspace.vue';
createApp(ProjectWorkspace, { serviceType: 'presales', session: { userId: 'admin' } }).mount('#app');
`;

test("project info autosaves local metadata and bid date, previews documents and protects historical records and conflicts", { timeout: 120000 }, async t => {
  const server = await createServer({
    root, base: "/", configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-project-areas"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "presales-project-areas-fixture",
      resolveId(id) { if (id === fixtureId) return id; },
      load(id) { if (id === fixtureId) return fixture; },
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (request.url?.split("?", 1)[0] !== "/__presales-project-areas") return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<div id="app"></div><script type="module" src="${fixtureId}"></script>`);
        });
      },
    }],
  });
  const project = {
    id: 301, name: "面积信息验证", customer: "测试学校", code: "AREA-301", serviceType: "presales",
    ownerName: "销售甲", status: "in_progress", currentNodeKey: "late-approval", draftVersion: "area-1",
    updatedAt: "2026-10-19T01:00:00Z", permissions: { canManage: true }, assignments: [], events: [],
    businessData: { projectInfo: { name: "面积信息验证", customer: "测试学校", totalArea: "120.25", designArea: "80.00" },
      projectInfoRecords: { "early-approval": { name: "旧立项资料" },
        "late-approval": { name: "面积信息验证", customer: "测试学校", totalArea: "10", designArea: "5", expectedBidAt: "2001-01-01" } },
      extra: { keep: true } },
    nodes: [
      { id: 3011, nodeKey: "early-approval", name: "前期立项", kind: "approval", status: "completed", sequence: 1, enabled: true, businessData: {}, permissions: { canEdit: false } },
      { id: 3012, nodeKey: "late-approval", name: "后期立项", kind: "approval", status: "active", sequence: 2, enabled: true, businessData: {}, permissions: { canEdit: true } },
    ],
  };
  const originalRecord = structuredClone(project.businessData.projectInfoRecords["early-approval"]);
  const writes = [], mutations = [], errors = [], diagnostics = [], saveResults = [];
  const documents = [{ id: 501, targetType: "project_node", targetId: 3011, category: "general",
    originalName: "原立项需求.pdf", mimeType: "application/pdf", size: 100, canDelete: false,
    downloadUrl: "/api/after-sales/attachments/501/download" }];
  let releaseUpload, releaseDelete, failDelete = false;
  let revision = 1, conflict = false, browser, page;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const pdfPage = await browser.newPage();
    await pdfPage.setContent("<p>Project requirements preview</p>");
    const pdf = await pdfPage.pdf({ format: "A4" });
    await pdfPage.close();
    page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "error") diagnostics.push(message.text()); });
    page.on("requestfailed", request => diagnostics.push({ url: request.url(), error: request.failure()?.errorText }));
    await page.route("**/api/**", async route => {
      const request = route.request(), url = new URL(request.url());
      if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) mutations.push({ method: request.method(), path: url.pathname });
      if (/\/attachments\/\d+\/download$/.test(url.pathname)) {
        await route.fulfill({ contentType: "application/pdf", body: pdf });
        return;
      }
      let body = { items: [] }, status = 200;
      if (url.pathname === "/api/after-sales/projects") body = { items: [project], page: 1, total: 1, totalPages: 1 };
      else if (url.pathname === "/api/after-sales/projects/301") {
        if (request.method() === "PATCH") {
          const payload = request.postDataJSON();
          writes.push(payload);
          if (conflict || payload.expectedDraftVersion !== project.draftVersion) {
            status = 409;
            body = { error: "项目资料已被其他人更新，当前填写已保留", code: "PROJECT_CONFLICT" };
          } else {
            if (payload.presalesProjectInfo) {
              for (const [key, value] of Object.entries(payload.presalesProjectInfo)) {
                project.businessData.projectInfo[key] = ["projectLevel", "urgency", "expectedBidAt"].includes(key) ? value : value === null ? null : Number(value).toFixed(2);
              }
            } else if (payload.businessData) project.businessData = payload.businessData;
            project.draftVersion = `area-${++revision}`;
            project.updatedAt = new Date(Date.now() + revision * 1000).toISOString();
            project.events.push({ id: revision, title: "更新项目资料", createdAt: project.updatedAt, actorName: "测试人员" });
            body = { item: project };
          }
        } else body = { item: project };
      }
      else if (url.pathname === "/api/after-sales/attachments" && (request.method() === "POST" || url.searchParams.get("targetType") === "presales_project")) {
        if (request.method() === "POST") {
          const payload = request.postDataBuffer().toString();
          assert.match(payload, /presales_project/);
          assert.match(payload, /301/);
          await new Promise(resolve => { releaseUpload = resolve; });
          const item = { id: 502, targetType: "presales_project", targetId: 301, category: "general",
            originalName: "补充需求.pdf", mimeType: "application/pdf", size: pdf.length, canDelete: true,
            downloadUrl: "/api/after-sales/attachments/502/download" };
          documents.push(item);
          body = { ok: true, item }; status = 201;
        } else {
          assert.equal(url.searchParams.get("targetType"), "presales_project");
          assert.equal(url.searchParams.get("targetId"), "301");
          body = { items: documents };
        }
      } else if (url.pathname === "/api/after-sales/attachments/502" && request.method() === "DELETE") {
        await new Promise(resolve => { releaseDelete = resolve; });
        if (failDelete) { status = 409; body = { error: "文档暂时不能删除，请重试" }; }
        else { documents.splice(documents.findIndex(row => row.id === 502), 1); body = { ok: true }; }
      }
      if (request.method() === "PATCH" && url.pathname === "/api/after-sales/projects/301") {
        saveResults.push({ status, draft: project.draftVersion, payload: request.postDataJSON() });
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    await page.goto(`${origin}/__presales-project-areas`);
    await page.locator(".as-project-data-row").click();
    const areaTab = page.getByRole("tab", { name: "项目信息", exact: true });
    await areaTab.click();
    const panel = page.getByRole("tabpanel", { name: "项目信息", exact: true });
    assert.equal(await page.getByRole("tab", { name: "面积信息", exact: true }).count(), 0);
    assert.equal(await page.getByRole("tab", { name: "费用信息", exact: true }).count(), 0);
    await panel.getByRole("table", { name: "售前项目费用" }).waitFor();
    await panel.getByRole("region", { name: "费用信息", exact: true }).getByText(/未关联 CRM/).waitFor();
    const total = panel.getByRole("textbox", { name: "项目总面积", exact: true });
    const design = panel.getByRole("textbox", { name: "设计面积", exact: true });
    const level = panel.getByRole("combobox", { name: "项目等级", exact: true });
    const urgency = panel.getByRole("combobox", { name: "紧急程度", exact: true });
    const expectedBid = panel.getByLabel("预计招标时间", { exact: true });
    assert.equal(await expectedBid.inputValue(), "", "the local date starts empty");
    const chooseLevel = async label => {
      await level.click();
      await page.getByRole("option", { name: label, exact: true }).click();
    };
    const chooseUrgency = async label => {
      await urgency.click();
      await page.getByRole("option", { name: label, exact: true }).click();
    };
    const metadataSaved = expected => page.waitForResponse(response => {
      const request = response.request();
      if (request.method() !== "PATCH" || new URL(request.url()).pathname !== "/api/after-sales/projects/301") return false;
      const values = request.postDataJSON().presalesProjectInfo;
      return values && Object.entries(expected).every(([key, value]) => values[key] === value);
    }).then(response => response.finished());
    assert.equal(await panel.getByRole("heading", { name: "项目信息", exact: true }).count(), 0);
    assert.equal(await panel.getByRole("button", { name: "立即保存" }).count(), 0);
    assert.equal(await panel.getByText("整个售前项目共用，面积与等级保存后同步展示在统计分析中。", { exact: true }).count(), 0);
    assert.equal(await panel.getByText("填写后自动保存", { exact: true }).count(), 0);
    for (const text of ["整个售前项目共用一组费用，由 CRM 和商城提供。", "面积单位为平方米（㎡），两项均可留空，最多保留两位小数。", "按项目重要性和金额范围选择，可留空。"]) {
      assert.equal(await panel.getByText(text, { exact: true }).count(), 0);
    }
    await panel.getByText("请选择项目等级", { exact: true }).waitFor();
    await level.click();
    await page.getByRole("option", { name: "常规，金额小", exact: true }).waitFor();
    assert.equal(await page.getByRole("option", { name: "未填写", exact: true }).count(), 0);
    assert.deepEqual(await page.getByRole("listbox").getByRole("option").allTextContents(), ["常规，金额小", "常规，金额大",
      "特殊，金额小", "特殊，金额大", "重要，金额小", "重要，金额大"]);
    await level.press("Escape");
    assert.equal(await level.evaluate(el => document.activeElement === el), true, "closing the menu keeps keyboard focus on the field");
    await panel.getByText("请选择紧急程度", { exact: true }).waitFor();
    await urgency.click();
    await page.getByRole("option", { name: "一般", exact: true }).waitFor();
    assert.deepEqual(await page.getByRole("listbox").getByRole("option").allTextContents(), ["一般", "紧急", "非常紧急"]);
    await urgency.press("Escape");
    assert.equal(await urgency.evaluate(el => document.activeElement === el), true);
    assert.equal(await total.inputValue(), "120.25");
    assert.equal(await design.inputValue(), "80.00");
    assert.equal(writes.length, 0, "viewing existing areas does not write");
    await page.getByRole("tab", { name: /^节点详情/ }).click();
    await page.getByRole("button", { name: "项目信息", exact: true }).click();
    const viewedInfo = page.getByRole("dialog", { name: "项目信息", exact: true });
    await viewedInfo.getByText("关闭", { exact: true }).click();
    await page.getByRole("button", { name: /^前期立项，/ }).click();
    await page.getByRole("button", { name: /^后期立项，/ }).click();
    await page.locator(".as-project-drawer-close").click();
    await page.locator(".as-project-data-row").click();
    await areaTab.click();
    assert.deepEqual(mutations, [], "viewing nodes and closing the info modal and project never mutates data");
    const docs = panel.getByRole("region", { name: "项目需求文档", exact: true });
    await docs.getByText("原立项需求.pdf", { exact: true }).waitFor();
    assert.equal(await docs.getByRole("button", { name: "删除：原立项需求.pdf", exact: true }).count(), 0,
      "historical node documents remain visible without a nonworking delete button");
    const uploading = page.waitForRequest(request => request.method() === "POST" && new URL(request.url()).pathname === "/api/after-sales/attachments");
    await docs.locator('input[type="file"]').setInputFiles({ name: "补充需求.pdf", mimeType: "application/pdf", buffer: pdf });
    await uploading;
    await page.getByRole("tab", { name: /^节点详情/ }).click();
    assert.equal(await panel.isVisible(), true, "uploads prevent a tab change before completion");
    await page.locator(".as-project-drawer-close").click();
    assert.equal(await panel.isVisible(), true, "uploads prevent the parent drawer from closing");
    releaseUpload();
    await docs.getByText("补充需求.pdf", { exact: true }).waitFor();
    assert.equal(writes.length, 0, "uploading documents does not rewrite project metadata or create no-op audit records");
    await docs.getByRole("button", { name: "预览：补充需求.pdf", exact: true }).first().click();
    const preview = page.getByRole("dialog", { name: "补充需求.pdf", exact: true });
    await preview.locator("canvas").first().waitFor();
    await preview.press("Escape");
    await preview.waitFor({ state: "hidden" });
    assert.equal(await panel.isVisible(), true);
    const remove = docs.getByRole("button", { name: "删除：补充需求.pdf", exact: true });
    await remove.click();
    const confirmation = page.getByRole("dialog", { name: "删除项目需求文档", exact: true });
    await confirmation.getByRole("button", { name: "取消", exact: true }).click();
    assert.equal(await remove.evaluate(el => document.activeElement === el), true);
    failDelete = true;
    await remove.click();
    const deleting = page.waitForRequest(request => request.method() === "DELETE");
    await confirmation.getByRole("button", { name: "确认删除", exact: true }).click();
    await deleting;
    await confirmation.press("Escape");
    assert.equal(await confirmation.isVisible(), true, "a pending delete cannot be dismissed");
    releaseDelete();
    await confirmation.getByRole("alert").filter({ hasText: "文档暂时不能删除" }).waitFor();
    failDelete = false;
    const retryDelete = page.waitForRequest(request => request.method() === "DELETE");
    await confirmation.getByRole("button", { name: "确认删除", exact: true }).click();
    await retryDelete;
    releaseDelete();
    await confirmation.waitFor({ state: "hidden" });
    await docs.getByText("补充需求.pdf", { exact: true }).waitFor({ state: "detached" });
    await docs.getByText("原立项需求.pdf", { exact: true }).waitFor();
    assert.equal(await docs.getByRole("heading", { name: "项目需求文档", exact: true }).evaluate(el => document.activeElement === el), true,
      "deleting a document returns focus to the document section instead of the removed button");
    await total.fill("1500.25");
    await design.fill("1000");
    const firstSave = metadataSaved({ totalArea: "1500.25", designArea: "1000", projectLevel: "重要，金额大", urgency: "紧急", expectedBidAt: "2026-11-25" });
    await chooseLevel("重要，金额大");
    await chooseUrgency("紧急");
    await expectedBid.fill("2026-11-25");
    await firstSave;
    assert.deepEqual(writes.at(-1).presalesProjectInfo, { totalArea: "1500.25", designArea: "1000", projectLevel: "重要，金额大", urgency: "紧急", expectedBidAt: "2026-11-25" });
    assert.equal(project.businessData.projectInfo.designArea, "1000.00");
    assert.deepEqual(project.businessData.projectInfoRecords["early-approval"], originalRecord);
    assert.deepEqual(project.businessData.extra, { keep: true });

    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await panel.evaluate(el => el.scrollWidth <= el.clientWidth), true);
      await page.screenshot({ path: path.resolve(root, `../../../.codex-artifacts/after-sales-presales-project-info-${width}.png`) });
      await level.click();
      const option = page.getByRole("option", { name: "重要，金额大", exact: true });
      await option.waitFor();
      assert.equal(await option.getAttribute("aria-selected"), "true");
      const menu = page.getByRole("listbox");
      const bounds = await menu.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width && bounds.y >= 0 && bounds.y + bounds.height <= 900, "dropdown fits inside the viewport");
      assert.equal(await level.evaluate(el => getComputedStyle(el).borderWidth), "0px", "the field has no second inner border");
      await page.screenshot({ path: path.resolve(root, `../../../.codex-artifacts/after-sales-presales-project-level-${width}.png`) });
      await level.press("Escape");
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole("tab", { name: /^节点详情/ }).click();
    await page.getByRole("button", { name: "项目信息", exact: true }).click();
    const info = page.getByRole("dialog", { name: "项目信息", exact: true });
    await info.getByRole("textbox", { name: "申请理由（选填）", exact: true }).fill("面积填写后的项目说明");
    await info.getByRole("button", { name: "立即保存", exact: true }).click();
    await info.waitFor({ state: "hidden" });
    await areaTab.click();
    assert.equal(project.businessData.projectInfo.totalArea, "1500.25", "editing a node's project info preserves canonical project areas");
    assert.equal(await total.inputValue(), "1500.25");
    await panel.getByText("重要，金额大", { exact: true }).waitFor();
    assert.equal(project.businessData.projectInfo.projectLevel, "重要，金额大", "editing a node's old project info preserves the project level");
    assert.equal(project.businessData.projectInfo.urgency, "紧急", "editing historical node info preserves the current project's urgency");
    assert.equal(await expectedBid.inputValue(), "2026-11-25", "editing historical node info preserves the local bid date");

    await page.getByRole("tab", { name: /^节点详情/ }).click();
    await page.getByRole("button", { name: /^前期立项，/ }).click();
    await areaTab.click();
    assert.equal(await total.getAttribute("readonly"), null, "project area editing is independent of the selected historical node");
    const zeroSave = metadataSaved({ totalArea: "0", designArea: null });
    await design.fill("");
    await total.fill("0");
    await zeroSave;
    assert.equal(project.businessData.projectInfo.totalArea, "0.00");
    assert.equal(project.businessData.projectInfo.designArea, null);
    await chooseLevel("特殊，金额小");
    await chooseUrgency("非常紧急");
    await expectedBid.fill("2026-12-01");
    await page.getByRole("tab", { name: /^节点详情/ }).click();
    assert.equal(project.businessData.projectInfo.projectLevel, "特殊，金额小", "changing tabs flushes the project level draft");
    assert.equal(project.businessData.projectInfo.urgency, "非常紧急", "the urgency can be edited with a historical node selected and is flushed before navigation");
    assert.equal(project.businessData.projectInfo.expectedBidAt, "2026-12-01", "historical node selection does not block the project date and leaving flushes it");
    await areaTab.click();

    const savedCount = writes.length;
    await total.fill("-1");
    await panel.getByRole("alert").waitFor();
    await page.getByRole("button", { name: "重试保存", exact: true }).click();
    assert.equal(writes.length, savedCount, "invalid values never reach the API");
    conflict = true;
    const conflictedUrgency = metadataSaved({ totalArea: "88", projectLevel: "常规，金额大", urgency: "一般", expectedBidAt: "2027-01-15" });
    await total.fill("88");
    await chooseLevel("常规，金额大");
    await chooseUrgency("一般");
    await expectedBid.fill("2027-01-15");
    await conflictedUrgency;
    await page.getByRole("button", { name: "重试保存", exact: true }).waitFor();
    await page.getByRole("alert").filter({ hasText: "项目资料已被其他人更新" }).waitFor();
    const conflictedClose = metadataSaved({ totalArea: "88", projectLevel: "常规，金额大", urgency: "一般", expectedBidAt: "2027-01-15" });
    await page.locator(".as-project-drawer-close").click();
    await conflictedClose;
    await page.getByRole("button", { name: "重试保存", exact: true }).waitFor();
    assert.equal(await panel.isVisible(), true, "failed saves prevent closing the project");
    assert.equal(await total.inputValue(), "88", "conflicting drafts remain editable");
    assert.equal(await expectedBid.inputValue(), "2027-01-15", "conflicts preserve the date draft");
    await panel.getByText("常规，金额大", { exact: true }).waitFor();
    await panel.getByText("一般", { exact: true }).waitFor();
    conflict = false;
    await page.getByRole("button", { name: "放弃修改并重新加载", exact: true }).click();
    await page.getByRole("alertdialog", { name: "是否放弃修改" }).getByRole("button", { name: "确认放弃", exact: true }).click();
    await panel.waitFor();
    assert.equal(await total.inputValue(), "0.00");
    await page.locator(".as-project-drawer-close").click();
    await page.locator(".as-project-data-row").click();
    await areaTab.click();
    assert.equal(await total.inputValue(), "0.00", "reopening reads saved values");
    assert.equal(await design.inputValue(), "");
    assert.equal(await expectedBid.inputValue(), "2026-12-01", "discarding a conflicting draft restores the saved date");
    await panel.getByText("特殊，金额小", { exact: true }).waitFor();
    await panel.getByText("非常紧急", { exact: true }).waitFor();
    await Promise.all([metadataSaved({ projectLevel: "" }), (async () => {
      const field = level.locator("xpath=ancestor::label[1]");
      await level.focus();
      await field.locator(".el-select__clear").click();
    })()]);
    await page.locator('.as-project-detail-panel > .as-alert[role="status"]').waitFor({ state: "hidden" });
    assert.equal(project.businessData.projectInfo.projectLevel, "", "the level is optional and can be cleared");
    await Promise.all([metadataSaved({ urgency: "" }), (async () => {
      const field = urgency.locator("xpath=ancestor::label[1]");
      await urgency.focus();
      await field.locator(".el-select__clear").click();
    })()]);
    await page.locator('.as-project-detail-panel > .as-alert[role="status"]').waitFor({ state: "hidden" });
    assert.equal(project.businessData.projectInfo.urgency, "", "urgency is optional and clearing it is saved");
    await Promise.all([metadataSaved({ expectedBidAt: "" }), expectedBid.fill("")]);
    assert.equal(project.businessData.projectInfo.expectedBidAt, "", "clearing the optional date is saved");

    await page.setViewportSize({ width: 390, height: 844 });
    await areaTab.waitFor({ state: "detached" });
    assert.equal(await areaTab.count(), 0, "mobile Web has no added project info tab");
    await page.getByRole("tab", { name: "费用信息", exact: true }).click();
    await page.getByRole("tabpanel", { name: "项目费用信息", exact: true }).waitFor();
    assert.equal(await page.getByRole("combobox", { name: "项目等级", exact: true }).count(), 0);
    assert.equal(await page.getByRole("combobox", { name: "紧急程度", exact: true }).count(), 0);
    assert.equal(await page.getByLabel("预计招标时间", { exact: true }).count(), 0);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.locator(".as-project-drawer-close").click();
    project.permissions.canManage = false;
    await page.locator(".as-project-data-row").click();
    await areaTab.click();
    assert.notEqual(await total.getAttribute("readonly"), null);
    assert.equal(await level.isDisabled(), true);
    assert.equal(await urgency.isDisabled(), true);
    assert.equal(await expectedBid.isDisabled(), true);
    assert.equal(await docs.locator('input[type="file"]').count(), 0, "read-only users have no upload entry");
    assert.equal(await panel.getByRole("button", { name: "立即保存" }).count(), 0);

    // An untouched CRM import has no local node info record or optional areas.
    await page.locator(".as-project-drawer-close").click();
    project.permissions.canManage = true;
    project.sourceCrmId = "CRM-EMPTY";
    project.crmSnapshot = { bidTime: "2028-12-31" };
    project.currentNodeKey = "early-approval";
    project.businessData = { projectInfo: { name: project.name, customer: project.customer, owner: "销售甲", info: "", reason: "" } };
    Object.assign(project.nodes[0], { status: "active", permissions: { canEdit: true }, businessData: {} });
    Object.assign(project.nodes[1], { status: "pending", permissions: { canEdit: false }, businessData: {} });
    const beforeViewingEmpty = mutations.length;
    await page.locator(".as-project-data-row").click();
    await page.getByRole("button", { name: /^前期立项，/ }).click();
    await page.getByRole("button", { name: "项目信息", exact: true }).click();
    await viewedInfo.getByText("关闭", { exact: true }).click();
    await page.getByRole("button", { name: "项目信息", exact: true }).click();
    await viewedInfo.getByRole("button", { name: "立即保存", exact: true }).click();
    await viewedInfo.waitFor({ state: "hidden" });
    await areaTab.click();
    assert.equal(await expectedBid.inputValue(), "", "a CRM bidTime does not populate the locally maintained date");
    await page.locator(".as-project-drawer-close").click();
    assert.equal(mutations.length, beforeViewingEmpty, "opening an empty CRM project and saving unchanged info never sends writes");
    assert.equal(project.businessData.projectInfoRecords, undefined);
    assert.deepEqual(errors, []);
  } catch (error) {
    await page?.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-project-info-failure.png") });
    t.diagnostic(JSON.stringify({ errors, writes, mutations, diagnostics, saveResults, page: await page?.locator("body").innerText() }));
    throw error;
  } finally { await browser?.close(); await server.close(); }
});
