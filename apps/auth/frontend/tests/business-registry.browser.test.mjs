import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));
const artifacts = fileURLToPath(new URL("../../../../.codex-artifacts/business-registry/", import.meta.url));
const api = "/api/org/business-registry";
const session = {
  sessionId: "registry-test-session", userId: "registry-admin", name: "测试管理员",
  canUseSystemAdmin: true, isFullAccessUser: true, canConfigurePermissions: true, canManagePlatformSettings: true,
};
const fixtures = Array.from({ length: 21 }, (_, index) => ({
  id: index + 1, companyName: `测试工商企业 ${String(index + 1).padStart(2, "0")}${index === 4 ? "（长名称排版验收分公司）" : ""}`,
  creditNo: `TEST${String(index + 1).padStart(14, "0")}`, companyCode: `TESTREG${String(index + 1).padStart(8, "0")}`,
  legalPerson: "测试法人", companyStatus: ["在营（开业）", "存续", "注销", "吊销", "清算"][index % 5], establishDate: "20130306",
  firstQueriedAt: "2026-10-11T02:00:00Z", lastQueriedAt: "2026-10-12T02:00:00Z", lastQueryId: index < 20 ? 1 : 2,
}));

test("business registry lookup saves each requested page and history is readable without paid calls", async () => {
  const server = await createServer({ root, server: { host: "127.0.0.1", port: 0, strictPort: false } });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  await mkdir(artifacts, { recursive: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, locale: "zh-CN" });
    await context.addInitScript((value) => {
      sessionStorage.setItem("mj_program_login_session", JSON.stringify(value));
      Object.defineProperty(crypto, "randomUUID", { value: undefined });
    }, session);
    const queries = [];
    const saved = [];
    const posts = [];
    let failNextRead = false;
    let abortNextResponse = false;
    let failNextHistoryRead = false;
    let configured = true;
    let releaseFirstSearch;
    let firstSearchResponse = new Promise((resolve) => { releaseFirstSearch = resolve; });
    let releaseNextSearch;
    let nextSearchResponse = null;
    await context.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      const path = url.pathname;
      let body = path === "/api/auth/session/validate" ? session : { items: [], orgRevision: 1 };
      if (path === `${api}/search`) {
        const payload = route.request().postDataJSON();
        posts.push(payload);
        body = queries.find((item) => item.requestId === payload.requestId);
        if (!body) {
          const failed = payload.keyword === "接口失败";
          const noCompanies = failed || ["没有结果", "处理中"].includes(payload.keyword);
          const companies = noCompanies ? [] : structuredClone(fixtures.slice((payload.pageNum - 1) * 20, payload.pageNum * 20));
          if (payload.keyword === "另一模糊词" && companies.length) companies[0].legalPerson = "新法人";
          body = { ...payload, id: queries.length + 1, status: payload.keyword === "处理中" ? "running" : failed ? "failed" : companies.length ? "succeeded" : "empty",
            message: failed ? "工商服务请求超时，未自动重试" : companies.length ? `已保存本页 ${companies.length} 条企业信息` : "查无数据",
            resultCount: companies.length, totalRecords: 21, companies, orderNo: "TEST-QUERY-ORDER",
            actorName: "测试管理员", actorUserId: "registry-admin", effectiveName: "测试管理员", effectiveUserId: "registry-admin",
            createdAt: "2026-10-12T02:00:00Z" };
          queries.unshift(body);
          for (const company of companies) {
            const current = saved.find((row) => row.id === company.id);
            if (current) Object.assign(current, company);
            else saved.push({ ...company });
          }
        }
        if (firstSearchResponse) { await firstSearchResponse; firstSearchResponse = null; }
        if (nextSearchResponse) { await nextSearchResponse; nextSearchResponse = null; }
        if (abortNextResponse) { abortNextResponse = false; await route.abort("failed"); return; }
      } else if ([`${api}/companies`, `${api}/queries`].includes(path)) {
        if (failNextRead) {
          failNextRead = false;
          await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "测试加载失败" }) });
          return;
        }
        const keyword = url.searchParams.get("keyword") || "";
        const page = Number(url.searchParams.get("page") || 1);
        const source = path.endsWith("companies") ? saved : queries;
        const matches = source.filter((row) => {
          if (!(row.companyName || row.keyword).includes(keyword)) return false;
          const textFields = path.endsWith("companies") ? ["companyName", "creditNo", "companyCode", "legalPerson"] : ["actorName"];
          if (textFields.some((key) => !String(row[key] || "").includes(url.searchParams.get(key === "actorName" ? "actor" : key) || ""))) return false;
          if (["companyStatus", "status", "pageNum", "resultCount"].some((key) => url.searchParams.get(key) && String(row[key]) !== url.searchParams.get(key))) return false;
          if (url.searchParams.get("establishDate") && row.establishDate.replaceAll("-", "") !== url.searchParams.get("establishDate").replaceAll("-", "")) return false;
          for (const [key, field] of [["lastQueriedOn", "lastQueriedAt"], ["createdOn", "createdAt"]]) {
            if (url.searchParams.get(key) && new Date(row[field]).toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" }) !== url.searchParams.get(key)) return false;
          }
          return true;
        });
        body = { configured, total: matches.length, items: matches.slice((page - 1) * 20, page * 20).map((row) => ({ ...row, queryCount: queries.filter((query) => query.companies.some((company) => company.id === row.id)).length })), filterOptions: { companyStatuses: [...new Set(saved.map((row) => row.companyStatus))] } };
      } else if (path.startsWith(`${api}/companies/`) && path.endsWith("/queries")) {
        if (failNextHistoryRead) {
          failNextHistoryRead = false;
          await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "历史查询加载失败" }) });
          return;
        }
        const companyId = Number(path.split("/").at(-2));
        const historyPage = Number(url.searchParams.get("page") || 1);
        const matches = queries.filter((query) => query.companies.some((company) => company.id === companyId));
        body = { company: saved.find((row) => row.id === companyId), page: historyPage, total: matches.length, items: matches.slice((historyPage - 1) * 20, historyPage * 20) };
      } else if (path.startsWith(`${api}/queries/`)) {
        body = queries.find((row) => row.id === Number(path.split("/").at(-1)));
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const url = `http://127.0.0.1:${server.httpServer.address().port}/auth/settings/business-registry`;
    await page.goto(url);
    const panel = page.getByRole("tabpanel", { name: "工商信息查询", exact: true });
    await panel.getByText("暂无已保存企业，完成查询后会自动记录在这里。").waitFor();
    const sidebar = page.getByRole("navigation", { name: "主导航" });
    assert.deepEqual(await sidebar.getByRole("button").allTextContents(), ["组织架构", "我司主体", "省市区域", "工商信息查询", "机器人群发"]);
    assert.match(await sidebar.getByRole("button", { name: "工商信息查询" }).getAttribute("class"), /active/);
    assert.equal(await panel.getByRole("heading", { name: "工商信息查询", exact: true }).count(), 0);
    assert.equal(await panel.getByRole("form", { name: "企业工商查询", exact: true }).count(), 0);
    assert.equal(await panel.getByRole("searchbox", { name: "搜索已保存企业" }).count(), 0);
    await panel.getByRole("row", { name: "企业列筛选" }).waitFor();
    await panel.getByRole("button", { name: "查询企业", exact: true }).click();
    const lookupDrawer = page.getByRole("dialog", { name: "企业工商查询", exact: true });
    await lookupDrawer.waitFor();
    const singleField = lookupDrawer.getByRole("region", { name: "单选企业", exact: true });
    const keyword = singleField.getByRole("combobox");
    await page.waitForFunction(() => document.activeElement?.getAttribute("role") === "combobox");
    assert.equal(await lookupDrawer.getByRole("combobox").count(), 2);
    assert.equal(await lookupDrawer.getByRole("spinbutton").count(), 0);
    assert.equal(await singleField.getByRole("button", { name: "查询", exact: true }).isDisabled(), true);
    await keyword.fill("测试工商");
    assert.equal(posts.length, 0);
    assert.equal(await page.getByRole("listbox", { name: "查询结果，单选企业" }).count(), 0);
    const [controlBox, inputBox, submitBox] = await singleField.getByRole("search", { name: "单选企业工商查询" }).evaluate((form) =>
      [form.querySelector(".registry-query-control"), form.querySelector("input"), form.querySelector('button[type="submit"]')].map((element) => element.getBoundingClientRect().toJSON()));
    assert.ok(submitBox.x >= inputBox.right && Math.abs(controlBox.right - submitBox.right) <= 2, "query action is inside the input's right edge");
    assert.ok(Math.abs(controlBox.y + controlBox.height / 2 - submitBox.y - submitBox.height / 2) < 1);
    await page.screenshot({ path: `${artifacts}/api-lookup-empty-1440.png` });
    await singleField.getByRole("button", { name: "查询", exact: true }).click();
    const busyButton = singleField.getByRole("button", { name: "查询中…", exact: true });
    await busyButton.waitFor();
    assert.equal((await busyButton.innerText()).trim(), "", "query progress only shows the right-side spinner");
    assert.equal(await busyButton.getAttribute("aria-busy"), "true");
    assert.equal(await singleField.getByRole("status").count(), 0, "no extra progress row below the field");
    await page.screenshot({ path: `${artifacts}/spinner-only-loading-1440.png` });
    assert.equal(await keyword.isDisabled(), true);
    assert.equal(await lookupDrawer.getByRole("button", { name: "查询中…", exact: true }).isDisabled(), true);
    assert.equal(await lookupDrawer.getByRole("button", { name: "关闭工商查询详情" }).isDisabled(), true);
    await page.keyboard.press("Escape");
    assert.equal(await lookupDrawer.isVisible(), true);
    assert.equal(posts.length, 1);
    releaseFirstSearch();
    const drawer = page.getByRole("dialog", { name: /^(工商查询详情|企业详情)$/ });
    await page.getByRole("listbox", { name: "查询结果，单选企业" }).waitFor();
    assert.equal(posts.length, 1);
    const resultList = page.getByRole("listbox", { name: "查询结果，单选企业" });
    const resultRegion = page.getByRole("region", { name: "企业查询结果", exact: true });
    assert.equal(await resultList.getByRole("option").count(), 20);
    assert.equal(saved.length, 20, "the full page is saved before any selection");
    await page.waitForFunction(() => document.activeElement?.getAttribute("role") === "combobox");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await resultList.waitFor({ state: "hidden" });
    assert.equal(await keyword.inputValue(), "测试工商企业 02", "chosen company name fills the field");
    assert.match(await keyword.getAttribute("title"), /TEST00000000000002/);
    await keyword.click();
    assert.equal(await resultList.getByRole("option", { selected: true }).count(), 1);
    await page.keyboard.press("End");
    await page.keyboard.press("Enter");
    assert.equal(await keyword.inputValue(), "测试工商企业 20");
    assert.equal(posts.length, 1, "choosing a company never calls the paid API");
    await keyword.click();
    await resultList.getByRole("option").first().click();
    assert.equal(await keyword.inputValue(), "测试工商企业 01");
    await keyword.fill("");
    assert.equal(await keyword.inputValue(), "");
    assert.equal(await singleField.getByRole("button", { name: "查询", exact: true }).isDisabled(), true);
    assert.equal(posts.length, 1);
    await keyword.fill("测试工商");
    await keyword.press("ArrowDown");
    await resultList.getByRole("option").first().click();
    await page.screenshot({ path: `${artifacts}/combined-field-selected-1440.png` });
    await keyword.click();
    await page.keyboard.press("Escape");
    assert.equal(await lookupDrawer.isVisible(), true, "first Escape closes the dropdown only");
    assert.equal(await keyword.getAttribute("aria-expanded"), "false");
    await keyword.press("ArrowDown");
    await lookupDrawer.getByRole("heading", { name: "企业工商查询", exact: true }).click();
    assert.equal(await keyword.getAttribute("aria-expanded"), "false", "outside click closes the result menu");
    assert.equal(await lookupDrawer.isVisible(), true);
    await keyword.press("ArrowDown");
    for (const width of [1440, 1024, 800]) {
      await page.setViewportSize({ width, height: 960 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      const bounds = await resultRegion.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1 && bounds.y + bounds.height <= 960, "results stay inside the viewport");
      await page.screenshot({ path: `${artifacts}/combined-field-results-${width}.png` });
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    assert.equal(posts[0].pageNum, 1);
    assert.equal(posts[0].pageSize, 20);
    assert.match(posts[0].requestId, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    await page.screenshot({ path: `${artifacts}/query-detail-1440.png` });
    assert.equal(await lookupDrawer.getByRole("button", { name: /查询.*页并保存/ }).count(), 0);
    nextSearchResponse = new Promise((resolve) => { releaseNextSearch = resolve; });
    await resultRegion.evaluate((element) => { element.scrollTop = element.scrollHeight; });
    await resultRegion.getByText("加载中…", { exact: true }).waitFor();
    assert.equal(await resultList.getByRole("option").count(), 20, "previous results stay visible while the next page loads");
    assert.equal(await lookupDrawer.getByRole("button", { name: "关闭工商查询详情" }).isDisabled(), true);
    const scrollBeforeAppend = await resultRegion.evaluate((element) => element.scrollTop);
    await resultRegion.evaluate((element) => { for (let index = 0; index < 5; index++) element.dispatchEvent(new Event("scroll")); });
    assert.equal(posts.length, 2, "repeated bottom events do not start concurrent paid requests");
    releaseNextSearch();
    await resultList.getByRole("option", { name: "测试工商企业 21，TEST00000000000021", exact: true }).waitFor();
    assert.equal(posts.length, 2);
    assert.equal(posts[1].pageNum, 2);
    assert.equal(posts[1].keyword, "测试工商", "next page uses the original keyword even after a company is selected");
    assert.equal(await resultList.getByRole("option").count(), 21, "next page is appended to the first page");
    assert.equal(await resultList.getByRole("option", { selected: true }).count(), 1, "selection survives appended pages");
    assert.equal(await keyword.inputValue(), "测试工商企业 01");
    assert.ok(Math.abs(await resultRegion.evaluate((element) => element.scrollTop) - scrollBeforeAppend) < 1, "appending preserves the scroll position");
    await resultRegion.evaluate((element) => { element.scrollTop = element.scrollHeight; });
    await resultRegion.getByText("已全部加载", { exact: true }).waitFor();
    assert.equal(await resultRegion.getByRole("button", { name: "加载更多", exact: true }).count(), 0);
    await page.screenshot({ path: `${artifacts}/load-more-complete-1440.png` });
    await lookupDrawer.getByRole("button", { name: "关闭工商查询详情" }).click();
    await panel.getByText("共 21 条 · 每页 20 条", { exact: true }).waitFor();
    assert.equal(await panel.getByRole("button", { name: "第 1 页", exact: true }).getAttribute("aria-current"), "page");
    for (const width of [1920, 1440, 1024, 800]) {
      await page.setViewportSize({ width, height: 960 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      const table = panel.getByRole("table", { name: "已保存企业", exact: true });
      assert.equal(await table.getByRole("columnheader", { name: "统一社会信用代码", exact: true }).count(), 1);
      assert.equal(await table.getByRole("columnheader", { name: "注册号", exact: true }).count(), 1);
      const row = table.locator("tbody tr").first();
      assert.equal(await row.getByRole("cell").first().textContent(), "1");
      assert.ok((await row.boundingBox()).height <= 50, "single-line enterprise records should use the template's compact rows");
      assert.ok((await panel.getByRole("navigation", { name: "工商信息查询记录分页" }).boundingBox()).y < 960, "pagination must remain visible");
      await page.screenshot({ path: `${artifacts}/saved-companies-${width}.png` });
    }
    const tableScroll = panel.getByLabel("已保存企业表格，可使用左右方向键浏览");
    const nameCell = panel.getByRole("table", { name: "已保存企业", exact: true }).locator("tbody tr").first().getByRole("cell").nth(1);
    const nameBefore = await nameCell.boundingBox();
    await tableScroll.focus();
    await page.keyboard.press("ArrowRight");
    assert.ok(await tableScroll.evaluate((element) => element.scrollLeft) > 0);
    assert.ok(Math.abs((await nameCell.boundingBox()).x - nameBefore.x) < 1, "company name stays frozen during horizontal scrolling");
    const header = panel.getByRole("columnheader", { name: "企业名称", exact: true });
    const headerBefore = await header.boundingBox();
    await tableScroll.evaluate((element) => { element.scrollTop = 300; });
    assert.ok(Math.abs((await header.boundingBox()).y - headerBefore.y) < 1, "column headings stay visible during vertical scrolling");
    await tableScroll.evaluate((element) => { element.scrollTop = 0; element.scrollLeft = 0; });
    const dragBox = await tableScroll.boundingBox();
    await page.mouse.move(dragBox.x + 420, dragBox.y + 110);
    await page.mouse.down();
    await page.mouse.move(dragBox.x + 340, dragBox.y + 110, { steps: 8 });
    await page.mouse.up();
    assert.ok(await tableScroll.evaluate((element) => element.scrollLeft) > 0, "table supports horizontal dragging");
    assert.equal(await drawer.isVisible(), false, "dragging must not open a query");
    await page.setViewportSize({ width: 1440, height: 960 });
    await panel.getByRole("button", { name: "第 2 页", exact: true }).click();
    await panel.getByText("测试工商企业 21", { exact: true }).waitFor();
    assert.equal(await panel.getByRole("button", { name: "第 2 页", exact: true }).getAttribute("aria-current"), "page");
    assert.equal(await panel.getByRole("table", { name: "已保存企业", exact: true }).locator("tbody tr").first().getByRole("cell").first().textContent(), "21");
    assert.equal(posts.length, 2);
    const nameFilter = panel.getByRole("searchbox", { name: "筛选企业名称", exact: true });
    await nameFilter.fill("测试工商企业 01");
    await panel.getByText("共 1 条 · 每页 20 条", { exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("companyName"), "测试工商企业 01");
    assert.equal(await nameFilter.evaluate((element) => element === document.activeElement), true, "typing a filter keeps focus after the response");
    await panel.getByRole("searchbox", { name: "筛选注册号", exact: true }).fill("missing-code");
    await panel.getByText("没有匹配的记录，请调整筛选条件。").waitFor();
    assert.equal(await nameFilter.inputValue(), "测试工商企业 01");
    await panel.getByRole("searchbox", { name: "筛选注册号", exact: true }).fill("");
    await panel.getByText("共 1 条 · 每页 20 条", { exact: true }).waitFor();
    const statusFilter = panel.getByRole("combobox", { name: "筛选经营状态", exact: true });
    await statusFilter.click();
    await page.getByRole("option", { name: "存续", exact: true }).click();
    await panel.getByText("没有匹配的记录，请调整筛选条件。").waitFor();
    await panel.getByRole("button", { name: "清空筛选经营状态", exact: true }).click();
    await page.keyboard.press("Escape");
    await panel.getByText("共 1 条 · 每页 20 条", { exact: true }).waitFor();
    await panel.getByLabel("筛选成立日期", { exact: true }).fill("2013-03-06");
    await panel.getByLabel("筛选最近查询日期", { exact: true }).fill("2026-10-12");
    await panel.getByText("共 1 条 · 每页 20 条", { exact: true }).waitFor();
    await page.reload();
    await panel.getByText("共 1 条 · 每页 20 条", { exact: true }).waitFor();
    assert.equal(await nameFilter.inputValue(), "测试工商企业 01");
    assert.equal(await panel.getByLabel("筛选成立日期", { exact: true }).inputValue(), "2013-03-06");
    assert.equal(posts.length, 2, "all column filters and reloads read local records only");
    const historyDrawer = page.getByRole("dialog", { name: "企业详情", exact: true });
    const companyRow = panel.getByRole("row", { name: "查看企业：测试工商企业 01", exact: true });
    await companyRow.getByRole("cell").nth(2).click();
    const companyTabs = historyDrawer.getByRole("tablist", { name: "企业详情页签" });
    const infoTab = companyTabs.getByRole("tab", { name: "工商信息", exact: true });
    const historyTab = companyTabs.getByRole("tab", { name: "历史查询", exact: true });
    const infoPanel = historyDrawer.getByRole("tabpanel", { name: "工商信息", exact: true });
    await infoPanel.getByText("TEST00000000000001", { exact: true }).waitFor();
    assert.deepEqual(await companyTabs.getByRole("tab").allTextContents(), ["工商信息", "历史查询"]);
    assert.equal(await infoTab.getAttribute("aria-selected"), "true", "clicking an ordinary data cell opens company information");
    assert.equal(await infoPanel.getByText("测试工商企业 01", { exact: true }).count(), 1);
    assert.equal(await infoPanel.getByText("测试法人", { exact: true }).count(), 1);
    assert.equal(await infoPanel.getByText("2013-03-06", { exact: true }).count(), 1);
    for (const width of [1440, 1024, 800]) {
      await page.setViewportSize({ width, height: 960 });
      await page.screenshot({ path: `${artifacts}/company-info-${width}.png` });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.equal(await infoPanel.evaluate(element => element.scrollWidth > element.clientWidth), false);
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.keyboard.press("Escape");
    await historyDrawer.waitFor({ state: "hidden" });
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "查看企业：测试工商企业 01");
    await companyRow.press("Space");
    await infoPanel.waitFor();
    await page.keyboard.press("Escape");
    await historyDrawer.waitFor({ state: "hidden" });
    const companyButton = panel.getByRole("button", { name: "查看测试工商企业 01的工商信息", exact: true });
    await companyButton.focus();
    await page.keyboard.press("Enter");
    await infoPanel.waitFor();
    await infoTab.focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(await historyTab.getAttribute("aria-selected"), "true");
    assert.equal(await historyTab.evaluate(element => element === document.activeElement), true);
    await historyDrawer.getByText("共 1 次查询", { exact: true }).waitFor();
    await historyDrawer.getByRole("button", { name: "查看记录1返回的企业", exact: true }).click();
    await drawer.getByText("查询结果 · 20 条", { exact: true }).waitFor();
    assert.equal(await drawer.getByRole("button", { name: "查询下一页并保存" }).count(), 0);
    await drawer.getByRole("button", { name: "返回历史查询", exact: true }).click();
    await historyDrawer.getByText("共 1 次查询", { exact: true }).waitFor();
    await page.keyboard.press("Escape");
    await drawer.waitFor({ state: "hidden" });
    assert.equal(posts.length, 2);
    await panel.getByRole("button", { name: "重置筛选", exact: true }).click();
    await panel.getByText("共 21 条 · 每页 20 条", { exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.has("companyName"), false);
    await panel.getByRole("button", { name: "查询记录", exact: true }).click();
    await panel.getByRole("table", { name: "工商查询记录", exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("view"), "queries");
    await panel.getByRole("row", { name: "查询记录列筛选" }).waitFor();
    await panel.getByRole("spinbutton", { name: "筛选查询页码", exact: true }).fill("2");
    await panel.getByText("共 1 条 · 每页 20 条", { exact: true }).waitFor();
    await panel.getByRole("spinbutton", { name: "筛选保存数量", exact: true }).fill("1");
    await panel.getByRole("searchbox", { name: "筛选操作人", exact: true }).fill("测试管理员");
    await panel.getByLabel("筛选查询日期", { exact: true }).fill("2026-10-12");
    await panel.getByText("共 1 条 · 每页 20 条", { exact: true }).waitFor();
    assert.equal(posts.length, 2);
    await panel.getByRole("button", { name: "重置筛选", exact: true }).click();
    await panel.getByText("共 2 条 · 每页 20 条", { exact: true }).waitFor();
    await page.screenshot({ path: `${artifacts}/query-history-1440.png` });
    await page.reload();
    await panel.getByRole("table", { name: "工商查询记录", exact: true }).waitFor();
    assert.equal(posts.length, 2);
    failNextRead = true;
    await panel.getByRole("button", { name: "刷新", exact: true }).click();
    await panel.getByRole("alert").filter({ hasText: "测试加载失败" }).waitFor();
    await panel.getByRole("button", { name: "重新加载", exact: true }).click();
    await panel.getByRole("table", { name: "工商查询记录", exact: true }).waitFor();
    await panel.getByRole("button", { name: "查询企业", exact: true }).click();
    await keyword.fill("接口失败");
    await singleField.getByRole("button", { name: "查询", exact: true }).click();
    await lookupDrawer.getByText("工商服务请求超时，未自动重试", { exact: true }).first().waitFor();
    assert.equal(posts.length, 3);
    assert.equal(saved.length, 21);
    await page.keyboard.press("Escape");
    // Simulate a lost response after the server has saved the request.
    abortNextResponse = true;
    await panel.getByRole("button", { name: "查询企业", exact: true }).click();
    await keyword.fill("另一模糊词");
    await singleField.getByRole("button", { name: "查询", exact: true }).click();
    await lookupDrawer.getByRole("alert").filter({ hasText: "相同条件再次提交会检查原请求结果" }).waitFor();
    const originalId = posts.at(-1).requestId;
    const queryCount = queries.length;
    await singleField.getByRole("button", { name: "查询", exact: true }).click();
    await resultList.waitFor();
    assert.equal(posts.at(-1).requestId, originalId);
    assert.equal(queries.length, queryCount);
    await lookupDrawer.getByRole("button", { name: "关闭工商查询详情" }).click();
    configured = false;
    await panel.getByRole("button", { name: "刷新", exact: true }).click();
    await panel.getByRole("status").waitFor({ state: "hidden" });
    await panel.getByRole("button", { name: "查询企业", exact: true }).click();
    await singleField.getByText(/工商查询服务尚未配置/).waitFor();
    assert.equal(await singleField.getByRole("button", { name: "查询", exact: true }).isDisabled(), true);
    await page.keyboard.press("Escape");
    await panel.getByRole("button", { name: "已保存企业", exact: true }).click();
    await panel.getByRole("table", { name: "已保存企业", exact: true }).waitFor();
    await page.screenshot({ path: `${artifacts}/unconfigured-1440.png` });
    const paidRequestsBeforeHistory = posts.length;
    failNextHistoryRead = true;
    await panel.getByRole("button", { name: "查看测试工商企业 01的2次历史查询", exact: true }).click();
    await historyDrawer.getByRole("alert").filter({ hasText: "历史查询加载失败" }).waitFor();
    await historyDrawer.getByRole("button", { name: "重新加载", exact: true }).click();
    await historyDrawer.getByText("共 2 次查询", { exact: true }).waitFor();
    assert.equal(await historyDrawer.getByRole("table", { name: "企业历史查询", exact: true }).locator("tbody tr").count(), 2);
    await historyDrawer.getByRole("button", { name: "查看记录4返回的企业", exact: true }).click();
    await drawer.getByText("另一模糊词", { exact: true }).waitFor();
    await drawer.getByRole("tabpanel", { name: "历史查询", exact: true }).getByText("新法人", { exact: true }).waitFor();
    assert.equal(await drawer.getByRole("button", { name: /查询.*页并保存/ }).count(), 0);
    await drawer.getByRole("button", { name: "返回历史查询", exact: true }).click();
    await historyDrawer.getByText("共 2 次查询", { exact: true }).waitFor();
    await page.waitForFunction(() => document.activeElement?.dataset.queryId === "4");
    await historyDrawer.getByRole("button", { name: "查看记录1返回的企业", exact: true }).click();
    await drawer.getByText("查询结果 · 20 条", { exact: true }).waitFor();
    assert.equal(await drawer.getByRole("tabpanel", { name: "历史查询", exact: true }).getByText("新法人", { exact: true }).count(), 0, "old query snapshots retain the old legal person");
    assert.equal(await drawer.getByRole("table", { name: "本次查询企业", exact: true }).locator("tbody tr").count(), 20);
    await page.screenshot({ path: `${artifacts}/company-history-query-detail-1440.png` });
    await drawer.getByRole("button", { name: "返回历史查询", exact: true }).click();
    await historyDrawer.getByText("共 2 次查询", { exact: true }).waitFor();
    // Existing saved query fixtures exercise local history pagination without external requests.
    const originalQuery = queries.find((query) => query.id === 1);
    for (let index = 100; index < 121; index++) queries.unshift({ ...structuredClone(originalQuery), id: index, keyword: `历史关键词 ${index}` });
    await historyDrawer.getByRole("button", { name: "刷新", exact: true }).click();
    await historyDrawer.getByText("共 23 次查询", { exact: true }).waitFor();
    for (const width of [1440, 1024, 800]) {
      await page.setViewportSize({ width, height: 960 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      const historyPagination = historyDrawer.getByRole("navigation", { name: "企业历史查询分页" });
      assert.ok((await historyPagination.boundingBox()).y < 960);
      await page.screenshot({ path: `${artifacts}/company-query-history-${width}.png` });
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    await historyDrawer.getByRole("button", { name: "下一页", exact: true }).click();
    await historyDrawer.getByText("第 2 / 2 页", { exact: true }).waitFor();
    await infoTab.click();
    await infoPanel.waitFor();
    await infoPanel.getByText("新法人", { exact: true }).waitFor();
    await historyTab.click();
    await historyDrawer.getByText("第 2 / 2 页", { exact: true }).waitFor();
    await historyDrawer.getByRole("button", { name: "查看记录1返回的企业", exact: true }).click();
    await drawer.getByText("查询结果 · 20 条", { exact: true }).waitFor();
    await infoTab.click();
    await infoPanel.waitFor();
    await historyTab.click();
    await drawer.getByText("查询结果 · 20 条", { exact: true }).waitFor();
    await drawer.getByRole("button", { name: "返回历史查询", exact: true }).click();
    await historyDrawer.getByText("第 2 / 2 页", { exact: true }).waitFor();
    await page.waitForFunction(() => document.activeElement?.dataset.queryId === "1");
    await page.keyboard.press("Escape");
    await historyDrawer.waitFor({ state: "hidden" });
    assert.equal(posts.length, paidRequestsBeforeHistory, "history views, retries, and pagination never call the paid API");
    configured = true;
    await panel.getByRole("button", { name: "刷新", exact: true }).click();
    await panel.getByRole("status").waitFor({ state: "hidden" });
    await panel.getByRole("button", { name: "查询企业", exact: true }).click();
    await keyword.fill("没有结果");
    await keyword.press("Enter");
    await page.getByText("没有匹配的企业，请调整关键词后重新查询。", { exact: true }).waitFor();
    assert.equal(await keyword.inputValue(), "没有结果");
    assert.equal(await page.getByRole("listbox", { name: "查询结果，单选企业" }).getByRole("option").count(), 0);
    await keyword.fill("处理中");
    await singleField.getByRole("button", { name: "查询", exact: true }).click();
    await page.getByText("查询仍在处理中，请稍后刷新结果。", { exact: true }).waitFor();
    const postsBeforeRefresh = posts.length;
    Object.assign(queries[0], { status: "succeeded", resultCount: 20, companies: structuredClone(fixtures.slice(0, 20)) });
    await lookupDrawer.getByRole("button", { name: "刷新查询状态", exact: true }).click();
    await page.getByRole("listbox", { name: "查询结果，单选企业" }).waitFor();
    assert.equal(posts.length, postsBeforeRefresh, "refreshing a running request reads only its saved record");
    abortNextResponse = true;
    await resultRegion.evaluate((element) => { element.scrollTop = element.scrollHeight; });
    await resultRegion.getByRole("alert").filter({ hasText: "点击重试会检查原请求结果" }).waitFor();
    const lostPageRequest = posts.at(-1);
    assert.equal(lostPageRequest.pageNum, 2);
    assert.equal(await resultList.getByRole("option").count(), 20);
    await resultRegion.getByRole("button", { name: "重试加载", exact: true }).click();
    await resultRegion.getByRole("button", { name: "查询处理中，刷新结果", exact: true }).waitFor();
    assert.equal(posts.at(-1).pageNum, 2, "retry after a lost page response keeps the original page");
    assert.equal(posts.at(-1).requestId, lostPageRequest.requestId);
    const postsBeforeMoreRefresh = posts.length;
    Object.assign(queries[0], { status: "succeeded", resultCount: 1, companies: structuredClone(fixtures.slice(20)) });
    await resultRegion.getByRole("button", { name: "查询处理中，刷新结果", exact: true }).click();
    await resultRegion.getByText("已全部加载", { exact: true }).waitFor();
    assert.equal(await resultList.getByRole("option").count(), 21);
    assert.equal(posts.length, postsBeforeMoreRefresh, "refreshing an in-progress next page uses only the saved query");
    await lookupDrawer.getByRole("button", { name: "关闭工商查询详情" }).click();
    await lookupDrawer.waitFor({ state: "hidden" });
    await page.waitForFunction(() => document.activeElement?.textContent.trim() === "查询企业");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    await server.close();
  }
});

test("single and multiple enterprise fields keep independent queries and preserve multi selections", async () => {
  const server = await createServer({ root, server: { host: "127.0.0.1", port: 0, strictPort: false } });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, locale: "zh-CN" });
    await context.addInitScript((value) => sessionStorage.setItem("mj_program_login_session", JSON.stringify(value)), session);
    const posts = [];
    const saved = new Map();
    const queries = new Map();
    let loseResponse = true;
    await context.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let body = path === "/api/auth/session/validate" ? session : { items: [], orgRevision: 1 };
      if ([`${api}/companies`, `${api}/queries`].includes(path)) body = { configured: true, items: [], total: saved.size };
      if (path === `${api}/search`) {
        const request = route.request().postDataJSON();
        posts.push(request);
        body = queries.get(request.requestId);
        if (!body) {
          const companies = structuredClone(fixtures.slice((request.pageNum - 1) * 20, request.pageNum * 20));
          if (request.keyword === "交叉查询") {
            // A fresh snapshot of a selected enterprise must match by credit code, not object/row ID.
            Object.assign(companies[0], { id: 1001, companyName: "测试工商企业 01新名称" });
            Object.assign(companies[2], { companyName: "测试无代码甲", creditNo: "***", companyCode: "" });
            Object.assign(companies[3], { companyName: "测试无代码乙", creditNo: "***", companyCode: "" });
          }
          body = { ...request, id: queries.size + 1, status: "succeeded", resultCount: companies.length, totalRecords: 21, companies };
          queries.set(request.requestId, body);
          companies.forEach((company) => saved.set(company.id, company));
        }
        if (request.keyword === "交叉查询" && loseResponse) {
          loseResponse = false;
          await route.abort("failed");
          return;
        }
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/auth/settings/business-registry`);
    await page.getByRole("button", { name: "查询企业", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "企业工商查询", exact: true });
    const single = drawer.getByRole("region", { name: "单选企业", exact: true });
    const multi = drawer.getByRole("region", { name: "多选企业", exact: true });
    const singleInput = single.getByRole("combobox");
    const multiInput = multi.getByRole("combobox");
    const selected = multi.getByRole("list", { name: "已选企业" });
    const singleResults = page.getByRole("listbox", { name: "查询结果，单选企业" });
    const multiResults = page.getByRole("listbox", { name: "查询结果，多选企业" });
    const multiRegion = page.getByRole("region", { name: "多选企业查询结果", exact: true });
    await single.getByRole("heading", { name: "单选企业", exact: true }).waitFor();
    await multi.getByRole("heading", { name: "多选企业", exact: true }).waitFor();
    assert.ok((await single.boundingBox()).y < (await multi.boundingBox()).y);
    assert.equal(await singleInput.evaluate((element) => element === document.activeElement), true);
    await singleInput.fill("单选关键词");
    await singleInput.press("Enter");
    await singleResults.getByRole("option").first().click();
    assert.equal(await singleInput.inputValue(), fixtures[0].companyName);
    await multiInput.fill("多选关键词");
    await multiInput.press("Enter");
    await multiResults.waitFor();
    assert.equal(saved.size, 20, "both selectors save the whole result page before selection");
    assert.equal(await multiResults.getAttribute("aria-multiselectable"), "true");
    await multiResults.getByRole("option").first().click();
    await multiResults.waitFor({ state: "hidden" });
    assert.equal(await multiInput.inputValue(), "", "choosing a company clears only the query text");
    assert.equal(await selected.getByRole("listitem").count(), 1);
    assert.equal(await multiInput.evaluate((element) => element === document.activeElement), true);
    assert.equal(await selected.evaluate((element) => Boolean(element.closest(".registry-query-control"))), true, "chips are inside the field");
    await multiInput.click();
    await multiResults.getByRole("option").nth(1).click();
    await multiResults.waitFor({ state: "hidden" });
    assert.equal(await singleInput.inputValue(), fixtures[0].companyName);
    assert.equal(await selected.getByRole("listitem").count(), 2);
    assert.equal(await selected.getByText(fixtures[0].creditNo).count(), 0, "chips display only company names");
    await multiInput.fill("待添加关键词");
    await selected.getByText(fixtures[0].companyName, { exact: true }).click();
    assert.equal(await multiResults.isVisible(), false, "clicking a selected chip does not reopen query results");
    assert.equal(await multiInput.inputValue(), "待添加关键词", "chip clicks preserve the text for the next company");
    assert.equal(await selected.getByRole("combobox").count(), 0, "selected chips cannot be edited");
    assert.deepEqual(await selected.getByRole("button").evaluateAll((buttons) => buttons.map((button) => button.getAttribute("aria-label"))),
      [`移除${fixtures[0].companyName}`, `移除${fixtures[1].companyName}`], "chips only expose removal actions");
    assert.equal(posts.length, 2, "chip clicks never start a paid query");
    await multiInput.fill("");
    await multiInput.press("ArrowDown");
    await multiInput.press("Home");
    await multiInput.press("Enter");
    await multiResults.waitFor({ state: "hidden" });
    assert.equal(await selected.getByRole("listitem").count(), 2, "choosing the same company cannot duplicate or remove its chip");
    assert.equal(posts.length, 2, "reopening the loaded results does not repeat a paid search");
    await multiInput.click();
    await multiRegion.evaluate((element) => { element.scrollTop = element.scrollHeight; });
    await multiResults.getByRole("option").nth(20).waitFor();
    await multiResults.getByRole("option").nth(20).click();
    await multiResults.waitFor({ state: "hidden" });
    assert.equal(saved.size, 21);
    assert.equal(await selected.getByRole("listitem").count(), 3);
    assert.equal(posts.at(-1).pageNum, 2);
    assert.equal(posts.at(-1).keyword, "多选关键词", "pagination uses the original query after the input was cleared");
    assert.equal(await drawer.isVisible(), true);
    await page.screenshot({ path: `${artifacts}/multi-chips-selected-1440.png` });
    await multiInput.fill("交叉查询");
    await multiInput.press("Enter");
    await multi.getByRole("alert").waitFor();
    assert.equal(await selected.getByRole("listitem").count(), 3, "failed re-query keeps selections");
    assert.equal(await single.getByRole("alert").count(), 0);
    const failedRequest = posts.at(-1).requestId;
    await multiInput.press("Enter");
    await multiResults.waitFor();
    assert.equal(posts.at(-1).requestId, failedRequest);
    assert.notEqual(posts[0].requestId, posts[1].requestId, "the fields use separate request identities");
    assert.equal(await multiResults.getByRole("option").first().getAttribute("aria-selected"), "true");
    await multiResults.getByRole("option").first().click();
    await multiResults.waitFor({ state: "hidden" });
    assert.equal(await selected.getByRole("listitem").count(), 3, "fresh snapshots match the existing chip by hidden credit code");
    await multiInput.click();
    await multiResults.getByRole("option").nth(2).click();
    await multiResults.waitFor({ state: "hidden" });
    await multiInput.click();
    await multiResults.getByRole("option").nth(3).click();
    await multiResults.waitFor({ state: "hidden" });
    assert.equal(await selected.getByRole("listitem").count(), 5, "masked identifiers do not merge different enterprises");
    await multiInput.click();
    await multiResults.getByRole("option").nth(4).click();
    await multiResults.waitFor({ state: "hidden" });
    for (const width of [1440, 1024, 800]) {
      await page.setViewportSize({ width, height: 768 });
      const control = await multi.locator(".registry-query-control").boundingBox();
      const submit = await multi.getByRole("button", { name: "查询", exact: true }).boundingBox();
      const input = await multiInput.boundingBox();
      assert.ok(submit.height <= 36 && input.x + input.width <= submit.x, "query action stays beside the last input line when chips wrap");
      for (const chip of await selected.getByRole("listitem").all()) {
        const bounds = await chip.boundingBox();
        assert.ok(bounds.x >= control.x && bounds.x + bounds.width <= control.x + control.width, "long names and multiple chips wrap inside the field");
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.screenshot({ path: `${artifacts}/multi-chips-${width}.png` });
      await multiInput.click();
      const bounds = await multiRegion.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1 && bounds.y + bounds.height <= 768);
      await page.screenshot({ path: `${artifacts}/multi-chips-results-${width}.png` });
      await multiInput.press("Escape");
      assert.equal(await drawer.isVisible(), true);
    }
    const requestsBeforeRemoving = posts.length;
    await selected.getByRole("button", { name: `移除${fixtures[20].companyName}`, exact: true }).click();
    assert.equal(await selected.getByRole("listitem").count(), 5, "a chip from a different page can be removed");
    await selected.getByRole("button", { name: `移除${fixtures[1].companyName}`, exact: true }).focus();
    await page.keyboard.press("Enter");
    assert.equal(await selected.getByRole("listitem").count(), 4, "chip removal is keyboard accessible");
    assert.equal(await multiInput.evaluate((element) => element === document.activeElement), true);
    await singleInput.click();
    assert.equal(await singleResults.getByRole("option", { selected: true }).count(), 1);
    assert.equal(await singleResults.getByRole("option").count(), 20, "multi pagination does not append to the single results");
    assert.equal(posts.length, requestsBeforeRemoving, "selecting, removing and reopening never call the paid service");
    await singleInput.press("Escape");
    await multiInput.click();
    await multiResults.getByRole("option").nth(1).click();
    await multiResults.waitFor({ state: "hidden" });
    assert.equal(await selected.getByRole("listitem").count(), 5, "a removed enterprise can be added again through the trailing input");
    assert.equal(await selected.getByRole("listitem").last().getByText(fixtures[1].companyName, { exact: true }).isVisible(), true);
    assert.equal(posts.length, requestsBeforeRemoving, "adding from loaded results makes no new request");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    await server.close();
  }
});

test("appended lookup pages stop at the end and recover without duplicating saved requests", async () => {
  const server = await createServer({ root, server: { host: "127.0.0.1", port: 0, strictPort: false } });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, locale: "zh-CN" });
    await context.addInitScript((value) => sessionStorage.setItem("mj_program_login_session", JSON.stringify(value)), session);
    const posts = [];
    const queries = new Map();
    let losePageResponse = true;
    let failPage = true;
    await context.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let body = path === "/api/auth/session/validate" ? session : { items: [], orgRevision: 1 };
      if ([`${api}/companies`, `${api}/queries`].includes(path)) body = { configured: true, items: [], total: 0 };
      if (path === `${api}/search`) {
        const request = route.request().postDataJSON();
        posts.push(request);
        body = queries.get(request.requestId);
        if (!body) {
          const failed = request.keyword === "业务失败" && request.pageNum === 2 && failPage;
          if (failed) failPage = false;
          const count = failed || request.pageNum === 3 ? 0 : request.pageNum === 1 || request.keyword === "无总数" ? 20 : 5;
          body = { ...request, id: queries.size + 1, status: failed ? "failed" : count ? "succeeded" : "empty",
            message: failed ? "测试业务失败" : "", resultCount: count, totalRecords: null,
            companies: Array.from({ length: count }, (_, index) => {
              const id = (request.pageNum - 1) * 20 + index + 1;
              return { ...fixtures[0], id, companyName: `${request.keyword} ${id}`, creditNo: `TEST${String(id).padStart(14, "0")}` };
            }) };
          queries.set(request.requestId, body);
        }
        if (request.keyword === "无总数" && request.pageNum === 2 && losePageResponse) {
          losePageResponse = false;
          await route.abort("failed");
          return;
        }
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/auth/settings/business-registry`);
    await page.getByRole("button", { name: "查询企业", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "企业工商查询", exact: true });
    const singleField = drawer.getByRole("region", { name: "单选企业", exact: true });
    const keyword = singleField.getByRole("combobox");
    const region = page.getByRole("region", { name: "企业查询结果", exact: true });
    const options = page.getByRole("listbox", { name: "查询结果，单选企业" }).getByRole("option");
    const bottom = () => region.evaluate((element) => { element.scrollTop = element.scrollHeight; });
    const search = async (value) => {
      await keyword.fill(value);
      await singleField.getByRole("button", { name: "查询", exact: true }).click();
      await options.filter({ hasText: `${value} 1` }).first().waitFor();
    };
    await search("无总数");
    assert.equal(posts.length, 1, "opening results never preloads another page");
    await bottom();
    await region.getByRole("alert").waitFor();
    const lostRequest = posts.at(-1);
    assert.equal(await options.count(), 20);
    await region.evaluate(async (element) => {
      element.scrollTop -= 40;
      await new Promise(requestAnimationFrame);
      element.scrollTop = element.scrollHeight;
      await new Promise(requestAnimationFrame);
    });
    assert.equal(posts.length, 2, "scrolling after failure never retries automatically");
    await page.screenshot({ path: `${artifacts}/load-more-retry-1440.png` });
    await region.getByRole("button", { name: "重试加载", exact: true }).click();
    await options.filter({ hasText: "无总数 40" }).waitFor();
    assert.equal(posts.at(-1).requestId, lostRequest.requestId);
    assert.equal(posts.at(-1).pageNum, 2);
    assert.equal(queries.size, 2, "a transport retry reuses the already saved query");
    assert.equal(await options.count(), 40);
    assert.equal(new Set(await options.allTextContents()).size, 40, "retried pages appear only once");
    await bottom();
    await region.getByText("已全部加载", { exact: true }).waitFor();
    assert.equal(posts.at(-1).pageNum, 3);
    assert.equal(await options.count(), 40, "an empty last page preserves all prior results");
    assert.equal(await region.getByRole("button", { name: "加载更多", exact: true }).count(), 0);
    await bottom();
    assert.equal(posts.length, 4);
    await search("短页");
    assert.equal(posts.at(-1).pageNum, 1, "a new keyword starts from page one");
    assert.equal(await options.count(), 20);
    assert.equal(await options.filter({ hasText: "无总数" }).count(), 0);
    assert.equal(await region.evaluate((element) => element.scrollTop), 0);
    await bottom();
    await region.getByText("已全部加载", { exact: true }).waitFor();
    assert.equal(await options.count(), 25, "an incomplete page with no total ends pagination");
    assert.equal(posts.at(-1).pageNum, 2);
    await search("业务失败");
    await bottom();
    await region.getByRole("alert").filter({ hasText: "测试业务失败" }).waitFor();
    const failedRequest = posts.at(-1);
    assert.equal(await options.count(), 20);
    await region.getByRole("button", { name: "重试加载", exact: true }).click();
    await region.getByText("已全部加载", { exact: true }).waitFor();
    assert.notEqual(posts.at(-1).requestId, failedRequest.requestId, "a deliberate retry after a final API failure creates a fresh query");
    assert.equal(posts.at(-1).pageNum, 2);
    assert.equal(await options.count(), 25);
    await options.filter({ hasText: "业务失败 25" }).click();
    assert.equal(await keyword.inputValue(), "业务失败 25", "companies from appended pages can be selected");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    await server.close();
  }
});
