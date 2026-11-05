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

test("settings catalog controls the available physical rewards", { timeout: 90000 }, async () => {
  const server = await createServer({
    root,
    configFile: path.join(root, "vite.config.ts"),
    server: { host: "127.0.0.1", port: 0 },
  });
  let browser;
  const prizes = [];
  const submitted = [];
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.addInitScript(() => {
      sessionStorage.setItem("mj_program_login_session", JSON.stringify({
        sessionId: "reward-catalog-test", userId: "employee", name: "管理员", loginType: "scan",
      }));
    });
    await page.route("**/api/**", async (route) => {
      const { pathname } = new URL(route.request().url());
      const method = route.request().method();
      const payload = ["POST", "PATCH"].includes(method) ? route.request().postDataJSON() : {};
      let body = { items: [] };
      if (pathname === "/api/auth/session/validate") {
        body = { sessionId: "reward-catalog-test", userId: "employee", name: "管理员", loginType: "scan" };
      } else if (pathname === "/api/after-sales/session/") {
        body = { canManageApp: true, canManageSettings: true, appPermission: "admin" };
      } else if (pathname === "/api/after-sales/reward-prizes" && method === "GET") {
        body = { items: prizes };
      } else if (pathname === "/api/after-sales/reward-prizes" && method === "POST") {
        const item = { id: prizes.length + 1, name: payload.name, enabled: true };
        prizes.push(item);
        body = { item };
      } else if (pathname.startsWith("/api/after-sales/reward-prizes/") && method === "PATCH") {
        const item = prizes.find((row) => String(row.id) === pathname.split("/").at(-1));
        Object.assign(item, payload);
        body = { item };
      } else if (pathname === "/api/after-sales/reward-prizes/options") {
        body = { items: prizes.filter((row) => row.enabled).map(({ id, name }) => ({ id, name })) };
      } else if (pathname === "/api/after-sales/providers") {
        body = { items: [{ id: 5, name: "测试人员", roleLabel: "安装人员" }] };
      } else if (pathname === "/api/after-sales/rewards" && method === "POST") {
        submitted.push(payload);
        body = { item: { id: 9, title: payload.title, prize: prizes.find((row) => row.id === payload.prizeId)?.name,
          rewardType: "prize", providerName: "测试人员", status: "pending" } };
      }
      return route.fulfill({ status: method === "POST" ? 201 : 200, contentType: "application/json", body: JSON.stringify(body) });
    });

    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/after-sales/`);
    const navigation = page.getByRole("navigation", { name: "主导航" });
    await navigation.getByRole("button", { name: "设置 / 权限" }).click();
    await page.getByRole("tab", { name: "实物奖励" }).click();
    try {
      await page.getByRole("tab", { name: "实物奖励" }).waitFor({ timeout: 10000 });
    } catch (reason) {
      throw new Error(`Settings did not load: ${JSON.stringify({ body: await page.locator("body").innerText(), pageErrors })}`, { cause: reason });
    }
    await page.getByRole("textbox", { name: "奖品名称" }).fill("工具包");
    await page.getByRole("button", { name: "添加奖品" }).click();
    await page.getByRole("textbox", { name: "奖品名称" }).fill("未保存的奖品");
    await page.getByRole("tab", { name: "安装人员标签库" }).click();
    await page.getByRole("alertdialog", { name: "是否放弃修改" }).getByRole("button", { name: "继续编辑" }).click();
    assert.equal(await page.getByRole("textbox", { name: "奖品名称" }).inputValue(), "未保存的奖品");
    await page.getByRole("tab", { name: "安装人员标签库" }).click();
    await page.getByRole("alertdialog", { name: "是否放弃修改" }).getByRole("button", { name: "确认放弃" }).click();
    await page.getByRole("tab", { name: "实物奖励" }).click();
    assert.equal(await page.getByRole("textbox", { name: "奖品名称" }).inputValue(), "");
    await page.getByRole("listitem").filter({ hasText: "工具包" }).getByRole("button", { name: "修改" }).click();
    await page.getByRole("textbox", { name: "修改工具包名称" }).fill("维修箱");
    await page.getByRole("button", { name: "保存" }).click();
    await page.getByRole("listitem").filter({ hasText: "维修箱" }).getByRole("button", { name: "停用" }).click();
    await page.getByRole("dialog", { name: "停用奖品" }).getByRole("button", { name: "确认停用" }).click();
    assert.equal(prizes[0].enabled, false);

    await navigation.getByRole("button", { name: "服务奖励" }).click();
    await page.getByRole("button", { name: "新增奖励" }).click();
    const dialog = page.getByRole("dialog", { name: "新增奖励" });
    await dialog.getByText("暂无可用奖品，请先在设置的“实物奖励”中添加。").waitFor();
    assert.equal(await dialog.getByRole("button", { name: "创建奖励" }).isDisabled(), true);
    await dialog.getByRole("button", { name: "取消" }).click();

    await navigation.getByRole("button", { name: "设置 / 权限" }).click();
    await page.getByRole("tab", { name: "实物奖励" }).click();
    await page.getByRole("listitem").filter({ hasText: "维修箱" }).getByRole("button", { name: "启用" }).click();
    await page.getByRole("dialog", { name: "启用奖品" }).getByRole("button", { name: "确认启用" }).click();
    if (process.env.MJ_PREVIEW_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.MJ_PREVIEW_SCREENSHOT_DIR, "after-sales-reward-prizes-desktop.png") });
    }
    await navigation.getByRole("button", { name: "服务奖励" }).click();
    await page.getByRole("button", { name: "新增奖励" }).click();
    const form = page.getByRole("dialog", { name: "新增奖励" });
    await form.getByRole("combobox", { name: "获得人员" }).click();
    await page.getByRole("option", { name: /测试人员/ }).click();
    await form.getByRole("textbox", { name: "奖励名称 *" }).fill("服务表现优秀");
    await form.getByRole("combobox", { name: "实物奖品" }).click();
    const selectFocus = await form.locator(".as-create-reward-prize .el-select__input").evaluate((input) => {
      const inputStyle = getComputedStyle(input);
      const wrapperStyle = getComputedStyle(input.closest(".el-select__wrapper"));
      return {
        inputBorder: inputStyle.borderTopWidth,
        inputOutline: inputStyle.outlineStyle,
        inputShadow: inputStyle.boxShadow,
        wrapperShadow: wrapperStyle.boxShadow,
      };
    });
    assert.equal(selectFocus.inputBorder, "0px");
    assert.equal(selectFocus.inputOutline, "none");
    assert.equal(selectFocus.inputShadow, "none");
    assert.notEqual(selectFocus.wrapperShadow, "none");
    if (process.env.MJ_PREVIEW_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.MJ_PREVIEW_SCREENSHOT_DIR, "after-sales-reward-prize-select.png") });
    }
    await page.getByRole("option", { name: "维修箱" }).click();
    await form.getByRole("button", { name: "创建奖励" }).click();
    assert.equal(submitted.length, 1);
    assert.equal(submitted[0].prizeId, prizes[0].id);
    assert.equal(submitted[0].prize, "");

    await page.locator(".module-route-drawer").getByRole("button", { name: "关闭" }).click();
    await navigation.getByRole("button", { name: "设置 / 权限" }).click();
    await page.getByRole("tab", { name: "实物奖励" }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    const panel = page.getByRole("region", { name: "实物奖励" });
    await panel.waitFor();
    const bounds = await panel.boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 391, JSON.stringify(bounds));
    if (process.env.MJ_PREVIEW_SCREENSHOT_DIR) {
      await page.screenshot({ path: path.join(process.env.MJ_PREVIEW_SCREENSHOT_DIR, "after-sales-reward-prizes-mobile.png") });
    }
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});
