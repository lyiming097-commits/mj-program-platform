import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const frontendRoot = fileURLToPath(new URL("../", import.meta.url));

const session = {
  sessionId: "company-entity-fixture",
  userId: "company-entity-admin",
  name: "平台管理员",
  isFullAccessUser: true,
  canUseSystemAdmin: true,
  canManagePlatformSettings: true,
  canConfigurePermissions: true,
};

const seededItems = [
  ["杭州迈杰教育科技有限公司", "91330110685829101A", "招商银行股份有限公司杭州余杭支行", "5719 0586 6410 606", "浙江省杭州市余杭区仓前街道龙潭路7号1幢C113室", "0571-57898509"],
  ["杭州德昌视讯科技有限公司", "9133011068909048XK", "招商银行股份有限公司杭州余杭支行", "5719 0593 9710 907", "浙江省杭州市余杭区仓前街道龙潭路7号杭州未来研创园1幢C114室", "0571-57889226"],
  ["杭州宝诺智能科技有限公司", "91330110MA27X5FG7A", "招商银行股份有限公司杭州余杭支行", "5719 0935 6510 302", "浙江省杭州市余杭区仓前街道龙潭路7号1幢C117室", "0571-57889225"],
  ["杭州智学未来科技有限公司", "91330110MABNJFH86U", "招商银行杭州余杭支行", "5719 1795 3210 908", "浙江省杭州市余杭区仓前街道龙潭路7号1幢C115室101", "0571-57898509"],
  ["浙江优学时代教育装备有限公司", "91330185MACAQLTH04", "招商银行股份有限公司杭州余杭支行", "5719 1905 6410 110", "杭州市临安区青山湖街道鹤亭街899号16幢1楼", "0571-57898509"],
  ["杭州德峰智能科技有限公司", "91330113MAC3EATW1H", "招商银行股份有限公司杭州余杭支行", "5719 1861 8210 101", "浙江省杭州市临平区东湖街道顺风路535号40幢701室、801室", "0571-57898509"],
].map(([companyName, taxNumber, bankName, bankAccount, address, phone], index) => ({
  id: index + 1,
  companyName,
  pinyin: index === 0 ? "hangzhoumaijiejiaoyukejiyouxiangongsi" : "",
  pinyinInitials: index === 0 ? "hzmjjykjyxgs" : "",
  taxNumber,
  bankName,
  bankAccount,
  address,
  phone,
}));

test("desktop backend management maintains the platform company entity source", async () => {
  const server = await createServer({
    root: frontendRoot,
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addInitScript((initialSession) => {
      window.sessionStorage.setItem("mj_program_login_session", JSON.stringify(initialSession));
    }, session);

    let items = seededItems.map((item) => ({ ...item }));
    let nextId = 7;
    const requests = [];
    const listRequests = [];
    await context.route("**/api/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path === "/api/auth/session/validate") {
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session) });
      }
      if (path === "/api/directory/company-entities" && request.method() === "GET") {
        const query = new URL(request.url()).searchParams;
        listRequests.push(Object.fromEntries(query));
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items, count: items.length, total: items.length, all: true, directoryRevision: "test-directory" }) });
      }
      if (path === "/api/directory/company-entities" && request.method() === "POST") {
        const item = { id: nextId++, ...request.postDataJSON() };
        items.push(item);
        requests.push({ method: "POST", item });
        return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ item }) });
      }
      const itemMatch = path.match(/^\/api\/directory\/company-entities\/(\d+)$/);
      if (itemMatch && request.method() === "PUT") {
        const id = Number(itemMatch[1]);
        const item = { id, ...request.postDataJSON() };
        items = items.map((candidate) => candidate.id === id ? item : candidate);
        requests.push({ method: "PUT", item });
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item }) });
      }
      if (itemMatch && request.method() === "DELETE") {
        const id = Number(itemMatch[1]);
        items = items.filter((candidate) => candidate.id !== id);
        requests.push({ method: "DELETE", id });
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, deletedId: String(id) }) });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], orgRevision: 1 }) });
    });

    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const appUrl = `http://127.0.0.1:${server.httpServer.address().port}/auth/settings/company-entities`;
    await page.goto(appUrl);

    const sidebar = page.getByRole("navigation", { name: "主导航" });
    await sidebar.getByRole("button", { name: "我司主体" }).waitFor();
    assert.deepEqual(await sidebar.getByRole("button").allTextContents(), ["组织架构", "我司主体", "省市区域", "工商信息查询", "机器人群发", "通知"]);
    assert.match(await sidebar.getByRole("button", { name: "我司主体" }).getAttribute("class"), /active/);
    assert.equal(await page.getByRole("tab", { name: "我司主体" }).getAttribute("aria-selected"), "true");

    const table = page.getByRole("table", { name: "我司主体资料" });
    await table.getByText("杭州迈杰教育科技有限公司").waitFor();
    assert.equal(await table.getByRole("row").count(), 7);
    assert.deepEqual(listRequests, [{ all: "true" }]);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);

    const companySearch = page.getByRole("searchbox", { name: "搜索我司主体名称、拼音、税号或ID" });
    await companySearch.fill("hang zhou mai jie");
    assert.equal(await table.getByRole("row").count(), 2);
    assert.equal(await table.getByText("杭州迈杰教育科技有限公司", { exact: true }).count(), 1);
    assert.equal(new URL(page.url()).searchParams.get("q"), "hang zhou mai jie");
    await companySearch.fill(seededItems[1].taxNumber.toLowerCase());
    assert.equal(await table.getByRole("row").count(), 2);
    assert.equal(await table.getByText(seededItems[1].companyName, { exact: true }).count(), 1);
    await page.getByRole("button", { name: "清除我司主体搜索" }).click();
    assert.equal(await table.getByRole("row").count(), 7);

    await table.getByRole("row", { name: "查看我司主体：杭州迈杰教育科技有限公司" }).click();
    let drawer = page.getByRole("dialog", { name: "杭州迈杰教育科技有限公司" });
    const detailSection = drawer.locator('[data-ai-section="auth.company-entity.details"]');
    await detailSection.waitFor();
    assert.equal(await detailSection.locator("[data-ai-field]").count(), 6);
    assert.equal(await drawer.getByText("主体 #1", { exact: true }).count(), 1);

    const drawerBounds = await drawer.locator(".platform-detail-drawer-panel").boundingBox();
    assert.ok(drawerBounds);
    assert.ok(Math.abs(drawerBounds.width - 720) <= 2, `expected a 720px drawer, got ${drawerBounds.width}px`);
    const sectionAppearance = await detailSection.evaluate((element) => {
      const style = window.getComputedStyle(element);
      return {
        backgroundColor: style.backgroundColor,
        borderRadius: style.borderTopLeftRadius,
        borderStyle: style.borderTopStyle,
      };
    });
    assert.deepEqual(sectionAppearance, {
      backgroundColor: "rgb(255, 255, 255)",
      borderRadius: "8px",
      borderStyle: "solid",
    });

    const companyFieldBounds = await detailSection.locator('[data-ai-field="auth.company-entity.companyName"]').boundingBox();
    const taxFieldBounds = await detailSection.locator('[data-ai-field="auth.company-entity.taxNumber"]').boundingBox();
    const addressFieldBounds = await detailSection.locator('[data-ai-field="auth.company-entity.address"]').boundingBox();
    assert.ok(companyFieldBounds && taxFieldBounds && addressFieldBounds);
    assert.ok(Math.abs(companyFieldBounds.y - taxFieldBounds.y) <= 2, "company name and tax number should share a row");
    assert.ok(addressFieldBounds.width > companyFieldBounds.width * 1.8, "address should span both detail columns");
    await page.screenshot({ path: "/tmp/mj-auth-company-entity-detail-standard.png", fullPage: true });

    await drawer.getByRole("button", { name: "编辑" }).click();
    assert.equal(await drawer.getByText("编辑中", { exact: true }).count(), 1);
    await drawer.getByLabel("电话").fill("0571-00000000");
    await drawer.getByRole("button", { name: "关闭我司主体详情" }).click();
    let discardDialog = page.getByRole("alertdialog", { name: "是否放弃修改" });
    await discardDialog.getByRole("button", { name: "继续编辑" }).click();
    assert.equal(await drawer.getByLabel("电话").inputValue(), "0571-00000000");
    await drawer.getByRole("button", { name: "关闭我司主体详情" }).click();
    discardDialog = page.getByRole("alertdialog", { name: "是否放弃修改" });
    await discardDialog.getByRole("button", { name: "确认放弃" }).click();
    await drawer.waitFor({ state: "detached" });

    await table.getByRole("row", { name: "查看我司主体：杭州迈杰教育科技有限公司" }).click();
    drawer = page.getByRole("dialog", { name: "杭州迈杰教育科技有限公司" });
    await drawer.getByRole("button", { name: "编辑" }).click();
    await drawer.getByLabel("电话").fill("0571-00000000");
    await drawer.getByRole("button", { name: "保存" }).click();
    await page.getByRole("status").filter({ hasText: "已保存我司主体" }).waitFor();
    assert.equal(requests.at(-1).method, "PUT");
    assert.equal(requests.at(-1).item.phone, "0571-00000000");
    await drawer.getByRole("button", { name: "关闭我司主体详情" }).click();

    await page.getByRole("button", { name: "新增" }).click();
    drawer = page.getByRole("dialog", { name: "新增我司主体" });
    const newItem = {
      companyName: "测试新增主体有限公司",
      taxNumber: "TEST913301",
      bankName: "测试银行杭州支行",
      bankAccount: "1000 2000 3000",
      address: "浙江省杭州市测试路1号",
      phone: "0571-12345678",
    };
    await drawer.getByLabel("公司名称").fill(newItem.companyName);
    await drawer.getByLabel("税号").fill(newItem.taxNumber);
    await drawer.getByLabel("开户银行").fill(newItem.bankName);
    await drawer.getByLabel("账号").fill(newItem.bankAccount);
    await drawer.getByLabel("地址").fill(newItem.address);
    await drawer.getByLabel("电话").fill(newItem.phone);
    await drawer.getByRole("button", { name: "保存" }).click();
    await page.getByRole("status").filter({ hasText: `已保存我司主体“${newItem.companyName}”` }).waitFor();
    assert.equal(requests.at(-1).method, "POST");
    drawer = page.getByRole("dialog", { name: newItem.companyName });
    await drawer.getByRole("button", { name: "删除" }).click();
    const deleteDialog = page.getByRole("alertdialog", { name: "是否删除我司主体" });
    await deleteDialog.getByRole("button", { name: "确认删除" }).click();
    await page.getByRole("status").filter({ hasText: `已删除我司主体“${newItem.companyName}”` }).waitFor();
    assert.equal(requests.at(-1).method, "DELETE");
    assert.equal(await table.getByRole("row").count(), 7);

    await page.screenshot({ path: "/tmp/mj-auth-company-entities-1440.png", fullPage: true });
    await page.setViewportSize({ width: 1024, height: 768 });
    const tableRegionBounds = await page.getByRole("region", { name: "我司主体表格，可使用方向键横向浏览" }).boundingBox();
    assert.ok(tableRegionBounds.x + tableRegionBounds.width <= 1024);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    await page.screenshot({ path: "/tmp/mj-auth-company-entities-1024.png", fullPage: true });
    assert.deepEqual(pageErrors, []);
    await context.close();
  } finally {
    await browser.close();
    await server.close();
  }
});
