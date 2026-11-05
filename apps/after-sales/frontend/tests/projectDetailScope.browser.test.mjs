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
const fixtureId = "/__project-detail-scope.js";
const fixture = `
import { createApp } from 'vue';
import '/src/styles.css';
import ProjectWorkspace from '/src/components/ProjectWorkspace.vue';
createApp(ProjectWorkspace, {
  serviceType: new URL(location.href).searchParams.get('type'),
  session: { userId: 'admin' },
}).mount('#app');
`;

function makeNode(id, nodeKey, name, status, estimatedFee, kind = "delivery") {
  return {
    id, nodeKey, name, status, kind, enabled: true, estimatedFee, actualFee: "30.00",
    permissions: { canEdit: status === "active", canAssign: true },
    statusLabel: status === "active" ? "进行中" : "已完成",
    updatedAt: "2026-10-14T01:00:00+00:00", businessData: {},
  };
}

test("presales fees belong to the project while other service fees and delivery materials stay node scoped", { timeout: 90000 }, async () => {
  const server = await createServer({
    root, base: "/", configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-project-detail-scope"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "project-detail-scope-fixture",
      resolveId(id) { if (id === fixtureId) return id; },
      load(id) { if (id === fixtureId) return fixture; },
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (!request.url?.startsWith("/__project-detail-scope?")) return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<div id="app"></div><script type="module" src="${fixtureId}"></script>`);
        });
      },
    }],
  });
  const projects = [
    { id: 301, name: "售前详情范围验证", serviceType: "presales", currentNodeKey: "early-plan",
      nodes: [makeNode(3011, "early-approval", "前期立项", "completed", "5.00", "approval"),
        makeNode(3012, "early-plan", "前期方案", "active", "10.00"),
        makeNode(3013, "budget-match", "预算匹配", "active", "20.00"),
        makeNode(3014, "early-plan-result", "前期方案结果", "pending", "0.00", "result"),
        makeNode(3015, "project-end", "售前项目结束", "pending", "0.00", "end")] },
    { id: 302, name: "售中详情范围验证", serviceType: "midsales", currentNodeKey: "construction-work",
      nodes: [makeNode(3021, "midsales-project", "项目立项", "completed", "5.00", "approval"),
        makeNode(3022, "construction-work", "工程施工", "active", "10.00")] },
    { id: 303, name: "售后详情范围验证", serviceType: "aftersales", currentNodeKey: "onsite-service",
      nodes: [makeNode(3031, "onsite-service", "上门售后", "active", "10.00")] },
  ].map(project => ({
    code: `S${project.id}`, customer: "测试学校", status: "in_progress", assignments: [], businessData: {},
    permissions: { canManage: true, canDelete: true, canSettle: true },
    ...project,
    events: [
      { id: 1, nodeId: project.nodes.at(-1).id, title: "其他节点的留痕", detail: "保留其他节点资料变更",
        createdAt: "2026-10-14T03:00:00+00:00", actorName: "王工" },
      { id: 2, nodeId: project.nodes[0].id, title: "旧节点的留痕", detail: "保留历史版本",
        createdAt: "2026-10-14T02:00:00+00:00", actorName: "系统管理员", actorUserId: "admin",
        authUserName: "项目经理", authUserId: "manager" },
      { id: 3, nodeId: null, title: "创建项目", detail: "项目记录",
        createdAt: "2026-10-14T01:00:00+00:00", actorName: "李工" },
    ],
  }));
  projects[0].nodes[1].businessData.schemeRounds = [{
    roundId: "scope-round-1", attachmentIds: [701], note: "本轮设计说明",
  }];
  const attachments = [
    { id: 701, targetType: "project_node", targetId: 3012, category: "scheme_submission",
      originalName: "前期方案.pdf", contentType: "application/pdf", size: 1024 },
    { id: 702, targetType: "midsales_proof", targetId: 801, category: "general",
      originalName: "售中评价报告.pdf", contentType: "application/pdf", size: 1024 },
    { id: 703, targetType: "project_node", targetId: 3031, category: "other",
      originalName: "售后交付报告.pdf", contentType: "application/pdf", size: 1024 },
    { id: 704, targetType: "project_node", targetId: 3022, category: "fee_estimated",
      originalName: "预计费用清单.pdf", contentType: "application/pdf", size: 1024 },
  ];
  const writes = [];
  const pageErrors = [];
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      const parts = url.pathname.split("/");
      let body = { items: [] };
      if (url.pathname === "/api/after-sales/projects") {
        body = { items: projects.filter(project => project.serviceType === url.searchParams.get("type")),
          total: 1, totalPages: 1, page: 1 };
      } else if (url.pathname === "/api/after-sales/attachments") {
        body = { items: attachments.filter(item => (
          item.targetType === url.searchParams.get("targetType")
          && String(item.targetId) === url.searchParams.get("targetId")
        )) };
      } else if (parts[3] === "projects" && parts[4]) {
        const project = projects.find(project => String(project.id) === parts[4]);
        body = { item: project };
        if (parts[7] === "proofs") {
          body = { items: [{ id: 801, proofType: "evaluation", status: "submitted", attachments: [attachments[1]] }] };
        } else if (route.request().method() === "PATCH") {
          const payload = route.request().postDataJSON();
          writes.push({ projectId: project.id, nodeKey: parts[6], payload });
          const node = project.nodes.find(node => node.nodeKey === parts[6]);
          Object.assign(node, payload, { updatedAt: "2026-10-14T04:00:00+00:00" });
        }
      }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    const feeFold = page.locator(".as-node-fees-fold");
    const history = page.getByRole("region", { name: "项目版本与留痕" });
    const historyTab = page.getByRole("tab", { name: /^版本与留痕/ });
    async function openProject(type) {
      await page.goto(`${origin}/__project-detail-scope?type=${type}`);
      await page.locator(".as-project-data-row").click();
      if (type === "presales") await page.getByRole("tab", { name: "项目信息", exact: true }).waitFor();
      else await feeFold.locator("summary").waitFor();
      const tabNames = await page.getByRole("tablist", { name: "项目详情视图" }).getByRole("tab").allTextContents();
      assert.equal(tabNames.length, type === "aftersales" ? 2 : 3);
      assert.ok(tabNames[0].startsWith("节点详情"));
      assert.ok(tabNames.includes("版本与留痕3"));
      if (type !== "presales") assert.equal(await feeFold.evaluate(el => el.parentElement.className), "as-node-main");
    }
    async function checkHistory() {
      assert.equal(await historyTab.textContent(), "版本与留痕3");
      await historyTab.click();
      await history.waitFor();
      assert.equal(await history.locator(".as-history-item").count(), 3);
      assert.match(await history.innerText(), /整个项目 · 包含全部节点 · 共 3 条记录/);
      assert.match(await history.innerText(), /系统管理员（代 项目经理 操作）/);
      assert.match(await history.innerText(), /其他节点的留痕/);
      assert.match(await history.innerText(), /旧节点的留痕/);
      assert.match(await history.innerText(), /创建项目/);
      assert.equal(await page.locator(".as-node-actionbar").count(), 0);
      assert.equal(await page.locator(".module-route-drawer .el-drawer__footer").isVisible(), false);
      await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-project-history.png") });
      await page.getByRole("tab", { name: /^节点详情/ }).click();
    }
    await openProject("presales");
    assert.equal(await page.locator(".as-node-materials-fold").count(), 0, "round attachments have no duplicate materials section");
    assert.equal(await feeFold.count(), 0);
    const estimatedFee = page.getByRole("spinbutton", { name: "当前节点预计费用", exact: true });
    assert.equal(await estimatedFee.count(), 0);
    await page.getByRole("tab", { name: "项目信息", exact: true }).click();
    await page.getByRole("region", { name: "费用信息", exact: true }).waitFor();
    assert.match(await page.getByRole("region", { name: "费用信息", exact: true }).innerText(), /未关联 CRM/);
    assert.equal(await page.locator(".as-node-actionbar").count(), 0);
    assert.equal(writes.length, 0, "reading project fees never writes node fees");
    await checkHistory();
    await page.locator(".as-presales-flow-node").filter({ hasText: "预算匹配" }).click();
    assert.equal(await feeFold.count(), 0);
    assert.equal(await estimatedFee.count(), 0);
    await checkHistory();
    await page.locator(".as-presales-flow-node").filter({ hasText: "前期立项" }).click();
    assert.equal(await page.locator(".as-node-materials-fold").count(), 0, "approval nodes have no empty delivery materials section");
    assert.equal(await feeFold.count(), 0);
    for (const name of ["前期方案结果", "售前项目结束"]) {
      await page.locator(".as-presales-flow-node").filter({ hasText: name }).click();
      assert.equal(await page.locator(".as-node-materials-fold").count(), 0, `${name} has no empty delivery materials section`);
      if (name === "前期方案结果") await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-presales-result-materials.png") });
    }
    await page.getByRole("button", { name: "前期方案，进行中", exact: true }).click();
    await page.locator("summary").filter({ hasText: "前期方案推进" }).click();
    await page.getByRole("button", { name: "第 1 次提交：填写附件和备注", exact: true }).click();
    const submissionDialog = page.getByRole("dialog", { name: "第 1 次提交", exact: true });
    await submissionDialog.getByText("前期方案.pdf", { exact: true }).waitFor();
    await submissionDialog.getByRole("button", { name: "关闭", exact: true }).click();
    attachments.push({ id: 705, targetType: "project_node", targetId: 3012, category: "general",
      originalName: "历史补充附件.pdf", contentType: "application/pdf", size: 1024 });
    attachments.push({ id: 706, targetType: "project_node", targetId: 3011, category: "general",
      originalName: "历史立项附件.pdf", contentType: "application/pdf", size: 1024 });
    await openProject("presales");
    await page.locator(".as-node-materials-fold > summary").click();
    await page.locator(".as-node-materials-fold").getByText("历史补充附件.pdf", { exact: true }).waitFor();
    assert.equal(await page.locator(".as-node-materials-fold").getByText("前期方案.pdf", { exact: true }).count(), 0);
    await page.locator(".as-presales-flow-node").filter({ hasText: "前期立项" }).click();
    await page.locator(".as-node-materials-fold > summary").filter({ hasText: "节点补充附件" }).click();
    await page.locator(".as-node-materials-fold").getByText("历史立项附件.pdf", { exact: true }).waitFor();
    assert.equal(await page.locator(".as-node-materials-fold").getByText("历史补充附件.pdf", { exact: true }).count(), 0);
    for (const type of ["midsales", "aftersales"]) {
      await openProject(type);
      await feeFold.locator("summary").click();
      assert.equal(await estimatedFee.inputValue(), "10.00");
      assert.equal(await page.getByRole("spinbutton", { name: "当前节点实际费用", exact: true }).count(), 0,
        "mobile actual fees remain readonly");
      if (type === "midsales") await feeFold.getByText("预计费用清单.pdf", { exact: true }).waitFor();
      await page.locator(".as-node-materials-fold > summary").click();
      assert.match(await page.locator(".as-node-materials-fold > summary").innerText(), /交付资料/);
      await page.getByText(type === "midsales" ? "售中评价报告.pdf" : "售后交付报告.pdf", { exact: true }).waitFor();
      if (type === "midsales") assert.equal(await page.getByRole("button", { name: "审核材料", exact: true }).count(), 1);
      await checkHistory();
    }
    await openProject("presales");
    await page.getByRole("tab", { name: "项目信息", exact: true }).click();
    const projectFees = page.getByRole("region", { name: "费用信息", exact: true });
    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await projectFees.evaluate(el => el.scrollWidth <= el.clientWidth), true, "fee section has no horizontal clipping");
      await page.screenshot({ path: path.resolve(root, `../../../.codex-artifacts/after-sales-project-scope-${width}.png`) });
    }
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});
