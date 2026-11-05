import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";
const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));
const artifacts = fileURLToPath(new URL("../../../../.codex-artifacts/notification-template/", import.meta.url));
const session = { sessionId: "notice-editor-fixture", userId: "admin", actorUserId: "admin", name: "通知管理员", canManagePlatformSettings: true, isFullAccessUser: true };
const departments = [{ deptId: "1", name: "研发部", pinyin: "yanfabu", pinyinInitials: "yfb", children: [{ deptId: "2", name: "产品组", pinyin: "chanpinzu", pinyinInitials: "cpz", children: [] }] }, { deptId: "3", name: "销售部", pinyin: "xiaoshoubu", pinyinInitials: "xsb", children: [] }];
const employees = [{ userId: "u1", name: "张三", pinyin: "zhangsan", pinyinInitials: "zs", departments: [{ deptId: "1" }, { deptId: "2" }] }, { userId: "u2", name: "李四", pinyin: "lisi", pinyinInitials: "ls", departments: [{ deptId: "2" }] }, { userId: "u3", name: "王五", pinyin: "wangwu", pinyinInitials: "ww", departments: [{ deptId: "3" }] }];
await test("notification forms reuse the template with full editor and protected drafts", async t => {
  const external = process.env.NOTIFICATION_EDITOR_BASE_URL;
  const server = external ? null : await createServer({ root, server: { host: "127.0.0.1", port: 0, strictPort: false } });
  if (server) await server.listen();
  const base = external || `http://127.0.0.1:${server.httpServer.address().port}`;
  const browser = await chromium.launch({ headless: true });
  await mkdir(artifacts, { recursive: true });
  async function fixture(width = 1440, timezoneId = "Asia/Shanghai", overrides = {}) {
    const context = await browser.newContext({ viewport: { width, height: 960 }, timezoneId, reducedMotion: "reduce" });
    await context.addInitScript(value => sessionStorage.setItem("mj_program_login_session", JSON.stringify(value)), session);
    const state = { writes: [], attachments: [], notices: [], failUpload: false, failSave: false, failReaders: false, holdSave: false, releaseSave: null, queries: [], history: [], capability: { canManage: true, canPublish: true }, readerRequests: [], readerTotal: 1, holdReaders: false, releaseReaders: null, failMutation: false, ...overrides };
    await context.route("**/api/**", async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
      const reply = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
      if (path === "/api/auth/session/validate") return reply(session);
      if (path === "/api/org/notices/capabilities") return reply(state.capability);
      if (path === "/api/org/notices/categories") return reply({ items: [{ id: 1, name: "制度通知" }, { id: 2, name: "工作安排" }] });
      if (path === "/api/org/departments/tree") return reply({ items: state.departments || departments });
      if (path === "/api/org/employees") return reply({ items: state.employees || employees });
      if (path === "/api/org/enabled-departments") return reply({ departmentIds: state.enabledDepartmentIds || ["1", "2", "3"] });
      if (path === "/api/org/notices/unread") return reply({ items: [], total: 0 });
      if (path === "/api/org/notices/history") { state.queries.push({ history: true, params: Object.fromEntries(url.searchParams) }); const start = (Number(url.searchParams.get("page") || 1) - 1) * 20; return reply({ items: state.history.slice(start, start + 20), total: state.history.length }); }
      if (path === "/api/org/notices" && method === "GET") {
        const params = Object.fromEntries(url.searchParams);
        state.queries.push({ params });
        let items = state.notices;
        if (state.receipts) {
          if (params.recipientUserId) items = items.filter(notice => state.receipts.some(person => person.noticeId === notice.id && person.userId === params.recipientUserId));
          if (params.unreadUserId) items = items.filter(notice => state.receipts.some(person => person.noticeId === notice.id && person.userId === params.unreadUserId && !person.readAt));
        }
        const start = (Number(params.page || 1) - 1) * 20;
        return reply({ items: items.slice(start, start + 20), total: items.length });
      }
      if (path === "/api/org/notices" && method === "POST" || /^\/api\/org\/notices\/\d+$/.test(path) && method === "PATCH") {
        state.writes.push({ method, payload: request.postDataJSON() });
        if (state.holdSave) await new Promise(resolve => { state.releaseSave = resolve; });
        if (state.failSave) return reply({ error: "保存失败，请稍后重试" }, 503);
        const payload = request.postDataJSON();
        const existing = method === "PATCH" ? state.notices[0] : null;
        const notice = { ...existing, id: "1", ...payload, expiresOn: payload.expiresAt, expiresAt: payload.expiresAt ? new Date(new Date(`${payload.expiresAt}T00:00:00+08:00`).getTime() + 86400000).toISOString() : "", status: method === "PATCH" ? state.notices[0].status : "draft", category: { id: payload.categoryId, name: payload.categoryId === 1 ? "制度通知" : "工作安排" }, attachments: state.attachments, recipientCount: existing?.recipientCount ?? 3, unreadCount: existing?.unreadCount ?? 3, createdAt: "2026-10-22T02:00:00Z" };
        state.notices = [notice]; return reply(notice, method === "POST" ? 201 : 200);
      }
      if (path === "/api/org/notices/1/attachments") {
        state.writes.push({ method, upload: true });
        if (state.failUpload) return reply({ error: "附件上传失败，请重试" }, 503);
        state.attachments = [{ id: "a1", name: "会议安排.txt", size: 6, url: "/api/org/notices/attachments/a1/download" }];
        state.notices[0].attachments = state.attachments;
        return reply({ items: state.attachments });
      }
      if (/^\/api\/org\/notices\/\d+\/(publish|withdraw)$/.test(path)) {
        const action = path.split("/").at(-1), notice = state.notices.find(item => item.id === path.split("/").at(-2));
        const payload = request.postDataJSON();
        state.writes.push({ [action]: true, ...payload });
        if (state.failMutation) return reply({ error: "操作失败，请重试" }, 503);
        notice.status = action === "publish" ? "published" : "withdrawn";
        if (action === "publish" && payload.level) notice.level = payload.level;
        if (action === "publish" && payload.resetRead) {
          notice.unreadCount = notice.recipientCount;
          for (const person of state.receipts || []) if (person.noticeId === notice.id) person.readAt = null;
        }
        const { contentHtml, ...summary } = notice;
        return reply(summary);
      }
      if (/^\/api\/org\/notices\/\d+$/.test(path)) {
        const id = path.split("/").at(-1);
        if (method === "DELETE") {
          state.writes.push({ delete: true });
          if (state.failMutation) return reply({ error: "操作失败，请重试" }, 503);
          state.notices = state.notices.filter(item => item.id !== id);
          return reply({ ok: true });
        }
        return reply([...state.notices, ...state.history].find(item => item.id === id));
      }
      if (/^\/api\/org\/notices\/\d+\/recipients$/.test(path)) {
        state.readerRequests.push({ id: path.split("/").at(-2), ...Object.fromEntries(url.searchParams) });
        const held = state.holdReaders;
        if (held) await new Promise(resolve => { state.releaseReaders = resolve; });
        if (state.failReaders) return reply({ error: "阅读名单加载失败" }, 503);
        return reply({ items: [{ confirmation: state.confirmation || null, userId: "u1", name: held ? "旧名单人员" : url.searchParams.get("page") === "2" ? "下一页人员" : "张三", departmentNames: ["研发部"], readAt: url.searchParams.get("status") === "read" ? "2026-10-22T02:00:00Z" : null }], total: state.readerTotal });
      }
      if (path === "/api/org/notices/attachments/a1" && method === "DELETE") { state.writes.push({ deleteAttachment: true }); state.attachments = []; return reply({}); }
      return reply({ items: [], total: 0, rules: [], revision: "1", orgRevision: "1" });
    });
    const page = await context.newPage(), errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "warning" && message.text().includes("Vue warn")) errors.push(message.text()); });
    await page.goto(`${base}/auth/settings/notifications${state.initialSearch || ""}`);
    await page.getByRole("tab", { name: state.capability.canPublish ? "通知列表" : "我的通知", exact: true }).waitFor();
    await page.getByRole("table").waitFor();
    return { context, page, state, errors };
  }
  async function choosePeople(page) {
    const department = page.getByRole("combobox", { name: "搜索部门名称、ID 或拼音", exact: true });
    await department.fill("cpz");
    await page.getByRole("checkbox", { name: "选择产品组", exact: true }).check();
    await department.fill("yfb");
    await page.getByRole("checkbox", { name: "选择研发部", exact: true }).check();
    await page.keyboard.press("Escape");
    const people = page.getByRole("combobox", { name: "搜索人员姓名、ID 或拼音", exact: true });
    await people.fill("ww"); await page.getByRole("option", { name: "王五 · 销售部", exact: true }).click();
    await people.fill("zs"); await page.getByRole("option", { name: "张三 · 研发部 / 产品组", exact: true }).click();
    await page.keyboard.press("Escape");
    assert.deepEqual(await page.getByRole("group", { name: "通知人员", exact: true }).locator(".starter-detail-chip > span").allTextContents(), ["王五", "张三"]);
  }
  const sampleNotice = (id = "1", extra = {}) => ({
    id, title: `部门通知 ${id}`, category: { id: 1, name: "制度通知" },
    contentHtml: "<p>请按通知安排执行。</p>", status: "published", attachments: [],
    createdAt: "2026-10-22T02:00:00Z", publishedAt: "2026-10-22T02:00:00Z",
    expiresOn: "2099-02-28", expiresAt: "2099-02-28T16:00:00Z",
    recipientSelection: { departments: [], people: ["u1"] }, recipientCount: 21, unreadCount: 20,
    ...extra,
  });
  try {
    for (const width of [1440, 1024]) await t.test(`${width}px fixed sequence column and centered template pagination across list and history`, async () => {
      const { context, page, state, errors } = await fixture(width, "Asia/Shanghai", {
        notices: Array.from({ length: 161 }, (_, index) => sampleNotice(String(index + 1))),
        history: Array.from({ length: 41 }, (_, index) => sampleNotice(String(index + 1))),
      });
      try {
        let table = page.getByRole("table", { name: "通知列表记录", exact: true });
        const pager = page.getByRole("navigation", { name: "通知列表分页", exact: true });
        const sequence = () => table.locator("tbody .notification-record-row > td:first-child");
        const expectFirst = value => page.waitForFunction(expected => document.querySelector('.notification-record-row > td:first-child')?.textContent.trim() === expected
          && document.querySelector('.notification-record-row [data-notice-id]')?.dataset.noticeId === expected, String(value));
        await expectFirst(1);
        assert.equal(await sequence().last().innerText(), "20");
        assert.equal(await table.getByRole("columnheader").first().innerText(), "序号");
        assert.equal(await table.getByRole("row", { name: "通知列表列筛选", exact: true }).getByRole("cell").first().innerText(), "");
        const numberHeader = table.getByRole("columnheader", { name: "序号", exact: true });
        assert.ok(Math.abs((await numberHeader.boundingBox()).width - 48) < 1);
        assert.equal(await pager.getByRole("button", { name: "上一页", exact: true }).isDisabled(), true);
        const footer = page.locator(".notification-pagination");
        const footerBounds = await footer.boundingBox(), pagerBounds = await pager.boundingBox();
        assert.ok(Math.abs((pagerBounds.x + pagerBounds.width / 2) - (footerBounds.x + footerBounds.width / 2)) < 1, "pagination is centered within the panel");
        const totalBounds = await footer.locator(".notification-pagination-total").boundingBox();
        assert.ok(totalBounds.x + totalBounds.width < pagerBounds.x, "left total does not overlap pagination");
        const scroll = page.getByRole("region", { name: "通知记录表格，可横向滚动", exact: true });
        await scroll.evaluate(node => { node.scrollLeft = 450; });
        await page.waitForFunction(() => document.querySelector('.notification-table-scroll').scrollLeft > 0);
        const scrollBounds = await scroll.boundingBox(), sequenceBounds = await sequence().first().boundingBox(), headerBounds = await numberHeader.boundingBox();
        assert.ok(Math.abs(sequenceBounds.x - scrollBounds.x) < 2 && Math.abs(headerBounds.x - scrollBounds.x) < 2, "sequence remains fixed while scrolling horizontally");
        await pager.getByRole("button", { name: "下一页", exact: true }).click();
        await expectFirst(21);
        assert.equal(await sequence().last().innerText(), "40");
        assert.equal(await pager.getByRole("button", { name: "第 2 页", exact: true }).getAttribute("aria-current"), "page");
        assert.equal(new URL(page.url()).searchParams.get("page"), "2");
        await pager.getByRole("button", { name: "第 9 页", exact: true }).click();
        await expectFirst(161);
        assert.equal(await sequence().count(), 1);
        assert.equal(await pager.getByRole("button", { name: "下一页", exact: true }).isDisabled(), true);
        assert.equal(await pager.locator(".notification-page-ellipsis").count(), 1);
        await pager.getByRole("button", { name: "上一页", exact: true }).click();
        await expectFirst(141);
        await scroll.evaluate(node => { node.scrollLeft = 0; });
        await table.getByRole("searchbox", { name: "按通知标题搜索", exact: true }).fill("部门通知");
        await expectFirst(1);
        assert.equal(state.queries.at(-1).params.page, "1");
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}notice-sequence-pagination-${width}.png` });
        await page.getByRole("tab", { name: "我的通知", exact: true }).click();
        table = page.getByRole("table", { name: "我的通知历史", exact: true });
        await table.waitFor();
        await expectFirst(1);
        assert.equal(await table.getByRole("columnheader").count(), 5);
        await pager.getByRole("button", { name: "第 3 页", exact: true }).click();
        await expectFirst(41);
        assert.equal(await sequence().count(), 1);
        assert.equal(await pager.getByRole("button", { name: "下一页", exact: true }).isDisabled(), true);
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    for (const width of [1440, 1024]) await t.test(`${width}px department names, paths and independent descendant scope survive draft saving`, async () => {
      const nestedDepartments = structuredClone(departments);
      nestedDepartments[0].children[0].children.push({ deptId: "4", name: "深层组", pinyin: "shencengzu", pinyinInitials: "scz", children: [] });
      const { context, page, state, errors } = await fixture(width, "Asia/Shanghai", {
        departments: nestedDepartments, enabledDepartmentIds: ["1", "2", "3", "4"],
        employees: [...employees, { userId: "u4", name: "赵六", departments: [{ deptId: "4" }] }],
      });
      try {
        await page.getByRole("button", { name: "新建通知", exact: true }).click();
        let dialog = page.getByRole("dialog", { name: "新建通知", exact: true });
        await dialog.getByRole("textbox", { name: "通知标题", exact: false }).fill("部门范围测试");
        await dialog.getByRole("textbox", { name: "通知正文", exact: true }).fill("浏览器测试正文");
        let input = dialog.getByRole("combobox", { name: "搜索部门名称、ID 或拼音", exact: true });
        await input.fill("Y-F-B");
        const grid = page.getByRole("grid", { name: "通知部门", exact: true });
        const parent = grid.getByRole("checkbox", { name: "选择研发部", exact: true });
        const include = grid.getByRole("checkbox", { name: "研发部包含所有下级部门", exact: true });
        await parent.check();
        assert.equal(await include.isChecked(), true);
        const selectedDepartments = page.getByRole("group", { name: "通知部门", exact: true });
        const parentChip = selectedDepartments.locator(".starter-detail-chip").filter({ has: page.getByRole("button", { name: "移除研发部", exact: true }) });
        await parentChip.getByText("含下级", { exact: true }).waitFor();
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}department-scope-badge-${width}.png` });
        await dialog.getByText("预计接收 3 人", { exact: true }).waitFor();
        await include.uncheck();
        assert.equal(await parent.isChecked(), true, "scope checkbox does not deselect the department");
        assert.equal(await parentChip.getByText("含下级", { exact: true }).count(), 0);
        await dialog.getByText("预计接收 1 人", { exact: true }).waitFor();
        await parent.uncheck();
        assert.equal(await include.isChecked(), false);
        await dialog.getByText("预计接收 0 人", { exact: true }).waitFor();
        await include.check();
        assert.equal(await parent.isChecked(), true, "checking descendant scope also selects the department");
        await parentChip.getByText("含下级", { exact: true }).waitFor();
        await dialog.getByText("预计接收 3 人", { exact: true }).waitFor();
        await include.uncheck();
        await input.fill("cpz");
        const childRow = grid.getByRole("row").filter({ has: page.getByRole("checkbox", { name: "选择产品组", exact: true }) });
        const shortName = childRow.locator(".starter-detail-toggle-name");
        const path = childRow.locator(".starter-detail-toggle-description");
        assert.equal(await shortName.textContent(), "产品组");
        assert.equal(await path.textContent(), "研发部 / 产品组");
        assert.equal(await path.evaluate(node => getComputedStyle(node).color), "rgb(100, 116, 139)");
        const nameBounds = await shortName.boundingBox(), pathBounds = await path.boundingBox();
        assert.ok(pathBounds.x >= nameBounds.x + nameBounds.width, "path is to the right of the short name");
        await childRow.getByRole("checkbox", { name: "选择产品组", exact: true }).check();
        await dialog.getByText("预计接收 3 人", { exact: true }).waitFor();
        await childRow.getByRole("checkbox", { name: "产品组包含所有下级部门", exact: true }).uncheck();
        await dialog.getByText("预计接收 2 人", { exact: true }).waitFor();
        await input.fill("研发部 / 产品组 / 深层组");
        assert.equal(await grid.getByRole("row").count(), 1, "full paths remain searchable");
        await input.fill("4");
        assert.equal(await grid.getByRole("checkbox", { name: "选择深层组", exact: true }).count(), 1);
        await input.fill("SHEN CENG ZU");
        await input.press("Enter");
        await dialog.getByText("预计接收 3 人", { exact: true }).waitFor();
        await input.fill("scz");
        await input.press("Tab");
        await page.keyboard.press("ArrowRight");
        const deepScope = grid.getByRole("checkbox", { name: "深层组包含所有下级部门", exact: true });
        assert.equal(await deepScope.evaluate(node => node === document.activeElement), true);
        await page.keyboard.press("Space");
        assert.equal(await deepScope.isChecked(), false);
        await page.keyboard.press("ArrowLeft");
        await page.keyboard.press("Enter");
        await dialog.getByText("预计接收 2 人", { exact: true }).waitFor();
        await page.keyboard.press("Escape");
        assert.equal(await input.evaluate(node => node === document.activeElement), true);
        assert.equal(await dialog.count(), 1);
        const selected = dialog.getByRole("group", { name: "通知部门", exact: true });
        assert.deepEqual(await selected.locator(".starter-detail-chip > span").allTextContents(), ["研发部", "产品组"]);
        await input.fill("");
        await input.click();
        const menuBounds = await grid.boundingBox();
        assert.ok(menuBounds.x >= 0 && menuBounds.x + menuBounds.width <= width && menuBounds.y >= 0 && menuBounds.y + menuBounds.height <= 960);
        assert.equal(await grid.locator("button input, label button").count(), 0);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}department-scope-${width}.png` });
        await page.keyboard.press("Escape");
        await dialog.getByRole("button", { name: "保存", exact: true }).click();
        await page.getByRole("button", { name: "部门范围测试", exact: true }).click();
        await page.getByRole("dialog", { name: "部门范围测试", exact: true }).waitFor();
        assert.deepEqual(state.writes[0].payload.recipientSelection.departments, [{ deptId: 1, includeSubDepartments: false }, { deptId: 2, includeSubDepartments: false }]);
        await page.getByRole("button", { name: "编辑", exact: true }).click();
        dialog = page.getByRole("dialog", { name: "编辑通知", exact: true });
        await dialog.getByText("预计接收 2 人", { exact: true }).waitFor();
        input = dialog.getByRole("combobox", { name: "搜索部门名称、ID 或拼音", exact: true });
        await input.fill("yfb");
        assert.equal(await parent.isChecked(), true);
        assert.equal(await include.isChecked(), false);
        assert.equal(await parentChip.getByText("含下级", { exact: true }).count(), 0);
        await include.check();
        await parentChip.getByText("含下级", { exact: true }).waitFor();
        await page.keyboard.press("Escape");
        await dialog.getByRole("button", { name: "保存", exact: true }).click();
        await page.getByRole("button", { name: "编辑", exact: true }).click();
        await dialog.waitFor();
        await parentChip.getByText("含下级", { exact: true }).waitFor();
        await input.fill("yfb");
        assert.equal(await include.isChecked(), true);
        await page.keyboard.press("Escape");
        await dialog.getByRole("button", { name: "关闭通知编辑器", exact: true }).click();
        assert.equal(await page.getByRole("alertdialog").count(), 0, "restored scope is a clean draft");
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    await t.test("disabled intermediate departments do not inflate descendant recipient counts", async () => {
      const { context, page, errors } = await fixture(1440, "Asia/Shanghai", { enabledDepartmentIds: ["1", "3", "4"], departments: [
        { ...departments[0], children: [{ ...departments[0].children[0], children: [{ deptId: "4", name: "独立启用组", children: [] }] }] }, departments[1],
      ], employees: [...employees, { userId: "u4", name: "赵六", departments: [{ deptId: "4" }] }] });
      try {
        await page.getByRole("button", { name: "新建通知", exact: true }).click();
        const dialog = page.getByRole("dialog", { name: "新建通知", exact: true });
        const input = dialog.getByRole("combobox", { name: "搜索部门名称、ID 或拼音", exact: true });
        await input.fill("yfb");
        await page.getByRole("checkbox", { name: "选择研发部", exact: true }).check();
        await dialog.getByText("预计接收 1 人", { exact: true }).waitFor();
        await input.fill("独立启用组");
        await page.getByRole("checkbox", { name: "选择独立启用组", exact: true }).check();
        await dialog.getByText("预计接收 2 人", { exact: true }).waitFor();
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    for (const width of [1440, 1024]) await t.test(`${width}px form layout, keyboard, validation, backdrop and unsaved protection`, async () => {
      const { context, page, state, errors } = await fixture(width);
      try {
        await page.getByRole("button", { name: "新建通知", exact: true }).click();
        const dialog = page.getByRole("dialog", { name: "新建通知", exact: true });
        await dialog.waitFor();
        assert.equal(await dialog.getByRole("button", { name: "保存", exact: true }).count(), 1);
        assert.equal(await dialog.getByRole("button", { name: "保存并发布", exact: true }).count(), 1);
        assert.equal(await dialog.getByRole("button", { name: "保存并重新发布", exact: true }).count(), 0);
        assert.equal(await dialog.getByLabel("到期日期", { exact: false }).getAttribute("type"), "date");
        assert.equal(await dialog.getByLabel("到期日期", { exact: false }).inputValue(), "");
        assert.equal(await dialog.getByLabel("到期日期", { exact: false }).evaluate(node => node.required), false);
        const information = dialog.getByRole("region", { name: "通知信息", exact: true });
        const content = dialog.getByRole("region", { name: "通知内容", exact: true });
        assert.equal(await dialog.locator("form > section").count(), 2);
        assert.equal(await information.getByRole("combobox", { name: "通知分类", exact: true }).count(), 1);
        assert.equal(await information.getByLabel("到期日期", { exact: true }).count(), 1);
        assert.equal(await information.getByText("通知对象", { exact: false }).count(), 1);
        assert.equal(await information.getByRole("group", { name: "通知部门", exact: true }).count(), 1);
        assert.equal(await information.getByRole("group", { name: "通知人员", exact: true }).count(), 1);
        assert.equal(await content.getByRole("textbox", { name: "通知标题", exact: true }).count(), 1);
        assert.equal(await content.getByRole("textbox", { name: "通知正文", exact: true }).count(), 1);
        assert.deepEqual(await content.locator(".notice-field > label").allTextContents(), ["标题 *", "正文 *", "附件"]);
        assert.equal(await content.locator("#notification-attachments").count(), 1);
        assert.equal(await dialog.locator("form").evaluate(node => node.scrollTop), 0, "opening the form keeps its first group visible");
        const panel = dialog.locator(".platform-detail-drawer-panel"), bounds = await panel.boundingBox();
        assert.ok(Math.abs(bounds.width - width / 2) < 1);
        await page.waitForFunction(() => Math.abs(document.querySelector(".platform-detail-drawer-panel").getBoundingClientRect().x - innerWidth / 2) < 1);
        assert.equal(await page.locator(".notification-rich-toolbar, .notification-audience-list").count(), 0);
        for (const name of ["加粗", "斜体", "下划线", "无序列表", "有序列表", "插入链接", "撤销", "重做", "粘贴"]) assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1);
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}new-notice-${width}.png` });
        await dialog.getByRole("button", { name: "关闭通知编辑器" }).click();
        assert.equal(await page.getByRole("alertdialog").count(), 0, "untouched default category is not dirty");
        await page.getByRole("button", { name: "新建通知", exact: true }).click();
        await dialog.getByRole("button", { name: "保存", exact: true }).click();
        await page.getByText("请填写通知标题", { exact: true }).first().waitFor();
        assert.equal(await page.getByRole("textbox", { name: "通知标题", exact: false }).getAttribute("aria-invalid"), "true");
        assert.equal(state.writes.length, 0);
        await page.getByRole("textbox", { name: "通知标题", exact: false }).fill("十月部门通知");
        const category = dialog.getByRole("combobox", { name: "通知分类", exact: true });
        await category.fill("工作"); await page.keyboard.press("Enter");
        await choosePeople(page);
        await dialog.getByText("预计接收 3 人", { exact: true }).waitFor();
        const body = dialog.getByRole("textbox", { name: "通知正文", exact: true });
        await body.fill("请查看通知正文并确认已读。"); await body.press("ControlOrMeta+A");
        await dialog.getByRole("button", { name: "加粗", exact: true }).click();
        assert.match(await body.innerHTML(), /<(b|strong)>/);
        await body.press("ArrowRight");
        await dialog.locator("#notification-attachments").setInputFiles({ name: "会议安排.txt", mimeType: "text/plain", buffer: Buffer.from("会议") });
        await dialog.getByRole("button", { name: "打开附件：会议安排.txt" }).waitFor();
        assert.equal(await dialog.locator('[aria-invalid="true"]').count(), 0, "corrected fields clear their validation errors");
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}filled-notice-${width}.png` });
        // A drag from drawer content to backdrop cannot dismiss the form.
        const start = await page.getByRole("textbox", { name: "通知标题", exact: false }).boundingBox();
        await page.mouse.move(start.x + 15, start.y + 10); await page.mouse.down(); await page.mouse.move(20, 350); await page.mouse.up();
        assert.equal(await page.getByRole("alertdialog").count(), 0);
        await page.mouse.click(20, 350);
        await page.getByRole("alertdialog", { name: "是否放弃修改" }).waitFor();
        await page.getByRole("button", { name: "继续编辑", exact: true }).click();
        assert.equal(await page.getByRole("textbox", { name: "通知标题", exact: false }).inputValue(), "十月部门通知");
        await page.keyboard.press("Escape");
        await page.getByRole("button", { name: "确认放弃", exact: true }).click();
        await page.getByRole("button", { name: "新建通知", exact: true }).waitFor();
        await page.waitForFunction(() => document.activeElement?.textContent.includes("新建通知"));
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    for (const width of [1440, 1024]) await t.test(`${width}px whole-row detail, template tabs, unread-first list and keyboard navigation`, async () => {
      const { context, page, state, errors } = await fixture(width, "Asia/Shanghai", { notices: [sampleNotice()], readerTotal: 21 });
      try {
        const table = page.getByRole("table", { name: "通知列表记录", exact: true });
        await page.getByRole("heading", { name: "通知列表", exact: true }).waitFor();
        assert.equal(await table.getByRole("columnheader", { name: "操作", exact: true }).count(), 0);
        assert.equal(await table.getByRole("columnheader").count(), 8);
        const filters = table.getByRole("row", { name: "通知列表列筛选", exact: true });
        const filterCells = filters.getByRole("cell");
        assert.equal(await filterCells.count(), 8);
        assert.equal(await filterCells.nth(1).getByRole("searchbox", { name: "按通知标题搜索", exact: true }).count(), 1);
        assert.equal(await filterCells.nth(2).getByRole("combobox", { name: "通知分类", exact: true }).count(), 1);
        assert.equal(await filterCells.nth(3).getByRole("group", { name: "发布时间范围", exact: true }).count(), 1);
        assert.equal(await filterCells.nth(5).getByRole("combobox", { name: "发布状态", exact: true }).count(), 1);
        assert.equal(await filterCells.nth(6).getByRole("combobox", { name: "接收人筛选", exact: true }).count(), 1);
        assert.equal(await filterCells.nth(7).getByRole("combobox", { name: "未完成人员筛选", exact: true }).count(), 1);
        const headingsBounds = await table.locator("thead tr").first().boundingBox(), filtersBounds = await filters.boundingBox();
        assert.ok(filtersBounds.y >= headingsBounds.y + headingsBounds.height - 1);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}notice-list-filters-${width}.png` });
        const category = table.getByRole("cell", { name: "制度通知", exact: true });
        const position = await category.boundingBox();
        await page.mouse.move(position.x + 45, position.y + 15);
        await page.mouse.down(); await page.mouse.move(position.x - 30, position.y + 15, { steps: 8 }); await page.mouse.up();
        assert.equal(await page.getByRole("dialog").count(), 0, "dragging the wide table must not open a notice");
        await category.click();
        const detail = page.getByRole("dialog", { name: "部门通知 1", exact: true });
        await detail.waitFor();
        await page.waitForFunction(() => Math.abs(document.querySelector(".platform-detail-drawer-panel").getBoundingClientRect().x - innerWidth / 2) < 1);
        const tabs = detail.getByRole("tablist", { name: "通知详情页签" });
        assert.equal(await tabs.getByRole("tab").count(), 2);
        assert.equal(await tabs.getByRole("tab").first().evaluate(node => node.getBoundingClientRect().height), 32);
        const contentTab = tabs.getByRole("tab", { name: "通知详情", exact: true });
        const readersTab = tabs.getByRole("tab", { name: "已读情况", exact: true });
        assert.equal(await contentTab.getAttribute("aria-selected"), "true");
        assert.equal(state.readerRequests.length, 0, "detail opens without requesting the recipient list");
        const content = detail.getByRole("region", { name: "通知内容", exact: true });
        assert.deepEqual(await content.getByRole("term").allTextContents(), ["标题", "正文", "附件"]);
        assert.equal(await content.getByRole("definition").first().textContent(), "部门通知 1");
        await content.getByText("请按通知安排执行。", { exact: true }).waitFor();
        await content.getByText("暂无附件", { exact: true }).waitFor();
        assert.deepEqual(await detail.getByRole("group", { name: "通知操作", exact: true }).getByRole("button").allTextContents(), ["撤回", "删除", "编辑"]);
        assert.equal(await detail.getByRole("button", { name: "关闭", exact: true }).count(), 0);
        assert.equal(await detail.getByRole("button", { name: "关闭通知详情", exact: true }).count(), 1);
        const headerBounds = await detail.locator("header").boundingBox(), tabBounds = await tabs.boundingBox(), bodyBounds = await detail.getByRole("tabpanel").boundingBox();
        assert.ok(tabBounds.y >= headerBounds.y + headerBounds.height - 1 && bodyBounds.y >= tabBounds.y + tabBounds.height - 1);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}notice-detail-${width}.png` });
        await contentTab.focus(); await page.keyboard.press("End");
        await detail.getByRole("cell", { name: "张三", exact: true }).waitFor();
        assert.equal(await readersTab.getAttribute("aria-selected"), "true");
        assert.equal(await readersTab.evaluate(node => document.activeElement === node), true);
        assert.deepEqual(state.readerRequests.map(item => item.status), ["unread"]);
        const pagination = detail.getByRole("group", { name: "阅读名单分页" });
        await pagination.getByRole("button", { name: "下一页", exact: true }).click();
        await detail.getByRole("cell", { name: "下一页人员", exact: true }).waitFor();
        await detail.getByRole("button", { name: "全部", exact: true }).click();
        await detail.getByRole("cell", { name: "张三", exact: true }).waitFor();
        assert.equal(state.readerRequests.at(-1).page, "1");
        assert.equal(state.readerRequests.at(-1).status, "all");
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}notice-readers-${width}.png` });
        await readersTab.focus(); await page.keyboard.press("Home");
        await detail.getByRole("tabpanel", { name: "通知详情", exact: true }).waitFor();
        await page.getByRole("button", { name: "关闭通知详情", exact: true }).click();
        const title = table.getByRole("button", { name: "部门通知 1", exact: true });
        await page.waitForFunction(() => document.activeElement?.textContent === "部门通知 1");
        await title.press("Enter");
        await detail.waitFor();
        assert.equal(await contentTab.getAttribute("aria-selected"), "true");
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    for (const width of [2048, 1024]) await t.test(`${width}px searchable single-person receipt/unread filters intersect, restore and clear`, async () => {
      const { context, page, state, errors } = await fixture(width, "Asia/Shanghai", {
        initialSearch: "?page=3",
        notices: [sampleNotice("1"), sampleNotice("2"), sampleNotice("3")],
        receipts: [
          { noticeId: "1", userId: "u1", readAt: "2026-10-22T02:00:00Z" },
          { noticeId: "1", userId: "u2", readAt: null },
          { noticeId: "2", userId: "u1", readAt: null },
          { noticeId: "3", userId: "u3", readAt: null },
        ],
      });
      const table = page.getByRole("table", { name: "通知列表记录", exact: true });
      const recipient = table.getByRole("combobox", { name: "接收人筛选", exact: true });
      const unread = table.getByRole("combobox", { name: "未完成人员筛选", exact: true });
      const expectNotices = ids => page.waitForFunction(expected => {
        const actual = [...document.querySelectorAll('.notification-record-row [data-notice-id]')].map(node => node.dataset.noticeId).sort();
        return JSON.stringify(actual) === JSON.stringify(expected);
      }, ids.sort());
      try {
        await recipient.fill("ZS");
        await page.getByRole("option", { name: "张三 · 研发部 / 产品组", exact: true }).click();
        await expectNotices(["1", "2"]);
        assert.equal(state.queries.at(-1).params.page, "1", "selecting a person resets pagination");
        assert.equal(await recipient.inputValue(), "张三", "selected people display only their name");
        assert.equal(new URL(page.url()).searchParams.get("recipientUserId"), "u1");
        await unread.fill("lisi");
        await page.getByRole("option", { name: "李四 · 产品组", exact: true }).click();
        await expectNotices(["1"]);
        assert.equal(await unread.inputValue(), "李四", "unread filter omits department after selection");
        const cells = table.locator("tbody tr.notification-record-row").getByRole("cell");
        assert.equal(await cells.nth(6).innerText(), "");
        assert.equal(await cells.nth(7).innerText(), "");
        await unread.fill("张三");
        await page.getByRole("option", { name: "张三 · 研发部 / 产品组", exact: true }).click();
        await expectNotices(["2"]);
        await page.reload();
        await expectNotices(["2"]);
        assert.equal(await recipient.inputValue(), "张三");
        assert.equal(await unread.inputValue(), "张三");
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}notice-person-selected-${width}.png` });
        await unread.fill("没有此人员");
        await page.getByText("无匹配选项", { exact: true }).waitFor();
        await page.keyboard.press("Escape");
        assert.equal(new URL(page.url()).searchParams.get("unreadUserId"), "u1", "cancelling search keeps the selected person");
        assert.equal(await unread.inputValue(), "张三");
        await page.getByRole("button", { name: "清空接收人筛选", exact: true }).click();
        assert.equal(await recipient.inputValue(), "");
        await unread.fill("U3");
        const option = page.getByRole("option", { name: "王五 · 销售部", exact: true });
        await option.waitFor();
        const bounds = await option.boundingBox();
        assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width, "person choices stay inside the viewport");
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}notice-person-menu-${width}.png` });
        await page.keyboard.press("Enter");
        await expectNotices(["3"]);
        assert.equal(state.queries.at(-1).params.recipientUserId, undefined);
        assert.equal(state.queries.at(-1).params.unreadUserId, "u3");
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}notice-person-filter-${width}.png` });
        await page.getByRole("button", { name: "清除筛选", exact: true }).click();
        await expectNotices(["1", "2", "3"]);
        assert.equal(new URL(page.url()).search, "");
        await page.getByRole("tab", { name: "我的通知", exact: true }).click();
        await page.getByText("你还没有收到通知", { exact: true }).waitFor();
        assert.equal(await recipient.count(), 0);
        assert.equal(await unread.count(), 0);
        assert.equal(state.queries.at(-1).params.recipientUserId, undefined);
        assert.equal(state.queries.at(-1).params.unreadUserId, undefined);
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    await t.test("column filters preserve query, date range, category and status through refresh and clear", async () => {
      const { context, page, state, errors } = await fixture(1440, "Asia/Shanghai", { notices: [sampleNotice()] });
      try {
        const filters = page.getByRole("row", { name: "通知列表列筛选", exact: true });
        await filters.getByRole("searchbox", { name: "按通知标题搜索", exact: true }).fill("部门通知");
        const category = filters.getByRole("combobox", { name: "通知分类", exact: true });
        await category.fill("工作");
        await page.getByRole("option", { name: "工作安排", exact: true }).click();
        await filters.getByLabel("开始日期", { exact: true }).fill("2026-10-01");
        await filters.getByLabel("结束日期", { exact: true }).fill("2026-10-31");
        await filters.getByRole("combobox", { name: "发布状态", exact: true }).click();
        const request = page.waitForRequest(value => {
          const url = new URL(value.url());
          return url.pathname === "/api/org/notices" && url.searchParams.get("status") === "published" && url.searchParams.get("dateTo") === "2026-10-31";
        });
        await page.getByRole("option", { name: "已发布", exact: true }).click();
        const sentRequest = await request;
        await sentRequest.response();
        const query = state.queries.at(-1).params;
        assert.equal(query.keyword, "部门通知");
        assert.equal(query.categoryId, "2");
        assert.equal(query.dateFrom, "2026-10-01");
        assert.equal(query.dateTo, "2026-10-31");
        assert.equal(query.status, "published");
        assert.equal(query.page, "1");
        assert.equal(new URL(page.url()).searchParams.get("q"), "部门通知");
        const refreshed = page.waitForResponse(value => value.url().includes("/api/org/notices?") && new URL(value.url()).searchParams.get("status") === "published");
        await page.getByRole("button", { name: "刷新通知记录", exact: true }).click();
        await refreshed;
        await filters.waitFor();
        assert.equal(await filters.getByRole("searchbox", { name: "按通知标题搜索", exact: true }).inputValue(), "部门通知");
        assert.equal(await filters.getByRole("combobox", { name: "通知分类", exact: true }).inputValue(), "工作安排");
        const cleared = page.waitForRequest(value => {
          const url = new URL(value.url());
          return url.pathname === "/api/org/notices" && !url.searchParams.has("keyword") && !url.searchParams.has("categoryId") && !url.searchParams.has("dateFrom") && !url.searchParams.has("status");
        });
        await page.getByRole("button", { name: "清除筛选", exact: true }).click();
        await cleared;
        assert.equal(new URL(page.url()).search, "");
        await page.getByRole("tab", { name: "我的通知", exact: true }).click();
        await page.getByText("你还没有收到通知", { exact: true }).waitFor();
        assert.equal(await page.getByRole("row", { name: "通知列表列筛选", exact: true }).getByRole("cell").count(), 5);
        assert.equal(await page.getByRole("combobox", { name: "发布状态", exact: true }).count(), 0);
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    for (const width of [1440, 1024]) await t.test(`${width}px edit, cancel and save keep the drawer visible without a second slide animation`, async () => {
      const { context, page, state, errors } = await fixture(width, "Asia/Shanghai", { notices: [sampleNotice()] });
      try {
        await page.emulateMedia({ reducedMotion: "no-preference" });
        await page.getByRole("button", { name: "部门通知 1", exact: true }).click();
        const original = page.getByRole("dialog", { name: "部门通知 1", exact: true });
        await original.waitFor();
        await page.waitForFunction(() => [...document.querySelector(".platform-detail-drawer-panel").getAnimations()].every(animation => animation.playState === "finished"));
        await page.evaluate(() => {
          const panel = document.querySelector(".platform-detail-drawer-panel");
          window.noticeEditTrace = [];
          window.noticeEditAnimations = [];
          window.noticeEditSample = () => {
            const current = document.querySelector(".platform-detail-drawer-panel");
            window.noticeEditTrace.push({ same: current === panel, count: document.querySelectorAll(".platform-detail-drawer-root").length, left: current?.getBoundingClientRect().left });
          };
          window.noticeEditObserver = new MutationObserver(window.noticeEditSample);
          window.noticeEditObserver.observe(document.body, { childList: true, subtree: true, attributes: true });
          document.addEventListener("animationstart", event => { if (event.animationName === "platform-detail-drawer-in") window.noticeEditAnimations.push(event.animationName); });
          window.noticeEditSample();
        });
        await original.getByRole("button", { name: "编辑", exact: true }).click();
        const editor = page.getByRole("dialog", { name: "编辑通知", exact: true });
        const title = editor.getByRole("textbox", { name: "通知标题", exact: false });
        await title.waitFor();
        await page.waitForFunction(() => document.activeElement?.id === "notification-title-input");
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}notice-inline-edit-${width}.png` });
        await title.fill("未保存的标题");
        await editor.getByRole("button", { name: "取消", exact: true }).click();
        const confirmation = page.getByRole("alertdialog", { name: "是否放弃修改", exact: true });
        await confirmation.getByRole("button", { name: "继续编辑", exact: true }).click();
        assert.equal(await title.inputValue(), "未保存的标题");
        await editor.getByRole("button", { name: "取消", exact: true }).click();
        await confirmation.getByRole("button", { name: "确认放弃", exact: true }).click();
        await original.getByRole("region", { name: "通知内容", exact: true }).waitFor();
        assert.equal(await original.getByRole("region", { name: "通知内容", exact: true }).getByRole("definition").first().textContent(), "部门通知 1");
        await original.getByRole("button", { name: "编辑", exact: true }).click();
        await title.fill("修改后的通知");
        await editor.getByRole("textbox", { name: "通知正文", exact: true }).fill("修改后的正文");
        state.failSave = true;
        await editor.getByRole("button", { name: "保存", exact: true }).click();
        await editor.getByRole("alert").filter({ hasText: "保存失败" }).waitFor();
        assert.equal(await title.inputValue(), "修改后的通知");
        state.failSave = false;
        await editor.getByRole("button", { name: "保存", exact: true }).click();
        const updated = page.getByRole("dialog", { name: "修改后的通知", exact: true });
        await updated.getByRole("region", { name: "通知内容", exact: true }).getByText("修改后的正文", { exact: true }).waitFor();
        await page.waitForFunction(() => document.activeElement?.textContent === "编辑");
        const trace = await page.evaluate(() => {
          window.noticeEditObserver.disconnect();
          return { frames: window.noticeEditTrace, animations: window.noticeEditAnimations };
        });
        assert.ok(trace.frames.length > 0);
        assert.ok(trace.frames.every(frame => frame.same && frame.count === 1 && Math.abs(frame.left - width / 2) < 1), "the original drawer remains visible at the same position for every observed update");
        assert.deepEqual(trace.animations, [], "editing, cancelling and saving never restart the slide animation");
        await updated.getByRole("button", { name: "关闭通知详情", exact: true }).click();
        await page.waitForFunction(() => document.activeElement?.dataset.noticeId === "1");
        assert.equal(await page.getByRole("dialog").count(), 0);
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    for (const status of ["published", "withdrawn", "expired"]) await t.test(`${status}: save keeps reads, confirmed republication clears them and a failed publication keeps input`, async () => {
      const { context, page, state, errors } = await fixture(1440, "Asia/Shanghai", {
        notices: [sampleNotice("1", { status, recipientCount: 2, unreadCount: 1 })],
        receipts: [{ noticeId: "1", userId: "u1", readAt: "2026-10-22T02:00:00Z" }],
      });
      try {
        await page.getByRole("button", { name: "部门通知 1", exact: true }).click();
        const detail = page.getByRole("dialog", { name: "部门通知 1", exact: true });
        await detail.getByRole("button", { name: "编辑", exact: true }).click();
        const editor = page.getByRole("dialog", { name: "编辑通知", exact: true });
        const save = editor.getByRole("button", { name: "保存", exact: true });
        const republish = editor.getByRole("button", { name: "保存并重新发布", exact: true });
        await republish.waitFor();
        assert.equal(await save.count(), 1);
        assert.equal(await editor.getByRole("button", { name: "保存并发布", exact: true }).count(), 0);
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}notice-save-actions-${status}.png` });
        await republish.click();
        const confirm = page.getByRole("alertdialog", { name: "重新发布通知", exact: true });
        await confirm.getByText(/清空所有接收人的已读、确认或接受状态/).waitFor();
        await confirm.getByRole("button", { name: "继续编辑", exact: true }).click();
        assert.equal(state.writes.length, 0, "cancelling republication saves nothing and clears no reads");
        await save.click();
        await detail.getByRole("button", { name: "编辑", exact: true }).waitFor();
        assert.equal(state.writes.filter(item => item.publish).length, 0);
        assert.equal(state.notices[0].status, status);
        assert.equal(state.notices[0].unreadCount, 1);
        assert.ok(state.receipts[0].readAt);
        await detail.getByRole("button", { name: "编辑", exact: true }).click();
        state.failMutation = true;
        await republish.click();
        await confirm.getByRole("button", { name: "保存并重新发布", exact: true }).click();
        await editor.getByRole("alert").filter({ hasText: "操作失败" }).waitFor();
        assert.equal(await editor.getByRole("textbox", { name: "通知标题", exact: false }).inputValue(), "部门通知 1");
        assert.ok(state.receipts[0].readAt);
        state.failMutation = false;
        await republish.click();
        await confirm.getByRole("button", { name: "保存并重新发布", exact: true }).click();
        await detail.getByRole("tab", { name: "已读情况", exact: true }).waitFor();
        assert.equal(state.writes.filter(item => item.publish).at(-1).resetRead, true);
        assert.equal(state.notices[0].status, "published");
        assert.equal(state.notices[0].unreadCount, 2);
        assert.equal(state.receipts[0].readAt, null);
        await detail.getByText("未读 2 / 接收 2 人", { exact: true }).waitFor();
        await detail.getByRole("tab", { name: "通知详情", exact: true }).click();
        await detail.getByRole("region", { name: "通知内容", exact: true }).getByText("请按通知安排执行。", { exact: true }).waitFor();
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    await t.test("detail actions confirm, preserve failures, refresh state and close after deletion", async () => {
      const { context, page, state, errors } = await fixture(1440, "Asia/Shanghai", { notices: [sampleNotice("1", { status: "draft" })] });
      try {
        await page.getByRole("button", { name: "部门通知 1", exact: true }).click();
        const detail = page.getByRole("dialog", { name: "部门通知 1", exact: true });
        const confirm = page.getByRole("alertdialog");
        await detail.getByRole("button", { name: "发布", exact: true }).click();
        await page.keyboard.press("Escape");
        await detail.waitFor();
        assert.equal(state.writes.length, 0);
        state.failMutation = true;
        await detail.getByRole("button", { name: "发布", exact: true }).click();
        await confirm.getByRole("button", { name: "发布", exact: true }).click();
        await detail.getByRole("alert").filter({ hasText: "操作失败" }).waitFor();
        state.failMutation = false;
        await detail.getByRole("button", { name: "发布", exact: true }).click();
        await confirm.getByRole("button", { name: "发布", exact: true }).click();
        await detail.getByRole("cell", { name: "张三", exact: true }).waitFor();
        assert.equal(await page.getByRole("dialog").count(), 1, "publication reuses the detail drawer");
        assert.equal(await detail.getByRole("tab", { name: "已读情况", exact: true }).getAttribute("aria-selected"), "true");
        await detail.getByRole("button", { name: "撤回", exact: true }).click();
        await confirm.getByRole("button", { name: "撤回", exact: true }).click();
        await detail.getByRole("button", { name: "重新发布", exact: true }).waitFor();
        assert.equal(await detail.locator("header").getByText("已撤回", { exact: true }).count(), 1);
        await detail.getByRole("button", { name: "删除", exact: true }).click();
        await page.keyboard.press("Escape");
        assert.equal(state.writes.filter(item => item.delete).length, 0);
        state.failMutation = true;
        await detail.getByRole("button", { name: "删除", exact: true }).click();
        await confirm.getByRole("button", { name: "永久删除", exact: true }).click();
        await detail.getByRole("alert").filter({ hasText: "操作失败" }).waitFor();
        state.failMutation = false;
        await detail.getByRole("button", { name: "删除", exact: true }).click();
        await confirm.getByRole("button", { name: "永久删除", exact: true }).click();
        await page.getByText("没有符合筛选条件的通知", { exact: true }).waitFor();
        assert.equal(await detail.count(), 0);
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    await t.test("late recipient responses cannot populate another notification", async () => {
      const { context, page, state, errors } = await fixture(1440, "Asia/Shanghai", { notices: [sampleNotice(), sampleNotice("2")], holdReaders: true });
      try {
        await page.getByRole("button", { name: "部门通知 1", exact: true }).click();
        await page.getByRole("tab", { name: "已读情况", exact: true }).click();
        await page.getByText("正在加载阅读名单…", { exact: true }).waitFor();
        while (!state.releaseReaders) await new Promise(resolve => setTimeout(resolve, 10));
        await page.getByRole("button", { name: "关闭通知详情", exact: true }).click();
        state.holdReaders = false;
        await page.getByRole("button", { name: "部门通知 2", exact: true }).click();
        const detail = page.getByRole("dialog", { name: "部门通知 2", exact: true });
        await detail.getByRole("tab", { name: "已读情况", exact: true }).click();
        await detail.getByRole("cell", { name: "张三", exact: true }).waitFor();
        const response = page.waitForResponse(value => value.url().includes("/notices/1/recipients"));
        state.releaseReaders(); await response;
        await page.waitForTimeout(100);
        assert.equal(await detail.getByText("旧名单人员", { exact: true }).count(), 0);
        assert.equal(await detail.getByRole("cell", { name: "张三", exact: true }).count(), 1);
        assert.deepEqual(errors, []);
      } finally { state.releaseReaders?.(); await context.close(); }
    });
    for (const publisher of [false, true]) await t.test(`${publisher ? "publisher" : "regular recipient"} sees content without others' reader lists or management actions`, async () => {
      const received = sampleNotice();
      delete received.recipientSelection; delete received.recipientCount; delete received.unreadCount;
      const { context, page, state, errors } = await fixture(1440, "Asia/Shanghai", { capability: { canManage: false, canPublish: publisher }, history: [received] });
      try {
        if (publisher) await page.getByRole("tab", { name: "我的通知", exact: true }).click();
        await page.getByRole("cell", { name: "制度通知", exact: true }).click();
        const detail = page.getByRole("dialog", { name: "部门通知 1", exact: true });
        await detail.getByRole("tabpanel", { name: "通知详情", exact: true }).waitFor();
        assert.equal(await detail.getByRole("tab", { name: "已读情况", exact: true }).count(), 0);
        for (const name of ["编辑", "发布", "重新发布", "撤回", "删除"]) assert.equal(await detail.getByRole("button", { name, exact: true }).count(), 0);
        assert.equal(state.readerRequests.length, 0);
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    for (const width of [1440, 1024]) await t.test(`${width}px notification levels default, persist and require republication to change`, async () => {
      const { context, page, state, errors } = await fixture(width);
      try {
        await page.getByRole("button", { name: "新建通知", exact: true }).click();
        let editor = page.getByRole("dialog", { name: "新建通知", exact: true });
        const picker = () => editor.getByRole("combobox", { name: "通知等级", exact: true });
        assert.match(await picker().inputValue(), /普通通知/);
        await picker().click();
        await page.getByRole("option", { name: "确认", exact: true }).click();
        await editor.getByRole("textbox", { name: "通知标题", exact: true }).fill("需要确认的通知");
        await editor.getByRole("textbox", { name: "通知正文", exact: true }).fill("请确认已经知晓。");
        await choosePeople(page);
        await editor.getByRole("button", { name: "保存并发布", exact: true }).click();
        let detail = page.getByRole("dialog", { name: "需要确认的通知", exact: true });
        await detail.getByRole("tab", { name: "确认情况", exact: true }).waitFor();
        assert.equal(state.writes.find(item => item.payload).payload.level, "confirm");
        await detail.getByRole("button", { name: "未确认", exact: true }).waitFor();
        await detail.getByRole("button", { name: "编辑", exact: true }).click();
        editor = page.getByRole("dialog", { name: "编辑通知", exact: true });
        assert.match(await picker().inputValue(), /确认/);
        await picker().click();
        await page.getByRole("option", { name: "确认并接受", exact: true }).click();
        await editor.getByText("确认声明：本人已阅读并知晓本次通知的全部内容，并同意按通知要求执行相关规定", { exact: true }).waitFor();
        assert.equal(await editor.getByRole("button", { name: "保存", exact: true }).isDisabled(), true);
        await editor.getByText("修改通知等级后，请保存并重新发布。", { exact: true }).waitFor();
        await editor.getByRole("button", { name: "保存并重新发布", exact: true }).click();
        await page.getByRole("alertdialog", { name: "重新发布通知", exact: true }).getByRole("button", { name: "保存并重新发布", exact: true }).click();
        await detail.getByRole("tab", { name: "接受情况", exact: true }).waitFor();
        assert.equal(state.writes.filter(item => item.payload).at(-1).payload.level, "confirm", "PATCH retains the active level until publication succeeds");
        assert.equal(state.writes.filter(item => item.publish).at(-1).level, "accept");
        state.confirmation = { userId: "u1", name: "张三", actorUserId: "u1", level: "accept", confirmedAt: "2026-10-23T07:00:00Z", statement: "本人已阅读并知晓本次通知的全部内容并同意按通知要求执行", enteredStatement: "我已阅读并接受通知内容", contentSnapshot: { title: "确认时的标题", contentHtml: "<p>确认时的正文</p>", attachments: [{ id: "a1", name: "确认时的附件.pdf" }] } };
        await detail.getByRole("button", { name: "已接受", exact: true }).click();
        await detail.getByText("确认记录", { exact: true }).click();
        await detail.getByText("我已阅读并接受通知内容", { exact: true }).waitFor();
        await detail.getByText("确认时的正文", { exact: true }).waitFor();
        await detail.getByText("确认时的附件.pdf", { exact: true }).waitFor();
        await page.screenshot({ path: `${artifacts}${external ? "deployed-" : ""}confirmation-record-${width}.png` });
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    await t.test("empty expiry saves, round-trips, can be set and cleared, and publishes", async () => {
      const { context, page, state, errors } = await fixture();
      try {
        await page.getByRole("button", { name: "新建通知", exact: true }).click();
        let editor = page.getByRole("dialog", { name: "新建通知", exact: true });
        await editor.getByRole("textbox", { name: "通知标题", exact: true }).fill("长期通知");
        await editor.getByRole("textbox", { name: "通知正文", exact: true }).fill("日期留空时长期有效。");
        await choosePeople(page);
        await editor.getByRole("button", { name: "保存", exact: true }).click();
        await page.getByRole("button", { name: "长期通知", exact: true }).click();
        let detail = page.getByRole("dialog", { name: "长期通知", exact: true });
        await detail.waitFor();
        assert.equal(state.writes[0].payload.expiresAt, "");
        await detail.getByText("长期有效", { exact: true }).waitFor();
        await detail.getByRole("button", { name: "编辑", exact: true }).click();
        editor = page.getByRole("dialog", { name: "编辑通知", exact: true });
        assert.equal(await editor.getByLabel("到期日期", { exact: true }).inputValue(), "");
        assert.equal(await editor.getByRole("region", { name: "通知内容", exact: true }).getByRole("textbox", { name: "通知标题", exact: true }).inputValue(), "长期通知");
        await editor.getByLabel("到期日期", { exact: true }).fill("2099-03-01");
        await editor.getByRole("button", { name: "保存", exact: true }).click();
        await detail.waitFor();
        assert.equal(state.writes.at(-1).payload.expiresAt, "2099-03-01");
        await detail.getByRole("button", { name: "编辑", exact: true }).click();
        assert.equal(await editor.getByLabel("到期日期", { exact: true }).inputValue(), "2099-03-01");
        await editor.getByLabel("到期日期", { exact: true }).fill("");
        await editor.getByRole("button", { name: "保存并发布", exact: true }).click();
        await detail.waitFor();
        assert.equal(state.writes.filter(item => item.payload).at(-1).payload.expiresAt, "");
        assert.equal(state.writes.filter(item => item.publish).length, 1);
        await detail.getByRole("tab", { name: "通知详情", exact: true }).click();
        await detail.getByText("长期有效", { exact: true }).waitFor();
        await detail.getByRole("button", { name: "编辑", exact: true }).click();
        assert.equal(await editor.getByLabel("到期日期", { exact: true }).inputValue(), "");
        assert.equal(await editor.getByRole("button", { name: "保存并重新发布", exact: true }).count(), 1);
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    await t.test("date-only expiry allows today in Beijing and round-trips across browser timezones", async () => {
      const { context, page, state, errors } = await fixture(1440, "America/Los_Angeles");
      try {
        await page.clock.install({ time: new Date("2099-02-28T17:00:00Z") });
        await page.getByRole("button", { name: "新建通知", exact: true }).click();
        const dialog = page.getByRole("dialog", { name: "新建通知", exact: true });
        await dialog.getByRole("textbox", { name: "通知标题", exact: false }).fill("当天到期通知");
        await choosePeople(page);
        await dialog.getByRole("textbox", { name: "通知正文", exact: true }).fill("当日有效至北京时间次日零点。");
        await dialog.getByLabel("到期日期", { exact: false }).fill("2099-02-28");
        await dialog.getByRole("button", { name: "保存", exact: true }).click();
        await dialog.getByText("到期日期不能早于今天", { exact: true }).first().waitFor();
        assert.equal(state.writes.length, 0);
        await dialog.getByLabel("到期日期", { exact: false }).fill("2099-03-01");
        await dialog.getByRole("button", { name: "保存", exact: true }).click();
        await page.getByRole("button", { name: "当天到期通知", exact: true }).waitFor();
        assert.equal(state.writes[0].payload.expiresAt, "2099-03-01");
        await page.getByRole("cell", { name: "2099-03-01", exact: true }).waitFor();
        await page.getByRole("cell", { name: "2099-03-01", exact: true }).click();
        await page.getByRole("button", { name: "编辑", exact: true }).click();
        const edit = page.getByRole("dialog", { name: "编辑通知", exact: true });
        await page.waitForFunction(() => document.activeElement?.id === "notification-title-input");
        assert.equal(await page.locator("body").evaluate(node => node.classList.contains("platform-detail-drawer-open")), true);
        assert.equal(await edit.getByLabel("到期日期", { exact: false }).inputValue(), "2099-03-01");
        await edit.getByRole("button", { name: "关闭通知编辑器", exact: true }).click();
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    });
    await t.test("save/upload failures keep input; retry publishes once and locks recipients", async () => {
      const { context, page, state, errors } = await fixture();
      try {
        await page.getByRole("button", { name: "新建通知", exact: true }).click();
        let dialog = page.getByRole("dialog", { name: "新建通知", exact: true });
        await page.getByRole("textbox", { name: "通知标题", exact: false }).fill("会议安排");
        await dialog.getByLabel("到期日期", { exact: false }).fill("2099-02-28");
        await choosePeople(page);
        const editor = dialog.getByRole("textbox", { name: "通知正文", exact: true });
        await editor.fill("请准时参加会议");
        await editor.press("ArrowRight");
        await editor.evaluate(node => {
          const canvas = document.createElement("canvas"); canvas.width = 4; canvas.height = 3;
          canvas.getContext("2d").fillRect(0,0,4,3);
          const source = canvas.toDataURL("image/png");
          const bytes = Uint8Array.from(atob(source.split(",")[1]), character => character.charCodeAt(0));
          const data = new DataTransfer(); data.items.add(new File([bytes], "正文图片.png", { type: "image/png" }));
          node.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
        });
        await editor.locator("img").waitFor();
        await dialog.locator("#notification-attachments").setInputFiles({ name: "会议安排.txt", mimeType: "text/plain", buffer: Buffer.from("会议") });
        state.failUpload = true;
        await dialog.getByRole("button", { name: "保存并发布", exact: true }).click();
        dialog = page.getByRole("dialog", { name: "编辑通知", exact: true });
        await dialog.getByRole("alert").filter({ hasText: "附件上传失败" }).waitFor();
        assert.equal(await page.getByRole("textbox", { name: "通知标题", exact: false }).inputValue(), "会议安排");
        assert.equal(await dialog.getByRole("button", { name: "打开附件：会议安排.txt" }).count(), 1);
        assert.equal(state.writes.filter(item => item.publish).length, 0);
        state.failUpload = false; state.failSave = true;
        await dialog.getByRole("button", { name: "保存并发布", exact: true }).click();
        await dialog.getByRole("alert").filter({ hasText: "保存失败" }).waitFor();
        state.failSave = false; state.holdSave = true;
        await dialog.getByRole("button", { name: "保存并发布", exact: true }).click();
        await page.waitForFunction(() => document.querySelector('[aria-label="关闭通知编辑器"]')?.disabled);
        await page.keyboard.press("Escape");
        assert.equal(await dialog.count(), 1);
        assert.equal(await dialog.getByRole("button", { name: "正在提交", exact: true }).isDisabled(), true);
        state.holdSave = false; state.releaseSave();
        await page.getByRole("dialog", { name: "会议安排", exact: true }).waitFor();
        assert.equal(await page.getByRole("tab", { name: "已读情况", exact: true }).getAttribute("aria-selected"), "true");
        assert.equal(state.writes.filter(item => item.method === "POST" && !item.upload && !item.publish).length, 1);
        assert.equal(state.writes.filter(item => item.publish).length, 1);
        assert.equal(state.writes.find(item => item.publish).resetRead, undefined);
        const payload = state.writes[0].payload;
        assert.equal(payload.expiresAt, "2099-02-28", "save sends a calendar date without time");
        assert.deepEqual(payload.recipientSelection.departments.map(item => item.deptId).sort(), [1,2]);
        assert.deepEqual(payload.recipientSelection.people.sort(), ["u1", "u3"]);
        await page.getByRole("button", { name: "已读", exact: true }).click();
        await page.getByRole("cell", { name: /已读/ }).waitFor();
        state.failReaders = true;
        await page.getByRole("button", { name: "未读", exact: true }).click();
        await page.getByRole("alert").filter({ hasText: "阅读名单加载失败" }).waitFor();
        state.failReaders = false;
        await page.getByRole("button", { name: "重试", exact: true }).click();
        await page.getByRole("cell", { name: "张三", exact: true }).waitFor();
        await page.getByRole("button", { name: "编辑", exact: true }).click();
        dialog = page.getByRole("dialog", { name: "编辑通知", exact: true });
        await dialog.getByRole("combobox", { name: "搜索部门名称、ID 或拼音", exact: true }).waitFor();
        assert.equal(await dialog.getByRole("combobox", { name: "搜索部门名称、ID 或拼音", exact: true }).isDisabled(), true);
        assert.deepEqual(await dialog.getByRole("group", { name: "通知人员", exact: true }).locator(".starter-detail-chip > span").allTextContents(), ["王五", "张三"]);
        assert.equal(await dialog.getByRole("group", { name: "通知部门", exact: true }).getByText("含下级", { exact: true }).count(), 2, "frozen audience still shows descendant scope");
        assert.equal(await dialog.getByLabel("到期日期", { exact: false }).inputValue(), "2099-02-28", "exclusive midnight is shown as the selected day");
        await dialog.getByRole("link", { name: "会议安排.txt", exact: true }).waitFor();
        await dialog.getByRole("button", { name: "移除附件：会议安排.txt", exact: true }).click();
        await page.getByRole("button", { name: "确认", exact: true }).click();
        await page.waitForFunction(() => !document.querySelector('.platform-attachment-list'));
        assert.equal(state.writes.filter(item => item.deleteAttachment).length, 1);
        await dialog.getByRole("button", { name: "保存", exact: true }).click();
        const detail = page.getByRole("dialog", { name: "会议安排", exact: true });
        await detail.waitFor();
        assert.equal(await detail.getByText("2099-02-28", { exact: true }).count(), 1);
        const image = detail.getByRole("button", { name: "查看图片原图", exact: true });
        await image.waitFor();
        await image.click();
        await page.getByRole("dialog", { name: "图片预览", exact: true }).waitFor();
        await page.keyboard.press("Escape");
        assert.equal(await detail.count(), 1, "closing image preview keeps notice drawer open");
        await page.getByRole("button", { name: "关闭通知详情", exact: true }).click();
        await page.getByRole("tab", { name: "我的通知", exact: true }).click();
        await page.getByText("你还没有收到通知", { exact: true }).waitFor();
        assert.ok(state.queries.some(item => item.history));
        assert.deepEqual(errors, []);
      } finally { state.releaseSave?.(); await context.close(); }
    });
  } finally { await browser.close(); if (server) await server.close(); }
});
