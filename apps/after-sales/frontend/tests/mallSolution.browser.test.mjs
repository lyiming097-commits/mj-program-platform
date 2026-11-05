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
const fixtureId = "/__mall-submission.js";
const fixture = `
import { createApp, h, reactive } from 'vue';
import '/src/styles.css';
import PresalesProgressPanel from '/src/components/PresalesProgressPanel.vue';
const state = reactive({
  sourceCrmId: 'crm-original', targetId: 2012, managed: true, editable: true,
  rounds: [
    { note: '第一轮原备注', attachmentIds: [] },
    { note: '第二轮原备注', attachmentIds: [] },
  ],
});
window.fixture = state;
createApp({ setup: () => () => h(PresalesProgressPanel, {
  ...state, nodeKey: 'early-plan', nodeName: '前期方案',
  'onUpdate:rounds': rounds => { state.rounds = rounds; },
}) }).mount('#app');
`;

test("submission resolves the CRM Mall link without losing round content", { timeout: 90000 }, async () => {
  const server = await createServer({
    root, base: "/", configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-mall-submission"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "mall-submission-fixture",
      resolveId(id) { if (id === fixtureId) return id; },
      load(id) { if (id === fixtureId) return fixture; },
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (request.url?.startsWith("/maijie-mall/")) {
            response.setHeader("Content-Type", "text/html; charset=utf-8");
            response.end("<main>对应商城方案</main>");
          } else if (request.url === "/__mall-submission") {
            response.setHeader("Content-Type", "text/html; charset=utf-8");
            response.end(`<div id="app"></div><script type="module" src="${fixtureId}"></script>`);
          } else next();
        });
      },
    }],
  });
  let browser;
  let releaseDelayed;
  let markDelayedStarted;
  const delayedStarted = new Promise(resolve => { markDelayedStarted = resolve; });
  let behavior = { status: 200, url: "/maijie-mall/#/opportunity/42/solution/7" };
  const requests = [];
  const errors = [];
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      let status = 200;
      let body = { items: [] };
      if (url.pathname.startsWith("/api/crm/opportunities/")) {
        requests.push(url.pathname);
        const current = behavior;
        const sourceId = decodeURIComponent(url.pathname.split("/")[4]);
        status = current.status;
        body = status === 200
          ? { opportunityId: current.sourceId ?? sourceId, projectDetailUrl: current.url, solution: null, products: [] }
          : { error: "接口测试错误", code: "TEST_ERROR" };
        if (current.delay) await new Promise(resolve => { releaseDelayed = resolve; markDelayedStarted(); });
      } else if (url.pathname.startsWith("/api/maijie-mall/")) {
        throw new Error("Must use CRM's existing authorized resolver");
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    await page.goto(`${origin}/__mall-submission`);
    await page.getByRole("button", { name: "第 2 次提交：填写附件和备注" }).waitFor();
    assert.equal(requests.length, 0, "no Mall lookup until a submission opens");
    const dialog = () => page.getByRole("dialog", { name: /^第 \d+ 次提交$/ });
    async function openRound(number = 2) {
      await page.getByRole("button", { name: new RegExp(`^第 ${number} 次提交：(填写|查看)附件和备注$`) }).click();
      await dialog().waitFor();
    }
    async function closeRound() {
      await dialog().getByRole("button", { name: /^(保存并关闭|关闭)$/ }).last().click();
      await dialog().waitFor({ state: "hidden" });
    }
    const link = () => dialog().getByRole("link", { name: "打开商城方案" });
    await openRound();
    await link().waitFor();
    assert.equal(requests.at(-1), "/api/crm/opportunities/crm-original/solution-products");
    assert.equal(await link().getAttribute("href"), `${origin}/maijie-mall/#/opportunity/42/solution/7`);
    assert.equal(await link().getAttribute("target"), "_blank");
    assert.match(await link().getAttribute("rel"), /noopener/);
    await dialog().getByLabel("备注", { exact: true }).fill("打开商城前未保存的备注");
    const opened = page.waitForEvent("popup");
    await link().focus();
    await link().press("Enter");
    const mallPage = await opened;
    await mallPage.getByText("对应商城方案", { exact: true }).waitFor();
    assert.equal(new URL(mallPage.url()).hash, "#/opportunity/42/solution/7");
    await mallPage.close();
    assert.equal(await dialog().getByLabel("备注", { exact: true }).inputValue(), "打开商城前未保存的备注");
    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      const entry = await dialog().locator(".as-round-mall-solution").boundingBox();
      const action = await link().boundingBox();
      assert.ok(action.x >= entry.x && action.x + action.width <= entry.x + entry.width + 1);
    }
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-mall-submission.png") });
    await closeRound();
    assert.equal(await page.evaluate(() => window.fixture.rounds[0].note), "第一轮原备注");
    assert.equal(await page.evaluate(() => window.fixture.rounds[1].note), "打开商城前未保存的备注");

    await openRound(1);
    await link().waitFor();
    assert.equal(await dialog().getByLabel("备注", { exact: true }).inputValue(), "第一轮原备注");
    assert.equal(await dialog().getByLabel("备注", { exact: true }).getAttribute("readonly"), "");
    assert.equal(await dialog().getByRole("button", { name: "保存并关闭", exact: true }).count(), 0);
    await closeRound();

    // A project with no saved solution still has a workspace URL.
    behavior = { status: 200, url: "/maijie-mall/#/opportunity/42/solution" };
    await openRound(2);
    await link().waitFor();
    assert.equal(await link().getAttribute("href"), `${origin}${behavior.url}`);
    assert.equal(await dialog().getByLabel("备注", { exact: true }).inputValue(), "打开商城前未保存的备注");
    await closeRound();

    for (const [status, message] of [
      [503, "商城方案暂时无法读取，请重试"],
      [403, "当前账号没有对应 CRM 项目的访问权限"],
      [404, "对应 CRM 项目不存在或当前账号无权访问"],
    ]) {
      behavior = { status };
      await openRound();
      await dialog().getByText(message, { exact: true }).waitFor();
      assert.equal(await link().count(), 0);
      behavior = { status: 200, url: "/maijie-mall/#/opportunity/42/solution" };
      await dialog().getByRole("button", { name: "重试", exact: true }).click();
      await link().waitFor();
      await closeRound();
    }
    behavior = { status: 200, url: "" };
    await openRound();
    await dialog().getByText("商城尚未关联此 CRM 项目，请在商城同步后重试", { exact: true }).waitFor();
    await closeRound();

    behavior = { status: 200, url: "https://oa.hzmaijie.com:4433/maijie-mall/#/opportunity/42/solution/7" };
    await openRound();
    await link().waitFor();
    assert.equal(await link().getAttribute("href"), `${origin}/maijie-mall/#/opportunity/42/solution/7`, "public-host aliases stay on the current platform session");
    await closeRound();

    for (const invalid of [
      { url: "https://example.com/other-app/#/opportunity/42/solution" },
      { url: "https://user:password@example.com/maijie-mall/#/opportunity/42/solution" },
      { url: "javascript:alert(1)" },
      { url: "/maijie-mall/#/opportunity/../solution" },
      { url: "/maijie-mall/#/opportunity/42/solution", sourceId: "another-crm" },
    ]) {
      behavior = { status: 200, ...invalid };
      await openRound();
      await dialog().getByText("商城方案暂时无法读取，请重试", { exact: true }).waitFor();
      assert.equal(await link().count(), 0);
      await closeRound();
    }

    const beforeLocal = requests.length;
    await page.evaluate(() => { window.fixture.sourceCrmId = ""; });
    await openRound();
    await dialog().getByText("本项目由迈杰服务独立维护，未关联商城项目", { exact: true }).waitFor();
    assert.equal(requests.length, beforeLocal);
    assert.equal(await link().count(), 0);
    await closeRound();

    behavior = { status: 200, url: "/maijie-mall/#/opportunity/41/solution", delay: true };
    await page.evaluate(() => { window.fixture.sourceCrmId = "crm-old"; });
    await openRound();
    await dialog().getByRole("button", { name: "正在关联…", exact: true }).waitFor();
    await delayedStarted;
    assert.equal(typeof releaseDelayed, "function");
    behavior = { status: 200, url: "/maijie-mall/#/opportunity/43/solution" };
    await page.evaluate(() => { window.fixture.sourceCrmId = "crm-new"; window.fixture.targetId = 2013; });
    await dialog().waitFor({ state: "hidden" });
    await openRound();
    await link().waitFor();
    const oldFinished = page.waitForResponse(response => response.url().includes("/crm-old/solution-products"));
    releaseDelayed();
    await oldFinished;
    assert.equal(await link().getAttribute("href"), `${origin}/maijie-mall/#/opportunity/43/solution`);
    await closeRound();

    // DingTalk opens the same project in its own workbench using the existing AppLink.
    await page.evaluate(() => { window.dd = { env: { platform: "pc" } }; });
    await openRound();
    await link().waitFor();
    const dingTalkUrl = new URL(await link().getAttribute("href"));
    assert.equal(dingTalkUrl.origin, "https://applink.dingtalk.com");
    assert.equal(dingTalkUrl.searchParams.get("targetDesktop"), "workbench");
    assert.equal(dingTalkUrl.searchParams.get("url"), `${origin}/maijie-mall/#/opportunity/43/solution`);
    await closeRound();

    await page.evaluate(() => { window.fixture.editable = false; });
    await openRound();
    await link().waitFor();
    assert.equal(await dialog().getByLabel("备注", { exact: true }).getAttribute("readonly"), "");
    await closeRound();

    await page.evaluate(() => { window.fixture.managed = false; });
    const beforeField = requests.length;
    await openRound();
    assert.equal(await dialog().getByText("商城方案", { exact: true }).count(), 0);
    assert.equal(requests.length, beforeField, "hidden field client does not receive the integration");
    await closeRound();
    assert.deepEqual(errors, []);
  } finally {
    releaseDelayed?.();
    await browser?.close();
    await server.close();
  }
});
