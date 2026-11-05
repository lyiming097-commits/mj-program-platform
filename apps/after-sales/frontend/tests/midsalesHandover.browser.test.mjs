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
const fixtureId = "/__midsales-handover.js";
const fixture = `
import { createApp } from 'vue';
import '/src/styles.css';
import ProjectWorkspace from '/src/components/ProjectWorkspace.vue';
createApp(ProjectWorkspace, {
  serviceType: new URL(location.href).searchParams.get('type'),
  session: { userId: 'admin' },
}).mount('#app');`;
const node = (id, nodeKey, name, kind = "delivery", status = "active") => ({
  id, nodeKey, name, kind, status, enabled: true, businessData: {},
  permissions: { canEdit: status === "active", canAssign: true },
  statusLabel: status === "active" ? "进行中" : "已完成", updatedAt: "2026-10-15T01:00:00Z",
});

test("presales selects midsales nodes before completion and midsales reads all rounds with deduplicated files", { timeout: 90000 }, async () => {
  const server = await createServer({
    root, base: "/", configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-midsales-handover"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "midsales-handover-fixture",
      resolveId(id) { if (id === fixtureId) return id; },
      load(id) { if (id === fixtureId) return fixture; },
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (!request.url?.startsWith("/__midsales-handover?")) return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<div id="app"></div><script type="module" src="${fixtureId}"></script>`);
        });
      },
    }],
  });
  const base = { customer: "测试学校", ownerName: "项目负责人", status: "in_progress", assignments: [], events: [], businessData: {},
    permissions: { canManage: true, canDelete: true, canSettle: true } };
  const source = { ...base, id: 401, name: "售前交接验证", serviceType: "presales", sourceCrmId: "original-crm",
    currentNodeKey: "project-end", nodes: [node(4018, "construction", "施工图", "delivery", "completed"), node(4019, "project-end", "售前项目结束", "end")] };
  const target = { ...base, id: 402, name: "售中交接验证", serviceType: "midsales", presalesProjectId: 401,
    currentNodeKey: "midsales-project", nodes: [node(4021, "midsales-project", "项目立项", "approval")] };
  const groups = [
    { targetType: "project_node", targetId: 4012, nodeKey: "early-plan", name: "前期方案", attachmentCount: 2, itemIds: [902, 901],
      categories: [{ value: "scheme_submission", label: "方案提交附件" }] },
    { targetType: "project_node", targetId: 4019, nodeKey: "project-end", name: "售前项目结束", attachmentCount: 1, itemIds: [903],
      categories: [{ value: "general", label: "普通附件" }] },
  ];
  const files = [
    { id: 901, targetId: 4012, category: "scheme_submission", originalName: "第一轮方案.pdf", mimeType: "application/pdf", size: 512 },
    { id: 902, targetId: 4012, category: "scheme_submission", originalName: "第二轮方案.pdf", mimeType: "application/pdf", size: 512 },
    { id: 900, targetId: 4012, category: "scheme_submission", originalName: "第二轮方案.pdf", mimeType: "application/pdf", size: 512 },
    { id: 903, targetId: 4019, category: "general", originalName: "交接照片.png", mimeType: "image/png", size: 70,
      downloadUrl: "/api/after-sales/attachments/903/download" },
  ];
  const writes = [];
  const calls = [];
  const errors = [];
  let archiveFailure = true;
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/api/**", async route => {
      const request = route.request();
      const url = new URL(request.url());
      calls.push(url.pathname + url.search);
      let body = { items: [] };
      let status = 200;
      if (url.pathname.endsWith("/attachments/903/download")) {
        return route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64") });
      }
      if (url.pathname === "/api/after-sales/projects") {
        body = { items: [url.searchParams.get("type") === "presales" ? source : target], total: 1, page: 1, totalPages: 1 };
      } else if (url.pathname.endsWith("/presales-materials")) {
        status = archiveFailure ? 503 : 200;
        body = archiveFailure ? { error: "售前资料暂时无法读取", code: "TEMPORARY_FAILURE" }
          : { project: { id: source.id, name: source.name, sourceCrmId: source.sourceCrmId }, groups, attachmentCount: 3 };
      } else if (url.pathname.startsWith("/api/crm/opportunities/")) {
        body = { opportunityId: "original-crm", projectDetailUrl: "/maijie-mall/#/opportunity/42/solution/7" };
      } else if (url.pathname === "/api/after-sales/attachments") {
        body = { items: files.filter(file => String(file.targetId) === url.searchParams.get("targetId")) };
      } else if (url.pathname === "/api/after-sales/projects/401/advance") {
        const payload = request.postDataJSON();
        writes.push(payload);
        source.status = "completed";
        source.midsalesProjectId = 402;
        source.nodes.at(-1).status = "completed";
        source.nodes.at(-1).businessData = payload.businessData;
        body = { item: source };
      } else if (url.pathname.startsWith("/api/after-sales/projects/")) {
        const project = url.pathname.split("/")[4] === "401" ? source : target;
        if (request.method() === "PATCH") {
          const payload = request.postDataJSON();
          const currentNode = project.nodes.find(row => row.nodeKey === url.pathname.split("/")[6]);
          if (currentNode) Object.assign(currentNode, payload);
        }
        body = { item: project };
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    async function open(type) {
      await page.goto(`${origin}/__midsales-handover?type=${type}`);
      await page.locator(".as-project-data-row").click();
      await page.getByRole("tab", { name: /^节点详情/ }).waitFor();
    }
    await open("presales");
    const handover = page.getByRole("region", { name: "转入售中服务", exact: true });
    await handover.getByRole("group", { name: "本项目包含的节点" }).waitFor();
    assert.equal(await handover.getByRole("checkbox").count(), 8);
    assert.equal(await handover.getByRole("checkbox", { name: "项目立项", exact: true }).isDisabled(), true);
    await handover.getByRole("checkbox", { name: "家具安装", exact: true }).uncheck();
    await handover.getByRole("checkbox", { name: "开学保障", exact: true }).uncheck();
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-handover-selection.png") });
    await page.getByRole("button", { name: "结束售前并转入售中", exact: true }).click();
    await page.getByRole("link", { name: "查看售中项目" }).waitFor();
    assert.equal(writes.length, 1);
    assert.equal(writes[0].businessData.midsalesNodeKeys.length, 6);
    assert.equal(writes[0].businessData.midsalesNodeKeys.includes("furniture-install"), false);
    assert.equal(writes[0].businessData.midsalesNodeKeys.includes("school-support"), false);
    assert.equal(await page.getByRole("link", { name: "查看售中项目" }).getAttribute("href"), "/after-sales/midsales/?projectId=402");
    assert.equal(await handover.getByRole("checkbox", { name: "设备安装", exact: true }).isDisabled(), true);

    await open("midsales");
    assert.equal(calls.some(url => url.endsWith("/presales-materials")), false, "source data loads only when its tab opens");
    await page.getByRole("tab", { name: "售前资料", exact: true }).click();
    const archive = page.getByRole("region", { name: "售前资料", exact: true });
    await archive.getByRole("alert").waitFor();
    assert.match(await archive.innerText(), /售前资料暂时无法读取/);
    archiveFailure = false;
    await archive.getByRole("button", { name: "重试", exact: true }).click();
    await archive.getByRole("link", { name: "打开商城方案", exact: true }).waitFor();
    assert.equal(await archive.getByRole("link", { name: "打开商城方案" }).getAttribute("href"), `${origin}/maijie-mall/#/opportunity/42/solution/7`);
    assert.ok(calls.includes("/api/crm/opportunities/original-crm/solution-products"));
    assert.equal(calls.some(url => url.includes("targetId=4012")), false);
    await archive.locator("summary").filter({ hasText: "前期方案" }).click();
    await archive.getByText("第二轮方案.pdf", { exact: true }).waitFor();
    await archive.getByText("第一轮方案.pdf", { exact: true }).waitFor();
    assert.equal(await archive.getByText("第二轮方案.pdf", { exact: true }).count(), 1);
    assert.match(await archive.innerText(), /共 3 个附件.*汇总各轮推进附件，同名文件保留最新上传版本/);
    await archive.locator("summary").filter({ hasText: "售前项目结束" }).click();
    await archive.getByRole("img", { name: "交接照片.png", exact: true }).waitFor();
    assert.equal(await archive.locator('input[type="file"]').count(), 0);
    assert.equal(await archive.getByRole("button", { name: /^删除/ }).count(), 0);
    assert.equal(await page.locator(".as-node-actionbar").count(), 0);
    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 960 });
      assert.ok(await archive.evaluate(el => el.scrollWidth <= el.clientWidth));
      await page.screenshot({ path: path.resolve(root, `../../../.codex-artifacts/after-sales-handover-materials-${width}.png`) });
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});
