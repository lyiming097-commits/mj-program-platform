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
const fixtureId = "/__presales-project-fees.js";
const fixture = `
import { createApp, h, ref } from 'vue';
import '/src/styles.css';
import PresalesProjectFees from '/src/components/PresalesProjectFees.vue';
const realNow = Date.now;
let timeOffset = 0;
Date.now = () => realNow() + timeOffset;
window.advanceFeeTime = milliseconds => { timeOffset += milliseconds; };
createApp({
  setup() {
    const source = ref('crm-one'), identity = ref('login-one'), visible = ref(true);
    let loginNumber = 1;
    return () => h('main', { style: 'padding:16px' }, [
      h('button', { onClick: () => { source.value = ''; } }, '查看独立项目'),
      h('button', { onClick: () => { source.value = 'crm-one'; } }, '返回第一个 CRM 项目'),
      h('button', { onClick: () => { source.value = 'crm-two'; } }, '查看另一个 CRM 项目'),
      h('button', { onClick: () => { identity.value = 'login-' + (++loginNumber); } }, '更换登录身份'),
      h('button', { onClick: () => { visible.value = !visible.value; } }, '切换费用页签'),
      visible.value ? h(PresalesProjectFees, { sourceCrmId: source.value, identityKey: identity.value }) : null,
    ]);
  },
}).mount('#app');
`;

test("presales fees use CRM expected amount and Mall project quote/A1 totals with independent errors and no writes", { timeout: 90000 }, async () => {
  const server = await createServer({
    root, base: "/", configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-presales-fees"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "presales-project-fees-fixture",
      resolveId(id) { if (id === fixtureId) return id; },
      load(id) { if (id === fixtureId) return fixture; },
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (request.url?.split("?", 1)[0] !== "/__presales-project-fees") return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<div id="app"></div><script type="module" src="${fixtureId}"></script>`);
        });
      },
    }],
  });
  let browser;
  let mallStatus = 200;
  let crmStatus = 200;
  let mallRows = [
    { opportunityId: "another-project", salespersonQuoteTotal: 999999, a1Total: 777777 },
    { opportunityId: "crm-one", salespersonQuoteTotal: 1500, expectedOrderTotal: 6666,
      a1Total: 1000, ownProductA1Total: 500, auxiliaryFeeTotal: 100 },
    { opportunityId: "crm-two", salespersonQuoteTotal: 0, a1Total: 0 },
  ];
  let heldMallResolve;
  let holdMall = false;
  const requests = [];
  const pageErrors = [];
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      requests.push({ path: url.pathname, projectId: url.searchParams.get('opportunityId'), method: route.request().method() });
      if (url.pathname === "/api/crm/opportunities/mall-amounts") {
        const responseRows = mallRows.filter(item => item.opportunityId === url.searchParams.get('opportunityId'));
        const responseStatus = mallStatus;
        if (holdMall) await new Promise(resolve => { heldMallResolve = resolve; });
        return route.fulfill({ status: responseStatus, contentType: "application/json", body: JSON.stringify(
          responseStatus === 200 ? { items: responseRows } : { error: "商城暂不可用" },
        ) });
      }
      const sourceId = url.pathname.split("/").at(-1);
      return route.fulfill({ status: crmStatus, contentType: "application/json", body: JSON.stringify(
        crmStatus === 200 ? { item: { id: sourceId, amount: sourceId === "crm-one" ? 2000 : 0,
          ourAmount: 111, totalAmount: 9000 } } : { error: "没有访问权限" },
      ) });
    });
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    await page.goto(`${origin}/__presales-project-fees`);
    const fees = page.getByRole("tabpanel", { name: "项目费用信息" });
    const table = page.getByRole("table", { name: "售前项目费用" });
    const row = label => table.getByRole("row").filter({ has: page.getByRole("rowheader", { name: label, exact: true }) });
    await row("预计费用").getByText("2,000.00 元", { exact: true }).waitFor();
    await row("对外报价").getByText("1,500.00 元", { exact: true }).waitFor();
    await row("实际费用").getByText("1,000.00 元", { exact: true }).waitFor();
    assert.equal(await fees.getByRole("spinbutton").count(), 0, "source amounts are readonly");
    assert.equal(await fees.getByText(/结算/).count(), 0);
    assert.deepEqual(requests.filter(item => item.path.endsWith('/mall-amounts')).map(item => item.projectId), ['crm-one'],
      'initial Mall query is restricted to the selected project');
    const initialRequests = requests.length;
    await page.getByRole('button', { name: '切换费用页签' }).click();
    assert.equal(await fees.count(), 0);
    await page.getByRole('button', { name: '切换费用页签' }).click();
    await row('实际费用').getByText('1,000.00 元', { exact: true }).waitFor();
    assert.equal(requests.length, initialRequests, 'fresh remount uses amounts without another source request');

    // An expired freshness window keeps the number visible during background
    // validation, and remounting while it is pending joins that same request.
    await page.evaluate(() => window.advanceFeeTime(31_000));
    holdMall = true;
    await page.getByRole('button', { name: '切换费用页签' }).click();
    const pendingRead = page.waitForRequest('**/mall-amounts?opportunityId=crm-one');
    await page.getByRole('button', { name: '切换费用页签' }).click();
    await pendingRead;
    await row('实际费用').getByText('1,000.00 元', { exact: true }).waitFor();
    assert.doesNotMatch(await table.innerText(), /读取中/);
    await page.getByRole('button', { name: '切换费用页签' }).click();
    await page.getByRole('button', { name: '切换费用页签' }).click();
    assert.equal(requests.filter(item => item.path.endsWith('/mall-amounts')).length, 2,
      'remount while loading does not duplicate the pending project request');
    holdMall = false;
    heldMallResolve();
    await page.waitForFunction(() => document.querySelector('table[aria-label="售前项目费用"]')?.getAttribute('aria-busy') === 'false');
    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await fees.evaluate(el => el.scrollWidth <= el.clientWidth), true);
      await page.screenshot({ path: path.resolve(root, `../../../.codex-artifacts/after-sales-presales-project-fees-${width}.png`) });
    }

    mallStatus = 502;
    await page.getByRole("button", { name: "更换登录身份" }).click();
    await fees.getByRole("alert").filter({ hasText: "商城费用读取失败" }).waitFor();
    assert.match(await row("预计费用").innerText(), /2,000.00 元/);
    assert.match(await row("对外报价").innerText(), /读取失败/);
    assert.doesNotMatch(await row("实际费用").innerText(), /1,000/);
    mallStatus = 200;
    await fees.getByRole("button", { name: "重试商城" }).click();
    await row("实际费用").getByText("1,000.00 元", { exact: true }).waitFor();

    holdMall = true;
    await page.getByRole("button", { name: "查看另一个 CRM 项目" }).click();
    await row("预计费用").getByText("0.00 元", { exact: true }).waitFor();
    assert.match(await row("实际费用").innerText(), /读取中/);
    await page.getByRole("button", { name: "查看独立项目" }).click();
    await fees.getByText(/未关联 CRM/).waitFor();
    const localRequestCount = requests.length;
    heldMallResolve();
    await page.waitForTimeout(100);
    assert.equal(requests.length, localRequestCount, "independent projects never query CRM or Mall");
    assert.match(await row("实际费用").innerText(), /未关联/);
    assert.doesNotMatch(await row("实际费用").innerText(), /0.00 元/);

    holdMall = false;
    await page.getByRole("button", { name: "查看另一个 CRM 项目" }).click();
    await row("对外报价").getByText("0.00 元", { exact: true }).waitFor();
    await row("实际费用").getByText("0.00 元", { exact: true }).waitFor();
    await page.getByRole("button", { name: "查看独立项目" }).click();
    mallRows = [{ opportunityId: "crm-two", salespersonQuoteTotal: null, a1Total: null }];
    await page.evaluate(() => window.advanceFeeTime(31_000));
    await page.getByRole("button", { name: "查看另一个 CRM 项目" }).click();
    await row("实际费用").getByText("暂无金额", { exact: true }).waitFor();
    assert.doesNotMatch(await row("实际费用").innerText(), /0.00/);

    await page.getByRole("button", { name: "查看独立项目" }).click();
    crmStatus = 403;
    await page.evaluate(() => window.advanceFeeTime(31_000));
    await page.getByRole("button", { name: "查看另一个 CRM 项目" }).click();
    await fees.getByRole("alert").filter({ hasText: "当前账号无权读取" }).waitFor();
    assert.match(await row("预计费用").innerText(), /读取失败/);
    assert.ok(requests.every(request => request.method === "GET"), "fee reads cannot submit or settle project data");
    assert.deepEqual(pageErrors, []);
  } finally {
    heldMallResolve?.();
    await browser?.close();
    await server.close();
  }
});
