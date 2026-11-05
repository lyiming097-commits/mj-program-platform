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

test("overview retains local work during CRM sync, retries errors and displays full totals with bounded lists", { timeout: 60000 }, async () => {
  const server = await createServer({ root, configFile: path.join(root, "vite.config.ts"), server: { host: "127.0.0.1", port: 0 } });
  let browser;
  let state = "http-error";
  let dashboardRequests = 0;
  const requests = [];
  const pageErrors = [];
  const local = { id: 1, name: "本地售中项目", customer: "测试学校", serviceType: "midsales", ownerName: "当前管理员", statusLabel: "进行中", currentNodeKey: "midsales-project" };
  const incomplete = {
    metrics: { activeProjects: 1, openTickets: 1, pendingFeedback: 0, pendingRewards: 0 },
    recentProjects: [local], tasks: [], alerts: [], taskTotal: 0, alertTotal: 0,
    crmScopeReady: false, crmSyncing: true, crmSyncError: "",
  };
  const complete = {
    metrics: { activeProjects: 1500, openTickets: 1500, pendingFeedback: 1500, pendingRewards: 1500 },
    recentProjects: [local, { ...local, id: 2, name: "CRM 售前项目", serviceType: "presales", currentNodeKey: "early-plan",
      activeNodes: [{ nodeKey: "early-plan", name: "前期方案" }, { nodeKey: "budget-match", name: "预算匹配" }] }],
    tasks: Array.from({ length: 8 }, (_, index) => ({ id: index + 1, nodeId: index + 1, nodeKey: "early-approval", title: `待办 ${index + 1}`, projectId: 2, projectName: "CRM 售前项目", serviceType: "presales", deadline: "2026-10-14T23:59:59+08:00", dueText: "已超时 1 天" })),
    alerts: Array.from({ length: 8 }, (_, index) => ({ id: `risk-${index}`, title: `风险 ${index + 1}`, description: "节点超时", projectId: 2, serviceType: "presales", level: "high" })),
    taskTotal: 1500, alertTotal: 4500, crmScopeReady: true, crmSyncing: false, crmSyncError: "",
  };
  const executorProject = {
    ...local, id: 2, name: "执行人任务项目", serviceType: "presales", status: "in_progress", currentNodeKey: "early-plan",
    businessData: {}, assignments: [], events: [], nodes: [
      { id: 21, nodeKey: "early-plan", name: "前期方案", kind: "delivery", status: "active", enabled: true, sequence: 2,
        businessData: { managementAssignment: { userId: "service-admin", name: "当前管理员" }, schemeRounds: [{}, {}, {}, {}] } },
    ],
  };
  const roundTasks = [
    { deadline: "2026-10-18T23:59:59+08:00", dueText: "还有 3 天到期" },
    { deadline: "2026-10-15T23:59:59+08:00", dueText: "今天到期" },
    { deadline: "2026-10-13T23:59:59+08:00", dueText: "已超时 2 天" },
    { deadline: "", dueText: "未设置预计完成时间" },
  ].map((timing, index) => ({
    id: `presales-task-${index + 1}`, nodeId: 21, nodeKey: "early-plan", roundNumber: index + 1,
    title: `前期方案 · 第 ${index + 1} 轮`, projectId: 2, projectName: executorProject.name, serviceType: "presales", ...timing,
  }));
  const executorData = {
    ...complete, recentProjects: [executorProject], tasks: roundTasks, taskTotal: 4, alertTotal: 3,
    alerts: [roundTasks[2], roundTasks[1], roundTasks[0]].map(task => ({
      ...task, id: `risk-${task.id}`, level: task.roundNumber === 3 ? "high" : "medium",
      title: `${task.projectName} / ${task.title}${task.dueText}`, description: "本轮预计完成提醒",
    })),
  };
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.clock.install();
    async function nextAutomaticRefresh() {
      const response = page.waitForResponse((item) => new URL(item.url()).pathname === "/api/after-sales/dashboard");
      await page.clock.fastForward(30_100);
      await response;
    }
    await page.addInitScript(() => sessionStorage.setItem("mj_program_login_session", JSON.stringify({
      sessionId: "dashboard-test", userId: "service-admin", name: "当前管理员", loginType: "scan",
    })));
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      requests.push(url.pathname);
      let body = { items: [] };
      let status = 200;
      if (url.pathname === "/api/auth/session/validate") {
        body = { sessionId: "dashboard-test", userId: "service-admin", name: "当前管理员", loginType: "scan" };
      } else if (url.pathname === "/api/after-sales/session/") {
        body = { canManageApp: true, canManageSettings: true, appPermission: "admin" };
      } else if (url.pathname === "/api/after-sales/dashboard") {
        dashboardRequests += 1;
        const captured = state;
        if (captured === "http-error") {
          status = 503;
          body = { ok: false, error: "总览读取失败" };
        } else if (captured === "pending") {
          body = incomplete;
          state = "ready";
        } else if (captured === "source-error") {
          body = { ...incomplete, crmSyncing: false, crmSyncError: "CRM 项目暂时无法读取，请稍后重试" };
        } else if (captured === "project-risk") {
          body = { ...executorData, tasks: [], taskTotal: 0 };
        } else body = captured === "executor" ? executorData : complete;
      } else if (url.pathname === "/api/after-sales/projects") {
        body = { items: [executorProject], total: 1, totalPages: 1, page: 1 };
      } else if (url.pathname === "/api/after-sales/projects/2") {
        body = { ok: true, item: executorProject };
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/after-sales/`);
    try {
      await page.getByText("总览暂未加载成功，稍后自动重试", { exact: true }).first().waitFor({ timeout: 6000 });
    } catch (reason) {
      throw new Error(JSON.stringify({ body: await page.locator("body").innerText(), requests, pageErrors }), { cause: reason });
    }
    const metrics = page.getByRole("region", { name: "关键指标" });
    assert.equal(await metrics.locator("strong").filter({ hasText: "—" }).count(), 4);
    state = "pending";
    await nextAutomaticRefresh();
    await page.getByRole("status").filter({ hasText: "以下统计暂未计入" }).waitFor();
    await page.getByText("本地售中项目", { exact: true }).waitFor();
    assert.equal(await metrics.locator("strong").first().innerText(), "1");
    await page.clock.fastForward(5100);
    await page.getByText("CRM 售前项目", { exact: true }).first().waitFor();
    assert.deepEqual(await page.getByRole("row").filter({ hasText: "CRM 售前项目" }).locator(".as-dashboard-node").allTextContents(), ["前期方案", "预算匹配"]);
    assert.equal(await metrics.locator("strong").first().innerText(), "1500");
    assert.equal(await page.getByRole("button", { name: /^待办 \d+/ }).count(), 8);
    assert.equal(await page.getByRole("button", { name: /^风险 \d+/ }).count(), 8);
    await page.getByText("1500 项待处理", { exact: false }).waitFor();
    assert.equal(await page.getByText("4500", { exact: true }).count(), 1);
    assert.ok(!requests.includes("/api/after-sales/projects"), "overview must not load project-list pages");
    for (const viewport of [{ width: 1440, height: 900 }, { width: 1024, height: 768 }]) {
      await page.setViewportSize(viewport);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "overview must not overflow the viewport");
      assert.equal(await page.getByRole("button", { name: "刷新总览" }).count(), 0);
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: path.join(root, "../../../.codex-artifacts/after-sales-dashboard-bounded.png"), fullPage: true });
    state = "source-error";
    await nextAutomaticRefresh();
    await page.getByRole("alert").filter({ hasText: "CRM 项目暂时无法读取" }).waitFor();
    assert.equal(await metrics.locator("strong").first().innerText(), "1");
    await page.getByText("本地售中项目", { exact: true }).waitFor();
    state = "ready";
    await nextAutomaticRefresh();
    await page.getByText("CRM 售前项目", { exact: true }).first().waitFor();
    state = "project-risk";
    await nextAutomaticRefresh();
    await page.getByText("当前没有待办", { exact: true }).waitFor();
    assert.equal(await page.locator(".as-task-row").count(), 0);
    assert.equal(await page.locator(".as-alert-row").count(), 3, "project risks must remain visible even when no task is assigned to this user");
    await page.locator(".as-alert-row").getByText("已超时 2 天", { exact: true }).waitFor();
    await page.screenshot({ path: path.join(root, "../../../.codex-artifacts/after-sales-risks-without-personal-tasks.png"), fullPage: true });
    state = "executor";
    await nextAutomaticRefresh();
    await page.getByRole("button", { name: /^前期方案 · 第 1 轮/ }).waitFor();
    assert.equal(await page.locator(".as-task-row").count(), 4);
    assert.equal(await page.locator(".as-alert-row").count(), 3);
    assert.equal(await page.locator(".as-task-row em.is-overdue").innerText(), "已超时 2 天");
    assert.equal(await page.locator(".as-severity.is-medium").count(), 2);
    for (const dueText of ["还有 3 天到期", "今天到期"]) {
      assert.ok(await page.locator(".as-task-row").getByText(dueText, { exact: true }).isVisible());
    }
    const undatedTask = page.getByRole("button", { name: /^前期方案 · 第 4 轮/ });
    assert.ok(await undatedTask.isVisible(), "undated tasks must remain in the list");
    assert.equal(await undatedTask.locator("em").count(), 0, "undated tasks must not render a deadline hint");
    await page.screenshot({ path: path.join(root, "../../../.codex-artifacts/after-sales-executor-reminders.png"), fullPage: true });
    await page.getByRole("button", { name: /^执行人任务项目 \/ 前期方案 · 第 1 轮/ }).click();
    await page.waitForURL(url => url.pathname === "/after-sales/presales/" && url.searchParams.get("projectId") === "2" && url.searchParams.get("nodeKey") === "early-plan");
    await page.getByRole("navigation", { name: "项目分页" }).waitFor();
    const before = dashboardRequests;
    await page.clock.fastForward(31000);
    assert.equal(dashboardRequests, before, "leaving overview must stop its refresh timer");
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});
