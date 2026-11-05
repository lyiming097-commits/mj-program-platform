import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { mkdir, readFile } from "node:fs/promises";
import test from "node:test";
const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(
  new URL("../../../../.codex-artifacts/package.json", import.meta.url),
);
const { chromium } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const session = {
  sessionId: "robot-test",
  userId: "admin",
  actorUserId: "admin",
  name: "管理员",
  canManagePlatformSettings: true,
  canConfigurePermissions: true,
};
const employees = [
  {
    userId: "01333608525827896521",
    name: "张三",
    pinyinInitials: "zs",
    accountStatus: "启用",
    departments: [{ deptId: 1, name: "销售部" }],
  },
];
const groups = [
  {
    id: 1,
    name: "渠道销售部",
    sentCount: 1,
    lastSentAt: "2026-10-19T06:00:00Z",
  },
];
const base = "/api/org/robot-messages";
const png = await readFile(
  new URL("./fixtures/robot-message.png", import.meta.url),
);
let browser, server, origin;
test.before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL("../", import.meta.url)),
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  await server.listen();
  origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ headless: true });
  await mkdir(".codex-artifacts/robot-messages", { recursive: true });
});
test.after(async () => {
  await browser?.close();
  await server?.close();
});
async function fixture({
  width = 1440,
  canManage = true,
  canSend = true,
  uncertain = false,
} = {}) {
  const context = await browser.newContext({
    viewport: { width, height: 900 },
  });
  const login = {
    ...session,
    canManagePlatformSettings: canManage,
    canConfigurePermissions: canManage,
  };
  await context.addInitScript(
    (login) =>
      sessionStorage.setItem("mj_program_login_session", JSON.stringify(login)),
    login,
  );
  const state = {
    sends: [],
    records: [],
    historyQueries: [],
    holdSend: null,
    saves: [],
    groups: [...groups],
    conflict: false,
    historyFailure: false,
    resolvePending: false,
    queries: [],
  };
  await context.route("**/api/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname;
    const fulfill = (body, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (path.startsWith(`${base}/public-images/`))
      return route.fulfill({ contentType: "image/png", body: png });
    if (path === "/api/auth/session/validate") return fulfill(login);
    if (path === `${base}/capabilities`)
      return fulfill({ canSend, canManage, configured: true, maxTargets: 100 });
    if (path === `${base}/people`) {
      state.queries.push(url.searchParams.get("keyword"));
      return fulfill({ items: employees, total: 1 });
    }
    if (path === `${base}/groups`) {
      if (request.method() === "POST") {
        const data = request.postDataJSON();
        state.groups.push({ id: 2, name: data.name, sentCount: 0 });
        return fulfill({ id: 2, name: data.name }, 201);
      }
      return fulfill({ items: state.groups });
    }
    if (path === `${base}/history`) {
      if (state.historyFailure)
        return fulfill({ error: "发送历史加载失败" }, 500);
      const filters = Object.fromEntries(
        ["sentDate", "sender", "target", "content", "status"].map((key) => [
          key,
          url.searchParams.get(key) || "",
        ]),
      );
      const page = Number(url.searchParams.get("page") || 1);
      state.historyQueries.push({ ...filters, page });
      const records = state.records.filter(
        (record) =>
          (!filters.sender || record.senderName.includes(filters.sender)) &&
          (!filters.target ||
            record.recipients.some((r) =>
              r.targetName.includes(filters.target),
            )) &&
          (!filters.content || record.content.includes(filters.content)) &&
          (!filters.status || record.status === filters.status) &&
          (!filters.sentDate ||
            record.createdAt.slice(0, 10) === filters.sentDate),
      );
      return fulfill({
        items: records.slice((page - 1) * 20, page * 20),
        total: records.length,
        page,
      });
    }
    if (path === `${base}/send`) {
      const data = request.postDataJSON();
      state.sends.push(data);
      if (state.holdSend) await state.holdSend;
      if (uncertain && !state.resolvePending)
        return fulfill({ error: "连接超时" }, 504);
      const images = [];
      const contentHtml = (data.contentHtml || "").replace(
        /<img\b[^>]*>/g,
        () => {
          const url = `${base}/public-images/00000000-0000-4000-8000-${String(images.length).padStart(12, "0")}/${"a".repeat(43)}`;
          images.push({ id: String(images.length), url });
          return `<img src="${url}" alt="图片">`;
        },
      );
      const record = {
        ...data,
        contentHtml,
        content:
          data.content ??
          contentHtml
            .replace(/<img\b[^>]*>/g, "[图片]")
            .replace(/<br\s*\/?>/g, "\n")
            .replace(/<\/?(?:p|div)>/g, "\n")
            .replace(/<[^>]+>/g, "")
            .trim(),
        images,
        senderName: "管理员",
        actorName: "管理员",
        createdAt: "2026-10-19T10:00:00Z",
        status: "unknown",
        recipients: [
          {
            id: 1,
            kind: "group",
            groupId: 1,
            targetName: "渠道销售部",
            status: "accepted",
            message: "钉钉已受理",
          },
          {
            id: 2,
            kind: "person",
            targetName: "张三",
            status: "unknown",
            message: "连接超时，请核实钉钉消息",
          },
        ],
      };
      state.records = [record];
      return fulfill(record, 202);
    }
    if (path.startsWith(`${base}/requests/`))
      return state.records.length
        ? fulfill(state.records[0])
        : fulfill({ error: "不存在" }, 404);
    if (path === `${base}/permissions`) {
      if (request.method() === "PUT") {
        state.saves.push(request.postDataJSON());
        return state.conflict
          ? fulfill({ error: "权限已更新", code: "REVISION_CONFLICT" }, 409)
          : fulfill({ ...request.postDataJSON(), revision: 2 });
      }
      return fulfill({ rules: [], revision: 1, orgRevision: 5 });
    }
    if (path === "/api/org/departments/tree")
      return fulfill({ items: [{ deptId: 1, name: "销售部", children: [] }] });
    if (path === "/api/org/employees") return fulfill({ items: employees });
    if (path === "/api/org/enabled-departments")
      return fulfill({ departmentIds: [1], revision: 1, orgRevision: 5 });
    return fulfill({ items: [] });
  });
  const page = await context.newPage(),
    errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(origin + "/auth/settings/robot-messages");
  if (canSend) {
    try {
      await page
        .getByRole("button", { name: "发送消息", exact: true })
        .waitFor({ timeout: 15000 });
    } catch (error) {
      const body = await page.locator("body").innerText();
      await context.close();
      throw new Error(
        `${error.message}; pageErrors=${JSON.stringify(errors)}; body=${body.slice(0, 1500)}`,
      );
    }
  } else
    await page
      .getByText("当前账号没有机器人发送权限，请联系后台管理员开通。")
      .waitFor();
  return { context, page, state, errors };
}
async function chooseRecipients(page) {
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  const picker = page.getByRole("dialog", { name: "发送消息", exact: true });
  await picker
    .getByRole("checkbox", { name: "群聊：渠道销售部", exact: true })
    .check();
  await picker.getByRole("tab", { name: "人员", exact: true }).click();
  await picker.getByRole("textbox", { name: "搜索人员" }).fill("zs");
  await picker
    .getByRole("checkbox", { name: "人员：张三", exact: true })
    .check();
  return picker;
}
test("history ledger creates messages in a modal and exposes complete recipient outcomes", async () => {
  for (const width of [1440, 1024, 800]) {
    const { context, page, state, errors } = await fixture({ width });
    try {
      await page.getByRole("table", { name: "发送历史记录" }).waitFor();
      assert.equal(
        await page.getByRole("textbox", { name: "发送内容" }).count(),
        0,
      );
      await page.getByText("暂无发送记录", { exact: true }).waitFor();
      const dialog = await chooseRecipients(page);
      await dialog
        .getByRole("textbox", { name: "发送内容" })
        .fill("本周渠道销售会议改为下午三点。\n请提前准备销售数据。");
      await page.screenshot({
        path: `.codex-artifacts/robot-messages/history-compose-${width}.png`,
      });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      await dialog.getByRole("button", { name: "发送", exact: true }).click();
      await dialog.waitFor({ state: "hidden" });
      await page.locator(".robot-history-row").waitFor();
      assert.equal(state.sends.length, 1);
      assert.deepEqual(state.sends[0].groupIds, [1]);
      assert.deepEqual(state.sends[0].userIds, ["01333608525827896521"]);
      assert.deepEqual(Object.keys(state.sends[0]).sort(), [
        "contentHtml",
        "groupIds",
        "requestId",
        "userIds",
      ]);
      assert.match(
        await page.locator(".robot-history-row").innerText(),
        /渠道销售部、张三/,
      );
      await page.screenshot({
        path: `.codex-artifacts/robot-messages/history-ledger-${width}.png`,
      });
      await page.getByRole("button", { name: "查看第 1 条发送记录" }).click();
      const detail = page.getByRole("dialog", { name: "发送记录详情" });
      await detail
        .getByText("连接超时，请核实钉钉消息", { exact: true })
        .waitFor();
      assert.equal(
        await detail.locator(".robot-detail-content").innerText(),
        state.records[0].content,
      );
      await page.screenshot({
        path: `.codex-artifacts/robot-messages/history-detail-${width}.png`,
        animations: "disabled",
      });
      await page.keyboard.press("Escape");
      await detail.waitFor({ state: "hidden" });
      await page.waitForFunction(
        () =>
          document.activeElement?.getAttribute("aria-label") ===
          "查看第 1 条发送记录",
      );
      assert.deepEqual(errors, []);
    } finally {
      await context.close();
    }
  }
});
test("compose preserves drafts on canceled close, traps rich editor focus, and discards only after confirmation", async () => {
  const { context, page, state, errors } = await fixture();
  try {
    const dialog = await chooseRecipients(page);
    const content = dialog.getByRole("textbox", { name: "发送内容" });
    await content.fill("尚未发送的草稿");
    await page.keyboard.press("Escape");
    const leave = page.getByRole("alertdialog");
    await leave.getByRole("button", { name: "继续编辑" }).click();
    assert.equal(await content.innerText(), "尚未发送的草稿");
    await content.focus();
    await page.keyboard.press("Tab");
    await page.waitForFunction(
      () => document.activeElement?.textContent.trim() === "取消",
    );
    await page.keyboard.press("Shift+Tab");
    assert.equal(
      await content.evaluate((el) => el === document.activeElement),
      true,
    );
    await dialog.getByRole("button", { name: "发送", exact: true }).focus();
    await page.keyboard.press("Tab");
    assert.equal(
      await dialog
        .getByRole("button", { name: "关闭发送消息" })
        .evaluate((el) => el === document.activeElement),
      true,
    );
    await page.mouse.click(5, 5);
    await leave.getByRole("button", { name: "继续编辑" }).click();
    assert.equal(await content.innerText(), "尚未发送的草稿");
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
    await leave.getByRole("button", { name: "确认放弃" }).click();
    await dialog.waitFor({ state: "hidden" });
    await page.waitForFunction(
      () => document.activeElement?.textContent.trim() === "发送消息",
    );
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    assert.equal(await content.innerText(), "");
    assert.equal(
      await dialog.getByRole("checkbox", { checked: true }).count(),
      0,
    );
    assert.equal(state.sends.length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await context.close();
  }
});
test("uncertain submission keeps its UUID and recipient labels across reload", async () => {
  const { context, page, state, errors } = await fixture({ uncertain: true });
  try {
    let dialog = await chooseRecipients(page);
    await dialog
      .getByRole("textbox", { name: "发送内容" })
      .fill("网络异常测试");
    await dialog.getByRole("button", { name: "发送", exact: true }).click();
    await dialog.getByRole("button", { name: "核对并继续本次发送" }).waitFor();
    const requestId = state.sends[0].requestId;
    assert.equal(
      await dialog
        .getByRole("button", { name: "发送", exact: true })
        .isDisabled(),
      true,
    );
    page.on("dialog", (d) => d.accept());
    await page.reload();
    await page.getByRole("button", { name: "查看待确认发送" }).click();
    dialog = page.getByRole("dialog", { name: "发送消息", exact: true });
    await dialog.getByRole("button", { name: "移除人员张三" }).waitFor();
    assert.equal(
      await dialog.getByRole("textbox", { name: "发送内容" }).innerText(),
      "网络异常测试",
    );
    state.resolvePending = true;
    await dialog.getByRole("button", { name: "核对并继续本次发送" }).click();
    await page.locator(".robot-history-row").waitFor();
    assert.equal(state.sends.length, 2);
    assert.equal(state.sends[1].requestId, requestId);
    assert.equal(state.sends[1].recipientLabels, undefined);
    assert.deepEqual(errors, []);
  } finally {
    await context.close();
  }
});
test("submission disables editing and dismissal until one request finishes", async () => {
  const { context, page, state, errors } = await fixture();
  let release;
  try {
    state.holdSend = new Promise((resolve) => {
      release = resolve;
    });
    const dialog = await chooseRecipients(page);
    await dialog
      .getByRole("textbox", { name: "发送内容" })
      .fill("提交保护测试");
    await dialog.getByRole("button", { name: "发送", exact: true }).click();
    await dialog.getByRole("button", { name: "正在提交…" }).waitFor();
    assert.equal(
      await dialog.getByRole("button", { name: "正在提交…" }).isDisabled(),
      true,
    );
    assert.equal(
      await dialog
        .getByRole("textbox", { name: "发送内容" })
        .getAttribute("contenteditable"),
      "false",
    );
    assert.equal(
      await dialog
        .getByRole("button", { name: "取消", exact: true })
        .isDisabled(),
      true,
    );
    await page.keyboard.press("Escape");
    await page.mouse.click(5, 5);
    assert.equal(await dialog.isVisible(), true);
    release();
    await dialog.waitFor({ state: "hidden" });
    assert.equal(state.sends.length, 1);
    assert.deepEqual(errors, []);
  } finally {
    release?.();
    await context.close();
  }
});
test("history column filters combine on the server, reset pagination and remain aligned while scrolling", async () => {
  const { context, page, state, errors } = await fixture({ width: 1024 });
  try {
    state.records = Array.from({ length: 25 }, (_, i) => ({
      requestId: `record-${i}`,
      content: `通知 ${i + 1}`,
      senderName: "管理员",
      createdAt: "2026-10-19T10:00:00Z",
      status: "accepted",
      recipients: [
        {
          id: i,
          kind: i % 2 === 0 ? "group" : "person",
          groupId: i % 2 === 0 ? 1 : null,
          targetName: i % 2 === 0 ? "渠道销售部" : "张三",
          status: "accepted",
        },
      ],
    }));
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await page.waitForFunction(
      () => document.querySelectorAll(".robot-history-row").length === 20,
    );
    await page.getByRole("button", { name: "下一页" }).click();
    await page.getByRole("button", { name: "查看第 21 条发送记录" }).waitFor();
    assert.equal(await page.locator(".robot-history-row").count(), 5);
    assert.equal(
      await page.getByRole("textbox", { name: "搜索发送历史" }).count(),
      0,
    );
    const filterRow = page.getByRole("row", { name: "发送历史列筛选" });
    assert.equal(await filterRow.locator("td").count(), 7);
    const search = filterRow.getByRole("textbox", { name: "筛选消息内容" });
    await search.fill("通知 25");
    await page.waitForFunction(
      () => document.querySelectorAll(".robot-history-row").length === 1,
    );
    assert.equal(state.historyQueries.at(-1).page, 1);
    assert.equal(new URL(page.url()).searchParams.get("content"), "通知 25");
    await page.getByRole("button", { name: "重置筛选" }).click();
    await page.waitForFunction(
      () => document.querySelectorAll(".robot-history-row").length === 20,
    );
    await filterRow
      .getByRole("textbox", { name: "筛选发送对象" })
      .fill("渠道销售部");
    await page.waitForFunction(
      () => document.querySelectorAll(".robot-history-row").length === 13,
    );
    assert.equal(state.historyQueries.at(-1).target, "渠道销售部");
    await filterRow.getByRole("textbox", { name: "筛选发送人" }).fill("管理员");
    await filterRow
      .getByLabel("筛选发送日期", { exact: true })
      .fill("2026-10-19");
    await filterRow.getByRole("combobox", { name: "筛选发送结果" }).click();
    await page.getByRole("option", { name: "钉钉已受理", exact: true }).click();
    await page.waitForResponse(
      (r) =>
        r.url().includes("/history?") && r.url().includes("status=accepted"),
    );
    await page.waitForFunction(
      () => document.querySelectorAll(".robot-history-row").length === 13,
    );
    assert.deepEqual(state.historyQueries.at(-1), {
      sentDate: "2026-10-19",
      sender: "管理员",
      target: "渠道销售部",
      content: "",
      status: "accepted",
      page: 1,
    });
    await page.reload();
    await page.waitForFunction(
      () => document.querySelectorAll(".robot-history-row").length === 13,
    );
    assert.equal(
      await filterRow.getByRole("textbox", { name: "筛选发送人" }).inputValue(),
      "管理员",
    );
    await page.screenshot({
      path: ".codex-artifacts/robot-messages/column-filters-active-1024.png",
      animations: "disabled",
    });
    await search.fill("没有这条记录");
    await page.getByText("没有匹配的发送记录", { exact: true }).waitFor();
    await page.getByRole("button", { name: "重置筛选" }).click();
    await page.waitForFunction(
      () => document.querySelectorAll(".robot-history-row").length === 20,
    );
    const scroll = page.getByRole("region", {
      name: "发送历史表格，可拖拽或使用左右键横向浏览",
    });
    await scroll.evaluate((el) => {
      el.scrollTop = 180;
    });
    const headerBounds = await filterRow.boundingBox();
    const scrollBounds = await scroll.boundingBox();
    assert.ok(
      headerBounds.y >= scrollBounds.y && headerBounds.y < scrollBounds.y + 90,
    );
    await scroll.evaluate((el) => {
      el.scrollTop = 0;
    });
    await scroll.focus();
    await page.keyboard.press("ArrowRight");
    assert.ok(await scroll.evaluate((el) => el.scrollLeft > 0));
    await scroll.evaluate((el) => {
      el.scrollLeft = 0;
    });
    const cell = await page
      .locator(".robot-history-row")
      .first()
      .locator("td")
      .nth(2)
      .boundingBox();
    await page.mouse.move(cell.x + 40, cell.y + 15);
    await page.mouse.down();
    await page.mouse.move(cell.x + 10, cell.y + 15, { steps: 5 });
    await page.mouse.up();
    assert.equal(
      await page.getByRole("dialog", { name: "发送记录详情" }).count(),
      0,
    );
    state.historyFailure = true;
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await page
      .getByRole("alert")
      .filter({ hasText: "发送历史加载失败" })
      .waitFor();
    state.historyFailure = false;
    await page.getByRole("button", { name: "重试", exact: true }).click();
    await page.waitForFunction(
      () => document.querySelectorAll(".robot-history-row").length === 20,
    );
    assert.deepEqual(errors, []);
  } finally {
    await context.close();
  }
});
test("robot permissions reuse department grants, save versions, and preserve conflicting drafts", async () => {
  const { context, page, state, errors } = await fixture();
  try {
    await page.getByRole("tab", { name: "权限管理", exact: true }).click();
    await page
      .getByRole("heading", { name: "机器人发送权限", exact: true })
      .waitFor();
    await page.getByRole("button", { name: "添加部门发送人员" }).click();
    await page
      .getByRole("checkbox", { name: "销售部部门", exact: true })
      .check();
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page.getByRole("button", { name: "已保存", exact: true }).waitFor();
    assert.equal(state.saves[0].revision, "1");
    assert.equal(state.saves[0].orgRevision, "5");
    await page.getByRole("button", { name: "排除张三", exact: true }).click();
    state.conflict = true;
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page
      .getByRole("alert")
      .filter({ hasText: "权限或组织已更新" })
      .waitFor();
    await page.getByRole("tab", { name: "发送历史", exact: true }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "继续编辑" })
      .click();
    assert.equal(
      await page.getByRole("button", { name: "恢复张三", exact: true }).count(),
      1,
    );
    await page.screenshot({
      path: ".codex-artifacts/robot-messages/permissions-1440.png",
    });
    assert.deepEqual(errors, []);
  } finally {
    await context.close();
  }
});
test("sender-only users cannot see management controls; denied users see an explicit access state", async () => {
  for (const canSend of [true, false]) {
    const { context, page, errors } = await fixture({
      canManage: false,
      canSend,
    });
    try {
      assert.equal(
        await page.getByRole("tab", { name: "权限管理", exact: true }).count(),
        0,
      );
      assert.equal(
        await page
          .getByRole("button", { name: "登记群聊", exact: true })
          .count(),
        0,
      );
      if (!canSend)
        assert.equal(
          await page
            .getByRole("button", { name: "发送消息", exact: true })
            .count(),
          0,
        );
      assert.deepEqual(errors, []);
    } finally {
      await context.close();
    }
  }
});
test("registration dialog preserves unsaved fields and picker supports keyboard and complete backdrop clicks", async () => {
  const { context, page, state, errors } = await fixture();
  try {
    await page.getByRole("button", { name: "登记群聊", exact: true }).click();
    await page
      .getByRole("textbox", { name: "群名称", exact: true })
      .fill("项目通知群");
    await page
      .getByRole("textbox", {
        name: "群标识（openConversationId）",
        exact: true,
      })
      .fill("cid-new");
    await page.keyboard.press("Escape");
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "继续编辑" })
      .click();
    assert.equal(
      await page
        .getByRole("textbox", { name: "群名称", exact: true })
        .inputValue(),
      "项目通知群",
    );
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "登记", exact: true })
      .click();
    await page
      .getByRole("alertdialog", { name: "登记群聊" })
      .waitFor({ state: "hidden" });
    assert.equal(state.groups.length, 2);
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    await page
      .getByRole("checkbox", { name: "群聊：项目通知群", exact: true })
      .waitFor();
    await page.waitForFunction(
      () => document.activeElement?.id === "robot-recipient-search",
    );
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () => document.activeElement?.textContent.trim() === "发送消息",
    );
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    const picker = page.getByRole("dialog", { name: "发送消息", exact: true });
    const bounds = await picker.boundingBox();
    await page.mouse.move(bounds.x + 20, bounds.y + 20);
    await page.mouse.down();
    await page.mouse.move(5, 5);
    await page.mouse.up();
    assert.equal(await picker.isVisible(), true);
    await page.mouse.click(5, 5);
    await picker.waitFor({ state: "hidden" });
    assert.deepEqual(errors, []);
  } finally {
    await context.close();
  }
});

async function addPicture(dialog, buffer = png) {
  await dialog.getByRole("button", { name: "添加图片", exact: true }).focus();
  await dialog
    .getByLabel("添加消息图片")
    .setInputFiles({ name: "notice.png", mimeType: "image/png", buffer });
  await dialog.locator(".platform-rich-editor-content img").first().waitFor();
}
async function pastePicture(
  editor,
  source = png.toString("base64"),
  type = "image/png",
) {
  await editor.focus();
  await editor.evaluate(
    (el, { source, type }) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      range.collapse(false);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      const clipboardData = new DataTransfer();
      const bytes = Uint8Array.from(atob(source), (c) => c.charCodeAt(0));
      clipboardData.items.add(new File([bytes], "clipboard.png", { type }));
      el.dispatchEvent(
        new ClipboardEvent("paste", {
          clipboardData,
          bubbles: true,
          cancelable: true,
        }),
      );
    },
    { source, type },
  );
}

test("template rich editor supports file and clipboard pictures, history previews and nested dismissal", async () => {
  for (const width of [1440, 1024, 800]) {
    const { context, page, state, errors } = await fixture({ width });
    try {
      const dialog = await chooseRecipients(page);
      const editor = dialog.getByRole("textbox", { name: "发送内容" });
      await editor.fill("渠道销售会议调整为下午三点，请查看附件。");
      await addPicture(dialog);
      await pastePicture(editor);
      await page.waitForFunction(
        () =>
          document.querySelectorAll(".platform-rich-editor-content img")
            .length === 2,
      );
      const image = editor.locator("img").first();
      assert.equal(
        await image.evaluate((el) => el.complete && el.naturalWidth > 0),
        true,
      );
      await image.click();
      const preview = page.getByRole("dialog", {
        name: "图片预览",
        exact: true,
      });
      await preview.waitFor();
      await page.keyboard.press("Escape");
      await preview.waitFor({ state: "hidden" });
      assert.equal(await dialog.isVisible(), true);
      assert.equal(await page.getByRole("alertdialog").count(), 0);
      await image.focus();
      await page.keyboard.press("Enter");
      await preview.waitFor();
      await page.mouse.click(60, 60);
      await preview.waitFor({ state: "hidden" });
      assert.equal(await dialog.isVisible(), true);
      await page.screenshot({
        path: `.codex-artifacts/robot-messages/rich-compose-${width}.png`,
      });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      await dialog.getByRole("button", { name: "发送", exact: true }).click();
      await dialog.waitFor({ state: "hidden" });
      assert.equal(state.sends.length, 1);
      assert.equal(
        (state.sends[0].contentHtml.match(/<img /g) || []).length,
        2,
      );
      await page.locator(".robot-history-images img").first().waitFor();
      await page.getByRole("button", { name: "查看第 1 条发送记录" }).click();
      const detail = page.getByRole("dialog", { name: "发送记录详情" });
      const detailImage = detail
        .getByRole("button", { name: "查看图片原图" })
        .first();
      await detailImage.focus();
      await page.keyboard.press("Enter");
      await preview.waitFor();
      await page.keyboard.press("Escape");
      await preview.waitFor({ state: "hidden" });
      assert.equal(await detail.isVisible(), true);
      await page.waitForFunction(
        () =>
          document.activeElement?.getAttribute("aria-label") === "查看图片原图",
      );
      await page.screenshot({
        path: `.codex-artifacts/robot-messages/rich-detail-${width}.png`,
        animations: "disabled",
      });
      await page.keyboard.press("Escape");
      await detail.waitFor({ state: "hidden" });
      assert.deepEqual(errors, []);
    } finally {
      await context.close();
    }
  }
});

test("image-only message larger than sessionStorage recovers from IndexedDB with its original request", async () => {
  const { context, page, state, errors } = await fixture({ uncertain: true });
  try {
    let dialog = await chooseRecipients(page);
    await addPicture(
      dialog,
      Buffer.concat([png, Buffer.alloc(4 * 1024 * 1024)]),
    );
    await dialog.getByRole("button", { name: "发送", exact: true }).click();
    await dialog.getByRole("button", { name: "核对并继续本次发送" }).waitFor();
    const original = state.sends[0];
    assert.ok(original.contentHtml.length > 5 * 1024 * 1024);
    page.on("dialog", (d) => d.accept());
    await page.reload();
    await page.getByRole("button", { name: "查看待确认发送" }).click();
    dialog = page.getByRole("dialog", { name: "发送消息", exact: true });
    await dialog.locator(".platform-rich-editor-content img").waitFor();
    assert.equal(
      await dialog
        .getByRole("textbox", { name: "发送内容" })
        .getAttribute("contenteditable"),
      "false",
    );
    state.resolvePending = true;
    await dialog.getByRole("button", { name: "核对并继续本次发送" }).click();
    await dialog.waitFor({ state: "hidden" });
    assert.equal(state.sends.length, 2);
    assert.equal(state.sends[1].requestId, original.requestId);
    assert.ok(state.sends[1].contentHtml === original.contentHtml);
    await page.reload();
    await page.getByRole("button", { name: "发送消息", exact: true }).waitFor();
    assert.equal(
      await page.getByRole("button", { name: "查看待确认发送" }).count(),
      0,
    );
    assert.deepEqual(errors, []);
  } finally {
    await context.close();
  }
});

test("invalid files and too many pasted images preserve the draft and prevent sending", async () => {
  const { context, page, state, errors } = await fixture();
  try {
    const dialog = await chooseRecipients(page);
    const editor = dialog.getByRole("textbox", { name: "发送内容" });
    await editor.fill("保留这段文字");
    await dialog.getByLabel("添加消息图片").setInputFiles({
      name: "bad.svg",
      mimeType: "image/svg+xml",
      buffer: Buffer.from("<svg/>"),
    });
    await dialog.getByRole("alert").filter({ hasText: "仅支持 PNG" }).waitFor();
    assert.equal(await editor.innerText(), "保留这段文字");
    await dialog.getByLabel("添加消息图片").setInputFiles({
      name: "large.png",
      mimeType: "image/png",
      buffer: Buffer.alloc(8 * 1024 * 1024 + 1),
    });
    await dialog
      .getByRole("alert")
      .filter({ hasText: "图片不能超过 8 MB" })
      .waitFor();
    assert.equal(await editor.innerText(), "保留这段文字");
    for (let i = 1; i <= 7; i++) {
      await pastePicture(editor);
      await page.waitForFunction(
        (count) =>
          document.querySelectorAll(".platform-rich-editor-content img")
            .length === count,
        i,
      );
    }
    await dialog
      .getByRole("alert")
      .filter({ hasText: "每条消息最多添加 6 张图片" })
      .waitFor();
    assert.equal(
      await dialog
        .getByRole("button", { name: "发送", exact: true })
        .isDisabled(),
      true,
    );
    assert.equal(state.sends.length, 0);
    assert.deepEqual(errors, []);
  } finally {
    await context.close();
  }
});

test("storage failure keeps the editable draft and submits no request", async () => {
  const { context, page, state, errors } = await fixture();
  try {
    const dialog = await chooseRecipients(page);
    const editor = dialog.getByRole("textbox", { name: "发送内容" });
    await editor.fill("存储空间不足时保留草稿");
    await page.evaluate(() => {
      IDBObjectStore.prototype.put = () => {
        throw new DOMException("Storage full", "QuotaExceededError");
      };
    });
    await dialog.getByRole("button", { name: "发送", exact: true }).click();
    await dialog
      .getByRole("alert")
      .filter({ hasText: "消息尚未提交" })
      .waitFor();
    assert.equal(state.sends.length, 0);
    assert.equal(await editor.getAttribute("contenteditable"), "true");
    assert.equal(await editor.innerText(), "存储空间不足时保留草稿");
    assert.deepEqual(errors, []);
  } finally {
    await context.close();
  }
});

test("application notifications expose the source and business reference in the shared history", async () => {
  const { context, page, state, errors } = await fixture();
  try {
    state.records = [
      {
        requestId: "application-notification",
        content: "订单审批已通过",
        contentHtml: "<p>订单审批已通过</p>",
        sourceKind: "application",
        sourceAppId: "crm",
        sourceService: "crm-backend",
        businessKey: "order:123:approved",
        senderName: "客户管理",
        actorName: "客户管理",
        status: "accepted",
        createdAt: "2026-10-20T02:00:00Z",
        recipients: [
          {
            id: 1,
            kind: "person",
            targetName: "张三",
            userId: "01333608525827896521",
            status: "accepted",
          },
        ],
      },
    ];
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await page
      .locator(".robot-history-row")
      .getByText("应用通知", { exact: true })
      .waitFor();
    await page.getByRole("button", { name: "查看第 1 条发送记录" }).click();
    const detail = page.getByRole("dialog", { name: "发送记录详情" });
    await detail.getByText("客户管理（crm）", { exact: true }).waitFor();
    await detail.getByText("order:123:approved", { exact: true }).waitFor();
    assert.equal(
      await detail.getByText("实际操作者", { exact: true }).count(),
      0,
    );
    await page.screenshot({
      path: ".codex-artifacts/robot-messages/application-notification-1440.png",
      animations: "disabled",
    });
    assert.deepEqual(errors, []);
  } finally {
    await context.close();
  }
});
