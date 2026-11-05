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

test("settlement pagination, partial receipts, later invoices, correction and conflict recovery", { timeout: 180000 }, async () => {
  const server = await createServer({ root, configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-finance"),
    server: { host: "127.0.0.1", port: 0 } });
  let browser, nextId = 10, conflictNext = false, conflictAlreadyApplied = false, conflictInvoiceAmount = null;
  const writes = [], requests = [], records = new Map();
  const sources = Array.from({ length: 105 }, (_, index) => ({
    id: index + 1, sourceNodeId: index + 1, nodeName: index % 2 ? "预算匹配" : "前期方案",
    projectId: index + 1, projectName: "结算项目" + (index + 1), projectCode: "FIN-" + (index + 1),
    customer: "学校客户", ownerName: "项目负责人", serviceType: "midsales", serviceTypeLabel: "售中服务",
    estimatedFee: "800.00", actualFee: "1000.00", externalQuote: "1500.00", serviceContent: "方案与技术服务",
    available: true, settlement: null,
  }));
  sources[3].externalQuote = "0.80";
  sources[0].customer = "学校甲"; sources[0].ownerName = "张经理";
  sources[1].customer = "结算项目1"; sources[1].ownerName = "学校甲";
  function event(record, kind, before = {}, reason = "") {
    return { id: record.revision, revision: record.revision, kind, createdAt: "2026-10-15T02:00:00+00:00",
      operatorName: "财务经办人", createdBy: "finance", createdActorId: "finance", reason,
      receiptDelta: Number(record.receivedAmount) - Number(before.receivedAmount || 0),
      invoiceDelta: Number(record.invoicedAmount) - Number(before.invoicedAmount || 0),
      before: { received_amount: before.receivedAmount, invoiced_amount: before.invoicedAmount },
      after: { received_amount: record.receivedAmount, invoiced_amount: record.invoicedAmount, invoice_number: record.invoiceNumber, status: record.status } };
  }
  function normalize(record) {
    ["receivedAmount", "invoicedAmount", "orderAmount", "invoiceDueAmount"].forEach(field => record[field] = Number(record[field] || 0).toFixed(2));
    record.remainingReceivable = (Number(record.orderAmount) - Number(record.receivedAmount)).toFixed(2);
    record.remainingInvoice = (Number(record.invoiceDueAmount) - Number(record.invoicedAmount)).toFixed(2);
    return record;
  }
  const companyRecord = normalize({ id: 2, code: "SET-COMPANY", revision: 1, sourceNodeId: 2, projectId: 2,
    serviceType: "midsales", bearer: "company", subjectType: "company", subjectId: "17", subjectName: "平台主体",
    status: "settled", budgetAmount: "800.00", finalAmount: "1000.00", orderAmount: "1000.00", externalQuote: "1500.00", events: [] });
  companyRecord.events.push({ id: 201, revision: 1, kind: "opening", createdAt: "2026-09-15T08:04:07+00:00",
    operatorName: "", createdBy: "legacy-finance", receiptDelta: "0.00", invoiceDelta: "0.00", before: {},
    reason: "升级前的历史汇总余额，非本次新增收款或开票；原始逐笔流水未记录。",
    after: { status: "settled", subject_type: "company", subject_name: "平台主体", subject_id: "", related_project_id: null,
      invoice_number: "", received_amount: "0.00", invoiced_amount: "0.00" } });
  records.set(2, companyRecord); sources[1].settlement = companyRecord;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => sessionStorage.setItem("mj_program_login_session", JSON.stringify({ sessionId: "finance-browser", userId: "finance", name: "财务经办人", loginType: "scan" })));
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url()), method = route.request().method();
      const payload = ["POST", "PATCH"].includes(method) ? route.request().postDataJSON() : {};
      requests.push(url.pathname + url.search);
      let body = { items: [] }, status = 200;
      if (url.pathname === "/api/auth/session/validate") body = { sessionId: "finance-browser", userId: "finance", name: "财务经办人", loginType: "scan" };
      else if (url.pathname === "/api/after-sales/session/") body = { canManageApp: true, canManageSettings: true, appPermission: "admin" };
      else if (url.pathname === "/api/after-sales/settlement-sources") {
        const state = url.searchParams.get("state");
        const rows = sources.filter(source => {
          const record = source.settlement;
          return source.projectName.includes(url.searchParams.get("projectSearch") || "")
            && source.customer.includes(url.searchParams.get("customerSearch") || "")
            && source.ownerName.includes(url.searchParams.get("ownerSearch") || "")
            && (!url.searchParams.get("sourceNodeId") || String(source.id) === url.searchParams.get("sourceNodeId"))
            && (state === "all" || state === "available" && !record || state === "unsettled" && record && record.status !== "settled" || state === "settled" && record?.status === "settled");
        });
        const size = Number(url.searchParams.get("pageSize") || 20), totalPages = Math.max(1, Math.ceil(rows.length / size));
        const current = Math.min(totalPages, Number(url.searchParams.get("page") || 1));
        body = { items: rows.slice((current - 1) * size, current * size), page: current, pageSize: size, total: rows.length, totalPages, nodeNames: ["前期方案", "预算匹配"] };
      } else if (url.pathname === "/api/after-sales/settlement-companies") body = { items: [{ id: 17, companyName: "平台主体", pinyin: "pingtaizhuti", pinyinInitials: "ptzt" }] };
      else if (url.pathname === "/api/after-sales/employees/directory") body = { items: [
        { userId: "employee-exact", name: "江松阳", pinyin: "jiangsongyang", pinyinInitials: "jsy", departments: [{ name: "技术部" }] },
        { userId: "other", name: "江松阳", pinyin: "jiangsongyang", pinyinInitials: "jsy", departments: [{ name: "业务部" }] },
        { userId: "legacy-finance", name: "历史财务", departments: [{ name: "财务部" }] },
      ] };
      else if (url.pathname === "/api/after-sales/settlement-projects") {
        body = { items: url.searchParams.get("userId") === "employee-exact" ? [{ id: 3, name: "人员专属项目", customer: "学校", serviceTypeLabel: "售前" }] : [], totalPages: 1, page: 1 };
      } else if (url.pathname === "/api/after-sales/settlements" && method === "POST") {
        writes.push(payload);
        const source = sources.find(source => source.id === payload.sourceNodeId);
        const record = normalize({ ...payload, id: nextId++, code: "SET-TEST", revision: 1,
          projectId: source.projectId, projectName: source.projectName, serviceType: source.serviceType,
          externalQuote: source.externalQuote, budgetAmount: source.estimatedFee, finalAmount: source.actualFee,
          orderAmount: payload.bearer === "customer" ? source.externalQuote : source.actualFee,
          invoiceDueAmount: payload.bearer === "customer" ? source.externalQuote : 0, events: [] });
        record.events.push(event(record, "created")); source.settlement = record; records.set(record.id, record);
        body = { item: record }; status = 201;
      } else if (url.pathname === "/api/after-sales/settlements") {
        body = { items: [...records.values()].filter(record => String(record.sourceNodeId) === url.searchParams.get("sourceNodeId")), page: 1, totalPages: 1 };
      } else if (/\/settlements\/\d+$/.test(url.pathname)) {
        const record = records.get(Number(url.pathname.split("/").at(-1)));
        if (method === "PATCH") {
          writes.push(payload);
          if (conflictNext) { record.revision++; record.remark = "财务同事补充"; conflictNext = false;
            if (conflictAlreadyApplied) { record.invoicedAmount = payload.invoicedAmount; normalize(record); conflictAlreadyApplied = false; }
            if (conflictInvoiceAmount !== null) { record.invoicedAmount = conflictInvoiceAmount; normalize(record); conflictInvoiceAmount = null; }
          }
          if (payload.expectedRevision !== record.revision) {
            status = 409; body = { code: "SETTLEMENT_REVISION_CONFLICT", error: "记录已被其他人更新，填写内容已保留" };
          } else {
            const before = { ...record };
            Object.assign(record, payload); record.revision++; normalize(record);
            record.events.unshift(event(record, payload.status === "cancelled" ? "cancelled" : payload.correctionReason ? "correction" : "invoice", before, payload.correctionReason));
            if (record.status === "cancelled") sources.find(source => source.id === record.sourceNodeId).settlement = null;
            body = { item: record };
          }
        } else body = { item: record };
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });

    const base = "http://127.0.0.1:" + server.httpServer.address().port;
    await page.goto(base + "/after-sales/");
    await page.getByRole("navigation", { name: "主导航" }).getByRole("button", { name: "结算中心" }).click().catch(async reason => {
      throw new Error(JSON.stringify({ pageErrors: errors, body: await page.locator("body").innerText() }), { cause: reason });
    });
    const table = page.getByRole("table", { name: "结算服务列表" });
    const row = id => table.getByRole("row").filter({ has: page.locator("td:first-child").getByText("结算项目" + id, { exact: true }) });
    await row(1).waitFor();
    await row(1).click();
    const drawer = page.getByRole("dialog", { name: "结算详情" });
    const detailsTab = drawer.getByRole("tab", { name: "结算详情", exact: true });
    const historyTab = drawer.getByRole("tab", { name: /版本与留痕/ });
    const audit = drawer.getByRole("region", { name: "结算版本与留痕" });
    const saveChanges = drawer.getByRole("button", { name: "保存修改", exact: true });
    const receivedTotal = drawer.getByRole("spinbutton", { name: "累计已收金额", exact: true });
    const invoicedTotal = drawer.getByRole("spinbutton", { name: "累计已开票金额", exact: true });
    assert.equal(await drawer.getByRole("button", { name: /恢复已保存|更正记录/ }).count(), 0);
    await drawer.getByRole("spinbutton", { name: "累计已收金额", exact: true }).fill("500");
    assert.equal(await drawer.getByRole("button", { name: "确认结清", exact: true }).isDisabled(), true);
    await historyTab.click();
    await drawer.getByText("暂无结算留痕", { exact: true }).waitFor();
    assert.equal(await drawer.getByRole("button", { name: "保存待结算", exact: true }).isVisible(), false);
    assert.equal(writes.length, 0);
    await historyTab.press("ArrowLeft");
    assert.equal(await detailsTab.getAttribute("aria-selected"), "true");
    assert.equal(await detailsTab.evaluate(element => element === document.activeElement), true);
    assert.equal(await drawer.getByRole("spinbutton", { name: "累计已收金额", exact: true }).inputValue(), "500");
    await page.evaluate(() => window.history.back());
    await page.getByRole("alertdialog").getByRole("button", { name: "继续编辑" }).click();
    assert.equal(await drawer.getByRole("spinbutton", { name: "累计已收金额", exact: true }).inputValue(), "500");
    await drawer.getByRole("button", { name: "关闭", exact: true }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "继续编辑" }).click();
    assert.equal(await drawer.getByRole("spinbutton", { name: "累计已收金额", exact: true }).inputValue(), "500");
    await drawer.getByRole("button", { name: "保存待结算", exact: true }).click();
    await saveChanges.waitFor();
    assert.equal(writes[0].status, "pending"); assert.equal(writes[0].receivedAmount, 500);
    const drawerScroller = drawer.locator(".el-drawer__body");
    const detailScrollTop = await drawerScroller.evaluate(element => { element.scrollTop = Math.min(160, element.scrollHeight - element.clientHeight); return element.scrollTop; });
    assert.ok(detailScrollTop > 0);
    await historyTab.click();
    await audit.getByRole("article", { name: "创建结算 · 版本 1", exact: true }).waitFor();
    assert.equal(await drawerScroller.evaluate(element => element.scrollTop), 0);
    assert.match(await audit.innerText(), /新增收款[\s\S]*\+￥500\.00/);
    assert.equal(await audit.getByText("新增开票", { exact: true }).count(), 0);
    await drawer.getByRole("button", { name: "返回结算详情", exact: true }).click();
    assert.ok(Math.abs(await drawerScroller.evaluate(element => element.scrollTop) - detailScrollTop) <= 1);
    await drawer.getByRole("button", { name: "关闭", exact: true }).click(); await drawer.waitFor({ state: "hidden" });
    await row(1).click();
    assert.equal(await receivedTotal.getAttribute("readonly"), null);
    assert.equal(await invoicedTotal.getAttribute("readonly"), null);
    await drawer.getByRole("spinbutton", { name: "本次收款金额", exact: true }).fill("1000");
    assert.equal(await receivedTotal.inputValue(), "1500");
    await drawer.getByRole("button", { name: "确认结清", exact: true }).click();
    await drawer.getByRole("spinbutton", { name: "本次收款金额", exact: true }).waitFor({ state: "hidden" });
    await drawer.getByRole("spinbutton", { name: "本次开票金额", exact: true }).fill("300");
    assert.equal(await invoicedTotal.inputValue(), "300");
    await drawer.getByRole("textbox", { name: "票据单号", exact: true }).fill("INV-A");
    await saveChanges.click();
    await page.waitForFunction(() => document.querySelector('input[placeholder="填写本次新增开票"]')?.value === "");
    assert.equal(records.get(10).invoicedAmount, "300.00");

    conflictNext = true;
    await drawer.getByRole("spinbutton", { name: "本次开票金额", exact: true }).fill("100");
    await saveChanges.click();
    const comparison = drawer.getByRole("region", { name: "结算版本核对" });
    await comparison.waitFor();
    assert.equal(await drawer.getByRole("spinbutton", { name: "本次开票金额", exact: true }).inputValue(), "100");
    await comparison.getByRole("button", { name: "已核对，保留本次修改" }).click();
    await saveChanges.click();
    await page.waitForFunction(() => document.querySelector('input[placeholder="填写本次新增开票"]')?.value === "");
    assert.equal(records.get(10).invoicedAmount, "400.00");
    assert.equal(records.get(10).remark, "财务同事补充");
    conflictNext = true; conflictAlreadyApplied = true;
    await drawer.getByRole("spinbutton", { name: "本次开票金额", exact: true }).fill("100");
    await saveChanges.click();
    await comparison.getByRole("button", { name: "已核对，保留本次修改" }).click();
    assert.equal(await drawer.getByRole("spinbutton", { name: "本次开票金额", exact: true }).inputValue(), "");
    await saveChanges.click();
    await saveChanges.waitFor({ state: "visible" });
    assert.equal(records.get(10).invoicedAmount, "500.00");
    await page.screenshot({ path: "/tmp/after-sales-settlement-finance-desktop.png", fullPage: true });
    await historyTab.click();
    const historyPanel = drawer.getByRole("tabpanel", { name: /版本与留痕/ });
    assert.equal(await historyPanel.evaluate(element => element.scrollWidth <= element.clientWidth), true);
    await page.screenshot({ path: "/tmp/after-sales-settlement-history-desktop.png", fullPage: true });
    await historyTab.press("Home");

    // Saved invoice metadata is directly editable; correcting it requests a reason automatically.
    await drawer.getByRole("textbox", { name: "票据单号", exact: true }).fill("INV-CORRECTED");
    await drawer.getByRole("textbox", { name: "更正原因", exact: true }).waitFor();
    const writesBeforeReason = writes.length;
    await saveChanges.click();
    await drawer.getByRole("alert").filter({ hasText: "请填写更正原因" }).waitFor();
    assert.equal(writes.length, writesBeforeReason);
    await drawer.getByRole("textbox", { name: "更正原因", exact: true }).fill("修正发票单号");
    await saveChanges.click();
    await drawer.getByRole("textbox", { name: "更正原因", exact: true }).waitFor({ state: "hidden" });
    assert.equal(records.get(10).invoiceNumber, "INV-CORRECTED");
    assert.equal(records.get(10).status, "settled");

    // A cumulative edit is retained across a revision conflict, even if the latest total is higher.
    await invoicedTotal.fill("450");
    await drawer.getByRole("textbox", { name: "更正原因", exact: true }).fill("核对累计开票金额");
    conflictNext = true; conflictInvoiceAmount = "550.00";
    await saveChanges.click();
    await comparison.getByRole("button", { name: "已核对，保留本次修改" }).click();
    assert.equal(await invoicedTotal.inputValue(), "450");
    await saveChanges.click();
    await drawer.getByRole("textbox", { name: "更正原因", exact: true }).waitFor({ state: "hidden" });
    assert.equal(records.get(10).invoicedAmount, "450.00");

    await receivedTotal.fill("1000");
    await drawer.getByText(/保存时将恢复为待结算/).waitFor();
    await drawer.getByRole("textbox", { name: "更正原因", exact: true }).fill("收款误录，恢复待结算");
    await saveChanges.click();
    await drawer.getByRole("spinbutton", { name: "本次收款金额", exact: true }).waitFor();
    assert.equal(records.get(10).receivedAmount, "1000.00"); assert.equal(records.get(10).status, "pending");
    await historyTab.click();
    assert.match(await audit.innerText(), /冲减收款[\s\S]*−￥500\.00/);
    await detailsTab.click();
    await drawer.getByRole("button", { name: "撤销记录", exact: true }).click();
    await drawer.getByRole("button", { name: "取消撤销", exact: true }).click();
    assert.equal(await drawer.getByRole("button", { name: "确认撤销", exact: true }).count(), 0);
    await drawer.getByRole("button", { name: "撤销记录", exact: true }).click();
    await drawer.getByRole("spinbutton", { name: "累计已收金额", exact: true }).fill("0");
    await drawer.getByRole("spinbutton", { name: "累计已开票金额", exact: true }).fill("0");
    await drawer.getByRole("textbox", { name: "撤销原因", exact: true }).fill("核对后冲回并撤销");
    await drawer.getByRole("button", { name: "确认撤销", exact: true }).click();
    await drawer.getByRole("button", { name: "确认撤销", exact: true }).waitFor({ state: "hidden" });
    assert.equal(records.get(10).status, "cancelled");
    assert.equal(await receivedTotal.isDisabled(), true);
    assert.equal(await invoicedTotal.isDisabled(), true);
    await drawer.getByRole("button", { name: "关闭", exact: true }).click(); await drawer.waitFor({ state: "hidden" });

    await row(1).click();
    await historyTab.click();
    await drawer.getByRole("button", { name: "SET-TEST · 已撤销", exact: true }).click();
    await audit.getByRole("heading", { name: "已撤销结算的留痕", exact: true }).waitFor();
    await audit.getByText("核对后冲回并撤销", { exact: true }).waitFor();
    assert.equal(await saveChanges.isVisible(), false);
    await drawer.getByRole("button", { name: "关闭", exact: true }).click(); await drawer.waitFor({ state: "hidden" });

    await row(2).click();
    const quoteField = drawer.locator(".as-field").filter({ has: page.getByText("对外报价", { exact: true }) });
    const costField = drawer.locator(".as-field").filter({ has: page.getByText("费用决算（实际成本）", { exact: true }) });
    assert.match(await quoteField.innerText(), /1,500/); assert.match(await costField.innerText(), /1,000/);
    await historyTab.click();
    await audit.getByText("历史财务", { exact: true }).waitFor();
    assert.match(await audit.innerText(), /2026\/09\/15 16:04:07/);
    assert.equal(await audit.getByText("新增收款", { exact: true }).count(), 0);
    await audit.getByText("查看期初记录", { exact: true }).click();
    assert.equal(await audit.getByRole("row").filter({ has: page.getByRole("rowheader", { name: "主体编号", exact: true }) }).count(), 0);
    assert.equal(await audit.getByRole("columnheader", { name: "变更前", exact: true }).count(), 0);
    await audit.getByText("经办账号：legacy-finance", { exact: true }).waitFor();
    await page.setViewportSize({ width: 1024, height: 768 });
    assert.equal(await audit.evaluate(element => element.scrollWidth <= element.clientWidth), true);
    await page.screenshot({ path: "/tmp/after-sales-settlement-opening-1024.png", fullPage: true });
    await page.setViewportSize({ width: 1440, height: 960 });
    await detailsTab.click();
    assert.equal(await drawer.getByLabel("承担主体类型").isEnabled(), true);
    assert.equal(await drawer.getByRole("combobox", { name: "具体公司" }).isEnabled(), true);
    await drawer.getByRole("textbox", { name: "结算说明", exact: true }).fill("补充成本归集说明");
    await drawer.getByRole("textbox", { name: "更正原因", exact: true }).fill("核对已结清归集说明");
    await saveChanges.click();
    await drawer.getByRole("textbox", { name: "更正原因", exact: true }).waitFor({ state: "hidden" });
    assert.equal(records.get(2).remark, "补充成本归集说明");
    assert.equal(records.get(2).status, "settled");
    await drawer.getByRole("button", { name: "关闭", exact: true }).click(); await drawer.waitFor({ state: "hidden" });

    await row(3).click();
    await drawer.getByLabel("费用承担方式").selectOption("company");
    await drawer.getByLabel("承担主体类型").selectOption("person");
    await drawer.getByRole("button", { name: /^承担人员：/ }).click();
    const personnel = page.getByRole("dialog", { name: "选择承担人员" });
    await personnel.getByRole("searchbox", { name: "搜索承担人员" }).fill("Jiang Song Yang");
    await personnel.getByRole("button").filter({ hasText: "技术部" }).click();
    await drawer.getByRole("combobox", { name: "关联项目" }).click();
    await page.getByRole("option", { name: /人员专属项目/ }).click();
    await drawer.getByRole("button", { name: "保存待结算", exact: true }).click();
    await saveChanges.waitFor();
    assert.equal(writes.at(-1).subjectId, "employee-exact"); assert.equal(writes.at(-1).relatedProjectId, "3");
    assert.ok(requests.some(url => url.includes("settlement-projects?") && url.includes("userId=employee-exact")));
    await drawer.getByRole("button", { name: "关闭", exact: true }).click(); await drawer.waitFor({ state: "hidden" });
    await row(4).click();
    await drawer.getByRole("spinbutton", { name: "累计已收金额", exact: true }).fill("0.70");
    await drawer.getByRole("button", { name: "保存待结算", exact: true }).click();
    await drawer.getByRole("spinbutton", { name: "本次收款金额", exact: true }).fill("0.10");
    assert.equal(await drawer.getByRole("button", { name: "确认结清", exact: true }).isEnabled(), true);
    await drawer.getByRole("button", { name: "确认结清", exact: true }).click();
    await drawer.getByRole("button", { name: "确认结清", exact: true }).waitFor({ state: "hidden" });
    assert.equal(writes.at(-1).receivedAmount, 0.8);
    await drawer.getByRole("button", { name: "关闭", exact: true }).click(); await drawer.waitFor({ state: "hidden" });
    const paging = page.getByRole("navigation", { name: "结算分页" });
    const totalCount = page.getByRole("status").filter({ hasText: /^共 \d+ 条$/ });
    const sizePicker = page.getByRole("combobox", { name: "每页结算数", exact: true });
    assert.equal(await paging.getByRole("button", { name: "上一页" }).isDisabled(), true);
    for (let index = 0; index < 5; index++) {
      await paging.getByRole("button", { name: "下一页" }).click();
      await page.waitForFunction(value => document.querySelector('[aria-label="结算分页"] [aria-current="page"]')?.textContent === value, String(index + 2));
      await table.locator("tbody tr td strong").first().waitFor();
    }
    await row(105).waitFor();
    assert.equal(await paging.getByRole("button", { name: "下一页" }).isDisabled(), true);
    await page.screenshot({ path: "/tmp/after-sales-settlement-pagination-1440.png", fullPage: true });
    for (const size of [50, 100, 20]) {
      await sizePicker.selectOption(String(size));
      await page.waitForFunction(expected => {
        const table = document.querySelector('[aria-label="结算服务列表"]');
        return table?.getAttribute("aria-busy") === "false" && table.tBodies[0].rows.length === expected
          && document.querySelector('[aria-label="结算分页"] [aria-current="page"]')?.textContent === "1";
      }, size);
      const request = new URL(requests.filter(url => url.startsWith("/api/after-sales/settlement-sources?")).at(-1), base);
      assert.equal(request.searchParams.get("pageSize"), String(size));
      assert.equal(request.searchParams.get("page"), "1");
    }
    await paging.getByRole("button", { name: "第 6 页", exact: true }).click();
    await row(105).waitFor();
    const projectSearch = page.getByRole("searchbox", { name: "搜索结算项目名称" });
    const customerSearch = page.getByRole("searchbox", { name: "搜索结算客户名称" });
    const ownerSearch = page.getByRole("searchbox", { name: "搜索结算负责人" });
    await projectSearch.fill("结算项目1");
    await row(1).waitFor();
    assert.equal(await row(2).count(), 0, "project input must not match customer text");
    await totalCount.filter({ hasText: "共 17 条" }).waitFor();
    assert.equal(await paging.getByRole("button", { name: "第 1 页", exact: true }).getAttribute("aria-current"), "page");
    await customerSearch.fill("学校甲");
    await totalCount.filter({ hasText: "共 1 条" }).waitFor();
    await ownerSearch.fill("学校甲");
    await table.getByText("没有找到匹配的结算服务", { exact: true }).waitFor();
    await customerSearch.fill("");
    await table.getByText("没有找到匹配的结算服务", { exact: true }).waitFor();
    await projectSearch.fill("");
    await row(2).waitFor();
    assert.equal(await ownerSearch.inputValue(), "学校甲");
    assert.equal(await row(1).count(), 0, "owner input must not match customer text");
    await ownerSearch.fill("张经理");
    await row(1).waitFor();
    assert.ok(requests.filter(url => url.startsWith("/api/after-sales/settlement-sources?")).every(url => !new URL(url, base).searchParams.has("search")));
    await page.screenshot({ path: "/tmp/after-sales-settlement-column-filters-1440.png", fullPage: true });
    await page.setViewportSize({ width: 1024, height: 768 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({ path: "/tmp/after-sales-settlement-list-1024.png", fullPage: true });
    assert.deepEqual(errors, []);
  } finally { await browser?.close(); await server.close(); }
});
