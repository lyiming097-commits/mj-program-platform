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

test("reward, ticket, feedback and team filters match their displayed columns independently", { timeout: 90000 }, async () => {
  const server = await createServer({ root, configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-column-filters"),
    server: { host: "127.0.0.1", port: 0 } });
  let browser;
  const rewards = [
    { id: 1, prize: "工具包", projectName: "西湖学校", providerName: "张工" },
    { id: 2, prize: "西湖学校纪念杯", projectName: "工具包试用", providerName: "李工" },
    { id: 3, prize: "工具包", projectName: "南湖学校", providerName: "王工" },
  ].map(item => ({ status: "pending", ...item }));
  const tickets = [
    { id: 1, title: "门锁故障", projectName: "西湖学校", reporterName: "张工", ownerName: "李工", nodeName: "设备安装" },
    { id: 2, title: "西湖学校排查", projectName: "南湖学校", reporterName: "李工", ownerName: "张工", nodeName: "现场服务" },
    { id: 3, title: "门锁故障", projectName: "西湖学校", reporterName: "王工", ownerName: "赵工", nodeName: "设备调试" },
  ].map(item => ({ code: "T-" + item.id, projectCode: "P-" + item.id, status: "open", ...item }));
  const feedback = tickets.map(item => ({ ...item, providerName: item.reporterName,
    feedbackType: "suggestion", feedbackTypeLabel: "改进建议", status: "submitted" }));
  const providers = [
    { id: 1, name: "张工", phone: "13800000001", city: "杭州", skills: ["安装"] },
    { id: 2, name: "李工", phone: "13800000002", city: "张工服务区", skills: ["张工技能"] },
  ].map(item => ({ certificationStatus: "certified", ...item }));
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => sessionStorage.setItem("mj_program_login_session", JSON.stringify({
      sessionId: "column-filter-test", userId: "manager", name: "管理员", loginType: "scan",
    })));
    await page.route("**/api/**", async route => {
      const { pathname } = new URL(route.request().url());
      let body = { items: [] };
      if (pathname === "/api/auth/session/validate") body = { sessionId: "column-filter-test", userId: "manager", name: "管理员", loginType: "scan" };
      else if (pathname === "/api/after-sales/session/") body = { canManageApp: true, canManageSettings: true, appPermission: "admin" };
      else if (pathname === "/api/after-sales/rewards") body = { items: rewards };
      else if (pathname === "/api/after-sales/tickets") body = { items: tickets };
      else if (pathname === "/api/after-sales/feedback") body = { items: feedback };
      else if (pathname === "/api/after-sales/providers") body = { items: providers };
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto("http://127.0.0.1:" + server.httpServer.address().port + "/after-sales/");
    const navigation = page.getByRole("navigation", { name: "主导航" });
    const search = name => page.getByRole("searchbox", { name, exact: true });
    const values = async (table, column, expected) => {
      await page.waitForFunction(({ label, column, expected }) => {
        const table = document.querySelector(`table[aria-label="${label}"]`);
        const rows = [...(table?.tBodies[0]?.rows || [])].filter(row => row.cells.length > 1);
        return JSON.stringify(rows.map(row => row.cells[column].querySelector("strong")?.textContent || row.cells[column].textContent)) === JSON.stringify(expected);
      }, { label: await table.getAttribute("aria-label"), column, expected });
    };

    await navigation.getByRole("button", { name: "服务奖励", exact: true }).click();
    const rewardTable = page.getByRole("table", { name: "服务奖励列表" });
    await search("搜索奖品名称").fill("西湖学校");
    await values(rewardTable, 1, ["工具包试用"]);
    await search("搜索奖品名称").fill("工具包");
    await search("搜索奖励项目名称").fill("西湖学校");
    await values(rewardTable, 2, ["张工"]);
    await search("搜索获得人员").fill("李工");
    await values(rewardTable, 0, []);
    await search("搜索奖品名称").fill("");
    await search("搜索奖励项目名称").fill("");
    await values(rewardTable, 1, ["工具包试用"]);
    assert.equal(await search("搜索获得人员").inputValue(), "李工");

    await navigation.getByRole("button", { name: "工单与反馈", exact: true }).click();
    const ticketTable = page.getByRole("table", { name: "工单列表" });
    await search("搜索工单").fill("西湖学校");
    await values(ticketTable, 0, ["西湖学校排查"]);
    await search("搜索工单").fill("门锁");
    await search("搜索工单所属项目").fill("西湖学校");
    await search("搜索工单节点").fill("设备安装");
    await search("搜索工单提交人").fill("张工");
    await search("搜索工单处理人").fill("李工");
    await values(ticketTable, 0, ["门锁故障"]);
    await search("搜索工单处理人").fill("张工");
    await values(ticketTable, 0, []);
    await search("搜索工单处理人").fill("李工");
    await values(ticketTable, 0, ["门锁故障"]);
    await page.screenshot({ path: "/tmp/after-sales-ticket-column-filters-1440.png", fullPage: true });
    await page.setViewportSize({ width: 1024, height: 768 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({ path: "/tmp/after-sales-ticket-column-filters-1024.png", fullPage: true });
    await page.setViewportSize({ width: 1440, height: 960 });

    await page.getByRole("tab", { name: /^反馈/ }).click();
    const feedbackTable = page.getByRole("table", { name: "反馈列表" });
    await search("搜索反馈").fill("西湖学校");
    await values(feedbackTable, 0, ["西湖学校排查"]);
    await search("搜索反馈").fill("门锁");
    await search("搜索反馈所属项目").fill("西湖学校");
    await search("搜索反馈节点").fill("设备安装");
    await search("搜索反馈类型").fill("改进建议");
    await search("搜索反馈提交人").fill("张工");
    await values(feedbackTable, 0, ["门锁故障"]);
    await search("搜索反馈提交人").fill("李工");
    await values(feedbackTable, 0, []);

    await navigation.getByRole("button", { name: "服务团队", exact: true }).click();
    const teamTable = page.getByRole("tabpanel", { name: "人员列表" }).getByRole("table");
    await search("搜索服务人员").fill("张工");
    await teamTable.getByRole("cell").filter({ has: page.getByText("张工", { exact: true }) }).waitFor();
    assert.equal(await teamTable.getByText("李工", { exact: true }).count(), 0);
    await search("搜索服务人员").fill("13800000002");
    await teamTable.getByText("李工", { exact: true }).waitFor();
    assert.equal(await teamTable.getByText("张工", { exact: true }).count(), 0);
    assert.deepEqual(errors, []);
  } finally { await browser?.close(); await server.close(); }
});
