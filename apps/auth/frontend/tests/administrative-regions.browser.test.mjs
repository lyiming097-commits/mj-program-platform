import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const { buildAdministrativeRegionTree } = await import("../src/administrative-regions.js");
const regionSource = JSON.parse(await readFile(new URL("../../backend/identity_api/data/administrative_regions.json", import.meta.url), "utf8"));
const regionDirectory = {
  ok: true,
  revision: "vant-area-data-2.2.0",
  stats: { provinces: 34, cities: 369, districts: 3478 },
  items: buildAdministrativeRegionTree(regionSource),
};

const session = {
  sessionId: "administrative-region-fixture",
  userId: "administrative-region-admin",
  name: "平台管理员",
  isFullAccessUser: true,
  canUseSystemAdmin: true,
  canManagePlatformSettings: true,
  canConfigurePermissions: true,
};

test("desktop backend management exposes the complete province city district directory", async () => {
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
    await context.route("**/api/**", (route) => {
      const requestUrl = new URL(route.request().url());
      const path = requestUrl.pathname;
      let data = path === "/api/auth/session/validate" ? session : { items: [], orgRevision: 1 };
      if (path === "/api/directory/administrative-regions") data = regionDirectory;
      if (path === "/api/directory/administrative-regions/search") {
        const keyword = requestUrl.searchParams.get("keyword") || "";
        data = {
          total: keyword.replace(/\s+/g, "").toLowerCase() === "yuhangqu" ? 1 : 0,
          items: keyword.replace(/\s+/g, "").toLowerCase() === "yuhangqu" ? [{
            level: "district",
            levelLabel: "区县",
            code: "330110",
            name: "余杭区",
            path: "浙江省 / 杭州市 / 余杭区",
            provinceCode: "330000",
            cityCode: "330100",
            pinyin: "yuhangqu",
            pinyinInitials: "yhq",
          }] : [],
        };
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
    });

    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const baseUrl = `http://127.0.0.1:${server.httpServer.address().port}`;
    await page.goto(`${baseUrl}/auth/settings/regions?province=330000&city=330100`);

    const sidebar = page.getByRole("navigation", { name: "主导航" });
    await sidebar.getByRole("button", { name: "省市区域" }).waitFor();
    assert.deepEqual(await sidebar.getByRole("button").allTextContents(), ["组织架构", "我司主体", "省市区域", "工商信息查询"]);
    assert.match(await sidebar.getByRole("button", { name: "省市区域" }).getAttribute("class"), /active/);
    assert.equal(await page.getByRole("tab", { name: "省市区域" }).getAttribute("aria-selected"), "true");

    const panel = page.getByRole("tabpanel", { name: "省市区域" });
    await panel.getByText("34 个省级 · 369 个市级 · 3478 个区县", { exact: true }).waitFor();
    const provinceDirectory = panel.getByRole("navigation", { name: "省级行政区" });
    assert.equal(await provinceDirectory.getByRole("button").count(), 34);
    assert.equal(await provinceDirectory.getByRole("button", { name: /浙江省/ }).getAttribute("aria-current"), "true");
    const cityDirectory = panel.getByRole("navigation", { name: "浙江省市级行政区" });
    assert.equal(await cityDirectory.getByRole("button").count(), 11);
    assert.equal(await cityDirectory.getByRole("button", { name: /杭州市/ }).getAttribute("aria-current"), "true");
    const districtList = panel.getByRole("list", { name: "杭州市区县" });
    assert.equal(await districtList.getByRole("listitem").count(), 13);
    assert.equal(await districtList.getByText("临平区", { exact: true }).count(), 1);
    assert.equal(await districtList.getByText("钱塘区", { exact: true }).count(), 1);
    assert.equal(await districtList.getByText("下城区", { exact: true }).count(), 0);
    assert.equal(await districtList.getByText("江干区", { exact: true }).count(), 0);

    const search = panel.getByRole("searchbox", { name: "搜索省市区名称、行政区代码或拼音" });
    await search.fill("yu hang qu");
    const results = panel.getByRole("table", { name: "省市区行政区域搜索结果" });
    const resultRow = results.getByRole("row").filter({ hasText: "浙江省 / 杭州市 / 余杭区" });
    await resultRow.waitFor();
    assert.equal(await resultRow.getByText("330110", { exact: true }).count(), 1);
    assert.equal(new URL(page.url()).searchParams.get("q"), "yu hang qu");
    await resultRow.getByRole("button", { name: "余杭区" }).click();
    await districtList.getByText("余杭区", { exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("q"), null);
    assert.equal(new URL(page.url()).searchParams.get("province"), "330000");
    assert.equal(new URL(page.url()).searchParams.get("city"), "330100");

    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    await page.screenshot({ path: "/tmp/mj-auth-administrative-regions-1440.png", fullPage: true });
    await page.setViewportSize({ width: 1024, height: 768 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    const panelBounds = await panel.boundingBox();
    assert.ok(panelBounds.x + panelBounds.width <= 1024);
    await page.screenshot({ path: "/tmp/mj-auth-administrative-regions-1024.png", fullPage: true });
    assert.deepEqual(pageErrors, []);
    await context.close();
  } finally {
    await browser.close();
    await server.close();
  }
});

test("directory loading retries the authoritative API and preserves URL selection without local fallback", async () => {
  const server = await createServer({ root: frontendRoot, server: { host: "127.0.0.1", port: 0, strictPort: false } });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  let releaseFirstResponse;
  const firstResponse = new Promise((resolve) => { releaseFirstResponse = resolve; });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addInitScript((initialSession) => {
      window.sessionStorage.setItem("mj_program_login_session", JSON.stringify(initialSession));
    }, session);
    let directoryRequests = 0;
    const publishedProvince = regionDirectory.items.find((item) => item.code === "340000");
    await context.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let data = path === "/api/auth/session/validate" ? session : { items: [], orgRevision: 1 };
      let status = 200;
      if (path === "/api/directory/administrative-regions") {
        directoryRequests += 1;
        if (directoryRequests === 1) {
          await firstResponse;
          status = 503;
          data = { ok: false, code: "DIRECTORY_UNAVAILABLE", error: "行政区域目录暂不可用" };
        } else {
          // A deliberately smaller server publication proves the UI uses the
          // response, rather than its former bundled directory.
          data = {
            ok: true, revision: "test-server-publication", items: [publishedProvince],
            stats: { provinces: 1, cities: publishedProvince.cities.length,
              districts: publishedProvince.cities.reduce((count, city) => count + city.districts.length, 0) },
          };
        }
      }
      return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    });
    const page = await context.newPage();
    const baseUrl = `http://127.0.0.1:${server.httpServer.address().port}`;
    await page.goto(`${baseUrl}/auth/settings/regions?province=340000&city=340100`);
    const panel = page.getByRole("tabpanel", { name: "省市区域" });
    await panel.getByRole("status").filter({ hasText: "正在加载行政区域" }).waitFor();
    assert.equal(await panel.getByRole("navigation", { name: "省级行政区" }).count(), 0);
    releaseFirstResponse();
    await panel.getByRole("alert").filter({ hasText: "行政区域目录暂不可用" }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("province"), "340000");
    assert.equal(new URL(page.url()).searchParams.get("city"), "340100");
    await panel.getByRole("button", { name: "重新加载行政区域" }).click();
    await panel.getByRole("navigation", { name: "省级行政区" }).waitFor();
    const provinces = panel.getByRole("navigation", { name: "省级行政区" }).getByRole("button");
    assert.equal(await provinces.count(), 1);
    assert.equal(await provinces.first().getAttribute("aria-current"), "true");
    assert.match(await provinces.first().textContent(), /安徽省/);
    await panel.getByRole("list", { name: "合肥市区县" }).waitFor();
    assert.equal(directoryRequests, 2);

    await page.reload();
    await panel.getByRole("list", { name: "合肥市区县" }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("city"), "340100");
    await context.close();
  } finally {
    releaseFirstResponse();
    await browser.close();
    await server.close();
  }
});
