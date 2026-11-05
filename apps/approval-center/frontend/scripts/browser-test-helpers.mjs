import assert from "node:assert/strict";
import fs from "node:fs/promises";

const ALLOWED_PERMISSION_SCOPES = new Set(["department", "departmentSub", "employee"]);

export const TEST_SESSION = Object.freeze({
  ok: true,
  sessionId: "approval-center-browser-smoke",
  tokenType: "Bearer",
  userId: "approval-smoke-user",
  name: "审批验收用户",
  nick: "审批验收",
  knownEmployee: true,
  status: "active",
  accountStatus: "active",
  canUseSystemAdmin: false,
  canManageApp: true,
  appPermission: "admin",
  canProxy: false,
  isProxying: false,
  actorUserId: "approval-smoke-user",
  actorName: "审批验收用户",
});

export const PAYMENT_TEMPLATE = Object.freeze({
  id: "tpl-payment",
  code: "PAYMENT_REQUEST",
  name: "付款申请",
  description: "收款信息、付款金额和财务审核",
  category: "财务",
  status: "published",
  currentVersion: 3,
  version: 3,
  ownerName: "财务部",
  updatedAt: "2026-09-17T06:00:00Z",
  formSchema: { fields: [
    { id: "field-payee", type: "text", label: "收款方", required: true },
    { id: "field-amount", type: "amount", label: "付款金额", required: true },
    { id: "field-description", type: "text", label: "付款说明", rows: 3, required: false },
    {
      id: "field-channel",
      type: "multiselect",
      label: "付款渠道",
      required: false,
      options: ["企业网银", "银行柜台", "其他"],
    },
  ] },
  flowSchema: {
    nodes: [
      {
        key: "node-finance",
        type: "approver",
        name: "财务审核",
        assigneeType: "initiator",
        assigneeIds: [],
        approvalMode: "all",
      },
    ],
  },
});

const INITIAL_DRAFTS = Object.freeze([
  {
    id: "draft-payment-submit",
    templateId: PAYMENT_TEMPLATE.id,
    templateName: PAYMENT_TEMPLATE.name,
    title: "九月供应商付款",
    values: {
      "field-payee": "星河设备有限公司",
      "field-amount": "1888.50",
    },
    createdAt: "2026-09-17T05:00:00Z",
    updatedAt: "2026-09-17T06:30:00Z",
  },
  {
    id: "draft-payment-delete",
    templateId: PAYMENT_TEMPLATE.id,
    templateName: PAYMENT_TEMPLATE.name,
    title: "待删除付款草稿",
    values: {
      "field-payee": "临时供应商",
      "field-amount": "100",
    },
    createdAt: "2026-09-17T05:10:00Z",
    updatedAt: "2026-09-17T06:40:00Z",
  },
]);

const PROCESSED_TASK = Object.freeze({
  id: "task-processed-approved",
  applicationId: "app-finally-rejected",
  applicationTitle: "已处理付款申请",
  serialNo: "AP202609170001",
  status: "approved",
  nodeName: "财务审核",
  initiatorName: "申请验收员",
  actedAt: "2026-09-17T07:15:00Z",
  application: {
    id: "app-finally-rejected",
    title: "已处理付款申请",
    serialNo: "AP202609170001",
    status: "rejected",
    statusLabel: "已拒绝",
    initiatorName: "申请验收员",
    currentNodeName: "流程已结束",
  },
});

const DEFAULT_CATEGORIES = Object.freeze([
  {
    id: "category-finance",
    name: "财务",
    description: "财务相关审批表单",
    sortOrder: 0,
  },
]);

function categoryIdForTemplate(template, categories) {
  const explicit = String(template?.categoryId ?? template?.category_id ?? "").trim();
  if (explicit) return explicit;
  const categoryName = String(template?.category?.name ?? template?.category ?? "").trim();
  const matched = categories.find(item => String(item.name || "").trim() === categoryName);
  return matched?.id || "category-uncategorized";
}

function categoryNameForTemplate(template, categories) {
  const explicit = String(template?.categoryName ?? template?.category_name ?? "").trim();
  if (explicit) return explicit;
  if (typeof template?.category === "object") return String(template.category?.name || "未分类").trim() || "未分类";
  return String(template?.category || categories.find(item => String(item.id) === categoryIdForTemplate(template, categories))?.name || "未分类").trim() || "未分类";
}

function slugCategoryName(value) {
  return String(value || "未分类").trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, "-") || "uncategorized";
}

export async function installApprovalMocks(page, {
  templates = [PAYMENT_TEMPLATE],
  categories = DEFAULT_CATEGORIES,
  permissionDirectory = { orgRevision: 1, departments: [], employees: [] },
} = {}) {
  let nextManagedTemplateListGate = null;
  let nextManagedTemplateListFailure = null;
  let nextPermissionDirectoryFailure = null;
  const categoryPermissionGates = new Map();
  const categoryPermissionFailures = new Map();
  const categoryPatchFailures = new Map();
  const initialCategories = categories.map((item, index) => ({
    id: String(item?.id ?? `category-${index + 1}`),
    name: String(item?.name || `分类${index + 1}`),
    description: String(item?.description || ""),
    sortOrder: Number.isFinite(Number(item?.sortOrder)) ? Number(item.sortOrder) : index,
    permissionCount: Number(item?.permissionCount || 0),
    canManage: item?.canManage !== false,
  }));
  templates.forEach((item) => {
    const categoryName = categoryNameForTemplate(item, initialCategories);
    if (!categoryName || categoryName === "未分类" || initialCategories.some(category => category.name === categoryName)) return;
    initialCategories.push({
      id: `category-${slugCategoryName(categoryName)}`,
      name: categoryName,
      description: "",
      sortOrder: initialCategories.length,
      permissionCount: 0,
      canManage: true,
    });
  });
  const normalizedTemplates = templates.map((item, index) => ({
    ...structuredClone(item),
    categoryId: categoryIdForTemplate(item, initialCategories),
    categoryName: categoryNameForTemplate(item, initialCategories),
    sortOrder: Number.isFinite(Number(item?.sortOrder ?? item?.categoryOrder))
      ? Number(item.sortOrder ?? item.categoryOrder)
      : index,
  }));
  const state = {
    calls: [],
    writes: [],
    permissionRequests: [],
    unexpected: [],
    templates: normalizedTemplates,
    categories: initialCategories,
    categoryPermissions: new Map(),
    categoryPermissionRevisions: new Map(),
    categoryRevision: 1,
    templateRevision: 1,
    drafts: INITIAL_DRAFTS.map((item) => structuredClone(item)),
    applications: [],
    processedTasks: [structuredClone(PROCESSED_TASK)],
    holdNextManagedTemplateListRequest() {
      if (nextManagedTemplateListGate) {
        throw new Error("A managed template list request is already being held");
      }
      let release;
      const pending = new Promise((resolve) => {
        release = resolve;
      });
      nextManagedTemplateListGate = { pending, release };
      return release;
    },
    failNextManagedTemplateListRequest(message = "分类表单加载失败", status = 503) {
      nextManagedTemplateListFailure = { message, status };
    },
    failNextCategoryPermissionsRequest(categoryId, {
      method = "GET",
      message = "分类权限请求失败",
      status = 503,
    } = {}) {
      const id = String(categoryId);
      const normalizedMethod = String(method).toUpperCase();
      if (!id || !["GET", "POST"].includes(normalizedMethod)) {
        throw new Error("Category permission failures require a category id and GET or POST method");
      }
      const key = `${normalizedMethod}:${id}`;
      const failures = categoryPermissionFailures.get(key) || [];
      failures.push({ message, status });
      categoryPermissionFailures.set(key, failures);
    },
    failNextCategoryPatchRequest(categoryId, {
      message = "分类保存失败",
      status = 503,
    } = {}) {
      const id = String(categoryId);
      if (!id) throw new Error("Category PATCH failures require a category id");
      const failures = categoryPatchFailures.get(id) || [];
      failures.push({ message, status });
      categoryPatchFailures.set(id, failures);
    },
    failNextPermissionDirectoryRequest(message = "权限目录加载失败", status = 503) {
      nextPermissionDirectoryFailure = { message, status };
    },
    holdCategoryPermissionsRequest(categoryId) {
      const id = String(categoryId);
      if (categoryPermissionGates.has(id)) {
        throw new Error(`A category permission request is already being held for ${id}`);
      }
      let release;
      const pending = new Promise((resolve) => {
        release = resolve;
      });
      categoryPermissionGates.set(id, { pending, release });
      return release;
    },
  };

  await page.addInitScript(({ key, session }) => {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(session));
    } catch {
      // The init script also runs in opaque initial documents.
    }
  }, { key: "mj_program_login_session", session: TEST_SESSION });

  await page.route("**/api/auth/session/validate*", route => fulfillJson(route, TEST_SESSION));
  await page.route("**/api/auth/logout*", route => fulfillJson(route, { ok: true }));
  await page.route("**/api/auth/proxy/stop*", route => fulfillJson(route, TEST_SESSION));
  await page.route("**/api/feedback/task-summary*", route => fulfillJson(route, {
    ok: true,
    awaitingConfirmationCount: 0,
    inProgressCount: 0,
  }));

  await page.route("**/api/approval-center/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/\/+$/, "");
    const method = request.method();
    state.calls.push({ method, path, query: Object.fromEntries(url.searchParams) });

    if (path.endsWith("/session") && method === "GET") {
      return fulfillJson(route, TEST_SESSION);
    }
    if (path.endsWith("/workspace") && method === "GET") {
      return fulfillJson(route, {
        ok: true,
        counts: { pending: 0, returned: 0, drafts: state.drafts.length, initiated: state.applications.length },
        recentTemplates: state.templates.filter(item => item.status === "published"),
        recentApplications: state.applications,
      });
    }

    const categoryPermissionMatch = path.match(/\/categories\/([^/]+)\/permissions$/);
    const categoryItemMatch = path.match(/\/categories\/([^/]+)$/);
    if (path.endsWith("/categories") && method === "GET") {
      const counts = new Map();
      state.templates.forEach((template) => {
        const id = categoryIdForTemplate(template, state.categories);
        counts.set(id, (counts.get(id) || 0) + 1);
      });
      const items = state.categories
        .map((category) => ({
          ...category,
          templateCount: Math.max(Number(category.templateCount || 0), counts.get(String(category.id)) || 0),
          permissionCount: (state.categoryPermissions.get(String(category.id)) || []).length,
        }))
        .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name, "zh-Hans-CN"));
      return fulfillJson(route, { ok: true, items, categories: items, revision: state.categoryRevision });
    }
    if (path.endsWith("/categories") && method === "POST") {
      const payload = request.postDataJSON() || {};
      const name = String(payload.name || "").trim() || "未命名分类";
      const baseId = `category-${slugCategoryName(name)}`;
      let id = baseId;
      let suffix = 2;
      while (state.categories.some(category => String(category.id) === id)) id = `${baseId}-${suffix++}`;
      const item = {
        id,
        name,
        description: String(payload.description || ""),
        sortOrder: state.categories.length,
        permissionCount: 0,
        canManage: true,
      };
      state.categories.push(item);
      state.categoryRevision += 1;
      state.writes.push({ method, path, payload });
      return fulfillJson(route, { ok: true, item, category: item, revision: state.categoryRevision }, 201);
    }
    if (path.endsWith("/categories/reorder") && method === "POST") {
      const payload = request.postDataJSON() || {};
      const items = Array.isArray(payload.items) ? payload.items : [];
      const orderMap = new Map(items.map((item, index) => [String(item?.id), Number.isFinite(Number(item?.sortOrder)) ? Number(item.sortOrder) : index]));
      state.categories = state.categories
        .map(category => ({ ...category, sortOrder: orderMap.has(String(category.id)) ? orderMap.get(String(category.id)) : category.sortOrder }))
        .sort((left, right) => left.sortOrder - right.sortOrder);
      state.categoryRevision += 1;
      state.writes.push({ method, path, payload });
      return fulfillJson(route, { ok: true, items: state.categories, revision: state.categoryRevision });
    }
    if (categoryPermissionMatch && ["GET", "POST"].includes(method)) {
      const categoryId = decodeURIComponent(categoryPermissionMatch[1]);
      const current = structuredClone(state.categoryPermissions.get(categoryId) || []);
      const payload = method === "POST" ? (request.postDataJSON() || {}) : null;
      if (payload) state.permissionRequests.push({ method, path, payload });
      const failureKey = `${method}:${categoryId}`;
      const failures = categoryPermissionFailures.get(failureKey) || [];
      const failure = failures.shift();
      if (failures.length) categoryPermissionFailures.set(failureKey, failures);
      else categoryPermissionFailures.delete(failureKey);
      if (failure) return fulfillJson(route, { error: failure.message }, failure.status);
      if (method === "GET") {
        const revision = String(state.categoryPermissionRevisions.get(categoryId) ?? "1");
        const gate = categoryPermissionGates.get(categoryId);
        if (gate) {
          categoryPermissionGates.delete(categoryId);
          await gate.pending;
        }
        return fulfillJson(route, {
          ok: true,
          items: current,
          rules: current,
          revision,
          orgRevision: permissionDirectory.orgRevision ?? 1,
        });
      }
      const next = Array.isArray(payload.items) ? payload.items : (Array.isArray(payload.rules) ? payload.rules : []);
      const invalidScopes = next.filter(item => !ALLOWED_PERMISSION_SCOPES.has(String(item?.scopeType ?? item?.scope_type ?? "")));
      if (invalidScopes.length) {
        state.unexpected.push({
          method,
          path,
          reason: "permission payload contains unsupported scope",
          scopes: invalidScopes.map(item => String(item?.scopeType ?? item?.scope_type ?? "")),
        });
        return fulfillJson(route, { error: "权限范围不受支持" }, 422);
      }
      state.categoryPermissions.set(categoryId, next.map((item, index) => ({
        ...item,
        targetId: String(item?.targetId ?? item?.target_id ?? ""),
        targetName: String(item?.targetName ?? item?.target_name ?? ""),
        sortOrder: Number.isFinite(Number(item?.sortOrder)) ? Number(item.sortOrder) : index,
      })));
      const currentRevision = Number.parseInt(
        String(state.categoryPermissionRevisions.get(categoryId) ?? "1"),
        10,
      );
      const nextRevision = String(Number.isSafeInteger(currentRevision) && currentRevision >= 1
        ? currentRevision + 1
        : 2);
      state.categoryPermissionRevisions.set(categoryId, nextRevision);
      state.writes.push({ method, path, payload });
      return fulfillJson(route, {
        ok: true,
        items: state.categoryPermissions.get(categoryId),
        rules: state.categoryPermissions.get(categoryId),
        revision: nextRevision,
        orgRevision: permissionDirectory.orgRevision ?? 1,
      });
    }
    if (categoryItemMatch && ["GET", "PATCH"].includes(method)) {
      const categoryId = decodeURIComponent(categoryItemMatch[1]);
      const category = state.categories.find(item => String(item.id) === categoryId);
      if (!category) return fulfillJson(route, { error: "分类不存在" }, 404);
      if (method === "GET") return fulfillJson(route, { ok: true, item: category, category });
      const failures = categoryPatchFailures.get(categoryId) || [];
      const failure = failures.shift();
      if (failures.length) categoryPatchFailures.set(categoryId, failures);
      else categoryPatchFailures.delete(categoryId);
      if (failure) return fulfillJson(route, { error: failure.message }, failure.status);
      const payload = request.postDataJSON() || {};
      Object.assign(category, {
        ...(payload.name !== undefined ? { name: String(payload.name || "").trim() } : {}),
        ...(payload.description !== undefined ? { description: String(payload.description || "") } : {}),
      });
      state.categoryRevision += 1;
      state.writes.push({ method, path, payload });
      return fulfillJson(route, { ok: true, item: category, category, revision: state.categoryRevision });
    }

    if (path.endsWith("/templates/reorder") && method === "POST") {
      const payload = request.postDataJSON() || {};
      const categoryId = String(payload.categoryId || "");
      if (payload.templateId && ["up", "down"].includes(payload.direction)) {
        const ordered = state.templates
          .filter(template => categoryIdForTemplate(template, state.categories) === categoryId)
          .sort((left, right) => left.sortOrder - right.sortOrder);
        const sourceIndex = ordered.findIndex(template => String(template.id) === String(payload.templateId));
        const targetIndex = sourceIndex + (payload.direction === "up" ? -1 : 1);
        if (sourceIndex >= 0 && targetIndex >= 0 && targetIndex < ordered.length) {
          [ordered[sourceIndex], ordered[targetIndex]] = [ordered[targetIndex], ordered[sourceIndex]];
        }
        const orderMap = new Map(ordered.map((template, index) => [String(template.id), index]));
        state.templates = state.templates.map(template => (
          orderMap.has(String(template.id)) ? { ...template, sortOrder: orderMap.get(String(template.id)) } : template
        ));
      } else {
        const items = Array.isArray(payload.items) ? payload.items : [];
        const orderMap = new Map(items.map((item, index) => [String(item?.id), Number.isFinite(Number(item?.sortOrder)) ? Number(item.sortOrder) : index]));
        state.templates = state.templates.map(template => (
          categoryIdForTemplate(template, state.categories) === categoryId && orderMap.has(String(template.id))
            ? { ...template, sortOrder: orderMap.get(String(template.id)) }
            : template
        ));
      }
      state.templates.sort((left, right) => left.sortOrder - right.sortOrder);
      state.templateRevision += 1;
      state.writes.push({ method, path, payload });
      return fulfillJson(route, { ok: true, items: state.templates, revision: state.templateRevision });
    }

    const templateMatch = path.match(/\/templates\/([^/]+)$/);
    if (path.endsWith("/templates") && method === "GET") {
      if (url.searchParams.get("scope") === "manage" && nextManagedTemplateListGate) {
        const gate = nextManagedTemplateListGate;
        nextManagedTemplateListGate = null;
        await gate.pending;
      }
      if (url.searchParams.get("scope") === "manage" && nextManagedTemplateListFailure) {
        const failure = nextManagedTemplateListFailure;
        nextManagedTemplateListFailure = null;
        return fulfillJson(route, { error: failure.message }, failure.status);
      }
      const status = url.searchParams.get("status");
      const q = String(url.searchParams.get("q") || "").toLowerCase();
      const categoryId = String(url.searchParams.get("categoryId") || "").trim();
      const category = String(url.searchParams.get("category") || "").trim();
      const filtered = state.templates.filter(item => (
        (!status || item.status === status)
        && (!q || `${item.name} ${item.category}`.toLowerCase().includes(q))
        && (!categoryId || categoryIdForTemplate(item, state.categories) === categoryId)
        && (!category || categoryNameForTemplate(item, state.categories) === category)
      ));
      const ordered = filtered
        .slice()
        .sort((left, right) => left.sortOrder - right.sortOrder || String(left.name || "").localeCompare(String(right.name || ""), "zh-Hans-CN"));
      const requestedPage = Math.max(1, Number.parseInt(url.searchParams.get("page") || "1", 10) || 1);
      const pageSize = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("pageSize") || "20", 10) || 20));
      const totalPages = Math.max(1, Math.ceil(ordered.length / pageSize));
      const page = Math.min(requestedPage, totalPages);
      const start = (page - 1) * pageSize;
      const items = ordered.slice(start, start + pageSize);
      return fulfillJson(route, {
        ok: true,
        templates: items,
        items,
        page,
        pageSize,
        total: ordered.length,
        totalPages,
        count: ordered.length,
        revision: state.templateRevision,
        categories: state.categories.map(item => item.name),
      });
    }
    if (path.endsWith("/templates") && method === "POST") {
      const payload = request.postDataJSON() || {};
      state.writes.push({ method, path, payload });
      const item = {
        id: `tpl-browser-${state.templates.filter(template => String(template.id).startsWith("tpl-browser-")).length + 1}`,
        status: "draft",
        currentVersion: 1,
        updatedAt: "2026-09-17T07:00:00Z",
        ...payload,
      };
      item.categoryId = categoryIdForTemplate(item, state.categories);
      item.categoryName = categoryNameForTemplate(item, state.categories);
      item.sortOrder = Number.isFinite(Number(payload.sortOrder)) ? Number(payload.sortOrder) : state.templates.length;
      state.templates.push(item);
      state.templateRevision += 1;
      return fulfillJson(route, { ok: true, item, template: item }, 201);
    }
    if (templateMatch && method === "GET") {
      const item = state.templates.find(template => String(template.id) === decodeURIComponent(templateMatch[1]));
      return item
        ? fulfillJson(route, { ok: true, item, template: item })
        : fulfillJson(route, { error: "表单不存在" }, 404);
    }
    if (templateMatch && ["PATCH", "PUT"].includes(method)) {
      const payload = request.postDataJSON() || {};
      state.writes.push({ method, path, payload });
      const id = decodeURIComponent(templateMatch[1]);
      const index = state.templates.findIndex(template => String(template.id) === id);
      const item = { ...(state.templates[index] || { id }), ...payload };
      item.categoryId = categoryIdForTemplate(item, state.categories);
      item.categoryName = categoryNameForTemplate(item, state.categories);
      item.sortOrder = Number.isFinite(Number(item.sortOrder ?? item.categoryOrder)) ? Number(item.sortOrder ?? item.categoryOrder) : (state.templates[index]?.sortOrder || index);
      if (index >= 0) state.templates.splice(index, 1, item);
      else state.templates.push(item);
      state.templateRevision += 1;
      return fulfillJson(route, { ok: true, item, template: item });
    }
    if (/\/templates\/[^/]+\/publish$/.test(path) && method === "POST") {
      state.writes.push({ method, path, payload: request.postDataJSON() || {} });
      return fulfillJson(route, { ok: true, status: "published", version: 1 });
    }
    if (/\/templates\/[^/]+\/versions$/.test(path) && method === "GET") {
      return fulfillJson(route, { ok: true, items: [], versions: [] });
    }

    if (path.endsWith("/permissions/directory") && method === "GET") {
      if (nextPermissionDirectoryFailure) {
        const failure = nextPermissionDirectoryFailure;
        nextPermissionDirectoryFailure = null;
        return fulfillJson(route, { error: failure.message }, failure.status);
      }
      return fulfillJson(route, permissionDirectory);
    }
    if (path.endsWith("/permissions") && method === "GET") {
      return fulfillJson(route, { revision: 1, items: [] });
    }

    if (path.endsWith("/directory/form-options") && method === "GET") {
      return fulfillJson(route, {
        ok: true,
        directorySource: "organization",
        orgRevision: 1,
        employees: [
          { userId: "employee-finance", name: "财务验收员", departments: [{ deptId: 10, name: "财务部" }] },
          { userId: "employee-manager", name: "部门负责人", departments: [{ deptId: 20, name: "管理部" }] },
        ],
        departments: [
          { deptId: 10, name: "财务部", parentDeptId: 1 },
          { deptId: 20, name: "管理部", parentDeptId: 1 },
        ],
      });
    }
    if (/\/directory\/(employees|departments)$/.test(path) && method === "GET") {
      return fulfillJson(route, {
        ok: true,
        items: [
          { id: "employee-finance", userId: "employee-finance", name: "财务验收员", departments: [{ name: "财务部" }] },
          { id: "employee-manager", userId: "employee-manager", name: "部门负责人", departments: [{ name: "管理部" }] },
        ],
      });
    }

    const draftMatch = path.match(/\/drafts\/([^/]+)$/);
    if (draftMatch && method === "GET") {
      const id = decodeURIComponent(draftMatch[1]);
      const item = state.drafts.find(draft => String(draft.id) === id);
      return item
        ? fulfillJson(route, { ok: true, item, draft: item })
        : fulfillJson(route, { error: "草稿不存在" }, 404);
    }
    if (draftMatch && method === "DELETE") {
      const id = decodeURIComponent(draftMatch[1]);
      state.writes.push({ method, path });
      const index = state.drafts.findIndex(draft => String(draft.id) === id);
      if (index < 0) return fulfillJson(route, { error: "草稿不存在" }, 404);
      state.drafts.splice(index, 1);
      return fulfillJson(route, { ok: true });
    }
    if (draftMatch && ["PATCH", "PUT"].includes(method)) {
      const id = decodeURIComponent(draftMatch[1]);
      const payload = request.postDataJSON() || {};
      state.writes.push({ method, path, payload });
      const index = state.drafts.findIndex(draft => String(draft.id) === id);
      const item = {
        ...(state.drafts[index] || { id }),
        ...payload,
        id,
        templateName: PAYMENT_TEMPLATE.name,
        updatedAt: "2026-09-17T08:00:00Z",
      };
      if (index >= 0) state.drafts.splice(index, 1, item);
      else state.drafts.push(item);
      return fulfillJson(route, { ok: true, item, draft: item });
    }
    if (path.endsWith("/drafts") && method === "POST") {
      const payload = request.postDataJSON() || {};
      state.writes.push({ method, path, payload });
      const item = {
        id: `draft-browser-${state.writes.length}`,
        templateName: PAYMENT_TEMPLATE.name,
        createdAt: "2026-09-17T08:00:00Z",
        updatedAt: "2026-09-17T08:00:00Z",
        ...payload,
      };
      state.drafts.push(item);
      return fulfillJson(route, { ok: true, item, draft: item }, 201);
    }
    if (path.endsWith("/drafts") && method === "GET") {
      const q = String(url.searchParams.get("q") || "").toLowerCase();
      const items = state.drafts.filter(item => (
        !q || `${item.title} ${item.templateName}`.toLowerCase().includes(q)
      ));
      return fulfillJson(route, { ok: true, drafts: items, items, total: items.length });
    }

    const applicationActionMatch = path.match(/\/applications\/([^/]+)\/(approve|reject|return|withdraw)$/);
    if (applicationActionMatch && method === "POST") {
      const id = decodeURIComponent(applicationActionMatch[1]);
      const action = applicationActionMatch[2];
      const payload = request.postDataJSON() || {};
      state.writes.push({ method, path, payload });
      const index = state.applications.findIndex(application => String(application.id) === id);
      if (index < 0) return fulfillJson(route, { error: "审批申请不存在" }, 404);
      const statusByAction = {
        approve: "approved",
        reject: "rejected",
        return: "returned",
        withdraw: "withdrawn",
      };
      const statusLabelByAction = {
        approve: "已通过",
        reject: "已拒绝",
        return: "已退回",
        withdraw: "已撤回",
      };
      const taskStatusByAction = {
        approve: "approved",
        reject: "rejected",
        return: "returned",
        withdraw: "cancelled",
      };
      const application = {
        ...state.applications[index],
        status: statusByAction[action],
        statusLabel: statusLabelByAction[action],
        currentNodeName: "",
        availableActions: [],
        revision: Number(state.applications[index].revision || 1) + 1,
        updatedAt: "2026-09-17T08:10:00Z",
        tasks: state.applications[index].tasks.map(task => (
          String(task.id) === String(payload.taskId)
            ? { ...task, status: taskStatusByAction[action], canAct: false, comment: payload.comment || "", actedAt: "2026-09-17T08:10:00Z" }
            : task
        )),
      };
      state.applications.splice(index, 1, application);
      return fulfillJson(route, { ok: true, item: application, application });
    }
    const applicationMatch = path.match(/\/applications\/([^/]+)$/);
    if (applicationMatch && method === "GET") {
      const id = decodeURIComponent(applicationMatch[1]);
      const item = state.applications.find(application => String(application.id) === id);
      return item
        ? fulfillJson(route, { ok: true, item, application: item })
        : fulfillJson(route, { error: "审批申请不存在" }, 404);
    }
    if (path.endsWith("/applications") && method === "POST") {
      const payload = request.postDataJSON() || {};
      state.writes.push({ method, path, payload });
      const template = state.templates.find(item => String(item.id) === String(payload.templateId)) || PAYMENT_TEMPLATE;
      const sequence = state.applications.length + 1;
      const application = {
        id: `app-submitted-${sequence}`,
        serialNo: `AP20260917${String(sequence).padStart(4, "0")}`,
        title: payload.title || template.name,
        templateId: template.id,
        templateName: template.name,
        initiatorName: TEST_SESSION.name,
        status: "pending",
        statusLabel: "审批中",
        currentNodeName: "财务审核",
        submittedAt: "2026-09-17T08:00:00Z",
        updatedAt: "2026-09-17T08:00:00Z",
        revision: 1,
        formSchema: structuredClone(template.formSchema),
        values: structuredClone(payload.values || {}),
        settings: { requireApprovalComment: false, requireRejectComment: true, requireReturnComment: true },
        tasks: [{
          id: `task-submitted-${sequence}`,
          nodeName: "财务审核",
          taskType: "approver",
          assigneeUserId: TEST_SESSION.userId,
          assigneeName: TEST_SESSION.name,
          status: "pending",
          canAct: true,
          activatedAt: "2026-09-17T08:00:00Z",
        }],
        events: [{
          id: `event-submitted-${sequence}`,
          action: "submitted",
          actionLabel: "提交审批",
          actorName: TEST_SESSION.name,
          createdAt: "2026-09-17T08:00:00Z",
        }],
        availableActions: ["approve", "reject", "return"],
      };
      state.applications.push(application);
      if (payload.draftId) {
        const draftIndex = state.drafts.findIndex(draft => String(draft.id) === String(payload.draftId));
        if (draftIndex >= 0) state.drafts.splice(draftIndex, 1);
      }
      return fulfillJson(route, { ok: true, item: application, application }, 201);
    }
    if (path.endsWith("/applications") && method === "GET") {
      return fulfillJson(route, {
        ok: true,
        applications: state.applications,
        items: state.applications,
        total: state.applications.length,
      });
    }
    if (path.endsWith("/tasks") && method === "GET") {
      const items = url.searchParams.get("view") === "processed" ? state.processedTasks : [];
      return fulfillJson(route, { ok: true, tasks: items, items, total: items.length });
    }
    if (path.endsWith("/exceptions") && method === "GET") {
      return fulfillJson(route, { ok: true, exceptions: [], items: [], total: 0 });
    }
    if (method === "GET") {
      state.unexpected.push({ method, path });
      return fulfillJson(route, { ok: true, items: [], total: 0 });
    }
    state.unexpected.push({ method, path });
    state.writes.push({ method, path, payload: request.postDataJSON() || {} });
    return fulfillJson(route, { ok: true, item: {} });
  });

  return state;
}

export function monitorBrowser(page) {
  const problems = [];
  page.on("console", message => {
    if (["warning", "error"].includes(message.type())) {
      problems.push(`console:${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", error => problems.push(`pageerror: ${error.message}`));
  page.on("requestfailed", request => {
    const failure = request.failure()?.errorText || "request failed";
    problems.push(`requestfailed: ${request.method()} ${request.url()} (${failure})`);
  });
  return problems;
}

export async function waitForSettledPage(page) {
  await page.locator("body").waitFor({ state: "visible" });
  await page.waitForFunction(() => !document.body.innerText.includes("正在加载审批数据..."));
  await page.waitForTimeout(120);
}

export async function assertViewportLayout(page, label) {
  const result = await page.evaluate(() => {
    const root = document.documentElement;
    const visible = element => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && rect.width > 2 && rect.height > 2;
    };
    const clippedText = [...document.querySelectorAll("button, [role='tab'], h1, h2, h3")]
      .filter(visible)
      .filter(element => element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2)
      .map(element => (element.getAttribute("aria-label") || element.textContent || element.tagName).trim().slice(0, 80));
    return {
      viewportWidth: window.innerWidth,
      documentWidth: root.scrollWidth,
      clippedText,
      bodyTextLength: document.body.innerText.trim().length,
    };
  });
  assert.ok(result.bodyTextLength > 20, `${label}: the page should contain meaningful visible text`);
  assert.ok(
    result.documentWidth <= result.viewportWidth + 2,
    `${label}: document width ${result.documentWidth}px exceeds viewport ${result.viewportWidth}px`,
  );
  assert.deepEqual(result.clippedText, [], `${label}: visible controls/headings must not clip their labels`);
}

export async function captureNonBlankScreenshot(page, target, label) {
  const screenshot = await page.screenshot({ path: target, fullPage: false });
  assert.ok(screenshot.byteLength > 12_000, `${label}: screenshot is unexpectedly small`);
  const sampled = new Set();
  const stride = Math.max(1, Math.floor(screenshot.byteLength / 4096));
  for (let index = 0; index < screenshot.byteLength; index += stride) sampled.add(screenshot[index]);
  assert.ok(sampled.size > 24, `${label}: screenshot appears visually blank`);
  const stats = await fs.stat(target);
  assert.equal(stats.size, screenshot.byteLength, `${label}: screenshot file should be fully written`);
  return { bytes: screenshot.byteLength, sampledByteValues: sampled.size };
}

async function fulfillJson(route, body, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json; charset=utf-8",
    body: JSON.stringify(body),
  });
}
