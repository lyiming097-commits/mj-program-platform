import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

import {
  PAYMENT_TEMPLATE,
  TEST_SESSION,
  assertViewportLayout,
  captureNonBlankScreenshot,
  installApprovalMocks,
  monitorBrowser,
  waitForSettledPage,
} from "./browser-test-helpers.mjs";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(scriptDirectory, "../../../..");
const require = createRequire(path.join(repository, ".codex-artifacts/package.json"));
const { chromium } = require("playwright");

const baseUrl = process.env.BROWSER_BASE_URL || "http://127.0.0.1:4197/approval-center/";
const outputDirectory = process.env.BROWSER_OUTPUT_DIR || "/tmp/approval-center-browser";
const preferredChromium = "/home/h3c/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome";
const executablePath = process.env.CHROMIUM_PATH
  || await fileExists(preferredChromium) ? (process.env.CHROMIUM_PATH || preferredChromium) : undefined;

const MANAGEMENT_CATEGORIES = [
  {
    id: "category-finance",
    name: "财务",
    description: "财务相关审批表单",
    sortOrder: 0,
  },
  {
    id: "category-personnel",
    name: "人事",
    description: "人事相关审批表单",
    sortOrder: 1,
  },
];

const REIMBURSEMENT_TEMPLATE = {
  ...PAYMENT_TEMPLATE,
  id: "tpl-reimbursement",
  code: "REIMBURSEMENT_REQUEST",
  name: "报销申请",
  description: "费用明细和报销审核",
  status: "draft",
  currentVersion: 1,
  version: 1,
  sortOrder: 1,
  updatedAt: "2026-09-17T06:10:00Z",
};

const FINANCE_CATEGORY_PERMISSIONS = [
  {
    permission: "admin",
    scopeType: "departmentSub",
    targetId: "10",
    targetName: "财务部",
    sortOrder: 0,
    includeSubDepartments: true,
  },
  {
    permission: "admin",
    scopeType: "employee",
    targetId: "employee-finance",
    targetName: "财务验收员",
    sortOrder: 1,
  },
];

const ALLOWED_PERMISSION_SCOPES = new Set(["department", "departmentSub", "employee"]);

function assertAllowedPermissionScopes(items, message) {
  assert.equal(Array.isArray(items), true, `${message} should be an array`);
  assert.equal(
    items.every(item => ALLOWED_PERMISSION_SCOPES.has(String(item?.scopeType || ""))),
    true,
    `${message} should contain only department, departmentSub, or employee scopes`,
  );
  assert.equal(
    items.some(item => String(item?.scopeType || "") === "excludedEmployee"),
    false,
    `${message} should not contain excludedEmployee scopes`,
  );
}

const PERSONNEL_CATEGORY_PERMISSIONS = [{
  permission: "admin",
  scopeType: "department",
  targetId: "20",
  targetName: "人事部",
  sortOrder: 0,
}];

const PERMISSION_DIRECTORY = {
  orgRevision: 17,
  departments: [
    {
      deptId: 10,
      name: "财务部",
      parentDeptId: null,
      pinyinInitials: "cwb",
      children: [
        {
          deptId: 11,
          name: "财务共享组",
          parentDeptId: 10,
          pinyinInitials: "cwgxz",
        },
      ],
    },
    { deptId: 20, name: "人事部", parentDeptId: null, pinyinInitials: "rsb" },
  ],
  employees: [
    {
      userId: "employee-finance",
      name: "财务验收员",
      pinyinInitials: "cwysy",
      departments: [{ deptId: 10, name: "财务部", pinyinInitials: "cwb" }],
    },
    {
      userId: "employee-shared-services",
      name: "共享专员",
      pinyinInitials: "gxzy",
      departments: [{ deptId: 11, name: "财务共享组", pinyinInitials: "cwgxz" }],
    },
    {
      userId: "employee-hr",
      name: "人事专员",
      pinyinInitials: "rszy",
      departments: [{ deptId: 20, name: "人事部", pinyinInitials: "rsb" }],
    },
  ],
};

await fs.mkdir(outputDirectory, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath });
const report = {
  ok: false,
  baseUrl,
  outputDirectory,
  desktop: {},
  categoryManager: {},
  emptyCategories: {},
  pagination: {},
  permissionFailures: {},
  mobile: {},
};

try {
  report.desktop = await runDesktop(browser);
  report.categoryManager = await runCategoryManager(browser);
  report.emptyCategories = await runEmptyCategories(browser);
  report.pagination = await runPaginationNormalization(browser);
  report.permissionFailures = await runPermissionFailures(browser);
  report.mobile = await runMobile(browser);
  report.ok = true;
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}

async function runDesktop(browserInstance) {
  const context = await browserInstance.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const problems = monitorBrowser(page);
  const api = await installApprovalMocks(context, {
    templates: [PAYMENT_TEMPLATE, REIMBURSEMENT_TEMPLATE],
    categories: MANAGEMENT_CATEGORIES,
    permissionDirectory: PERMISSION_DIRECTORY,
  });
  api.categoryPermissions.set("category-finance", structuredClone(FINANCE_CATEGORY_PERMISSIONS));
  api.categoryPermissionRevisions.set("category-finance", "revision-finance");
  api.categoryPermissions.set("category-personnel", structuredClone(PERSONNEL_CATEGORY_PERMISSIONS));
  api.categoryPermissionRevisions.set("category-personnel", "revision-personnel");
  assertAllowedPermissionScopes(
    api.categoryPermissions.get("category-finance"),
    "finance category fixture",
  );
  const screenshots = {};

  try {
    await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "审批首页", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "发起审批", exact: true }).count(), 1);
    await assertViewportLayout(page, "desktop home");

    await page.getByRole("button", { name: /付款申请/ }).first().click();
    await page.getByRole("heading", { name: "发起付款申请", exact: true }).waitFor();
    await page.getByLabel(/^收款方/).waitFor();
    assert.equal(new URL(page.url()).pathname, "/approval-center/apply/tpl-payment/");
    assert.equal(await page.getByLabel("申请标题", { exact: true }).count(), 1);
    assert.equal(await page.getByLabel(/^收款方/).count(), 1);
    assert.equal(await page.getByLabel(/^付款金额/).count(), 1);
    await page.getByRole("button", { name: "关闭发起审批", exact: true }).click();
    await page.getByRole("heading", { name: "审批首页", exact: true }).waitFor();

    const draftFormUrl = new URL("apply/tpl-payment/", baseUrl);
    draftFormUrl.searchParams.set("draftId", "draft-payment-submit");
    draftFormUrl.searchParams.set("return", "/approval-center/drafts/");
    await page.goto(draftFormUrl.toString(), { waitUntil: "domcontentloaded" });
    await page.getByRole("heading", { name: "发起付款申请", exact: true }).waitFor();
    assert.equal(await page.getByLabel("申请标题", { exact: true }).inputValue(), "九月供应商付款");
    assert.equal(await page.getByLabel(/^收款方/).inputValue(), "星河设备有限公司");
    const paymentDescription = page.getByLabel(/^付款说明/);
    assert.equal(await paymentDescription.evaluate(element => element.tagName), "TEXTAREA");
    assert.equal(await paymentDescription.getAttribute("rows"), "3");
    assert.ok(
      api.calls.some(call => call.method === "GET" && call.path.endsWith("/drafts/draft-payment-submit")),
      "opening a draft URL should fetch that draft by id",
    );
    const paymentChannel = page.getByRole("combobox", { name: "付款渠道", exact: true });
    await paymentChannel.click();
    const channelOptions = page.getByRole("listbox", { name: "付款渠道", exact: true });
    await channelOptions.getByRole("option", { name: "企业网银", exact: true }).click();
    await channelOptions.getByRole("option", { name: "银行柜台", exact: true }).click();
    screenshots.application = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "desktop-application-multiselect.png"),
      "desktop application multiselect",
    );
    await assertViewportLayout(page, "desktop application multiselect");
    await paymentChannel.press("Escape");
    assert.equal(await channelOptions.count(), 0, "Escape should close only the multiselect dropdown");
    assert.equal(await page.getByRole("heading", { name: "发起付款申请", exact: true }).count(), 1);
    const applicationBodyBeforeSave = await page.locator(".approval-drawer-content").boundingBox();
    await page.getByLabel("申请标题", { exact: true }).fill("暂存付款申请");
    await page.getByRole("button", { name: "保存草稿", exact: true }).click();
    await page.locator(".approval-feedback-toast-panel").getByText("草稿已保存", { exact: true }).waitFor();
    await page.getByRole("button", { name: "已保存", exact: true }).waitFor();
    const applicationBodyAfterSave = await page.locator(".approval-drawer-content").boundingBox();
    assert.ok(applicationBodyBeforeSave && applicationBodyAfterSave
      && Math.abs(applicationBodyBeforeSave.y - applicationBodyAfterSave.y) < 1,
    "saving a draft must not move the application form");
    await page.getByLabel("申请标题", { exact: true }).fill("九月供应商付款（已确认）");
    assert.equal(await page.getByRole("button", { name: "保存草稿", exact: true }).isEnabled(), true,
      "editing a saved draft should enable saving again");
    await page.getByRole("button", { name: "提交审批", exact: true }).click();
    await page.waitForURL(url => url.pathname.includes("/approval-center/applications/app-submitted-1/"));
    await page.locator(".approval-feedback-toast-panel").getByText("审批已提交", { exact: true }).waitFor();
    await page.getByRole("heading", { name: "九月供应商付款（已确认）", exact: true }).waitFor();
    const submission = api.writes.find(call => call.method === "POST" && call.path.endsWith("/applications"));
    assert.equal(submission?.payload?.draftId, "draft-payment-submit", "draft submission should carry its draftId");
    assert.equal(submission?.payload?.values?.["field-payee"], "星河设备有限公司");
    assert.deepEqual(submission?.payload?.values?.["field-channel"], ["企业网银", "银行柜台"]);
    assert.equal(await page.getByRole("button", { name: "退回并结束", exact: true }).count(), 1);

    await page.getByRole("button", { name: "同意", exact: true }).click();
    await page.getByRole("heading", { name: "同意审批", exact: true }).waitFor();
    await page.getByRole("button", { name: "确认同意", exact: true }).click();
    await page.getByRole("heading", { name: "同意审批", exact: true }).waitFor({ state: "detached" });
    await page.getByLabel("审批概要", { exact: true }).getByText("已通过", { exact: true }).waitFor();
    await page.locator(".approval-feedback-toast-panel").getByText("审批已同意", { exact: true }).waitFor();
    assert.ok(
      api.writes.some(call => call.method === "POST" && call.path.endsWith("/applications/app-submitted-1/approve")),
      "confirming approval should call the approve action",
    );

    await page.goto(new URL("drafts/", baseUrl).toString(), { waitUntil: "domcontentloaded" });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "草稿箱", exact: true }).waitFor();
    await page.getByRole("button", { name: "删除草稿待删除付款草稿", exact: true }).click();
    const deleteDialog = page.getByRole("alertdialog");
    await deleteDialog.getByRole("heading", { name: "删除这份草稿？", exact: true }).waitFor();
    await deleteDialog.getByRole("button", { name: "确认删除", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "草稿已删除" }).waitFor();
    assert.ok(
      api.writes.some(call => call.method === "DELETE" && call.path.endsWith("/drafts/draft-payment-delete")),
      "confirming draft deletion should issue DELETE for the selected draft",
    );

    await page.getByRole("button", { name: "审批中心", exact: true }).click();
    await page.getByRole("heading", { name: "审批中心", exact: true }).waitFor();
    await page.getByText("暂无审批中心数据", { exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/approval-center/approvals/");
    assert.equal(new URL(page.url()).searchParams.get("tab"), null);

    await page.getByRole("button", { name: "我已处理", exact: true }).click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("tab") === "processed");
    assert.equal(
      await page.getByRole("button", { name: "我已处理", exact: true }).getAttribute("aria-current"),
      "page",
    );
    await page.getByRole("columnheader", { name: "处理结果", exact: true }).waitFor();
    await page.getByRole("columnheader", { name: "申请状态", exact: true }).waitFor();
    const processedRow = page.getByRole("row").filter({ hasText: "已处理付款申请" });
    await processedRow.waitFor();
    assert.equal(await processedRow.getByText("已同意", { exact: true }).count(), 1);
    assert.equal(await processedRow.getByText("已拒绝", { exact: true }).count(), 1);

    const sidebarNavigation = page.locator("aside.platform-sidebar.is-fixed")
      .getByRole("navigation", { name: "主导航", exact: true });
    const sidebarLabels = (await sidebarNavigation.getByRole("button").allInnerTexts()).map(label => label.trim());
    assert.equal(await sidebarNavigation.getByRole("button", { name: "设置", exact: true }).count(), 1);
    assert.equal(await sidebarNavigation.getByRole("button", { name: "表单管理", exact: true }).count(), 1);
    assert.ok(
      sidebarLabels.indexOf("表单管理") > sidebarLabels.indexOf("草稿箱")
        && sidebarLabels.indexOf("表单管理") < sidebarLabels.indexOf("设置"),
      `template management should appear above settings in the sidebar (${sidebarLabels.join(", ")})`,
    );
    assert.equal(
      await sidebarNavigation.getByRole("button", { name: "权限设置", exact: true }).count(),
      0,
      "global permission settings should be named settings in the sidebar",
    );

    await sidebarNavigation.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByRole("heading", { name: "权限分配", exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/approval-center/settings/permissions/");
    assert.equal(await page.getByRole("tablist", { name: "设置页面", exact: true }).count(), 0);

    await page.getByRole("button", { name: "添加人员管理员", exact: true }).click();
    const permissionPicker = page.getByRole("dialog", { name: "添加人员", exact: true });
    await permissionPicker.getByRole("checkbox", { name: "财务验收员管理员", exact: true }).check();
    await permissionPicker.getByRole("button", { name: "关闭", exact: true }).click();
    await page.getByRole("button", { name: "移除财务验收员", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "保存", exact: true }).isEnabled(), true);

    await page.evaluate(() => window.history.back());
    const leaveSettingsDialog = page.getByRole("alertdialog", { name: "是否放弃修改", exact: true });
    await leaveSettingsDialog.waitFor();
    await page.waitForURL(url => url.pathname === "/approval-center/settings/permissions/");
    await leaveSettingsDialog.getByRole("button", { name: "继续编辑", exact: true }).click();
    await leaveSettingsDialog.waitFor({ state: "detached" });
    assert.equal(new URL(page.url()).pathname, "/approval-center/settings/permissions/");
    assert.equal(
      await page.getByRole("button", { name: "保存", exact: true }).isEnabled(),
      true,
      "cancelling browser Back should preserve unsaved permission changes",
    );

    await page.evaluate(() => window.history.back());
    await leaveSettingsDialog.waitFor();
    await page.waitForURL(url => url.pathname === "/approval-center/settings/permissions/");
    await leaveSettingsDialog.getByRole("button", { name: "确认放弃", exact: true }).click();
    await page.waitForURL(url => (
      url.pathname === "/approval-center/approvals/"
      && url.searchParams.get("tab") === "processed"
    ));
    await page.getByRole("heading", { name: "审批中心", exact: true }).waitFor();

    await page.evaluate(() => window.history.forward());
    await page.waitForURL(url => url.pathname === "/approval-center/settings/permissions/");
    await page.getByRole("heading", { name: "权限分配", exact: true }).waitFor();
    assert.equal(
      await page.getByRole("alertdialog", { name: "是否放弃修改", exact: true }).count(),
      0,
      "confirming browser Back should clear dirty state before a forward navigation",
    );

    const templateManagementCallStart = api.calls.length;
    await sidebarNavigation.getByRole("button", { name: "表单管理", exact: true }).click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("categoryId") === "category-finance");
    await page.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    const selectedCategoryName = page.getByLabel("分类名称", { exact: true });
    await selectedCategoryName.waitFor();
    assert.equal(await selectedCategoryName.inputValue(), "财务");
    await page.getByText("付款申请", { exact: true }).first().waitFor();
    assert.equal(new URL(page.url()).pathname, "/approval-center/templates/");
    assert.equal(await page.getByRole("tablist", { name: "设置页面", exact: true }).count(), 0);
    assert.equal(
      await page.getByText("维护审批表单、字段和流程", { exact: true }).count(),
      0,
      "template management should not render a duplicate visible page header",
    );
    assert.equal(
      await page.getByText("全部分类", { exact: true }).count(),
      0,
      "template management should only expose real approval categories",
    );
    const initialManagedTemplateCalls = api.calls
      .slice(templateManagementCallStart)
      .filter(call => call.method === "GET" && call.path.endsWith("/templates") && call.query.scope === "manage");
    assert.ok(initialManagedTemplateCalls.length > 0, "opening template management should request its first category");
    assert.equal(
      initialManagedTemplateCalls.every(call => call.query.categoryId === "category-finance"),
      true,
      "opening template management should never request an unscoped all-category list",
    );
    assert.match(
      await sidebarNavigation.getByRole("button", { name: "表单管理", exact: true }).getAttribute("class"),
      /\bactive\b/,
      "template management should be selected in the sidebar",
    );
    assert.equal(await page.getByRole("button", { name: "新建表单", exact: true }).count(), 1);
    assert.equal(await page.getByRole("button", { name: "编辑付款申请", exact: true }).count(), 1);

    const categoryNavigation = page.getByRole("navigation", { name: "审批分类列表", exact: true });
    await categoryNavigation.locator('[data-category-id="category-finance"]').waitFor();
    assert.equal(await categoryNavigation.locator('[data-category-id="category-personnel"]').count(), 1);

    const categorySidebar = page.getByRole("complementary", { name: "审批分类", exact: true });
    const groupSettings = page.getByRole("complementary", { name: "分组设置", exact: true });
    const groupSettingsSave = groupSettings.locator('[data-ai-action="approval.category.settings.save"]');
    await groupSettings.getByRole("heading", { name: "管理权限", exact: true }).waitFor();
    await groupSettings.getByText("权限部门", { exact: true }).waitFor();
    await groupSettings.getByText("权限人员", { exact: true }).waitFor();
    assert.equal(
      await groupSettings.getByText("已排除人员", { exact: true }).count(),
      0,
      "category permissions should not expose an excluded employees section",
    );
    await groupSettings.getByRole("button", { name: "添加部门管理员", exact: true }).waitFor();
    await groupSettings.getByRole("button", { name: "添加人员管理员", exact: true }).waitFor();
    await groupSettings.getByRole("button", { name: "移除财务部", exact: true }).waitFor();
    await groupSettings.getByRole("button", { name: "移除财务验收员", exact: true }).waitFor();
    await groupSettings.getByText("含下级", { exact: true }).waitFor();
    assert.equal(
      await groupSettings.getByRole("button", { name: "移除共享专员", exact: true }).count(),
      0,
      "unselected employees should not appear as permission source chips",
    );
    assert.equal(
      await groupSettings.getByRole("button", { name: "排除共享专员", exact: true }).count(),
      0,
      "category permissions should not expose an excluded employee action",
    );
    assert.equal(await groupSettingsSave.isDisabled(), true, "unchanged group settings should not save");
    assert.equal(
      await groupSettings.locator('[data-ai-action="approval.category.permissions.save"]').count(),
      0,
      "category permissions should not expose a separate save action",
    );
    assert.equal(
      await groupSettings.getByRole("button", { name: "保存权限", exact: true }).count(),
      0,
      "category permissions should not expose a separate save button",
    );
    assert.equal(
      await groupSettings.getByRole("button", { name: "编辑财务", exact: true }).count(),
      0,
      "category names should be edited inline instead of through an edit-category action",
    );
    assert.equal(
      await page.getByLabel("分类说明", { exact: true }).count(),
      0,
      "category settings should not expose a category description field",
    );
    assert.equal(
      await groupSettings.getByRole("button", { name: "设置财务管理权限", exact: true }).count(),
      0,
      "category permissions should no longer have a separate settings entry point",
    );
    assert.equal(
      await page.getByRole("dialog", { name: "财务管理权限", exact: true }).count(),
      0,
      "category permissions should render inline instead of in the legacy dialog",
    );
    assert.equal(await categorySidebar.getByRole("button", { name: "编辑财务", exact: true }).count(), 0);
    assert.equal(await categorySidebar.getByRole("button", { name: "设置财务管理权限", exact: true }).count(), 0);
    assert.deepEqual(
      await categorySidebar.locator(".approval-category-sidebar-actions").getByRole("button").evaluateAll(buttons => (
        buttons.map(button => button.getAttribute("aria-label"))
      )),
      ["上移分类财务", "下移分类财务"],
      "the category footer should contain only the up and down ordering actions",
    );

    const permissionOnlyWritesStart = api.writes.length;
    await groupSettings.getByRole("button", { name: "添加部门管理员", exact: true }).click();
    const categoryDepartmentPicker = page.getByRole("dialog", { name: "添加部门", exact: true });
    const financeDepartmentCheckbox = categoryDepartmentPicker.getByRole("checkbox", {
      name: "财务部部门",
      exact: true,
    });
    const financeIncludeSubDepartments = categoryDepartmentPicker.getByRole("checkbox", {
      name: "财务部包含子部门",
      exact: true,
    });
    await financeDepartmentCheckbox.waitFor();
    assert.equal(await financeDepartmentCheckbox.isChecked(), true, "saved departments should be checked initially");
    assert.equal(
      await financeIncludeSubDepartments.isChecked(),
      true,
      "saved include-sub-departments state should be restored",
    );
    const childDepartmentCheckbox = categoryDepartmentPicker.getByRole("checkbox", {
      name: "财务共享组部门",
      exact: true,
    });
    await childDepartmentCheckbox.waitFor();
    assert.equal(
      await childDepartmentCheckbox.isDisabled(),
      true,
      "a child department should be inherited when its parent includes sub-departments",
    );
    await categoryDepartmentPicker.getByRole("checkbox", { name: "人事部部门", exact: true }).check();
    await categoryDepartmentPicker.getByRole("checkbox", { name: "人事部包含子部门", exact: true }).check();
    await categoryDepartmentPicker.getByRole("button", { name: "关闭", exact: true }).click();
    await categoryDepartmentPicker.waitFor({ state: "detached" });
    await groupSettings.getByRole("button", { name: "移除人事部", exact: true }).waitFor();

    await groupSettings.getByRole("button", { name: "移除财务验收员", exact: true }).click();
    assert.equal(
      await groupSettings.getByRole("button", { name: "移除财务验收员", exact: true }).count(),
      0,
      "an existing employee permission should be removable inline",
    );
    await groupSettings.getByRole("button", { name: "添加人员管理员", exact: true }).click();
    const categoryEmployeePicker = page.getByRole("dialog", { name: "添加人员", exact: true });
    await categoryEmployeePicker.getByLabel("搜索人员", { exact: true }).fill("gxzy");
    await categoryEmployeePicker.getByRole("checkbox", { name: "共享专员管理员", exact: true }).check();
    await categoryEmployeePicker.getByRole("button", { name: "关闭", exact: true }).click();
    await categoryEmployeePicker.waitFor({ state: "detached" });
    await groupSettings.getByRole("button", { name: "移除共享专员", exact: true }).waitFor();

    assert.equal(await groupSettingsSave.isEnabled(), true, "editing inline rules should enable unified saving");
    const financePermissionSaveResponse = page.waitForResponse(response => (
      response.request().method() === "POST"
      && decodeURIComponent(new URL(response.url()).pathname)
        .endsWith("/categories/category-finance/permissions")
    ));
    await groupSettingsSave.click();
    await financePermissionSaveResponse;
    const financePermissionWrite = api.writes.find(call => (
      call.method === "POST"
      && decodeURIComponent(call.path).endsWith("/categories/category-finance/permissions")
    ));
    assertAllowedPermissionScopes(
      financePermissionWrite?.payload?.items,
      "saved finance category permission payload",
    );
    assert.deepEqual(financePermissionWrite?.payload, {
      items: [
        {
          permission: "admin",
          scopeType: "departmentSub",
          targetId: "10",
          targetName: "财务部",
          sortOrder: 0,
          includeSubDepartments: true,
        },
        {
          permission: "admin",
          scopeType: "departmentSub",
          targetId: "20",
          targetName: "人事部",
          sortOrder: 1,
          includeSubDepartments: true,
        },
        {
          permission: "admin",
          scopeType: "employee",
          targetId: "employee-shared-services",
          targetName: "共享专员",
          sortOrder: 0,
        },
      ],
      revision: "revision-finance",
      orgRevision: "17",
    });
    const permissionOnlyWrites = api.writes.slice(permissionOnlyWritesStart).filter(call => (
      decodeURIComponent(call.path).includes("/categories/category-finance")
    ));
    assert.deepEqual(
      permissionOnlyWrites.map(call => ({ method: call.method, permissionWrite: call.path.endsWith("/permissions") })),
      [{ method: "POST", permissionWrite: true }],
      "changing only permissions should issue one permission POST and no category PATCH",
    );
    assert.equal(await groupSettingsSave.isDisabled(), true, "saving should clear the unified dirty state");

    await sidebarNavigation.getByRole("button", { name: "设置", exact: true }).click();
    await page.waitForURL(url => url.pathname === "/approval-center/settings/permissions/");
    await page.getByRole("heading", { name: "权限分配", exact: true }).waitFor();
    assert.equal(
      await page.getByRole("alertdialog", { name: "是否放弃修改", exact: true }).count(),
      0,
      "saved category permissions should allow navigating to settings without confirmation",
    );
    await page.evaluate(() => window.history.back());
    await page.waitForURL(url => (
      url.pathname === "/approval-center/templates/"
      && url.searchParams.get("categoryId") === "category-finance"
    ));
    await groupSettings.getByRole("button", { name: "移除共享专员", exact: true }).waitFor();
    assert.equal(
      await page.getByRole("alertdialog", { name: "是否放弃修改", exact: true }).count(),
      0,
      "saved category permissions should allow browser Back without confirmation",
    );

    await groupSettings.getByRole("button", { name: "添加人员管理员", exact: true }).click();
    let dirtyEmployeePicker = page.getByRole("dialog", { name: "添加人员", exact: true });
    await dirtyEmployeePicker.getByRole("checkbox", { name: "人事专员管理员", exact: true }).check();
    await dirtyEmployeePicker.getByRole("button", { name: "关闭", exact: true }).click();
    await dirtyEmployeePicker.waitFor({ state: "detached" });
    await groupSettings.getByRole("button", { name: "移除人事专员", exact: true }).waitFor();

    const leaveCategoryPermissionDialog = page.getByRole("alertdialog", { name: "是否放弃修改", exact: true });
    await sidebarNavigation.getByRole("button", { name: "设置", exact: true }).click();
    await leaveCategoryPermissionDialog.waitFor();
    await leaveCategoryPermissionDialog.getByRole("button", { name: "继续编辑", exact: true }).click();
    await leaveCategoryPermissionDialog.waitFor({ state: "detached" });
    assert.equal(new URL(page.url()).pathname, "/approval-center/templates/");
    assert.equal(
      new URL(page.url()).searchParams.get("categoryId"),
      "category-finance",
      "continuing after sidebar navigation should keep the category URL",
    );
    assert.equal(
      await groupSettings.getByRole("button", { name: "移除人事专员", exact: true }).count(),
      1,
      "continuing after sidebar navigation should preserve the category permission draft",
    );
    await sidebarNavigation.getByRole("button", { name: "设置", exact: true }).click();
    await leaveCategoryPermissionDialog.waitFor();
    await leaveCategoryPermissionDialog.getByRole("button", { name: "确认放弃", exact: true }).click();
    await page.waitForURL(url => url.pathname === "/approval-center/settings/permissions/");
    await page.getByRole("heading", { name: "权限分配", exact: true }).waitFor();

    await sidebarNavigation.getByRole("button", { name: "表单管理", exact: true }).click();
    await page.waitForFunction(() => (
      location.pathname === "/approval-center/templates/"
      && new URL(location.href).searchParams.get("categoryId") === "category-finance"
    ));
    await groupSettings.getByRole("button", { name: "添加人员管理员", exact: true }).click();
    dirtyEmployeePicker = page.getByRole("dialog", { name: "添加人员", exact: true });
    await dirtyEmployeePicker.getByRole("checkbox", { name: "人事专员管理员", exact: true }).check();
    await dirtyEmployeePicker.getByRole("button", { name: "关闭", exact: true }).click();
    await dirtyEmployeePicker.waitFor({ state: "detached" });
    await groupSettings.getByRole("button", { name: "移除人事专员", exact: true }).waitFor();

    await page.evaluate(() => window.history.back());
    await leaveCategoryPermissionDialog.waitFor();
    await page.waitForFunction(() => (
      location.pathname === "/approval-center/templates/"
      && new URL(location.href).searchParams.get("categoryId") === "category-finance"
    ));
    await leaveCategoryPermissionDialog.getByRole("button", { name: "继续编辑", exact: true }).click();
    await leaveCategoryPermissionDialog.waitFor({ state: "detached" });
    assert.equal(
      await groupSettings.getByRole("button", { name: "移除人事专员", exact: true }).count(),
      1,
      "continuing after browser Back should preserve the category permission draft",
    );
    await page.evaluate(() => window.history.back());
    await leaveCategoryPermissionDialog.waitFor();
    await leaveCategoryPermissionDialog.getByRole("button", { name: "确认放弃", exact: true }).click();
    await page.waitForURL(url => url.pathname === "/approval-center/settings/permissions/");
    await page.getByRole("heading", { name: "权限分配", exact: true }).waitFor();
    await page.evaluate(() => window.history.forward());
    await page.waitForURL(url => (
      url.pathname === "/approval-center/templates/"
      && url.searchParams.get("categoryId") === "category-finance"
    ));
    await groupSettings.getByRole("button", { name: "移除共享专员", exact: true }).waitFor();
    assert.equal(
      await page.getByRole("alertdialog", { name: "是否放弃修改", exact: true }).count(),
      0,
      "confirming browser Back should clear the category permission dirty state",
    );

    const categoryNameDraft = groupSettings.getByLabel("分类名称", { exact: true });
    await categoryNameDraft.fill("财务草稿");
    assert.equal(await groupSettingsSave.isEnabled(), true, "editing a category name should mark group settings dirty");
    await categoryNavigation.locator('[data-category-id="category-personnel"]').click();
    await leaveCategoryPermissionDialog.waitFor();
    await leaveCategoryPermissionDialog.getByRole("button", { name: "继续编辑", exact: true }).click();
    await leaveCategoryPermissionDialog.waitFor({ state: "detached" });
    assert.equal(
      new URL(page.url()).searchParams.get("categoryId"),
      "category-finance",
      "continuing category-name editing should keep the current category URL",
    );
    assert.equal(
      await categoryNavigation.locator('[data-category-id="category-finance"]').getAttribute("aria-current"),
      "page",
      "continuing category-name editing should keep the current category selected",
    );
    assert.equal(
      await categoryNameDraft.inputValue(),
      "财务草稿",
      "continuing category-name editing should preserve the unsaved draft",
    );
    await categoryNavigation.locator('[data-category-id="category-personnel"]').click();
    await leaveCategoryPermissionDialog.waitFor();
    await leaveCategoryPermissionDialog.getByRole("button", { name: "确认放弃", exact: true }).click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("categoryId") === "category-personnel");
    await groupSettings.getByRole("button", { name: "移除人事部", exact: true }).waitFor();
    assert.equal(await categoryNameDraft.inputValue(), "人事", "discarding the name draft should load the next category name");

    const releaseFinancePermissions = api.holdCategoryPermissionsRequest("category-finance");
    const pendingFinancePermissions = page.waitForRequest(request => (
      request.method() === "GET"
      && decodeURIComponent(new URL(request.url()).pathname).endsWith("/categories/category-finance/permissions")
    ));
    await categoryNavigation.locator('[data-category-id="category-finance"]').click();
    await pendingFinancePermissions;
    await groupSettings.getByRole("status").filter({ hasText: "正在加载权限..." }).waitFor();
    await categoryNavigation.locator('[data-category-id="category-personnel"]').click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("categoryId") === "category-personnel");
    await groupSettings.getByRole("button", { name: "移除人事部", exact: true }).waitFor();
    const staleFinancePermissionResponse = page.waitForResponse(response => (
      response.request().method() === "GET"
      && decodeURIComponent(new URL(response.url()).pathname).endsWith("/categories/category-finance/permissions")
    ));
    releaseFinancePermissions();
    await staleFinancePermissionResponse;
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(
      await groupSettings.getByRole("button", { name: "移除人事部", exact: true }).count(),
      1,
      "the current category permissions should remain visible after a stale response",
    );
    assert.equal(
      await groupSettings.getByRole("button", { name: "移除财务部", exact: true }).count(),
      0,
      "a stale category permission response must not replace the inline editor",
    );
    assert.equal(await categoryNameDraft.inputValue(), "人事");

    await categoryNavigation.locator('[data-category-id="category-finance"]').click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("categoryId") === "category-finance");
    await groupSettings.getByRole("button", { name: "移除财务部", exact: true }).waitFor();
    await page.getByText("付款申请", { exact: true }).first().waitFor();

    const templateWorkspaceBeforeNotice = await page.locator(".approval-template-management").boundingBox();
    const addCategoryButton = page.getByRole("button", { name: "新增审批分类", exact: true });
    await addCategoryButton.click();
    const createCategoryDialog = page.getByRole("dialog", { name: "新增审批分类", exact: true });
    assert.equal(
      await createCategoryDialog.getByLabel(/^分类名称/).evaluate(element => document.activeElement === element),
      true,
      "opening the category dialog should move focus to its first field",
    );
    assert.equal(
      await createCategoryDialog.getByLabel("分类说明", { exact: true }).count(),
      0,
      "new categories should only ask for a name",
    );
    await createCategoryDialog.getByLabel(/^分类名称/).fill("行政");
    const categoryCreateResponse = page.waitForResponse(response => (
      response.request().method() === "POST"
      && decodeURIComponent(new URL(response.url()).pathname).endsWith("/categories")
      && response.status() === 201
    ));
    await createCategoryDialog.getByRole("button", { name: "创建", exact: true }).click();
    await categoryCreateResponse;
    await createCategoryDialog.waitFor({ state: "detached" });
    const successToast = page.locator(".approval-feedback-toast-panel");
    await successToast.getByText("分类已创建", { exact: true }).waitFor();
    await page.waitForFunction(() => getComputedStyle(document.querySelector(".approval-feedback-toast-panel")).opacity === "1");
    screenshots.categorySuccess = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "desktop-category-success.png"),
      "desktop category success toast",
    );
    const toastBounds = await successToast.boundingBox();
    const templateWorkspaceWithNotice = await page.locator(".approval-template-management").boundingBox();
    assert.ok(toastBounds && toastBounds.width <= 420
      && Math.abs(toastBounds.y - 16) <= 1
      && Math.abs(toastBounds.x + toastBounds.width / 2 - page.viewportSize().width / 2) <= 1,
    `desktop success toast should be centered 16px from the viewport top (${JSON.stringify(toastBounds)})`);
    assert.ok(templateWorkspaceBeforeNotice && templateWorkspaceWithNotice
      && Math.abs(templateWorkspaceBeforeNotice.y - templateWorkspaceWithNotice.y) < 1
      && Math.abs(templateWorkspaceBeforeNotice.height - templateWorkspaceWithNotice.height) < 1,
    "success toast must not move or shrink the template management workspace");
    assert.equal(await page.locator(".approval-page-shell > .approval-alert.is-success").count(), 0);
    for (const width of [1400, 1024, 768]) {
      await page.setViewportSize({ width, height: 900 });
      const compactToastBounds = await successToast.boundingBox();
      assert.ok(compactToastBounds
        && compactToastBounds.y > 56
        && Math.abs(compactToastBounds.y + compactToastBounds.height - (page.viewportSize().height - 16)) <= 1,
      `success toast should clear compact desktop navigation and stay 16px from the bottom at ${width}px (${JSON.stringify(compactToastBounds)})`);
      if (width === 1024) {
        screenshots.compactToast = await captureNonBlankScreenshot(
          page,
          path.join(outputDirectory, "compact-category-success.png"),
          "compact desktop category success toast",
        );
      }
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await successToast.waitFor({ state: "detached", timeout: 4500 });
    const createdCategory = api.categories.find(category => category.name === "行政");
    assert.ok(createdCategory, "creating a category should add it to the category directory");
    await page.waitForFunction(
      categoryId => new URL(location.href).searchParams.get("categoryId") === categoryId,
      createdCategory.id,
    );
    await categoryNameDraft.waitFor();
    assert.equal(await categoryNameDraft.inputValue(), "行政");
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "新增审批分类");
    assert.equal(
      await addCategoryButton.evaluate(element => document.activeElement === element),
      true,
      "saving a category should return focus to the opening control",
    );
    const categoryCreate = api.writes.find(call => call.method === "POST" && call.path.endsWith("/categories"));
    assert.deepEqual(categoryCreate?.payload, { name: "行政" });
    assert.equal(
      await page.getByRole("button", { name: "编辑行政", exact: true }).count(),
      0,
      "existing categories should not expose the removed edit-category action",
    );

    const categoryItemPath = `/categories/${createdCategory.id}`;
    const nameOnlyWritesStart = api.writes.length;
    await categoryNameDraft.fill("行政事项");
    await page.waitForFunction(() => (
      document.querySelector('[data-ai-action="approval.category.settings.save"]')?.disabled === false
    ));
    const nameOnlySaveResponse = page.waitForResponse(response => (
      response.request().method() === "PATCH"
      && decodeURIComponent(new URL(response.url()).pathname).endsWith(categoryItemPath)
    ));
    await groupSettingsSave.click();
    await nameOnlySaveResponse;
    await page.getByRole("status").filter({ hasText: "设置已保存" }).waitFor();
    await successToast.getByRole("button", { name: "关闭提示", exact: true }).click();
    await successToast.waitFor({ state: "detached" });
    assert.equal(await categoryNameDraft.inputValue(), "行政事项");
    assert.equal(api.categories.find(category => category.id === createdCategory.id)?.name, "行政事项");
    const nameOnlyWrites = api.writes.slice(nameOnlyWritesStart).filter(call => (
      decodeURIComponent(call.path).includes(`/categories/${createdCategory.id}`)
    ));
    assert.deepEqual(
      nameOnlyWrites.map(call => ({ method: call.method, payload: call.payload })),
      [{ method: "PATCH", payload: { name: "行政事项" } }],
      "changing only the category name should issue one category PATCH and no permission POST",
    );
    assert.equal(await groupSettingsSave.isDisabled(), true, "a name-only save should clear dirty state");

    await categoryNameDraft.fill("行政流程");
    await groupSettings.getByRole("button", { name: "添加人员管理员", exact: true }).click();
    const combinedEmployeePicker = page.getByRole("dialog", { name: "添加人员", exact: true });
    await combinedEmployeePicker.getByRole("checkbox", { name: "人事专员管理员", exact: true }).check();
    await combinedEmployeePicker.getByRole("button", { name: "关闭", exact: true }).click();
    await combinedEmployeePicker.waitFor({ state: "detached" });
    await groupSettings.getByRole("button", { name: "移除人事专员", exact: true }).waitFor();
    const combinedWritesStart = api.writes.length;
    const combinedNameResponse = page.waitForResponse(response => (
      response.request().method() === "PATCH"
      && decodeURIComponent(new URL(response.url()).pathname).endsWith(categoryItemPath)
    ));
    const combinedPermissionResponse = page.waitForResponse(response => (
      response.request().method() === "POST"
      && decodeURIComponent(new URL(response.url()).pathname)
        .endsWith(`/categories/${createdCategory.id}/permissions`)
    ));
    await groupSettingsSave.click();
    await Promise.all([combinedNameResponse, combinedPermissionResponse]);
    const combinedWrites = api.writes.slice(combinedWritesStart).filter(call => (
      decodeURIComponent(call.path).includes(`/categories/${createdCategory.id}`)
    ));
    assert.deepEqual(
      combinedWrites.map(call => ({ method: call.method, permissionWrite: call.path.endsWith("/permissions") })),
      [
        { method: "PATCH", permissionWrite: false },
        { method: "POST", permissionWrite: true },
      ],
      "saving a changed name and permissions should PATCH the category before POSTing permissions",
    );
    assert.deepEqual(combinedWrites[0]?.payload, { name: "行政流程" });
    assert.equal(
      combinedWrites[1]?.payload?.items?.some(item => item.targetId === "employee-hr"),
      true,
      "the combined save should persist the permission draft",
    );
    assert.equal(await categoryNameDraft.inputValue(), "行政流程");
    assert.equal(api.categories.find(category => category.id === createdCategory.id)?.name, "行政流程");
    assert.equal(await groupSettingsSave.isDisabled(), true, "a combined save should clear both dirty states");

    await page.getByRole("button", { name: "上移分类行政流程", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "分类顺序已更新" }).waitFor();
    const categoryReorder = api.writes.find(call => call.method === "POST" && call.path.endsWith("/categories/reorder"));
    assert.ok(categoryReorder?.payload?.revision, "category reorder should carry the loaded revision");
    assert.deepEqual(
      categoryReorder.payload.items.map(item => item.id),
      ["category-finance", createdCategory.id, "category-personnel"],
      "moving a category up should persist the complete visible order",
    );

    await page.getByRole("button", { name: "新建表单", exact: true }).click();
    await page.getByRole("heading", { name: "新建审批表单", exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("categoryId"), createdCategory.id);
    assert.equal(await page.getByLabel("所属分类", { exact: true }).inputValue(), createdCategory.id);
    assert.equal(await page.getByLabel("所属分类", { exact: true }).isDisabled(), true);
    const categoryEditorSteps = page.getByRole("navigation", { name: "表单配置步骤", exact: true });
    await categoryEditorSteps.getByRole("button").filter({ hasText: "表单设计" }).click();
    await page.getByRole("heading", { name: "字段控件", exact: true }).waitFor();
    assert.equal(
      new URL(page.url()).searchParams.get("categoryId"),
      createdCategory.id,
      "editor step changes should preserve the selected category in the URL",
    );
    await page.getByRole("button", { name: "返回表单管理", exact: true }).click();
    await page.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    assert.equal(
      new URL(page.url()).searchParams.get("categoryId"),
      createdCategory.id,
      "returning from the editor should restore the selected category",
    );

    const invalidCategoryUrl = new URL("templates/?categoryId=deleted-category", baseUrl);
    await page.goto(invalidCategoryUrl.toString(), { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => new URL(location.href).searchParams.get("categoryId") === "category-finance");
    await page.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    await waitForCategoryName(page, "财务");
    await page.getByText("付款申请", { exact: true }).first().waitFor();
    assert.equal(
      new URL(page.url()).searchParams.get("categoryId"),
      "category-finance",
      "an unavailable category should normalize the URL to the first real category",
    );
    assert.equal(await page.getByText("全部分类", { exact: true }).count(), 0);

    const refreshedCategoryNavigation = page.getByRole("navigation", { name: "审批分类列表", exact: true });
    const templateManagement = await page.locator(".approval-template-management").elementHandle();
    assert.ok(templateManagement, "template management should be mounted before switching categories");
    const releasePersonnelTemplates = api.holdNextManagedTemplateListRequest();
    const personnelRequest = page.waitForRequest(request => {
      const url = new URL(request.url());
      return request.method() === "GET"
        && url.pathname.endsWith("/api/approval-center/templates")
        && url.searchParams.get("scope") === "manage"
        && url.searchParams.get("categoryId") === "category-personnel";
    });
    try {
      await refreshedCategoryNavigation.locator('[data-category-id="category-personnel"]').click();
      await personnelRequest;
      await page.waitForFunction(() => new URL(location.href).searchParams.get("categoryId") === "category-personnel");
      await page.getByRole("status").filter({ hasText: "正在更新表单..." }).waitFor();
      assert.equal(
        await templateManagement.evaluate(element => element.isConnected),
        true,
        "switching categories should keep the existing template management workspace mounted",
      );
      assert.equal(
        await page.locator(".approval-template-management").isVisible(),
        true,
        "switching categories should keep the template management workspace visible",
      );
      assert.equal(
        await page.getByRole("status").filter({ hasText: "正在加载审批数据..." }).count(),
        0,
        "switching categories should not replace the workspace with the global loading panel",
      );
      assert.equal(
        await page.getByText("付款申请", { exact: true }).count(),
        0,
        "switching categories should remove the previous category's forms while the next category loads",
      );
    } finally {
      releasePersonnelTemplates();
    }
    await waitForCategoryName(page, "人事");
    assert.equal(
      await templateManagement.evaluate(element => element.isConnected),
      true,
      "the same template management workspace should remain mounted after category data settles",
    );

    await refreshedCategoryNavigation.locator('[data-category-id="category-finance"]').click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("categoryId") === "category-finance");
    await waitForCategoryName(page, "财务");
    await page.getByText("付款申请", { exact: true }).first().waitFor();

    const categoryFailureMessage = "人事分类表单加载失败";
    api.failNextManagedTemplateListRequest(categoryFailureMessage);
    const failedPersonnelResponse = page.waitForResponse(response => {
      const url = new URL(response.url());
      return response.request().method() === "GET"
        && response.status() === 503
        && url.pathname.endsWith("/api/approval-center/templates")
        && url.searchParams.get("scope") === "manage"
        && url.searchParams.get("categoryId") === "category-personnel";
    });
    await refreshedCategoryNavigation.locator('[data-category-id="category-personnel"]').click();
    await failedPersonnelResponse;
    await page.getByRole("alert").filter({ hasText: categoryFailureMessage }).waitFor();
    await waitForCategoryName(page, "人事");
    assert.equal(
      new URL(page.url()).searchParams.get("categoryId"),
      "category-personnel",
      "a failed category request should still leave the requested category explicit in the URL",
    );
    assert.equal(
      await refreshedCategoryNavigation.locator('[data-category-id="category-personnel"]').getAttribute("aria-current"),
      "page",
      "the failed category should remain visibly selected so the error has clear context",
    );
    assert.equal(
      await page.getByText("付款申请", { exact: true }).count(),
      0,
      "a failed category request must not continue showing the previous category's forms",
    );
    assert.equal(
      await page.getByRole("button", { name: "编辑付款申请", exact: true }).count(),
      0,
      "a failed category request must not allow editing a form from the previous category",
    );
    assert.equal(
      await page.locator(".approval-template-table").count(),
      0,
      "a failed category request should clear the stale form table",
    );
    const expectedFailureConsoleIndex = problems.findIndex(problem => (
      problem === "console:error: Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
    ));
    assert.notEqual(expectedFailureConsoleIndex, -1, "the injected 503 should be the only expected browser error");
    problems.splice(expectedFailureConsoleIndex, 1);

    await refreshedCategoryNavigation.locator('[data-category-id="category-finance"]').click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("categoryId") === "category-finance");
    await waitForCategoryName(page, "财务");
    await page.getByText("付款申请", { exact: true }).first().waitFor();
    const templateTable = page.locator(".approval-template-table");
    assert.equal(
      await templateTable.getByRole("columnheader", { name: "序号", exact: true }).count(),
      1,
      "template management should expose a leading sequence-number column",
    );
    assert.deepEqual(
      await templateTable.locator("tbody .approval-template-index-cell").allTextContents(),
      ["1", "2"],
      "template sequence numbers should start at one on the first page",
    );
    assert.deepEqual(
      await templateTable.locator("tbody .approval-primary-cell strong").allInnerTexts(),
      ["付款申请", "报销申请"],
    );
    await page.getByRole("button", { name: "下移付款申请", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "表单顺序已更新" }).waitFor();
    const templateReorder = api.writes.find(call => call.method === "POST" && call.path.endsWith("/templates/reorder"));
    assert.equal(templateReorder?.payload?.categoryId, "category-finance");
    assert.ok(templateReorder?.payload?.revision, "template reorder should carry the loaded revision");
    assert.equal(templateReorder?.payload?.templateId, "tpl-payment");
    assert.equal(templateReorder?.payload?.direction, "down");
    assert.deepEqual(
      await templateTable.locator("tbody .approval-primary-cell strong").allInnerTexts(),
      ["报销申请", "付款申请"],
      "moving a form down should immediately update the visible order",
    );

    const templateStatusFilter = page.getByRole("combobox", { name: "表单状态筛选", exact: true });
    assert.equal(await templateStatusFilter.evaluate(element => element.tagName), "BUTTON");
    await templateStatusFilter.click();
    const statusOptions = page.getByRole("listbox", { name: "表单状态筛选", exact: true });
    assert.equal(await templateStatusFilter.getAttribute("aria-expanded"), "true");
    screenshots.statusMenu = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "desktop-template-status-menu.png"),
      "desktop template status menu",
    );
    assert.equal(
      await statusOptions.getByRole("option", { name: "全部状态", exact: true }).getAttribute("aria-selected"),
      "true",
    );
    await templateStatusFilter.press("Escape");
    await statusOptions.waitFor({ state: "detached" });
    assert.equal(await templateStatusFilter.evaluate(element => document.activeElement === element), true);
    await templateStatusFilter.click();
    await page.getByRole("heading", { name: "表单", exact: true }).click();
    await statusOptions.waitFor({ state: "detached" });
    assert.equal(new URL(page.url()).searchParams.get("status"), null);

    await templateStatusFilter.press("ArrowDown");
    await templateStatusFilter.press("Enter");
    await page.waitForFunction(() => new URL(location.href).searchParams.get("status") === "draft");
    await templateStatusFilter.press("Home");
    await templateStatusFilter.press("Enter");
    await page.waitForFunction(() => !new URL(location.href).searchParams.has("status"));
    await templateStatusFilter.press("End");
    await templateStatusFilter.press("Enter");
    await page.waitForFunction(() => new URL(location.href).searchParams.get("status") === "published");
    await templateStatusFilter.press("Home");
    await templateStatusFilter.press("Enter");
    await page.waitForFunction(() => !new URL(location.href).searchParams.has("status"));

    await templateStatusFilter.click();
    await statusOptions.getByRole("option", { name: "草稿", exact: true }).click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("status") === "draft");
    await templateTable.getByRole("button", { name: "编辑报销申请", exact: true }).waitFor();
    await page.waitForFunction(() => document.querySelectorAll(".approval-template-table tbody tr").length === 1);
    assert.equal(new URL(page.url()).searchParams.get("categoryId"), "category-finance");
    assert.equal(new URL(page.url()).searchParams.get("page"), null);
    assert.equal(new URL(page.url()).searchParams.get("q"), null, "selecting status must not submit the search form");
    assert.equal(await templateStatusFilter.evaluate(element => document.activeElement === element), true);
    assert.ok(api.calls.some(call => (
      call.method === "GET"
      && call.path.endsWith("/templates")
      && call.query.scope === "manage"
      && call.query.status === "draft"
    )), "selecting status should fetch the filtered category");

    await templateStatusFilter.press("ArrowDown");
    await statusOptions.waitFor();
    await templateStatusFilter.press("Home");
    await templateStatusFilter.press("Enter");
    await page.waitForFunction(() => !new URL(location.href).searchParams.has("status"));
    await page.waitForFunction(() => document.querySelectorAll(".approval-template-table tbody tr").length === 2);
    assert.equal(await templateStatusFilter.getAttribute("aria-expanded"), "false");

    await page.getByRole("searchbox", { name: "搜索表单管理", exact: true }).fill("付款");
    await page.getByRole("button", { name: "查询", exact: true }).click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("q") === "付款");
    assert.equal(
      new URL(page.url()).pathname,
      "/approval-center/templates/",
      "template filters should stay within the template management route",
    );
    await page.getByText("付款申请", { exact: true }).first().waitFor();
    await page.getByRole("status").filter({ hasText: "清除搜索和状态筛选后可调整表单顺序" }).waitFor();
    assert.equal(
      await page.getByRole("button", { name: "上移付款申请", exact: true }).isDisabled(),
      true,
      "filtered template results should not allow ambiguous reorder operations",
    );
    await assertTemplateManagementFillsWorkspace(page);
    await assertViewportLayout(page, "desktop template management");
    const formPanel = await page.locator(".approval-category-content").boundingBox();
    const editAction = await page.getByRole("button", { name: "编辑付款申请", exact: true }).boundingBox();
    const updatedAtCell = await templateTable.getByRole("row").filter({ hasText: "付款申请" }).locator("td").nth(4).boundingBox();
    assert.ok(
      formPanel && editAction && editAction.x >= formPanel.x && editAction.x + editAction.width <= formPanel.x + formPanel.width,
      "desktop form actions should remain visible without horizontal scrolling",
    );
    assert.ok(
      updatedAtCell && updatedAtCell.x + updatedAtCell.width <= editAction.x,
      "desktop form actions should not cover the updated date",
    );
    await page.setViewportSize({ width: 1400, height: 900 });
    const compactPanel = await page.locator(".approval-category-content").boundingBox();
    const compactEditAction = await page.getByRole("button", { name: "编辑付款申请", exact: true }).boundingBox();
    assert.ok(
      compactPanel && compactEditAction && compactEditAction.x + compactEditAction.width <= compactPanel.x + compactPanel.width,
      "form actions should fit the narrowest three-column desktop layout",
    );
    await page.setViewportSize({ width: 1440, height: 900 });
    screenshots.templates = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "desktop-template-management.png"),
      "desktop template management",
    );

    const filteredListUrl = page.url();
    const editButton = page.getByRole("button", { name: "编辑付款申请", exact: true });
    const browserPageCount = context.pages().length;
    await editButton.click();
    await page.getByRole("heading", { name: "编辑表单：付款申请", exact: true }).waitFor();
    assert.equal(await page.getByLabel("表单名称").inputValue(), "付款申请");
    assert.equal(new URL(page.url()).pathname, "/approval-center/templates/tpl-payment/edit/");
    assert.equal(new URL(page.url()).searchParams.get("categoryId"), "category-finance");
    assert.equal(await page.title(), "编辑表单：付款申请 - 审批中心");
    assert.equal(context.pages().length, browserPageCount, "editing outside DingTalk stays in the application page");
    const existingEditorSteps = page.getByRole("navigation", { name: "表单配置步骤", exact: true });
    await existingEditorSteps.getByRole("button").filter({ hasText: "表单设计" }).click();
    await page.getByRole("heading", { name: "字段控件", exact: true }).waitFor();
    await page.locator(".form-preview-field").filter({ hasText: "付款金额" }).locator(".form-preview-select").click();
    assert.equal(await page.getByLabel("字段类型").inputValue(), "number");
    await page.getByRole("button", { name: "返回表单管理", exact: true }).click();
    await page.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    assert.equal(page.url(), filteredListUrl, "returning from the editor should retain category and search filters");
    assert.equal(await page.getByRole("tablist", { name: "设置页面", exact: true }).count(), 0);

    const listUrl = page.url();
    const dingTalkPage = await context.newPage();
    await dingTalkPage.addInitScript(() => {
      Object.defineProperty(navigator, "userAgent", { configurable: true, value: `${navigator.userAgent} DingTalk` });
      window.__approvalWorkbenchClicks = [];
      window.__approvalNavigationCalls = [];
      window.open = (...args) => { window.__approvalNavigationCalls.push(["window.open", args]); return null; };
      window.DingTalkPC = { env: { platform: "pc" }, biz: { util: {
        openLink: (...args) => window.__approvalNavigationCalls.push(["DingTalkPC.openLink", args]),
      } } };
      window.dd = { env: { platform: "pc" }, biz: { util: {
        openLink: (...args) => window.__approvalNavigationCalls.push(["dd.openLink", args]),
        invokeWorkbench: (...args) => window.__approvalNavigationCalls.push(["dd.invokeWorkbench", args]),
      } } };
      document.addEventListener("click", (event) => {
        const anchor = event.target.closest?.("a[href^='https://applink.dingtalk.com/page/link']");
        if (!anchor) return;
        window.__approvalWorkbenchClicks.push({ href: anchor.href, trusted: event.isTrusted });
        event.preventDefault();
      }, { capture: true });
    });
    await dingTalkPage.goto(listUrl, { waitUntil: "domcontentloaded" });
    await dingTalkPage.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    const dingTalkEditLink = dingTalkPage.getByRole("link", { name: "编辑付款申请", exact: true });
    await dingTalkEditLink.waitFor();
    const workbenchUrl = new URL(await dingTalkEditLink.getAttribute("href"));
    const editorUrl = new URL("/approval-center/templates/tpl-payment/edit/", listUrl);
    editorUrl.searchParams.set("step", "basic");
    editorUrl.searchParams.set("categoryId", "category-finance");
    editorUrl.searchParams.set("return", `${new URL(listUrl).pathname}${new URL(listUrl).search}`);
    assert.equal(`${workbenchUrl.origin}${workbenchUrl.pathname}`, "https://applink.dingtalk.com/page/link");
    assert.deepEqual([...workbenchUrl.searchParams.keys()], ["url", "targetDesktop"]);
    assert.equal(workbenchUrl.searchParams.get("url"), editorUrl.href);
    assert.equal(workbenchUrl.searchParams.get("targetDesktop"), "workbench");
    assert.equal(await dingTalkEditLink.getAttribute("target"), null, "AppLink must not request an OS browser tab");
    const dingTalkPageCount = context.pages().length;
    await dingTalkEditLink.click();
    assert.deepEqual(await dingTalkPage.evaluate(() => window.__approvalWorkbenchClicks), [
      { href: workbenchUrl.href, trusted: true },
    ], "a real click should hand the AppLink to the DingTalk workbench");
    assert.deepEqual(await dingTalkPage.evaluate(() => window.__approvalNavigationCalls), [], "editing must not open an OS window or call a browser-navigation JSAPI");
    assert.equal(dingTalkPage.url(), listUrl, "opening a workbench tab must preserve the filtered list");
    assert.equal(page.url(), listUrl, "the ordinary-browser list must stay intact");
    assert.equal(context.pages().length, dingTalkPageCount, "intercepted AppLink must not open a Chromium tab");

    const dingTalkEditorPage = await context.newPage();
    await dingTalkEditorPage.goto(editorUrl.href, { waitUntil: "domcontentloaded" });
    await dingTalkEditorPage.getByRole("heading", { name: "编辑表单：付款申请", exact: true }).waitFor();
    assert.equal(await dingTalkEditorPage.title(), "编辑表单：付款申请 - 审批中心");
    assert.equal(await dingTalkEditorPage.getByLabel("表单名称").inputValue(), "付款申请");
    assert.equal(dingTalkPage.url(), listUrl, "loading the editor in another tab must not navigate its source list");

    const dingTalkSteps = dingTalkEditorPage.getByRole("navigation", { name: "表单配置步骤", exact: true });
    await dingTalkSteps.getByRole("button").filter({ hasText: "表单设计" }).click();
    await dingTalkEditorPage.getByRole("heading", { name: "字段控件", exact: true }).waitFor();
    assert.equal(new URL(dingTalkEditorPage.url()).searchParams.get("step"), "form");
    assert.equal(new URL(dingTalkEditorPage.url()).searchParams.get("return"), `${new URL(listUrl).pathname}${new URL(listUrl).search}`);
    await dingTalkSteps.getByRole("button").filter({ hasText: "基础设置" }).click();
    const dingTalkDescription = dingTalkEditorPage.getByLabel("表单说明");
    const editedDescription = `${await dingTalkDescription.inputValue()} 钉钉端内未保存修改`;
    await dingTalkDescription.fill(editedDescription);
    await dingTalkEditorPage.getByText("有未保存修改", { exact: true }).waitFor();

    const leaveEditorDialog = dingTalkEditorPage.getByRole("alertdialog", { name: "是否放弃修改", exact: true });
    await dingTalkEditorPage.getByRole("button", { name: "返回表单管理", exact: true }).click();
    await leaveEditorDialog.waitFor();
    assert.equal(new URL(dingTalkEditorPage.url()).pathname, "/approval-center/templates/tpl-payment/edit/");
    await leaveEditorDialog.getByRole("button", { name: "继续编辑", exact: true }).click();
    assert.equal(await dingTalkDescription.inputValue(), editedDescription, "cancelling should retain unsaved edits");
    await dingTalkEditorPage.getByRole("button", { name: "返回表单管理", exact: true }).click();
    await leaveEditorDialog.waitFor();
    await leaveEditorDialog.getByRole("button", { name: "确认放弃", exact: true }).click();
    await dingTalkEditorPage.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    assert.equal(dingTalkEditorPage.url(), listUrl, "returning from a workbench tab should restore filtered list state");
    assert.equal(dingTalkPage.url(), listUrl, "the original workbench list should retain its filters");
    await dingTalkEditorPage.close();
    await dingTalkPage.close();
    assert.equal(context.pages().length, browserPageCount);

    const legacyTemplatesUrl = new URL("settings/templates/?categoryId=category-finance&q=%E4%BB%98%E6%AC%BE&status=published", baseUrl);
    await page.goto(legacyTemplatesUrl.toString(), { waitUntil: "domcontentloaded" });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/approval-center/templates/");
    assert.equal(new URL(page.url()).searchParams.get("categoryId"), "category-finance");
    assert.equal(new URL(page.url()).searchParams.get("q"), "付款");
    assert.equal(new URL(page.url()).searchParams.get("status"), "published");

    await page.goto(new URL("templates/new/?step=basic&starter=payment", baseUrl).toString(), {
      waitUntil: "domcontentloaded",
    });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "新建审批表单", exact: true }).waitFor();
    assert.equal(await page.getByLabel("表单名称").inputValue(), "付款申请");
    await page.getByLabel("表单说明").fill("验证编辑器内部步骤切换");
    const editorSteps = page.getByRole("navigation", { name: "表单配置步骤", exact: true });
    await editorSteps.getByRole("button").filter({ hasText: "表单设计" }).click();
    await page.getByRole("heading", { name: "字段控件", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "文本", exact: true }).count(), 1);
    assert.equal(await page.getByRole("button", { name: "下拉单选", exact: true }).count(), 1);
    assert.equal(await page.getByRole("button", { name: "下拉多选", exact: true }).count(), 1);
    for (const removedType of ["单行文本", "多行文本", "金额", "单选", "多选"]) {
      assert.equal(
        await page.getByRole("button", { name: removedType, exact: true }).count(),
        0,
        `${removedType} should not be available as a new field type`,
      );
    }
    assert.equal(await page.getByRole("alertdialog").count(), 0, "editor steps should bypass the leave-page guard");
    assert.equal(new URL(page.url()).searchParams.get("step"), "form");
    await assertEditorColumns(page, ".form-designer", [
      ".form-control-palette",
      ".form-canvas-column",
      ".form-property-panel",
    ], "desktop form editor");

    await page.getByRole("button", { name: "下拉单选", exact: true }).click();
    await page.getByLabel("选项（每行一个）").fill("重复选项\n重复选项");
    await editorSteps.getByRole("button").filter({ hasText: "预览发布" }).click();
    await page.getByRole("heading", { name: "发布检查", exact: true }).waitFor();
    await page.getByText("“下拉单选”的选项内容不重复", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "发布表单", exact: true }).isDisabled(), true);
    assert.equal(await page.getByText("流程状态变化时通知发起人", { exact: true }).count(), 0);
    await editorSteps.getByRole("button").filter({ hasText: "表单设计" }).click();
    await page.getByLabel("选项（每行一个）").fill("选项一\n选项二");

    const fieldRows = page.locator(".form-preview-field");
    const initialFieldCount = await fieldRows.count();
    await page.getByRole("button", { name: "文本", exact: true }).click();
    await page.waitForFunction(
      expected => document.querySelectorAll(".form-preview-field").length === expected,
      initialFieldCount + 1,
    );
    assert.equal(await fieldRows.count(), initialFieldCount + 1, "adding a field should append exactly one field");
    const fieldName = page.getByLabel("字段名称");
    await fieldName.fill("审批摘要");
    const textRows = page.getByLabel("行数", { exact: true });
    assert.equal(await textRows.inputValue(), "1");
    await textRows.fill("4");
    await page.getByRole("checkbox", { name: "必填字段", exact: true }).check();
    assert.equal(await fieldName.inputValue(), "审批摘要");
    assert.match(await page.locator(".form-preview-field.active .form-preview-label").innerText(), /审批摘要/);
    await page.getByRole("button", { name: "保存草稿", exact: true }).click();
    await page.waitForURL(url => url.pathname.includes("/templates/tpl-browser-1/edit/"));
    await page.getByRole("heading", { name: "编辑表单：付款申请", exact: true }).waitFor();
    await page.locator(".form-preview-field").filter({ hasText: "审批摘要" }).waitFor();
    assert.ok(
      (await page.locator(".form-preview-label").allInnerTexts()).some(label => label.includes("审批摘要")),
      "saved fields should survive the editor remount",
    );
    await page.locator(".form-preview-field").filter({ hasText: "审批摘要" }).locator(".form-preview-select").click();
    assert.equal(await page.getByLabel("行数", { exact: true }).inputValue(), "4");
    const templateCreate = api.writes.find(call => call.method === "POST" && call.path.endsWith("/templates"));
    assert.ok(templateCreate);
    assert.equal(templateCreate.payload.categoryId, "category-finance");
    const savedSummary = templateCreate.payload.formSchema.fields.find(field => field.label === "审批摘要");
    assert.equal(savedSummary?.type, "text");
    assert.equal(savedSummary?.rows, 4);
    assert.equal(
      templateCreate.payload.formSchema.fields.some(field => ["textarea", "amount", "radio", "checkbox"].includes(field.type)),
      false,
      "new drafts should persist only the current field types",
    );
    assert.equal(
      templateCreate.payload.formSchema.fields.some(field => field.type !== "text" && Object.hasOwn(field, "rows")),
      false,
      "rows should only be persisted for text fields",
    );

    await editorSteps.getByRole("button").filter({ hasText: "流程设置" }).click();
    await page.getByRole("heading", { name: "流程设置", exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("step"), "flow");
    await page.getByRole("button", { name: "审批节点", exact: true }).click();
    await page.getByLabel("节点名称").fill("财务复核");
    await page.getByLabel("人员来源").selectOption("initiator");
    await page.getByText("财务复核", { exact: true }).waitFor();
    await assertEditorColumns(page, ".flow-workspace", [".flow-canvas", ".flow-property-panel"], "desktop flow editor");
    await page.getByRole("button", { name: "保存草稿", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "草稿已保存" }).waitFor();
    await page.getByText("所有修改已保存", { exact: true }).waitFor();
    assert.equal(await page.locator(".template-editor-shell > .approval-alert.is-success").count(), 0);
    screenshots.editor = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "desktop-flow-editor.png"),
      "desktop flow editor",
    );
    await assertViewportLayout(page, "desktop flow editor");

    await page.goto(new URL("templates/new/?step=form&starter=payment", baseUrl).toString(), {
      waitUntil: "domcontentloaded",
    });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "字段控件", exact: true }).waitFor();
    await page.getByRole("button", { name: "下拉单选", exact: true }).click();
    const choiceOptions = page.getByLabel("选项（每行一个）", { exact: true });
    await choiceOptions.fill("");
    await page.getByRole("alert").filter({ hasText: "至少添加 1 个有效选项" }).waitFor();
    const validationSteps = page.getByRole("navigation", { name: "表单配置步骤", exact: true });
    await validationSteps.getByRole("button").filter({ hasText: "流程设置" }).click();
    await page.getByRole("heading", { name: "流程设置", exact: true }).waitFor();
    await page.getByRole("button", { name: "审批节点", exact: true }).click();
    await page.getByLabel("人员来源").selectOption("initiator");
    await validationSteps.getByRole("button").filter({ hasText: "预览发布" }).click();
    await page.getByRole("heading", { name: "发布检查", exact: true }).waitFor();
    await page.getByText(/“下拉单选”至少配置 1 个有效选项/).waitFor();
    assert.equal(
      await page.getByRole("button", { name: "发布表单", exact: true }).isDisabled(),
      true,
      "a choice field without options should block publishing",
    );

    await page.goto(new URL("unknown-route/", baseUrl).toString(), { waitUntil: "domcontentloaded" });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "审批首页", exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/approval-center/");

    assert.deepEqual(api.unexpected, [], "desktop browser should not call an unmocked approval endpoint");
    assert.deepEqual(problems, [], "desktop flow should not emit browser errors or failed requests");
    return { screenshots, apiCalls: api.calls.length, writes: api.writes.length, problems };
  } finally {
    await context.close();
  }
}

async function runMobile(browserInstance) {
  const context = await browserInstance.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();
  const problems = monitorBrowser(page);
  const api = await installApprovalMocks(page, { permissionDirectory: PERMISSION_DIRECTORY });
  api.categoryPermissions.set("category-finance", structuredClone(FINANCE_CATEGORY_PERMISSIONS));
  api.categoryPermissionRevisions.set("category-finance", "revision-finance");
  const screenshots = {};

  try {
    await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "审批首页", exact: true }).waitFor();
    await page.getByRole("button", { name: /付款申请/ }).first().click();
    await page.getByRole("heading", { name: "发起付款申请", exact: true }).waitFor();
    const mobileDescription = page.getByLabel(/^付款说明/);
    assert.equal(await mobileDescription.evaluate(element => element.tagName), "TEXTAREA");
    assert.equal(await mobileDescription.getAttribute("rows"), "3");
    const mobilePaymentChannel = page.getByRole("combobox", { name: "付款渠道", exact: true });
    await mobilePaymentChannel.click();
    await page.getByRole("listbox", { name: "付款渠道", exact: true })
      .getByRole("option", { name: "企业网银", exact: true })
      .click();
    screenshots.application = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "mobile-application-multiselect.png"),
      "mobile application multiselect",
    );
    await assertViewportLayout(page, "mobile application multiselect");
    await mobilePaymentChannel.press("Escape");
    await mobilePaymentChannel.click();
    await page.getByRole("listbox", { name: "付款渠道", exact: true })
      .getByRole("option", { name: "企业网银", exact: true })
      .click();
    await mobilePaymentChannel.press("Escape");
    await page.getByRole("button", { name: "关闭发起审批", exact: true }).click();
    await page.getByRole("heading", { name: "审批首页", exact: true }).waitFor();
    await page.goto(new URL("approvals/", baseUrl).toString());
    await page.getByRole("heading", { name: "审批中心", exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/approval-center/approvals/");
    await page.getByRole("button", { name: "抄送我的", exact: true }).click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("tab") === "copied");
    assert.equal(
      await page.getByRole("button", { name: "抄送我的", exact: true }).getAttribute("aria-current"),
      "page",
    );
    await assertViewportLayout(page, "mobile empty approvals");
    screenshots.approvals = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "mobile-empty-approvals.png"),
      "mobile empty approvals",
    );

    await page.goto(new URL("settings/permissions/", baseUrl).toString());
    await page.getByRole("heading", { name: "权限分配", exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/approval-center/settings/permissions/");
    assert.equal(await page.getByRole("tablist", { name: "设置页面", exact: true }).count(), 0);
    const permissionGrid = await page.locator(".permission-grid").evaluate(grid => {
      const bounds = [...grid.children].map(child => child.getBoundingClientRect());
      return {
        viewportWidth: window.innerWidth,
        widths: bounds.map(box => box.width),
        lefts: bounds.map(box => box.left),
        tops: bounds.map(box => box.top),
        scrollWidth: grid.scrollWidth,
        clientWidth: grid.clientWidth,
      };
    });
    assert.equal(permissionGrid.widths.length, 3);
    assert.ok(permissionGrid.tops[0] < permissionGrid.tops[1] && permissionGrid.tops[1] < permissionGrid.tops[2],
      `mobile permission panels should stack vertically (${JSON.stringify(permissionGrid)})`);
    assert.ok(permissionGrid.widths.every(width => width <= permissionGrid.viewportWidth)
      && permissionGrid.scrollWidth <= permissionGrid.clientWidth + 1,
    `mobile permission workspace should not require page-level horizontal scrolling (${JSON.stringify(permissionGrid)})`);
    await page.getByRole("heading", { name: "具体人员", exact: true }).waitFor();
    assert.equal(await page.locator(".platform-topbar").count(), 0);
    await assertViewportLayout(page, "mobile permission settings");
    screenshots.settingsPermissions = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "mobile-settings-permissions.png"),
      "mobile permission settings",
    );

    await page.goto(new URL("templates/?categoryId=category-finance", baseUrl).toString());
    await page.waitForFunction(() => new URL(location.href).searchParams.get("categoryId") === "category-finance");
    await page.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    await waitForCategoryName(page, "财务");
    await page.getByText("付款申请", { exact: true }).first().waitFor();
    assert.equal(
      await page.locator(".approval-template-table").getByRole("columnheader", { name: "序号", exact: true }).count(),
      1,
      "mobile template management should retain the sequence-number column",
    );
    assert.equal(await page.getByText("全部分类", { exact: true }).count(), 0);
    assert.equal(new URL(page.url()).pathname, "/approval-center/templates/");
    assert.equal(await page.getByRole("tablist", { name: "设置页面", exact: true }).count(), 0);
    const mobileStatusFilter = page.getByRole("combobox", { name: "表单状态筛选", exact: true });
    await mobileStatusFilter.click();
    const mobileStatusOptions = page.getByRole("listbox", { name: "表单状态筛选", exact: true });
    screenshots.statusMenu = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "mobile-template-status-menu.png"),
      "mobile template status menu",
    );
    const mobileOptionBounds = await mobileStatusOptions.getByRole("option", { name: "已发布", exact: true }).boundingBox();
    const mobileMenuBounds = await mobileStatusOptions.boundingBox();
    assert.ok(mobileOptionBounds?.height >= 44, "mobile status options should keep a 44px touch target");
    assert.ok(
      mobileMenuBounds && mobileMenuBounds.x >= 0 && mobileMenuBounds.x + mobileMenuBounds.width <= 390,
      "mobile status menu should fit inside the viewport",
    );
    await assertViewportLayout(page, "mobile template status menu");
    await mobileStatusOptions.getByRole("option", { name: "已发布", exact: true }).click();
    await page.waitForFunction(() => new URL(location.href).searchParams.get("status") === "published");
    await page.getByRole("button", { name: "编辑付款申请", exact: true }).waitFor();
    await mobileStatusFilter.click();
    await mobileStatusOptions.getByRole("option", { name: "全部状态", exact: true }).click();
    await page.waitForFunction(() => !new URL(location.href).searchParams.has("status"));
    const mobileGroupSettings = page.getByRole("complementary", { name: "分组设置", exact: true });
    const mobilePermissionRemoveButton = mobileGroupSettings.getByRole("button", { name: "移除财务部", exact: true });
    const mobilePermissionAddButton = mobileGroupSettings.getByRole("button", { name: "添加部门管理员", exact: true });
    const mobileGroupSettingsSaveButton = mobileGroupSettings.locator('[data-ai-action="approval.category.settings.save"]');
    await mobilePermissionRemoveButton.waitFor();
    await mobileGroupSettings.getByRole("button", { name: "移除财务验收员", exact: true }).waitFor();
    assert.equal(
      await mobileGroupSettings.getByText("已排除人员", { exact: true }).count(),
      0,
      "mobile category permissions should not expose an excluded employees section",
    );
    await mobilePermissionAddButton.waitFor();
    assert.equal(
      await mobileGroupSettings.getByRole("button", { name: "设置财务管理权限", exact: true }).count(),
      0,
      "mobile template management should not expose the legacy category permission entry point",
    );
    assert.equal(
      await mobileGroupSettings.getByRole("button", { name: "保存权限", exact: true }).count(),
      0,
      "mobile template management should use only the unified group-settings save action",
    );
    await assertMobileTemplateManagementStack(page);
    const mobileTemplateMoveButton = page.getByRole("button", { name: "下移付款申请", exact: true });
    assert.ok(
      (await mobileTemplateMoveButton.boundingBox())?.height >= 44,
      "mobile template ordering actions should keep a 44px touch target",
    );
    for (const [control, label] of [
      [mobilePermissionAddButton, "add"],
      [mobilePermissionRemoveButton, "remove"],
      [mobileGroupSettingsSaveButton, "save"],
    ]) {
      assert.ok(
        (await control.boundingBox())?.height >= 44,
        `mobile category permission ${label} action should keep a 44px touch target`,
      );
    }
    await mobilePermissionAddButton.click();
    const mobileDepartmentPicker = page.getByRole("dialog", { name: "添加部门", exact: true });
    const mobileDepartmentCheckbox = mobileDepartmentPicker.getByRole("checkbox", {
      name: "财务部部门",
      exact: true,
    });
    const mobileDepartmentPickerClose = mobileDepartmentPicker.getByRole("button", { name: "关闭", exact: true });
    await mobileDepartmentCheckbox.waitFor();
    assert.equal(
      await mobileDepartmentPicker.getByRole("checkbox", { name: "财务部包含子部门", exact: true }).isChecked(),
      true,
      "mobile department picker should restore the saved include-sub-departments state",
    );
    const mobileDepartmentPickerGeometry = await mobileDepartmentPicker.evaluate((dialog) => {
      const list = dialog.querySelector(".permission-department-list");
      const scrollHost = list?.parentElement;
      const selectTarget = dialog.querySelector(".permission-department-select-target");
      const closeButton = dialog.querySelector('[aria-label="关闭"]');
      const rect = element => element?.getBoundingClientRect();
      return {
        hostClientWidth: scrollHost?.clientWidth || 0,
        hostScrollWidth: scrollHost?.scrollWidth || 0,
        listClientWidth: list?.clientWidth || 0,
        listScrollWidth: list?.scrollWidth || 0,
        selectTarget: rect(selectTarget) ? {
          width: rect(selectTarget).width,
          height: rect(selectTarget).height,
        } : null,
        closeButton: rect(closeButton) ? {
          width: rect(closeButton).width,
          height: rect(closeButton).height,
        } : null,
      };
    });
    assert.ok(
      mobileDepartmentPickerGeometry.hostScrollWidth <= mobileDepartmentPickerGeometry.hostClientWidth + 1
        && mobileDepartmentPickerGeometry.listScrollWidth <= mobileDepartmentPickerGeometry.listClientWidth + 1,
      `mobile department picker should not require horizontal scrolling (${JSON.stringify(mobileDepartmentPickerGeometry)})`,
    );
    assert.ok(
      mobileDepartmentPickerGeometry.selectTarget?.width >= 44
        && mobileDepartmentPickerGeometry.selectTarget?.height >= 44,
      `mobile department selection should keep a 44px touch target (${JSON.stringify(mobileDepartmentPickerGeometry)})`,
    );
    assert.ok(
      mobileDepartmentPickerGeometry.closeButton?.width >= 44
        && mobileDepartmentPickerGeometry.closeButton?.height >= 44,
      `mobile picker close should keep a 44px touch target (${JSON.stringify(mobileDepartmentPickerGeometry)})`,
    );
    await mobileDepartmentPickerClose.focus();
    await page.keyboard.press("Shift+Tab");
    assert.equal(
      await mobileDepartmentPicker.evaluate(dialog => dialog.contains(document.activeElement)),
      true,
      "reverse tabbing from the first picker control should remain inside the modal",
    );
    await page.keyboard.press("Tab");
    assert.equal(
      await mobileDepartmentPickerClose.evaluate(button => button === document.activeElement),
      true,
      "forward tabbing from the last picker control should wrap to the first control",
    );
    screenshots.categoryPermissions = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "mobile-category-permissions.png"),
      "mobile inline category permission picker",
    );
    await assertViewportLayout(page, "mobile inline category permission picker");
    await mobileDepartmentPickerClose.click();
    await mobileDepartmentPicker.waitFor({ state: "detached" });
    assert.equal(
      await mobilePermissionAddButton.evaluate(button => button === document.activeElement),
      true,
      "closing the mobile department picker should restore focus to its trigger",
    );
    const mobilePermissionAddEmployeeButton = mobileGroupSettings.getByRole("button", {
      name: "添加人员管理员",
      exact: true,
    });
    await mobilePermissionAddEmployeeButton.click();
    const mobileEmployeePicker = page.getByRole("dialog", { name: "添加人员", exact: true });
    await mobileEmployeePicker.getByRole("checkbox", { name: "财务验收员管理员", exact: true }).waitFor();
    const mobileEmployeePickerGeometry = await mobileEmployeePicker.evaluate((dialog) => {
      const list = dialog.querySelector(".permission-employee-list");
      const scrollHost = list?.parentElement;
      return {
        hostClientWidth: scrollHost?.clientWidth || 0,
        hostScrollWidth: scrollHost?.scrollWidth || 0,
        listClientWidth: list?.clientWidth || 0,
        listScrollWidth: list?.scrollWidth || 0,
      };
    });
    assert.ok(
      mobileEmployeePickerGeometry.hostScrollWidth <= mobileEmployeePickerGeometry.hostClientWidth + 1
        && mobileEmployeePickerGeometry.listScrollWidth <= mobileEmployeePickerGeometry.listClientWidth + 1,
      `mobile employee picker should not require horizontal scrolling (${JSON.stringify(mobileEmployeePickerGeometry)})`,
    );
    await mobileEmployeePicker.getByRole("button", { name: "关闭", exact: true }).click();
    await mobileEmployeePicker.waitFor({ state: "detached" });
    await assertViewportLayout(page, "mobile template management");
    screenshots.settingsTemplates = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "mobile-settings-templates.png"),
      "mobile template management",
    );

    await page.getByRole("button", { name: "新增审批分类", exact: true }).click();
    const mobileCategoryDialog = page.getByRole("dialog", { name: "新增审批分类", exact: true });
    await mobileCategoryDialog.getByLabel(/^分类名称/).fill("行政");
    await mobileCategoryDialog.getByRole("button", { name: "创建", exact: true }).click();
    await mobileCategoryDialog.waitFor({ state: "detached" });
    const mobileSuccessToast = page.locator(".approval-feedback-toast-panel");
    await mobileSuccessToast.getByText("分类已创建", { exact: true }).waitFor();
    await page.waitForFunction(() => getComputedStyle(document.querySelector(".approval-feedback-toast-panel")).opacity === "1");
    const mobileToastBounds = await mobileSuccessToast.boundingBox();
    assert.ok(mobileToastBounds && mobileToastBounds.y >= 0
      && mobileToastBounds.x >= 0
      && mobileToastBounds.x + mobileToastBounds.width <= page.viewportSize().width
      && mobileToastBounds.y + mobileToastBounds.height <= page.viewportSize().height,
    `mobile success toast should fit within the viewport (${JSON.stringify(mobileToastBounds)})`);
    await page.waitForFunction(() => document.querySelector('.approval-category-item.is-active')?.textContent.includes('行政'));
    const mobileSelectedCategory = await page.locator(".approval-category-list").evaluate(list => {
      const listRect = list.getBoundingClientRect();
      const selectedRect = list.querySelector(".approval-category-item.is-active").getBoundingClientRect();
      return { top: listRect.top, bottom: listRect.bottom, selectedTop: selectedRect.top, selectedBottom: selectedRect.bottom };
    });
    assert.ok(mobileSelectedCategory.selectedTop >= mobileSelectedCategory.top - 1
      && mobileSelectedCategory.selectedBottom <= mobileSelectedCategory.bottom + 1,
    `the newly selected mobile category should be visible in its own list (${JSON.stringify(mobileSelectedCategory)})`);
    await assertViewportLayout(page, "mobile category success toast");
    screenshots.categorySuccess = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "mobile-category-success.png"),
      "mobile category success toast",
    );

    await page.goto(new URL("templates/new/?step=form&starter=payment", baseUrl).toString(), {
      waitUntil: "domcontentloaded",
    });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "字段控件", exact: true }).waitFor();
    await assertViewportLayout(page, "mobile form editor");
    await assertInternalHorizontalScroll(page, ".template-editor-main", ".form-designer", "mobile form editor");
    await assertEditorColumns(page, ".form-designer", [
      ".form-control-palette",
      ".form-canvas-column",
      ".form-property-panel",
    ], "mobile form editor");
    screenshots.form = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "mobile-form-editor.png"),
      "mobile form editor",
    );

    await page.goto(new URL("templates/new/?step=flow&starter=payment", baseUrl).toString(), {
      waitUntil: "domcontentloaded",
    });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "流程设置", exact: true }).waitFor();
    await page.getByRole("button", { name: "审批节点", exact: true }).click();
    await assertViewportLayout(page, "mobile flow editor");
    await assertInternalHorizontalScroll(page, ".template-editor-main", ".flow-workspace", "mobile flow editor");
    await assertEditorColumns(page, ".flow-workspace", [".flow-canvas", ".flow-property-panel"], "mobile flow editor");
    screenshots.flow = await captureNonBlankScreenshot(
      page,
      path.join(outputDirectory, "mobile-flow-editor.png"),
      "mobile flow editor",
    );

    assert.deepEqual(api.unexpected, [], "mobile browser should not call an unmocked approval endpoint");
    assert.deepEqual(problems, [], "mobile flow should not emit browser errors or failed requests");
    return { screenshots, apiCalls: api.calls.length, problems };
  } finally {
    await context.close();
  }
}

async function runCategoryManager(browserInstance) {
  const context = await browserInstance.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const problems = monitorBrowser(page);
  const api = await installApprovalMocks(page, {
    templates: [PAYMENT_TEMPLATE],
    categories: [MANAGEMENT_CATEGORIES[0]],
  });
  const categoryManagerSession = {
    ...TEST_SESSION,
    canManageApp: false,
    canManageTemplates: true,
    managedCategoryIds: ["category-finance"],
    appPermission: "",
  };
  await page.route("**/api/auth/session/validate*", route => route.fulfill({ json: categoryManagerSession }));
  await page.route("**/api/approval-center/session/*", route => route.fulfill({ json: categoryManagerSession }));

  try {
    await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "审批首页", exact: true }).waitFor();
    const sidebarNavigation = page.locator("aside.platform-sidebar.is-fixed")
      .getByRole("navigation", { name: "主导航", exact: true });
    assert.equal(await sidebarNavigation.getByRole("button", { name: "表单管理", exact: true }).count(), 1);
    assert.equal(await sidebarNavigation.getByRole("button", { name: "设置", exact: true }).count(), 0);
    assert.equal(await sidebarNavigation.getByRole("button", { name: "数据中心", exact: true }).count(), 0);

    await sidebarNavigation.getByRole("button", { name: "表单管理", exact: true }).click();
    await page.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    await page.getByRole("button", { name: "编辑付款申请", exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/approval-center/templates/");
    assert.equal(await page.getByRole("button", { name: "新增审批分类", exact: true }).count(), 0);
    assert.equal(await page.getByRole("tablist", { name: "设置页面", exact: true }).count(), 0);

    await page.getByRole("button", { name: "编辑付款申请", exact: true }).click();
    await page.getByRole("heading", { name: "编辑表单：付款申请", exact: true }).waitFor();
    await page.getByRole("button", { name: "返回表单管理", exact: true }).click();
    await page.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/approval-center/templates/");

    await page.goto(new URL("settings/permissions/?categoryId=category-finance", baseUrl).toString(), {
      waitUntil: "domcontentloaded",
    });
    await page.waitForURL(url => url.pathname === "/approval-center/templates/");
    await page.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("categoryId"), "category-finance");
    assert.equal(await sidebarNavigation.getByRole("button", { name: "设置", exact: true }).count(), 0);
    assert.equal(
      api.calls.some(call => call.path.endsWith("/permissions") && call.method === "GET"),
      false,
      "category managers must not request global permission settings",
    );
    assert.deepEqual(api.unexpected, [], "category-manager browser should not call an unmocked approval endpoint");
    assert.deepEqual(problems, [], "category-manager flow should not emit browser errors or failed requests");
    return { apiCalls: api.calls.length, problems };
  } finally {
    await context.close();
  }
}

async function runEmptyCategories(browserInstance) {
  const context = await browserInstance.newContext({ viewport: { width: 1024, height: 768 } });
  const page = await context.newPage();
  const problems = monitorBrowser(page);
  const api = await installApprovalMocks(page, { templates: [], categories: [] });

  try {
    await page.goto(new URL("templates/", baseUrl).toString(), { waitUntil: "domcontentloaded" });
    await waitForSettledPage(page);
    await page.getByRole("heading", { name: "表单管理", exact: true }).waitFor();
    await page.getByText("暂无审批分类", { exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.has("categoryId"), false);
    assert.equal(await page.getByText("全部分类", { exact: true }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "新增审批分类", exact: true }).count(), 1);
    assert.equal(await page.getByRole("button", { name: "新建表单", exact: true }).count(), 0);
    assert.deepEqual(
      api.calls.filter(call => (
        call.method === "GET"
        && call.path.endsWith("/templates")
        && call.query.scope === "manage"
      )),
      [],
      "an empty category directory should not request an unscoped managed template list",
    );
    assert.deepEqual(api.unexpected, [], "empty category flow should not call an unmocked approval endpoint");
    assert.deepEqual(problems, [], "empty category flow should not emit browser errors or failed requests");
    return { apiCalls: api.calls.length, problems };
  } finally {
    await context.close();
  }
}

async function runPaginationNormalization(browserInstance) {
  const context = await browserInstance.newContext({ viewport: { width: 1024, height: 768 } });
  const page = await context.newPage();
  const problems = monitorBrowser(page);
  const paginatedTemplates = Array.from({ length: 25 }, (_, index) => ({
    ...PAYMENT_TEMPLATE,
    id: `tpl-page-${index + 1}`,
    code: `PAGE_TEMPLATE_${index + 1}`,
    name: `分页表单 ${String(index + 1).padStart(2, "0")}`,
    categoryId: "category-finance",
    categoryName: "财务",
    sortOrder: index,
  }));
  const api = await installApprovalMocks(page, {
    templates: paginatedTemplates,
    categories: [MANAGEMENT_CATEGORIES[0]],
  });

  try {
    const oversizedPageUrl = new URL("templates/", baseUrl);
    oversizedPageUrl.searchParams.set("categoryId", "category-finance");
    oversizedPageUrl.searchParams.set("page", "999");
    await page.goto(oversizedPageUrl.toString(), { waitUntil: "domcontentloaded" });
    await waitForSettledPage(page);
    await page.waitForFunction(() => new URL(location.href).searchParams.get("page") === "2");
    await page.getByText("第 2 / 2 页", { exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("categoryId"), "category-finance");
    assert.deepEqual(
      await page.locator(".approval-template-table tbody .approval-primary-cell strong").allInnerTexts(),
      ["分页表单 21", "分页表单 22", "分页表单 23", "分页表单 24", "分页表单 25"],
      "an oversized page should render the server's actual last page",
    );
    assert.deepEqual(
      await page.locator(".approval-template-table tbody .approval-template-index-cell").allTextContents(),
      ["21", "22", "23", "24", "25"],
      "template sequence numbers should account for the current page offset",
    );
    const templateRequests = api.calls.filter(call => (
      call.method === "GET"
      && call.path.endsWith("/templates")
      && call.query.scope === "manage"
    ));
    assert.equal(templateRequests[0]?.query?.page, "999");
    assert.equal(templateRequests[0]?.query?.pageSize, "20");
    assert.deepEqual(api.unexpected, [], "pagination normalization should not call an unmocked approval endpoint");
    assert.deepEqual(problems, [], "pagination normalization should not emit browser errors or failed requests");
    return { apiCalls: api.calls.length, problems };
  } finally {
    await context.close();
  }
}

async function runPermissionFailures(browserInstance) {
  const context = await browserInstance.newContext({ viewport: { width: 1280, height: 800 } });
  const categoryPath = "/categories/category-finance";
  const permissionPath = "/categories/category-finance/permissions";
  const permissionPageUrl = new URL(
    "templates/?categoryId=category-finance",
    baseUrl,
  ).toString();

  async function createScenarioPage() {
    const page = await context.newPage();
    const problems = monitorBrowser(page);
    const api = await installApprovalMocks(page, {
      templates: [PAYMENT_TEMPLATE],
      categories: [MANAGEMENT_CATEGORIES[0]],
      permissionDirectory: PERMISSION_DIRECTORY,
    });
    api.categoryPermissions.set("category-finance", structuredClone(FINANCE_CATEGORY_PERMISSIONS));
    api.categoryPermissionRevisions.set("category-finance", "revision-finance");
    assertAllowedPermissionScopes(
      api.categoryPermissions.get("category-finance"),
      "permission failure finance category fixture",
    );
    return { page, problems, api };
  }

  function categoryPermissionPosts(api) {
    return api.calls.filter(call => (
      call.method === "POST" && decodeURIComponent(call.path).endsWith(permissionPath)
    ));
  }

  function unifiedSaveCalls(api, startIndex = 0) {
    return api.calls.slice(startIndex).filter(call => (
      (call.method === "PATCH" && decodeURIComponent(call.path).endsWith(categoryPath))
      || (call.method === "POST" && decodeURIComponent(call.path).endsWith(permissionPath))
    ));
  }

  function summarizeUnifiedSaveCalls(calls) {
    return calls.map(call => (
      `${call.method}:${decodeURIComponent(call.path).endsWith(permissionPath) ? "permissions" : "category"}`
    ));
  }

  async function prepareCombinedDraft(page, name) {
    const groupSettings = page.getByRole("complementary", { name: "分组设置", exact: true });
    const categoryName = groupSettings.getByLabel("分类名称", { exact: true });
    const save = groupSettings.locator('[data-ai-action="approval.category.settings.save"]');
    await categoryName.fill(name);
    await groupSettings.getByRole("button", { name: "添加人员管理员", exact: true }).click();
    const employeePicker = page.getByRole("dialog", { name: "添加人员", exact: true });
    await employeePicker.getByRole("checkbox", { name: "人事专员管理员", exact: true }).check();
    await employeePicker.getByRole("button", { name: "关闭", exact: true }).click();
    await employeePicker.waitFor({ state: "detached" });
    const draftEmployee = groupSettings.getByRole("button", { name: "移除人事专员", exact: true });
    await draftEmployee.waitFor();
    assert.equal(await save.isEnabled(), true, "a changed name and permissions should enable unified saving");
    return { groupSettings, categoryName, save, draftEmployee };
  }

  function assertExpected503Only(problems, label) {
    const serviceUnavailable = problems.filter(problem => (
      problem.includes("503 (Service Unavailable)")
    ));
    assert.equal(serviceUnavailable.length, 1, `${label} should emit one expected 503 resource error`);
    assert.deepEqual(
      problems.filter(problem => !problem.includes("503 (Service Unavailable)")),
      [],
      `${label} should not emit unrelated browser errors`,
    );
  }

  async function runLoadFailureScenario({ label, message, savedName, injectFailure, responseMatches }) {
    const { page, problems, api } = await createScenarioPage();
    try {
      injectFailure(api);
      const failedResponsePromise = page.waitForResponse(response => (
        response.request().method() === "GET"
        && response.status() === 503
        && responseMatches(new URL(response.url()).pathname)
      ));
      await page.goto(permissionPageUrl, { waitUntil: "domcontentloaded" });
      await failedResponsePromise;
      await waitForSettledPage(page);

      const groupSettings = page.getByRole("complementary", { name: "分组设置", exact: true });
      const alert = groupSettings.getByRole("alert").filter({ hasText: message });
      const addDepartment = groupSettings.getByRole("button", { name: "添加部门管理员", exact: true });
      const addEmployee = groupSettings.getByRole("button", { name: "添加人员管理员", exact: true });
      const categoryName = groupSettings.getByLabel("分类名称", { exact: true });
      const save = groupSettings.locator('[data-ai-action="approval.category.settings.save"]');
      await alert.waitFor();
      await addDepartment.waitFor();
      await addEmployee.waitFor();
      assert.equal(await addDepartment.isDisabled(), true, `${label} should disable adding departments`);
      assert.equal(await addEmployee.isDisabled(), true, `${label} should disable adding employees`);
      assert.equal(await save.isDisabled(), true, `${label} should disable saving`);
      assert.equal(categoryPermissionPosts(api).length, 0, `${label} must not issue a permission POST`);

      await categoryName.fill(savedName);
      assert.equal(
        await save.isEnabled(),
        true,
        `${label} should still allow saving a category-name-only change`,
      );
      const nameSaveCallStart = api.calls.length;
      const categoryPatchPromise = page.waitForResponse(response => (
        response.request().method() === "PATCH"
        && response.status() === 200
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(categoryPath)
      ));
      await save.click();
      const categoryPatch = await categoryPatchPromise;
      await page.getByRole("status").filter({ hasText: "设置已保存" }).waitFor();
      assert.deepEqual(categoryPatch.request().postDataJSON(), { name: savedName });
      assert.deepEqual(
        summarizeUnifiedSaveCalls(unifiedSaveCalls(api, nameSaveCallStart)),
        ["PATCH:category"],
        `${label} should PATCH only the category name while permissions are unavailable`,
      );
      assert.equal(categoryPermissionPosts(api).length, 0, `${label} name save must not issue a permission POST`);
      assert.equal(api.categories.find(category => category.id === "category-finance")?.name, savedName);
      assert.equal(await categoryName.inputValue(), savedName);
      assert.equal(await save.isDisabled(), true, `${label} name save should clear the name dirty state`);

      await page.waitForTimeout(180);
      assert.equal(await alert.isVisible(), true, `${label} should keep the readable error visible`);
      const retry = alert.getByRole("button", { name: "重试", exact: true });
      await retry.waitFor();
      const recoveredResponsePromise = page.waitForResponse(response => (
        response.request().method() === "GET"
        && response.status() === 200
        && responseMatches(new URL(response.url()).pathname)
      ));
      await retry.click();
      await recoveredResponsePromise;
      await groupSettings.getByRole("button", { name: "移除财务部", exact: true }).waitFor();
      assert.equal(await alert.count(), 0, `${label} retry should clear the load error`);
      assert.equal(await categoryName.inputValue(), savedName, `${label} retry should preserve the saved category name`);
      assert.equal(await addDepartment.isEnabled(), true, `${label} retry should restore department editing`);
      assert.equal(await addEmployee.isEnabled(), true, `${label} retry should restore employee editing`);
      assert.equal(await save.isDisabled(), true, `${label} retry should restore a clean loaded draft`);
      assert.equal(categoryPermissionPosts(api).length, 0, `${label} retry must not issue a permission POST`);
      assert.deepEqual(api.unexpected, [], `${label} should not call an unmocked approval endpoint`);
      assertExpected503Only(problems, label);
      return { apiCalls: api.calls.length, permissionPosts: 0 };
    } finally {
      await page.close();
    }
  }

  async function runSaveFailureScenario() {
    const { page, problems, api } = await createScenarioPage();
    const label = "category permission save failure";
    const message = "分类权限暂时无法保存";
    try {
      await page.goto(permissionPageUrl, { waitUntil: "domcontentloaded" });
      await waitForSettledPage(page);
      const groupSettings = page.getByRole("complementary", { name: "分组设置", exact: true });
      const save = groupSettings.locator('[data-ai-action="approval.category.settings.save"]');
      await groupSettings.getByRole("button", { name: "添加人员管理员", exact: true }).click();
      const employeePicker = page.getByRole("dialog", { name: "添加人员", exact: true });
      await employeePicker.getByRole("checkbox", { name: "人事专员管理员", exact: true }).check();
      await employeePicker.getByRole("button", { name: "关闭", exact: true }).click();
      await employeePicker.waitFor({ state: "detached" });
      const draftEmployee = groupSettings.getByRole("button", { name: "移除人事专员", exact: true });
      await draftEmployee.waitFor();
      assert.equal(await save.isEnabled(), true, "editing category permissions should mark the draft dirty");

      api.failNextCategoryPermissionsRequest("category-finance", {
        method: "POST",
        message,
        status: 503,
      });
      const failedResponsePromise = page.waitForResponse(response => (
        response.request().method() === "POST"
        && response.status() === 503
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(permissionPath)
      ));
      await save.click();
      const failedResponse = await failedResponsePromise;
      const failedPayload = failedResponse.request().postDataJSON();
      assertAllowedPermissionScopes(failedPayload.items, `${label} failed payload`);
      const saveAlert = groupSettings.getByRole("alert").filter({ hasText: message });
      const categoryName = groupSettings.getByLabel("分类名称", { exact: true });
      await saveAlert.waitFor();
      assert.equal(await draftEmployee.count(), 1, "a failed save should preserve the permission draft");
      assert.equal(await save.isEnabled(), true, "a failed save should preserve dirty state for retry");
      assert.notEqual(
        await categoryName.getAttribute("aria-invalid"),
        "true",
        "a permission save failure must not mark the category name invalid",
      );
      assert.equal(failedPayload.revision, "revision-finance", "the failed save should use the loaded revision");
      assert.equal(
        api.writes.filter(call => call.method === "POST" && decodeURIComponent(call.path).endsWith(permissionPath)).length,
        0,
        "a failed save must not mutate mock permission state",
      );
      await page.waitForTimeout(180);
      assert.equal(await saveAlert.isVisible(), true, "a save error should remain readable until retry");

      const firstSuccessPromise = page.waitForResponse(response => (
        response.request().method() === "POST"
        && response.status() === 200
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(permissionPath)
      ));
      await save.click();
      const firstSuccess = await firstSuccessPromise;
      const firstSuccessPayload = firstSuccess.request().postDataJSON();
      assertAllowedPermissionScopes(firstSuccessPayload.items, `${label} retry payload`);
      const firstSuccessData = await firstSuccess.json();
      assert.equal(
        firstSuccessPayload.revision,
        "revision-finance",
        "retrying a failed save should retain the original loaded revision",
      );
      assert.deepEqual(
        firstSuccessPayload.items,
        failedPayload.items,
        "retrying a failed save should submit the unchanged permission draft",
      );
      assert.equal(await save.isDisabled(), true, "a successful retry should clear dirty state");
      assert.equal(await saveAlert.count(), 0, "a successful retry should clear the save error");

      await draftEmployee.click();
      assert.equal(await save.isEnabled(), true, "a second edit should create a new dirty draft");
      const secondSuccessPromise = page.waitForResponse(response => (
        response.request().method() === "POST"
        && response.status() === 200
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(permissionPath)
      ));
      await save.click();
      const secondSuccess = await secondSuccessPromise;
      const secondSuccessPayload = secondSuccess.request().postDataJSON();
      assert.equal(
        String(secondSuccessPayload.revision),
        String(firstSuccessData.revision),
        "the next save should use the revision returned by the previous successful save",
      );
      assert.equal(await save.isDisabled(), true, "the second successful save should clear dirty state");
      assert.equal(categoryPermissionPosts(api).length, 3, "the flow should make one failed and two successful saves");
      assert.equal(
        api.writes.filter(call => call.method === "POST" && decodeURIComponent(call.path).endsWith(permissionPath)).length,
        2,
        "only successful category permission saves should mutate mock state",
      );
      assert.deepEqual(api.unexpected, [], `${label} should not call an unmocked approval endpoint`);
      assertExpected503Only(problems, label);
      return {
        apiCalls: api.calls.length,
        permissionPosts: categoryPermissionPosts(api).length,
        firstRevision: String(firstSuccessData.revision),
        secondPayloadRevision: String(secondSuccessPayload.revision),
      };
    } finally {
      await page.close();
    }
  }

  async function runCategoryPatchFailureScenario() {
    const { page, problems, api } = await createScenarioPage();
    const label = "unified save category PATCH failure";
    const message = "分类名称暂时无法保存";
    const nextName = "财务审批";
    try {
      await page.goto(permissionPageUrl, { waitUntil: "domcontentloaded" });
      await waitForSettledPage(page);
      const { groupSettings, categoryName, save, draftEmployee } = await prepareCombinedDraft(page, nextName);

      api.failNextCategoryPatchRequest("category-finance", { message, status: 503 });
      const failedPatchPromise = page.waitForResponse(response => (
        response.request().method() === "PATCH"
        && response.status() === 503
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(categoryPath)
      ));
      await save.click();
      const failedPatch = await failedPatchPromise;
      await groupSettings.getByRole("alert").filter({ hasText: message }).waitFor();
      assert.deepEqual(failedPatch.request().postDataJSON(), { name: nextName });
      assert.equal(categoryPermissionPosts(api).length, 0, "a failed category PATCH must prevent permission POST");
      assert.equal(api.categories.find(category => category.id === "category-finance")?.name, "财务");
      assert.equal(await categoryName.inputValue(), nextName, "a failed PATCH should preserve the name draft");
      assert.equal(await draftEmployee.count(), 1, "a failed PATCH should preserve the permission draft");
      assert.equal(await save.isEnabled(), true, "a failed PATCH should keep both drafts saveable");

      const retryCallStart = api.calls.length;
      const retryPatchPromise = page.waitForResponse(response => (
        response.request().method() === "PATCH"
        && response.status() === 200
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(categoryPath)
      ));
      const retryPermissionPromise = page.waitForResponse(response => (
        response.request().method() === "POST"
        && response.status() === 200
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(permissionPath)
      ));
      await save.click();
      await Promise.all([retryPatchPromise, retryPermissionPromise]);
      const retryPermissionWrite = api.writes.slice().reverse().find(call => (
        call.method === "POST" && decodeURIComponent(call.path).endsWith(permissionPath)
      ));
      assertAllowedPermissionScopes(
        retryPermissionWrite?.payload?.items,
        `${label} retry payload`,
      );
      assert.deepEqual(
        summarizeUnifiedSaveCalls(unifiedSaveCalls(api, retryCallStart)),
        ["PATCH:category", "POST:permissions"],
        "retrying after a failed PATCH should save the name before permissions",
      );
      assert.equal(api.categories.find(category => category.id === "category-finance")?.name, nextName);
      assert.equal(
        api.categoryPermissions.get("category-finance")?.some(item => item.targetId === "employee-hr"),
        true,
        "the retry should persist the preserved permission draft",
      );
      assert.equal(await save.isDisabled(), true, "the successful retry should clear both dirty states");
      assert.deepEqual(api.unexpected, [], `${label} should not call an unmocked approval endpoint`);
      assertExpected503Only(problems, label);
      return {
        apiCalls: api.calls.length,
        retryOrder: summarizeUnifiedSaveCalls(unifiedSaveCalls(api, retryCallStart)),
      };
    } finally {
      await page.close();
    }
  }

  async function runPartialUnifiedSaveFailureScenario() {
    const { page, problems, api } = await createScenarioPage();
    const label = "unified save permission POST failure";
    const permissionMessage = "分类权限暂时无法保存";
    const partialMessage = "分类名称已保存，管理权限保存失败，请重试";
    const nextName = "财务协同";
    try {
      await page.goto(permissionPageUrl, { waitUntil: "domcontentloaded" });
      await waitForSettledPage(page);
      const { groupSettings, categoryName, save, draftEmployee } = await prepareCombinedDraft(page, nextName);

      api.failNextCategoryPermissionsRequest("category-finance", {
        method: "POST",
        message: permissionMessage,
        status: 503,
      });
      const firstAttemptCallStart = api.calls.length;
      const categoryPatchPromise = page.waitForResponse(response => (
        response.request().method() === "PATCH"
        && response.status() === 200
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(categoryPath)
      ));
      const failedPermissionPromise = page.waitForResponse(response => (
        response.request().method() === "POST"
        && response.status() === 503
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(permissionPath)
      ));
      await save.click();
      await Promise.all([categoryPatchPromise, failedPermissionPromise]);
      const failedPermissionRequest = api.permissionRequests.slice().reverse().find(request => (
        request.method === "POST" && decodeURIComponent(request.path).endsWith(permissionPath)
      ));
      assertAllowedPermissionScopes(
        failedPermissionRequest?.payload?.items,
        `${label} failed payload`,
      );
      await groupSettings.getByRole("alert").filter({ hasText: partialMessage }).waitFor();
      assert.deepEqual(
        summarizeUnifiedSaveCalls(unifiedSaveCalls(api, firstAttemptCallStart)),
        ["PATCH:category", "POST:permissions"],
        "the first combined attempt should PATCH the name before the failed permission POST",
      );
      assert.equal(api.categories.find(category => category.id === "category-finance")?.name, nextName);
      assert.equal(await categoryName.inputValue(), nextName, "the successful name change should stay visible");
      assert.notEqual(
        await categoryName.getAttribute("aria-invalid"),
        "true",
        "a failed permission POST after a successful name PATCH must not mark the category name invalid",
      );
      assert.equal(await draftEmployee.count(), 1, "a failed permission POST should preserve its draft");
      assert.equal(
        api.categoryPermissions.get("category-finance")?.some(item => item.targetId === "employee-hr"),
        false,
        "a failed permission POST must not mutate saved permissions",
      );
      assert.equal(await save.isEnabled(), true, "the remaining permission draft should keep saving enabled");

      const retryCallStart = api.calls.length;
      const retryPermissionPromise = page.waitForResponse(response => (
        response.request().method() === "POST"
        && response.status() === 200
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(permissionPath)
      ));
      await save.click();
      await retryPermissionPromise;
      const retryPermissionWrite = api.writes.slice().reverse().find(call => (
        call.method === "POST" && decodeURIComponent(call.path).endsWith(permissionPath)
      ));
      assertAllowedPermissionScopes(
        retryPermissionWrite?.payload?.items,
        `${label} retry payload`,
      );
      assert.deepEqual(
        summarizeUnifiedSaveCalls(unifiedSaveCalls(api, retryCallStart)),
        ["POST:permissions"],
        "retrying a partial save should POST permissions without repeating the successful PATCH",
      );
      assert.equal(
        api.categoryPermissions.get("category-finance")?.some(item => item.targetId === "employee-hr"),
        true,
        "the retry should persist the remaining permission draft",
      );
      assert.equal(await save.isDisabled(), true, "the permission-only retry should clear dirty state");
      assert.equal(
        await groupSettings.getByRole("alert").filter({ hasText: partialMessage }).count(),
        0,
        "the successful retry should clear the partial-save error",
      );
      assert.deepEqual(api.unexpected, [], `${label} should not call an unmocked approval endpoint`);
      assertExpected503Only(problems, label);
      return {
        apiCalls: api.calls.length,
        firstAttemptOrder: summarizeUnifiedSaveCalls(unifiedSaveCalls(api, firstAttemptCallStart))
          .slice(0, 2),
        retryOrder: summarizeUnifiedSaveCalls(unifiedSaveCalls(api, retryCallStart)),
      };
    } finally {
      await page.close();
    }
  }

  async function runStalePermissionSaveScenario() {
    const page = await context.newPage();
    const problems = monitorBrowser(page);
    const api = await installApprovalMocks(page, {
      templates: [PAYMENT_TEMPLATE],
      categories: MANAGEMENT_CATEGORIES,
      permissionDirectory: PERMISSION_DIRECTORY,
    });
    api.categoryPermissions.set("category-finance", structuredClone(FINANCE_CATEGORY_PERMISSIONS));
    api.categoryPermissionRevisions.set("category-finance", "revision-finance");
    api.categoryPermissions.set("category-personnel", structuredClone(PERSONNEL_CATEGORY_PERMISSIONS));
    api.categoryPermissionRevisions.set("category-personnel", "revision-personnel");

    const label = "stale category permission save failure";
    const staleMessage = "旧分类权限保存失败";
    const permissionPostPattern = /\/api\/approval-center\/categories\/category-finance\/permissions\/?(?:\?.*)?$/;
    let releaseHeldResponse = () => {};
    let markPostStarted = () => {};
    const heldResponse = new Promise(resolve => { releaseHeldResponse = resolve; });
    const postStarted = new Promise(resolve => { markPostStarted = resolve; });
    const holdPermissionPost = async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      markPostStarted();
      await heldResponse;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: staleMessage }),
      });
    };

    try {
      await page.route(permissionPostPattern, holdPermissionPost);
      await page.goto(permissionPageUrl, { waitUntil: "domcontentloaded" });
      await waitForSettledPage(page);

      const groupSettings = page.getByRole("complementary", { name: "分组设置", exact: true });
      const categoryNavigation = page.getByRole("navigation", { name: "审批分类列表", exact: true });
      const categoryName = groupSettings.getByLabel("分类名称", { exact: true });
      const save = groupSettings.locator('[data-ai-action="approval.category.settings.save"]');
      await groupSettings.getByRole("button", { name: "添加人员管理员", exact: true }).click();
      const employeePicker = page.getByRole("dialog", { name: "添加人员", exact: true });
      await employeePicker.getByRole("checkbox", { name: "人事专员管理员", exact: true }).check();
      await employeePicker.getByRole("button", { name: "关闭", exact: true }).click();
      await employeePicker.waitFor({ state: "detached" });
      await groupSettings.getByRole("button", { name: "移除人事专员", exact: true }).waitFor();

      await save.click();
      await postStarted;
      assert.equal(await save.getAttribute("aria-busy"), "true", "the old category save should still be pending");

      await categoryNavigation.locator('[data-category-id="category-personnel"]').click();
      const discardDialog = page.getByRole("alertdialog", { name: "是否放弃修改", exact: true });
      await discardDialog.waitFor();
      await discardDialog.getByRole("button", { name: "确认放弃", exact: true }).click();
      await page.waitForFunction(() => (
        new URL(location.href).searchParams.get("categoryId") === "category-personnel"
      ));
      await groupSettings.getByRole("button", { name: "移除人事部", exact: true }).waitFor();
      assert.equal(await categoryName.inputValue(), "人事");

      const staleResponsePromise = page.waitForResponse(response => (
        response.request().method() === "POST"
        && response.status() === 503
        && decodeURIComponent(new URL(response.url()).pathname).endsWith(permissionPath)
      ));
      releaseHeldResponse();
      await staleResponsePromise;
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

      assert.equal(
        await groupSettings.getByRole("alert").filter({ hasText: staleMessage }).count(),
        0,
        "a stale permission failure must not show the old category error in the new category",
      );
      assert.equal(
        await groupSettings.getByRole("alert").filter({ hasText: /管理权限保存失败/ }).count(),
        0,
        "a stale permission failure must not show a generic save error in the new category",
      );
      assert.notEqual(
        await categoryName.getAttribute("aria-invalid"),
        "true",
        "a stale permission failure must not invalidate the new category name",
      );
      assert.equal(await save.isDisabled(), true, "the new category should remain clean after the stale response");
      assert.equal(
        await categoryNavigation.locator('[data-category-id="category-personnel"]').getAttribute("aria-current"),
        "page",
        "the stale response must not change the selected category",
      );
      assert.deepEqual(api.unexpected, [], `${label} should not call an unmocked approval endpoint`);
      assertExpected503Only(problems, label);
      return { apiCalls: api.calls.length, staleErrorVisible: false };
    } finally {
      releaseHeldResponse();
      await page.close();
    }
  }

  try {
    const categoryGet = await runLoadFailureScenario({
      label: "category permission GET failure",
      message: "分类权限加载暂时不可用",
      savedName: "财务权限加载异常",
      injectFailure(api) {
        api.failNextCategoryPermissionsRequest("category-finance", {
          method: "GET",
          message: "分类权限加载暂时不可用",
          status: 503,
        });
      },
      responseMatches(pathname) {
        return decodeURIComponent(pathname).endsWith(permissionPath);
      },
    });
    const directoryGet = await runLoadFailureScenario({
      label: "permission directory GET failure",
      message: "组织权限目录暂时不可用",
      savedName: "财务目录加载异常",
      injectFailure(api) {
        api.failNextPermissionDirectoryRequest("组织权限目录暂时不可用", 503);
      },
      responseMatches(pathname) {
        return pathname.endsWith("/permissions/directory");
      },
    });
    const save = await runSaveFailureScenario();
    const categoryPatchFailure = await runCategoryPatchFailureScenario();
    const partialSaveFailure = await runPartialUnifiedSaveFailureScenario();
    const staleSaveFailure = await runStalePermissionSaveScenario();
    return { categoryGet, directoryGet, save, categoryPatchFailure, partialSaveFailure, staleSaveFailure };
  } finally {
    await context.close();
  }
}

async function waitForCategoryName(page, expectedName) {
  await page.waitForFunction(name => {
    const groupSettings = document.querySelector('[aria-label="分组设置"]');
    return groupSettings?.querySelector('input[aria-label="分类名称"]')?.value === name;
  }, expectedName);
}

async function assertTemplateManagementFillsWorkspace(page) {
  const geometry = await page.evaluate(() => {
    const rectFor = selector => {
      const rect = document.querySelector(selector)?.getBoundingClientRect();
      return rect ? {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      } : null;
    };
    return {
      viewportHeight: window.innerHeight,
      documentHeight: document.documentElement.scrollHeight,
      management: rectFor(".approval-template-management"),
      sidebar: rectFor(".approval-category-sidebar"),
      sidebarActions: rectFor(".approval-category-sidebar-actions"),
      groupDetails: rectFor(".approval-group-details"),
      content: rectFor(".approval-category-content"),
      pagination: rectFor('.approval-pagination[aria-label="表单分页"]'),
    };
  });

  const {
    viewportHeight,
    documentHeight,
    management,
    sidebar,
    sidebarActions,
    groupDetails,
    content,
    pagination,
  } = geometry;
  assert.ok(
    [management, sidebar, sidebarActions, groupDetails, content, pagination].every(Boolean),
    `desktop template management should render every full-height region (${JSON.stringify(geometry)})`,
  );
  assert.ok(
    management.height >= viewportHeight * 0.6,
    `template management should fill the available workspace height (${JSON.stringify(geometry)})`,
  );
  assert.ok(
    viewportHeight - management.bottom <= 16,
    `template management should reach the workspace bottom (${JSON.stringify(geometry)})`,
  );
  assert.ok(
    documentHeight <= viewportHeight + 1,
    `template management should not create an outer page scrollbar (${JSON.stringify(geometry)})`,
  );
  assert.ok(
    [sidebar, groupDetails, content].every(panel => (
      Math.abs(panel.top - management.top) <= 1
      && Math.abs(panel.bottom - management.bottom) <= 1
    )),
    `category, group settings, and form panels should share the full workspace height (${JSON.stringify(geometry)})`,
  );
  assert.ok(
    sidebar.right <= groupDetails.left + 1 && groupDetails.right <= content.left + 1,
    `the three desktop management columns should not overlap (${JSON.stringify(geometry)})`,
  );
  assert.ok(
    Math.abs(sidebarActions.bottom - sidebar.bottom) <= 2,
    `category actions should stay at the bottom of the category panel (${JSON.stringify(geometry)})`,
  );
  assert.ok(
    Math.abs(pagination.bottom - content.bottom) <= 2,
    `form pagination should stay at the bottom of the form panel (${JSON.stringify(geometry)})`,
  );
}

async function assertMobileTemplateManagementStack(page) {
  const geometry = await page.evaluate(() => {
    const rectFor = selector => {
      const rect = document.querySelector(selector)?.getBoundingClientRect();
      return rect ? {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      } : null;
    };
    return {
      viewportWidth: window.innerWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      management: rectFor(".approval-template-management"),
      sidebar: rectFor(".approval-category-sidebar"),
      groupDetails: rectFor(".approval-group-details"),
      content: rectFor(".approval-category-content"),
    };
  });
  const { viewportWidth, documentScrollWidth, bodyScrollWidth, management, sidebar, groupDetails, content } = geometry;
  assert.ok(
    [management, sidebar, groupDetails, content].every(panel => panel?.width > 0 && panel?.height > 0),
    `mobile template management should render all three regions (${JSON.stringify(geometry)})`,
  );
  assert.ok(
    sidebar.bottom <= groupDetails.top + 1 && groupDetails.bottom <= content.top + 1,
    `mobile template management should stack category, group settings, and forms in order (${JSON.stringify(geometry)})`,
  );
  assert.ok(
    [sidebar, groupDetails, content].every(panel => (
      panel.left >= management.left - 1 && panel.right <= management.right + 1
    )),
    `mobile template management regions should stay within their grid (${JSON.stringify(geometry)})`,
  );
  assert.ok(
    documentScrollWidth <= viewportWidth + 1 && bodyScrollWidth <= viewportWidth + 1,
    `mobile template management should not create global horizontal overflow (${JSON.stringify(geometry)})`,
  );
}

async function assertEditorColumns(page, containerSelector, columnSelectors, label) {
  const geometry = await page.evaluate(({ containerSelector: container, columnSelectors: columns }) => {
    const root = document.querySelector(container);
    const rootRect = root?.getBoundingClientRect();
    const rects = columns.map(selector => {
      const rect = document.querySelector(selector)?.getBoundingClientRect();
      return rect ? { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width } : null;
    });
    return { root: rootRect ? { width: rootRect.width, height: rootRect.height } : null, rects };
  }, { containerSelector, columnSelectors });
  assert.ok(geometry.root?.width > 0 && geometry.root?.height > 0, `${label}: editor container should be rendered`);
  assert.ok(geometry.rects.every(Boolean), `${label}: every editor column should be rendered`);
  for (let index = 1; index < geometry.rects.length; index += 1) {
    assert.ok(
      geometry.rects[index - 1].right <= geometry.rects[index].left + 1,
      `${label}: column ${index} overlaps column ${index + 1}`,
    );
  }
  assert.ok(geometry.rects.every(rect => rect.width >= 200), `${label}: editor columns should keep useful widths`);
}

async function assertInternalHorizontalScroll(page, hostSelector, contentSelector, label) {
  const result = await page.evaluate(({ hostSelector: host, contentSelector: content }) => {
    const hostElement = document.querySelector(host);
    const contentElement = document.querySelector(content);
    return {
      hostClientWidth: hostElement?.clientWidth || 0,
      hostScrollWidth: hostElement?.scrollWidth || 0,
      contentWidth: contentElement?.getBoundingClientRect().width || 0,
      overflowX: hostElement ? getComputedStyle(hostElement).overflowX : "",
    };
  }, { hostSelector, contentSelector });
  assert.ok(result.hostClientWidth > 0, `${label}: horizontal scroll host should be rendered`);
  const geometry = JSON.stringify(result);
  assert.ok(result.contentWidth > result.hostClientWidth, `${label}: wide editor should exceed the mobile host (${geometry})`);
  assert.ok(result.hostScrollWidth >= result.contentWidth - 2, `${label}: wide content must remain inside its scroll host (${geometry})`);
  assert.match(result.overflowX, /auto|scroll/, `${label}: horizontal overflow must be handled internally`);
}

async function fileExists(target) {
  try {
    await fs.access(target);
    return true;
  } catch {
    return false;
  }
}
