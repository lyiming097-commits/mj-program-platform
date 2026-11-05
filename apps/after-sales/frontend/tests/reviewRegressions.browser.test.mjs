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

test("failed and conflicting project drafts survive close, node switching and navigation; team pages include older records", { timeout: 90000 }, async () => {
  const server = await createServer({ root, configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-review"),
    server: { host: "127.0.0.1", port: 0 } });
  let browser;
  const project = { id: 901, code: "MS901", name: "自动保存验证项目", customer: "隔离测试客户",
    serviceType: "midsales", status: "in_progress", currentNodeKey: "device-install", assignments: [], events: [], businessData: {},
    updatedAt: "project-1", draftVersion: "project-info-1", permissions: { canManage: true, canDelete: true },
    nodes: [[9011, "device-install", "设备安装"], [9012, "device-debug", "设备调试"]].map(([id, nodeKey, name], index) => ({
      id, nodeKey, name, sequence: index + 1, kind: "delivery", status: "active", enabled: true,
      estimatedFee: "100", updatedAt: `node-${id}-1`, businessData: {}, permissions: { canEdit: true, canAssign: true },
    })),
  };
  const providers = Array.from({ length: 125 }, (_, index) => ({ id: index + 1,
    name: `服务人员${String(index + 1).padStart(3, "0")}`, certificationStatus: "certified", city: "杭州" }));
  let failing = true;
  let sequence = 1;
  let failedRequests = 0;
  const providerPages = [];
  const errors = [];
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => sessionStorage.setItem("mj_program_login_session", JSON.stringify({
      sessionId: "review-regression", userId: "review-admin", name: "测试管理员", loginType: "scan",
    })));
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      const method = route.request().method();
      let status = 200;
      let body = { items: [] };
      if (url.pathname === "/api/auth/session/validate") body = { sessionId: "review-regression", userId: "review-admin", name: "测试管理员", loginType: "scan" };
      else if (url.pathname === "/api/after-sales/session/") body = { canManageApp: true, canManageSettings: true, appPermission: "admin" };
      else if (url.pathname === "/api/after-sales/projects") body = { items: [project], total: 1, page: 1, totalPages: 1 };
      else if (url.pathname === "/api/after-sales/projects/901") body = { item: project };
      else if (url.pathname.startsWith("/api/after-sales/projects/901/nodes/") && method === "PATCH") {
        const payload = route.request().postDataJSON();
        const node = project.nodes.find(item => item.nodeKey === url.pathname.split("/").at(-1));
        if (failing) { status = 503; body = { error: "测试网络暂不可用", code: "SAVE_FAILED" }; failedRequests += 1; }
        else if (payload.expectedUpdatedAt !== node.updatedAt) {
          status = 409; body = { error: "节点已被其他人更新，填写已保留", code: "PROJECT_NODE_CONFLICT" };
        } else {
          node.estimatedFee = String(payload.estimatedFee);
          node.businessData = { ...node.businessData, ...payload.businessData };
          node.updatedAt = `node-${node.id}-${++sequence}`;
          project.updatedAt = `project-${sequence}`;
          body = { item: project };
        }
      } else if (url.pathname === "/api/after-sales/providers") {
        const requestedPage = Number(url.searchParams.get("page"));
        providerPages.push(requestedPage);
        body = { items: providers.slice((requestedPage - 1) * 100, requestedPage * 100), total: 125, page: requestedPage, totalPages: 2 };
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/after-sales/`);
    const nav = page.getByRole("navigation", { name: "主导航" });
    await nav.getByRole("button", { name: "售中服务", exact: true }).click();
    await page.locator(".as-project-data-row").filter({ hasText: project.name }).click();
    const fee = page.getByLabel("当前节点预计费用", { exact: true });
    const expandFee = async () => page.locator(".as-node-main details").filter({ has: page.locator("summary", { hasText: "费用信息" }) })
      .evaluate(element => { element.open = true; });
    await expandFee();
    await fee.fill("250");
    await page.getByRole("alert").filter({ hasText: "测试网络暂不可用" }).first().waitFor();
    const previousFailures = failedRequests;
    await page.locator(".as-midsales-flow-node").filter({ hasText: "设备调试" }).click();
    await page.waitForFunction(() => document.querySelector(".as-project-detail-panel")?.textContent.includes("填写内容已保留"));
    assert.equal(await fee.inputValue(), "250");
    assert.ok(failedRequests > previousFailures);
    await page.locator(".as-project-drawer-close").click();
    assert.ok(await fee.isVisible(), "failed save must not close the drawer");
    failing = false;
    await page.getByRole("button", { name: "重试保存", exact: true }).click();
    await page.getByRole("button", { name: "重试保存", exact: true }).waitFor({ state: "hidden" });
    assert.equal(project.nodes[0].estimatedFee, "250");
    await page.locator(".as-midsales-flow-node").filter({ hasText: "设备调试" }).click();
    await expandFee();
    assert.equal(await fee.inputValue(), "100");

    project.nodes[1].estimatedFee = "900";
    project.nodes[1].updatedAt = "remote-change";
    await fee.fill("300");
    await page.getByRole("alert").filter({ hasText: "节点已被其他人更新" }).first().waitFor();
    assert.equal(project.nodes[1].estimatedFee, "900");
    assert.equal(await fee.inputValue(), "300");
    await page.getByRole("button", { name: "放弃修改并重新加载", exact: true }).click();
    const confirm = page.getByRole("alertdialog", { name: "是否放弃修改" });
    await confirm.getByRole("button", { name: "继续编辑" }).click();
    assert.equal(await fee.inputValue(), "300");
    await page.getByRole("button", { name: "放弃修改并重新加载", exact: true }).click();
    await confirm.getByRole("button", { name: "确认放弃" }).click();
    await page.waitForFunction(() => document.querySelector('[aria-label="当前节点预计费用"]')?.value === "900");
    await expandFee();

    failing = true;
    await fee.fill("400");
    await page.getByRole("alert").filter({ hasText: "测试网络暂不可用" }).first().waitFor();
    await page.goBack();
    await confirm.getByRole("button", { name: "继续编辑" }).click();
    assert.equal(await fee.inputValue(), "400");
    await page.goBack();
    await confirm.getByRole("button", { name: "确认放弃" }).click();
    await page.locator(".as-project-drawer-close").waitFor({ state: "hidden" });
    assert.equal(project.nodes[1].estimatedFee, "900");

    await nav.getByRole("button", { name: "服务团队", exact: true }).click();
    const pagination = page.getByRole("navigation", { name: "服务团队分页" });
    await pagination.getByRole("button", { name: "第 7 页", exact: true }).click();
    await page.getByText("服务人员125", { exact: true }).waitFor();
    assert.ok(providerPages.includes(1) && providerPages.includes(2));
    const search = page.getByRole("searchbox").first();
    await search.fill("服务人员125");
    await page.getByRole("status").filter({ hasText: "共 1 条" }).waitFor();
    assert.equal(await pagination.getByRole("button", { name: "第 1 页", exact: true }).getAttribute("aria-current"), "page");
    await page.getByText("服务人员125", { exact: true }).waitFor();
    assert.deepEqual(errors, []);
  } finally { await browser?.close(); await server.close(); }
});
