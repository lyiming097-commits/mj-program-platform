<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import {
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CircleAlert,
  Copy,
  Database,
  FileCheck2,
  FileClock,
  FilePenLine,
  Files,
  FolderOpen,
  FolderPlus,
  Inbox,
  LayoutTemplate,
  LoaderCircle,
  Plus,
  RotateCcw,
  Search,
  Send,
  Trash2,
  UserRound,
  UsersRound,
  X,
} from "@lucide/vue";

import { approvalApi, itemsOf } from "@/approvalApi";
import AdminPermissionSettings from "@/components/AdminPermissionSettings.vue";
import UnsavedChangesDialog from "@/components/UnsavedChangesDialog.vue";
import ApprovalFilterSelect from "@/components/approval/ApprovalFilterSelect.vue";

const props = defineProps({
  page: { type: String, required: true },
  query: { type: Object, default: () => ({}) },
  canManage: { type: Boolean, default: false },
  canManageApp: { type: Boolean, default: false },
  managedCategoryIds: { type: Array, default: () => [] },
  editorLinkForTemplate: { type: Function, default: null },
});

const emit = defineEmits([
  "navigate",
  "open-application",
  "apply",
  "edit-template",
  "new-template",
  "dirty-change",
  "confirm-open-change",
  "success-notice",
]);

const UNCATEGORIZED_ID = "__uncategorized__";

const loading = ref(false);
const templateRefreshing = ref(false);
const templateRefreshVisible = ref(false);
const templateDataReady = ref(false);
const errorMessage = ref("");
const workspace = ref({});
const rows = ref([]);
const templates = ref([]);
const total = ref(0);
const categories = ref([]);
const categoryListRef = ref(null);
const selectedCategoryId = ref(String(props.query.categoryId || "").trim());
const categoryLoading = ref(false);
const categoryError = ref("");
const categoryDialogOpen = ref(false);
const categoryDialogBusy = ref(false);
const categoryDialogError = ref("");
const categoryDialogRef = ref(null);
const categoryNameInputRef = ref(null);
const categoryDraft = reactive({ name: "" });
const categoryNameDraft = ref("");
const categoryNameSnapshot = ref("");
const categoryNameError = ref("");
const groupSaveError = ref("");
const categoryPermissionEditorRef = ref(null);
const categoryPermissionDirty = ref(false);
const categoryPermissionReady = ref(false);
const groupSaveBusy = ref(false);
const reorderBusy = ref("");
const categoryRevision = ref("");
const templateRevision = ref("");
const searchDraft = ref(String(props.query.q || ""));
const deleteDraftTarget = ref(null);
const deletingDraft = ref(false);
const deleteDraftError = ref("");
let categoryDialogReturnFocus = null;
let pendingDialogFocus = null;
let categoriesLoaded = false;
const loadedTemplateRequestKey = ref("");
let loadRequestSequence = 0;
let groupSaveSequence = 0;
let templateRefreshTimer = null;

const approvalTabs = [
  { id: "pending", label: "待我处理", icon: Inbox },
  { id: "processed", label: "我已处理", icon: CheckCircle2 },
  { id: "initiated", label: "我发起的", icon: Send },
  { id: "copied", label: "抄送我的", icon: Copy },
];

const starterTemplates = [
  {
    id: "procurement",
    name: "采购申请",
    description: "用于搭建采购事由、预算金额和审批节点。",
    category: "采购",
    icon: LayoutTemplate,
  },
  {
    id: "payment",
    name: "付款申请",
    description: "用于搭建收款信息、付款金额和财务审核。",
    category: "财务",
    icon: FileCheck2,
  },
  {
    id: "contract",
    name: "合同审批",
    description: "用于搭建合同信息、相对方和审批流程。",
    category: "合同",
    icon: Files,
  },
];
const templateStatusOptions = [
  { value: "", label: "全部状态" },
  { value: "draft", label: "草稿" },
  { value: "published", label: "已发布" },
];

const currentTab = computed(() => {
  const requested = String(props.query.tab || "pending");
  return approvalTabs.some((tab) => tab.id === requested) ? requested : "pending";
});
const isTaskView = computed(() => props.page === "approvals" && ["pending", "processed"].includes(currentTab.value));
const pageNumber = computed(() => Math.max(1, Number(props.query.page || 1) || 1));
const pageSize = 20;
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const dashboardCounts = computed(() => {
  const source = workspace.value?.counts || workspace.value?.summary || {};
  return {
    pending: numeric(source.pending ?? source.pendingTasks ?? workspace.value?.pendingCount),
    returned: numeric(source.returned ?? source.returnedApplications ?? workspace.value?.returnedCount),
    drafts: numeric(source.drafts ?? workspace.value?.draftCount),
    initiated: numeric(source.initiated ?? source.myApplications ?? workspace.value?.initiatedCount),
  };
});
const recentTemplates = computed(() => {
  const fromWorkspace = itemsOf(workspace.value?.recentTemplates || [], ["templates"]);
  return fromWorkspace.length ? fromWorkspace : templates.value.slice(0, 6);
});
const recentApplications = computed(() => itemsOf(
  workspace.value?.recentApplications || [],
  ["applications"],
));
const pageTitle = computed(() => ({
  home: "审批首页",
  approvals: "审批中心",
  drafts: "草稿箱",
  templates: "表单管理",
  data: "数据中心",
}[props.page] || "审批中心"));
const pageDescription = computed(() => ({
  home: "处理待办并发起新的审批",
  approvals: "集中查看与处理审批事项",
  drafts: "继续填写尚未提交的申请",
  templates: "维护审批表单、字段和流程",
  data: "查询有权限查看的审批数据",
}[props.page] || ""));
const selectedCategory = computed(() => (
  categories.value.find((category) => String(category.id) === String(selectedCategoryId.value)) || null
));
const canManageSelectedCategory = computed(() => Boolean(selectedCategory.value?.canManage));
const canManageCategories = computed(() => Boolean(
  props.canManageApp || (props.canManage && !props.managedCategoryIds.length),
));
const templateOrderingFiltered = computed(() => Boolean(props.query.q || props.query.status));
const expectedTemplateRequestKey = computed(() => (
  selectedCategoryId.value
    ? templateRequestKey(selectedCategoryId.value, props.query, pageNumber.value)
    : ""
));
const templateRowsCurrent = computed(() => (
  !selectedCategoryId.value || loadedTemplateRequestKey.value === expectedTemplateRequestKey.value
));
const templateOrderRows = computed(() => templateRowsCurrent.value ? rows.value : []);
const categoryNameDirty = computed(() => Boolean(
  selectedCategory.value
  && normalizeId(categoryNameDraft.value) !== normalizeId(categoryNameSnapshot.value)
));
const groupSettingsDirty = computed(() => categoryNameDirty.value || categoryPermissionDirty.value);
const groupSaveDisabled = computed(() => (
  !selectedCategory.value
  || !canManageCategories.value
  || !groupSettingsDirty.value
  || (categoryPermissionDirty.value && !categoryPermissionReady.value)
  || groupSaveBusy.value
));

function numeric(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : 0;
}

function normalizeId(value) {
  return String(value ?? "").trim();
}

function normalizeSortOrder(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeCategory(item, fallbackOrder = 0) {
  const id = normalizeId(item?.id ?? item?.categoryId ?? item?.category_id ?? item?.key);
  if (!id) return null;
  return {
    id,
    name: normalizeId(item?.name ?? item?.label) || id,
    description: normalizeId(item?.description ?? item?.note),
    sortOrder: normalizeSortOrder(item?.sortOrder ?? item?.sort_order ?? item?.order, fallbackOrder),
    templateCount: numeric(item?.templateCount ?? item?.template_count ?? item?.count),
    canManage: Boolean(
      item?.canManage
      || item?.can_manage
      || item?.managed
      || props.canManageApp
      || props.managedCategoryIds.some((value) => normalizeId(value?.id ?? value) === id),
    ),
    permissionCount: numeric(item?.permissionCount ?? item?.permission_count),
    managePermission: item?.managePermission ?? item?.manage_permission ?? null,
  };
}

function normalizeCategories(payload) {
  const source = itemsOf(payload, ["categoryItems", "categories", "items", "results"]);
  return source
    .map((item, index) => normalizeCategory(item, index))
    .filter(Boolean)
    .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name, "zh-Hans-CN"));
}

function templateCategoryId(template) {
  const raw = template?.categoryId
    ?? template?.category_id
    ?? template?.category?.id
    ?? template?.categoryKey
    ?? template?.category;
  return normalizeId(raw) || UNCATEGORIZED_ID;
}

function templateCategoryName(template) {
  const explicit = normalizeId(template?.categoryName ?? template?.category_name ?? template?.category?.name);
  if (explicit) return explicit;
  if (typeof template?.category === "string" || typeof template?.category === "number") {
    return normalizeId(template.category) || "未分类";
  }
  return "未分类";
}

function normalizeTemplate(template, fallbackOrder = 0) {
  if (!template || typeof template !== "object") return null;
  return {
    ...template,
    categoryId: templateCategoryId(template),
    categoryName: templateCategoryName(template),
    sortOrder: normalizeSortOrder(template?.sortOrder ?? template?.sort_order ?? template?.categoryOrder ?? template?.category_order, fallbackOrder),
  };
}

function alignTemplateCategories(templateRows = []) {
  const byName = new Map(categories.value.map((category) => [String(category.name).trim(), category]));
  return templateRows.map((template) => {
    const matched = byName.get(String(template.categoryName || "").trim());
    if (!matched || matched.id === template.categoryId) return template;
    return { ...template, categoryId: String(matched.id) };
  });
}

function currentQuery(overrides = {}) {
  const params = new URLSearchParams();
  const next = { ...props.query, ...overrides };
  Object.entries(next).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "" || value === false) return;
    params.set(key, String(value));
  });
  return params.toString();
}

function pagePath(overrides = {}) {
  const base = {
    approvals: "/approval-center/approvals/",
    drafts: "/approval-center/drafts/",
    templates: "/approval-center/templates/",
    data: "/approval-center/data/",
  }[props.page] || "/approval-center/";
  const query = currentQuery(overrides);
  return `${base}${query ? `?${query}` : ""}`;
}

function templateManagementPath(overrides = {}) {
  return pagePath(overrides);
}

function selectCategory(categoryId) {
  const nextId = normalizeId(categoryId);
  if (!nextId || !categories.value.some((category) => category.id === nextId)) return;
  if (nextId === selectedCategoryId.value && normalizeId(props.query.categoryId) === nextId) return;
  if (!groupSettingsDirty.value) selectedCategoryId.value = nextId;
  emit("navigate", templateManagementPath({ categoryId: nextId, category: "", page: "" }), { replace: true });
}

function switchTab(tab) {
  emit("navigate", pagePath({ tab, page: "", q: props.query.q || "" }));
}

function submitSearch() {
  const q = searchDraft.value.trim();
  emit("navigate", pagePath({ q, page: "" }), { replace: true });
}

function clearSearch() {
  searchDraft.value = "";
  emit("navigate", pagePath({ q: "", page: "" }), { replace: true });
}

function editorHref(template) {
  return props.editorLinkForTemplate?.(template.id, { categoryId: template.categoryId }) || "";
}

function changeStatus(status) {
  emit("navigate", pagePath({ status, page: "" }), { replace: true });
}

function changePage(page) {
  const normalized = Math.min(pageCount.value, Math.max(1, page));
  emit("navigate", pagePath({ page: normalized === 1 ? "" : normalized }));
}

function normalizeCollection(payload, keys = []) {
  const collection = itemsOf(payload, keys);
  const count = numeric(payload?.count ?? payload?.total ?? payload?.pagination?.total ?? collection.length);
  return { collection, count };
}

function templateRequestKey(categoryId, query, page) {
  return JSON.stringify([
    categoryId,
    normalizeId(query.q),
    normalizeId(query.status),
    page,
  ]);
}

function refreshPageData() {
  return props.page === "templates"
    ? load({ refreshCategories: true, forceTemplates: true })
    : load();
}

async function load(options = {}) {
  const requestId = ++loadRequestSequence;
  const query = { ...props.query };
  const requestedPage = Math.max(1, Number(query.page || 1) || 1);
  const templatePage = props.page === "templates";
  const initialTemplateLoad = templatePage && !templateDataReady.value;
  if (!templatePage || initialTemplateLoad) loading.value = true;
  if (templatePage && !initialTemplateLoad) {
    templateRefreshing.value = true;
    window.clearTimeout(templateRefreshTimer);
    templateRefreshVisible.value = false;
    templateRefreshTimer = window.setTimeout(() => {
      if (requestId === loadRequestSequence && templateRefreshing.value) {
        templateRefreshVisible.value = true;
      }
    }, 160);
  }
  errorMessage.value = "";
  try {
    if (props.page === "home") {
      const [workspaceResult, templateResult] = await Promise.all([
        approvalApi.workspace(),
        approvalApi.templates({ status: "published", pageSize: 12 }),
      ]);
      if (requestId !== loadRequestSequence) return;
      workspace.value = workspaceResult || {};
      templates.value = normalizeCollection(templateResult, ["templates"]).collection;
      rows.value = [];
      total.value = 0;
      return;
    }
    if (props.page === "templates") {
      const refreshCategories = options?.refreshCategories === true;
      const forceTemplates = options?.forceTemplates === true;
      if (!categoriesLoaded || refreshCategories) {
        categoryLoading.value = !categories.value.length;
        categoryError.value = "";
        try {
          const categoryResult = await approvalApi.categories({ scope: "manage" });
          if (requestId !== loadRequestSequence) return;
          categories.value = normalizeCategories(categoryResult);
          categoryRevision.value = String(categoryResult?.revision || categoryResult?.categoryRevision || "");
          categoriesLoaded = true;
        } catch (categoryLoadError) {
          if (requestId !== loadRequestSequence) return;
          categoryError.value = categoryLoadError instanceof Error ? categoryLoadError.message : "分类加载失败";
          if (!categoriesLoaded) {
            selectedCategoryId.value = "";
            templates.value = [];
            rows.value = [];
            total.value = 0;
            templateDataReady.value = true;
            loadedTemplateRequestKey.value = "";
            return;
          }
        }
      }

      const requestedCategoryId = normalizeId(query.categoryId);
      const requestedCategory = categories.value.find((category) => category.id === requestedCategoryId);
      const effectiveCategoryId = requestedCategory?.id || categories.value[0]?.id || "";
      const normalizeCategoryUrl = categoriesLoaded && requestedCategoryId !== effectiveCategoryId;
      const effectivePage = normalizeCategoryUrl ? 1 : requestedPage;
      selectedCategoryId.value = effectiveCategoryId;

      if (!effectiveCategoryId) {
        templates.value = [];
        rows.value = [];
        total.value = 0;
        templateRevision.value = "";
        templateDataReady.value = true;
        loadedTemplateRequestKey.value = templateRequestKey("", query, 1);
        if (normalizeCategoryUrl || query.page) {
          emit("navigate", templateManagementPath({ categoryId: "", page: "" }), { replace: true });
        }
        return;
      }

      const requestKey = templateRequestKey(effectiveCategoryId, query, effectivePage);
      if (!forceTemplates && templateDataReady.value && loadedTemplateRequestKey.value === requestKey) {
        if (normalizeCategoryUrl) {
          emit("navigate", templateManagementPath({ categoryId: effectiveCategoryId, page: "" }), { replace: true });
        }
        return;
      }

      const result = await approvalApi.templates({
        scope: "manage",
        q: query.q,
        status: query.status,
        categoryId: effectiveCategoryId,
        page: effectivePage,
        pageSize,
      });
      if (requestId !== loadRequestSequence) return;
      const normalized = normalizeCollection(result, ["templates"]);
      let normalizedTemplates = normalized.collection.map(normalizeTemplate).filter(Boolean);
      templateRevision.value = String(result?.revision || result?.templateRevision || "");
      normalizedTemplates = alignTemplateCategories(normalizedTemplates);
      templates.value = normalizedTemplates;
      rows.value = normalizedTemplates
        .filter((template) => templateCategoryId(template) === effectiveCategoryId)
        .sort((left, right) => left.sortOrder - right.sortOrder || String(left.name || "").localeCompare(String(right.name || ""), "zh-Hans-CN"));
      total.value = numeric(result?.count ?? result?.total ?? rows.value.length);
      if (!total.value) total.value = rows.value.length;
      const responsePage = Math.max(1, Number(result?.page ?? effectivePage) || effectivePage);
      const normalizePageUrl = responsePage !== effectivePage;
      templateDataReady.value = true;
      loadedTemplateRequestKey.value = templateRequestKey(effectiveCategoryId, query, responsePage);
      if (normalizeCategoryUrl || normalizePageUrl) {
        emit("navigate", templateManagementPath({
          categoryId: effectiveCategoryId,
          page: responsePage === 1 ? "" : responsePage,
        }), { replace: true });
      }
      return;
    }
    if (props.page === "approvals") {
      const result = isTaskView.value
        ? await approvalApi.tasks({
          view: currentTab.value,
          q: props.query.q,
          status: props.query.status,
          page: pageNumber.value,
          pageSize,
        })
        : await approvalApi.applications({
          view: currentTab.value,
          q: props.query.q,
          status: props.query.status,
          page: pageNumber.value,
          pageSize,
        });
      if (requestId !== loadRequestSequence) return;
      const normalized = normalizeCollection(result, ["tasks", "applications"]);
      rows.value = normalized.collection;
      total.value = normalized.count;
      return;
    }
    if (props.page === "drafts") {
      const result = await approvalApi.drafts({
        q: props.query.q,
        page: pageNumber.value,
        pageSize,
      });
      if (requestId !== loadRequestSequence) return;
      const normalized = normalizeCollection(result, ["drafts"]);
      rows.value = normalized.collection;
      total.value = normalized.count;
      return;
    }
    if (props.page === "data") {
      const result = await approvalApi.applications({
        view: "all",
        q: props.query.q,
        status: props.query.status,
        page: pageNumber.value,
        pageSize,
      });
      if (requestId !== loadRequestSequence) return;
      const normalized = normalizeCollection(result, ["applications"]);
      rows.value = normalized.collection;
      total.value = normalized.count;
      return;
    }
  } catch (error) {
    if (requestId !== loadRequestSequence) return;
    errorMessage.value = error instanceof Error ? error.message : "页面数据加载失败";
    rows.value = [];
    total.value = 0;
    if (templatePage) {
      templates.value = [];
      templateRevision.value = "";
      loadedTemplateRequestKey.value = "";
    }
  } finally {
    if (requestId === loadRequestSequence) {
      window.clearTimeout(templateRefreshTimer);
      templateRefreshTimer = null;
      categoryLoading.value = false;
      templateRefreshing.value = false;
      templateRefreshVisible.value = false;
      loading.value = false;
      flushPendingDialogFocus();
    }
  }
}

function rowId(row) {
  return row?.applicationId ?? row?.application?.id ?? row?.id ?? "";
}

function rowTitle(row) {
  return row?.title
    || row?.applicationTitle
    || row?.application?.title
    || row?.templateName
    || row?.template?.name
    || "未命名审批";
}

function rowNumber(row) {
  return row?.serialNo || row?.number || row?.applicationNo || row?.application?.serialNo || row?.application?.number || row?.code || "-";
}

function templateRowNumber(index) {
  return ((pageNumber.value - 1) * pageSize) + index + 1;
}

function rowInitiator(row) {
  return row?.initiatorName
    || row?.createdByName
    || row?.application?.initiatorName
    || row?.applicantName
    || "-";
}

function rowNode(row) {
  return row?.currentNodeName || row?.nodeName || row?.taskName || row?.application?.currentNodeName || "-";
}

function statusLabelFor(value, fallback = "") {
  const status = String(value || "").toLowerCase();
  return {
    draft: "草稿",
    waiting: "未开始",
    pending: "审批中",
    in_progress: "审批中",
    approved: "已通过",
    rejected: "已拒绝",
    returned: "已退回",
    withdrawn: "已撤回",
    copied: "已抄送",
    cancelled: "已取消",
    disabled: "已停用",
    published: "已发布",
    exception: "异常",
    error: "异常",
  }[status] || fallback || (status || "-");
}

function statusClassFor(value) {
  const status = String(value || "").toLowerCase();
  if (["approved", "published", "copied"].includes(status)) return "is-success";
  if (["rejected", "returned", "exception", "error", "failed"].includes(status)) return "is-danger";
  if (["pending", "in_progress"].includes(status)) return "is-warning";
  return "is-neutral";
}

function applicationStatusValue(row) {
  return String(row?.application?.status || row?.applicationStatus || row?.status || "").toLowerCase();
}

function applicationStatusLabel(row) {
  return statusLabelFor(
    applicationStatusValue(row),
    row?.application?.statusLabel || row?.statusLabel,
  );
}

function taskStatusLabel(row) {
  const status = String(row?.status || "").toLowerCase();
  const labels = {
    waiting: "未开始",
    pending: "待处理",
    approved: "已同意",
    rejected: "已拒绝",
    returned: "已退回",
    copied: "已抄送",
    cancelled: "已取消",
  };
  return labels[status] || row?.statusLabel || status || "-";
}

function templateStatusLabel(template) {
  const status = String(template?.status || "draft").toLowerCase();
  return { published: "已发布", draft: "草稿", disabled: "已停用" }[status] || status;
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date).replaceAll("/", "-");
}

function emitNewTemplate(starter = "") {
  if (!selectedCategory.value || !canManageSelectedCategory.value) return;
  emit("new-template", starter, {
    categoryId: selectedCategoryId.value,
    categoryName: selectedCategory.value.name || "",
  });
}

function flushPendingDialogFocus() {
  const pending = pendingDialogFocus;
  if (!pending) return;
  nextTick(() => {
    window.requestAnimationFrame(() => {
      if (pendingDialogFocus !== pending) return;
      const fallbackTarget = pending.fallbackSelector
        ? document.querySelector(pending.fallbackSelector)
        : null;
      const focusTarget = fallbackTarget || (pending.target?.isConnected ? pending.target : null);
      if (!focusTarget) return;
      focusTarget.focus?.();
      pendingDialogFocus = null;
    });
  });
}

function restoreDialogFocus(target, fallbackSelector = "") {
  pendingDialogFocus = { target, fallbackSelector };
  flushPendingDialogFocus();
}

function dialogFocusableElements(dialog) {
  if (!dialog) return [];
  return [...dialog.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter((element) => element.getAttribute("aria-hidden") !== "true");
}

function handleDialogKeydown(event) {
  if (!categoryDialogOpen.value) return;
  const dialog = categoryDialogRef.value;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopImmediatePropagation();
    closeCategoryDialog();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = dialogFocusableElements(dialog);
  if (!focusable.length) {
    event.preventDefault();
    dialog?.focus?.();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const activeElement = document.activeElement;
  if (!dialog?.contains(activeElement)) {
    event.preventDefault();
    first.focus();
  } else if (event.shiftKey && activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function dismissCategoryDialog() {
  categoryDialogOpen.value = false;
  categoryDialogError.value = "";
  const returnFocus = categoryDialogReturnFocus;
  categoryDialogReturnFocus = null;
  restoreDialogFocus(
    returnFocus,
    '[data-ai-action="approval.category.create"]',
  );
}

function openCategoryCreate() {
  if (!canManageCategories.value) return;
  if (groupSettingsDirty.value) {
    groupSaveError.value = "请先保存或放弃当前修改，再新增分类";
    return;
  }
  categoryDialogReturnFocus = document.activeElement;
  categoryDraft.name = "";
  categoryDialogError.value = "";
  categoryDialogOpen.value = true;
  nextTick(() => categoryNameInputRef.value?.focus?.());
}

function closeCategoryDialog() {
  if (categoryDialogBusy.value) return;
  dismissCategoryDialog();
}

async function saveCategory() {
  const name = String(categoryDraft.name || "").trim();
  if (!name || categoryDialogBusy.value) {
    categoryDialogError.value = "请输入分类名称";
    return;
  }
  categoryDialogBusy.value = true;
  categoryDialogError.value = "";
  categoryError.value = "";
  try {
    const result = await approvalApi.createCategory({ name });
    const item = normalizeCategory(result?.item || result?.category || result, categories.value.length);
    categoryRevision.value = String(result?.revision || categoryRevision.value);
    if (item) {
      categories.value = [...categories.value, { ...item, canManage: true }]
        .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name, "zh-Hans-CN"));
      selectCategory(item.id);
    }
    dismissCategoryDialog();
    emit("success-notice", "分类已创建");
    if (!item) await load({ refreshCategories: true, forceTemplates: true });
  } catch (error) {
    categoryDialogError.value = error instanceof Error ? error.message : "分类保存失败";
  } finally {
    categoryDialogBusy.value = false;
  }
}

function handleCategoryNameInput() {
  categoryNameError.value = "";
}

async function saveGroupSettings() {
  const category = selectedCategory.value;
  const categoryId = normalizeId(category?.id);
  const name = normalizeId(categoryNameDraft.value);
  if (!category || !categoryId || !canManageCategories.value || groupSaveBusy.value) return;
  if (!name) {
    categoryNameError.value = "请输入分类名称";
    return;
  }

  const shouldSaveName = categoryNameDirty.value;
  const shouldSavePermissions = categoryPermissionDirty.value;
  if (!shouldSaveName && !shouldSavePermissions) return;

  const requestSequence = ++groupSaveSequence;
  const permissionEditor = categoryPermissionEditorRef.value;
  groupSaveBusy.value = true;
  categoryNameError.value = "";
  groupSaveError.value = "";
  let nameSaved = false;
  try {
    if (shouldSaveName) {
      const result = await approvalApi.updateCategory(categoryId, { name });
      if (requestSequence !== groupSaveSequence || categoryId !== selectedCategoryId.value) return;
      const item = normalizeCategory(result?.item || result?.category || result, category.sortOrder);
      const savedName = normalizeId(item?.name) || name;
      categoryRevision.value = String(result?.revision || categoryRevision.value);
      categories.value = categories.value.map((entry) => (
        entry.id === categoryId ? { ...entry, ...(item || {}), name: savedName } : entry
      ));
      templates.value = templates.value.map((template) => (
        templateCategoryId(template) === categoryId ? { ...template, categoryName: savedName } : template
      ));
      rows.value = rows.value.map((template) => (
        templateCategoryId(template) === categoryId ? { ...template, categoryName: savedName } : template
      ));
      categoryNameDraft.value = savedName;
      categoryNameSnapshot.value = savedName;
      nameSaved = true;
    }

    if (shouldSavePermissions) {
      const permissionResult = await permissionEditor?.save?.();
      if (
        requestSequence !== groupSaveSequence
        || categoryId !== selectedCategoryId.value
        || permissionResult?.stale
      ) return;
      if (!permissionResult?.ok) {
        const permissionMessage = permissionResult?.error instanceof Error
          ? permissionResult.error.message
          : "管理权限保存失败，请重试";
        groupSaveError.value = nameSaved
          ? "分类名称已保存，管理权限保存失败，请重试"
          : permissionMessage;
        return;
      }
    }

    if (requestSequence !== groupSaveSequence || categoryId !== selectedCategoryId.value) return;
    emit("success-notice", "设置已保存");
  } catch (error) {
    if (requestSequence !== groupSaveSequence || categoryId !== selectedCategoryId.value) return;
    const message = error instanceof Error ? error.message : "设置保存失败";
    if (shouldSaveName && !nameSaved) categoryNameError.value = message;
    else groupSaveError.value = message;
  } finally {
    if (requestSequence === groupSaveSequence) groupSaveBusy.value = false;
  }
}

async function moveCategory(category, direction) {
  if (!canManageCategories.value || !category || reorderBusy.value) return;
  const index = categories.value.findIndex((item) => item.id === category.id);
  const targetIndex = index + direction;
  if (index < 0 || targetIndex < 0 || targetIndex >= categories.value.length) return;
  const next = categories.value.slice();
  [next[index], next[targetIndex]] = [next[targetIndex], next[index]];
  const ordered = next.map((item, itemIndex) => ({ ...item, sortOrder: itemIndex }));
  categories.value = ordered;
  categoryError.value = "";
  reorderBusy.value = `category:${category.id}`;
  try {
    const result = await approvalApi.reorderCategories({
      items: ordered.map((item, itemIndex) => ({ id: item.id, sortOrder: itemIndex })),
      revision: categoryRevision.value || undefined,
    });
    categoryRevision.value = String(result?.revision || categoryRevision.value);
    emit("success-notice", "分类顺序已更新");
  } catch (error) {
    const reorderError = error instanceof Error ? error.message : "分类排序失败";
    await load({ refreshCategories: true, forceTemplates: true });
    categoryError.value = reorderError;
  } finally {
    reorderBusy.value = "";
  }
}

function categoryMoveDisabled(category, direction) {
  const index = categories.value.findIndex((item) => item.id === category?.id);
  return !canManageCategories.value || index < 0 || index + direction < 0 || index + direction >= categories.value.length || Boolean(reorderBusy.value);
}

function templateMoveDisabled(template, direction) {
  const list = templateOrderRows.value;
  const index = list.findIndex((item) => String(item.id) === String(template?.id));
  const absoluteIndex = (pageNumber.value - 1) * pageSize + index;
  return !canManageSelectedCategory.value
    || templateRefreshing.value
    || templateOrderingFiltered.value
    || index < 0
    || absoluteIndex + direction < 0
    || absoluteIndex + direction >= total.value
    || Boolean(reorderBusy.value);
}

async function moveTemplate(template, direction) {
  if (!template
    || !canManageSelectedCategory.value
    || templateRefreshing.value
    || templateOrderingFiltered.value
    || reorderBusy.value
    || templateMoveDisabled(template, direction)) return;
  errorMessage.value = "";
  reorderBusy.value = `template:${template.id}`;
  try {
    const result = await approvalApi.reorderTemplates({
      categoryId: selectedCategoryId.value,
      templateId: template.id,
      direction: direction < 0 ? "up" : "down",
      revision: templateRevision.value || undefined,
    });
    templateRevision.value = String(result?.revision || templateRevision.value);
    await load({ forceTemplates: true });
    emit("success-notice", "表单顺序已更新");
  } catch (error) {
    const reorderError = error instanceof Error ? error.message : "表单排序失败";
    await load({ forceTemplates: true });
    errorMessage.value = reorderError;
  } finally {
    reorderBusy.value = "";
  }
}

function handleCategoryPermissionDirty(dirty) {
  categoryPermissionDirty.value = Boolean(dirty);
}

function handleCategoryPermissionReady(ready) {
  categoryPermissionReady.value = Boolean(ready);
}

function handleCategoryPermissionConfirmOpenChange(open) {
  emit("confirm-open-change", Boolean(open));
}

function handleCategoryPermissionSaved(payload = {}) {
  const categoryId = normalizeId(payload?.categoryId ?? selectedCategoryId.value);
  const count = Number(payload?.count);
  if (categoryId && Number.isFinite(count) && count >= 0) {
    categories.value = categories.value.map((category) => (
      category.id === categoryId ? { ...category, permissionCount: count } : category
    ));
  }
  categoryPermissionDirty.value = false;
}

function applyToTemplate(template) {
  if (!template?.id) return;
  emit("apply", template.id);
}

function openRow(row) {
  const id = rowId(row);
  if (id) emit("open-application", id);
}

function openDraft(row) {
  const templateId = row?.templateId || row?.template?.id;
  if (templateId) emit("apply", templateId, row?.id, row);
}

function requestDeleteDraft(row) {
  deleteDraftTarget.value = row;
  deleteDraftError.value = "";
}

function cancelDeleteDraft() {
  if (deletingDraft.value) return;
  deleteDraftTarget.value = null;
  deleteDraftError.value = "";
}

async function confirmDeleteDraft() {
  const target = deleteDraftTarget.value;
  if (!target?.id || deletingDraft.value) return;
  deletingDraft.value = true;
  deleteDraftError.value = "";
  try {
    await approvalApi.deleteDraft(target.id);
    deleteDraftTarget.value = null;
    emit("success-notice", "草稿已删除");
    const remainingTotal = Math.max(0, total.value - 1);
    total.value = remainingTotal;
    const remainingPages = Math.max(1, Math.ceil(remainingTotal / pageSize));
    if (pageNumber.value > remainingPages) {
      emit("navigate", pagePath({ page: remainingPages === 1 ? "" : remainingPages }), { replace: true });
    } else {
      await load();
    }
  } catch (error) {
    deleteDraftError.value = error instanceof Error ? error.message : "草稿删除失败";
  } finally {
    deletingDraft.value = false;
  }
}

watch(
  () => [selectedCategoryId.value, selectedCategory.value?.name || ""],
  ([nextCategoryId, nextName], previous = []) => {
    const [previousCategoryId, previousName] = previous;
    if (nextCategoryId !== previousCategoryId) {
      groupSaveSequence += 1;
      groupSaveBusy.value = false;
      groupSaveError.value = "";
      categoryNameDraft.value = nextName;
      categoryNameSnapshot.value = nextName;
      categoryNameError.value = "";
      return;
    }
    if (!categoryNameDirty.value && nextName !== previousName) {
      categoryNameDraft.value = nextName;
      categoryNameSnapshot.value = nextName;
      categoryNameError.value = "";
    }
  },
  { immediate: true },
);

watch(groupSettingsDirty, (dirty) => emit("dirty-change", dirty), { immediate: true, flush: "sync" });

watch(
  () => [selectedCategoryId.value, categories.value.length],
  async () => {
    await nextTick();
    const list = categoryListRef.value;
    const selected = list?.querySelector(".approval-category-item.is-active");
    if (!selected) return;
    const bounds = list.getBoundingClientRect();
    const itemBounds = selected.getBoundingClientRect();
    if (itemBounds.top < bounds.top) list.scrollTop += itemBounds.top - bounds.top;
    else if (itemBounds.bottom > bounds.bottom) list.scrollTop += itemBounds.bottom - bounds.bottom;
  },
  { flush: "post" },
);

watch(
  () => [props.page, JSON.stringify(props.query)],
  () => {
    searchDraft.value = String(props.query.q || "");
    load();
  },
);

onMounted(() => {
  window.addEventListener("keydown", handleDialogKeydown, true);
  load();
});

onBeforeUnmount(() => {
  loadRequestSequence += 1;
  groupSaveSequence += 1;
  window.clearTimeout(templateRefreshTimer);
  window.removeEventListener("keydown", handleDialogKeydown, true);
  emit("dirty-change", false);
  emit("confirm-open-change", false);
});
</script>

<template>
  <div class="approval-page-shell">
    <header v-if="page !== 'templates'" class="approval-page-header">
      <div class="min-w-0">
        <h1>{{ pageTitle }}</h1>
        <p>{{ pageDescription }}</p>
      </div>
      <div class="approval-page-actions">
        <button
          v-if="page === 'home'"
          type="button"
          class="approval-button approval-button-primary"
          data-ai-action="approval.application.start"
          @click="emit('navigate', '/approval-center/?focus=templates')"
        >
          <Plus class="h-4 w-4" aria-hidden="true" />
          发起审批
        </button>
        <button
          v-if="!['home', 'templates'].includes(page)"
          type="button"
          class="approval-icon-button"
          aria-label="刷新页面数据"
          title="刷新"
          @click="load"
        >
          <RotateCcw class="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </header>
    <h1 v-else class="sr-only">{{ pageTitle }}</h1>

    <div v-if="errorMessage" class="approval-alert is-error" role="alert">
      <CircleAlert class="h-4 w-4 shrink-0" aria-hidden="true" />
      <span class="min-w-0 flex-1">{{ errorMessage }}</span>
      <button type="button" class="approval-link-button" @click="refreshPageData">重试</button>
    </div>
    <div v-if="loading" class="approval-status-panel" role="status">
      <LoaderCircle class="h-5 w-5 animate-spin text-blue-600" aria-hidden="true" />
      正在加载审批数据...
    </div>

    <template v-else-if="page === 'home'">
      <section class="approval-metric-grid" aria-label="审批概览">
        <button type="button" class="approval-metric" @click="emit('navigate', '/approval-center/approvals/?tab=pending')">
          <span class="approval-metric-icon is-blue"><Inbox aria-hidden="true" /></span>
          <span class="approval-metric-body"><strong>{{ dashboardCounts.pending }}</strong><span>待我处理</span></span>
          <ArrowRight aria-hidden="true" />
        </button>
        <button type="button" class="approval-metric" @click="emit('navigate', '/approval-center/approvals/?tab=initiated&status=returned')">
          <span class="approval-metric-icon is-amber"><FilePenLine aria-hidden="true" /></span>
          <span class="approval-metric-body"><strong>{{ dashboardCounts.returned }}</strong><span>已退回</span></span>
          <ArrowRight aria-hidden="true" />
        </button>
        <button type="button" class="approval-metric" @click="emit('navigate', '/approval-center/drafts/')">
          <span class="approval-metric-icon is-slate"><FileClock aria-hidden="true" /></span>
          <span class="approval-metric-body"><strong>{{ dashboardCounts.drafts }}</strong><span>草稿</span></span>
          <ArrowRight aria-hidden="true" />
        </button>
        <button type="button" class="approval-metric" @click="emit('navigate', '/approval-center/approvals/?tab=initiated')">
          <span class="approval-metric-icon is-emerald"><Send aria-hidden="true" /></span>
          <span class="approval-metric-body"><strong>{{ dashboardCounts.initiated }}</strong><span>我发起的</span></span>
          <ArrowRight aria-hidden="true" />
        </button>
      </section>

      <section id="approval-start-templates" class="approval-section-band" aria-labelledby="approval-start-title">
        <div class="approval-section-heading">
          <div>
            <h2 id="approval-start-title">发起审批</h2>
            <p>选择已发布表单填写申请</p>
          </div>
        </div>
        <div v-if="recentTemplates.length" class="approval-template-grid">
          <button
            v-for="template in recentTemplates"
            :key="template.id"
            type="button"
            class="approval-template-tile"
            @click="applyToTemplate(template)"
          >
            <span class="approval-template-icon"><FileCheck2 aria-hidden="true" /></span>
            <span class="min-w-0 flex-1 text-left">
              <strong>{{ template.name || "未命名表单" }}</strong>
              <small>{{ template.category || "未分类" }}</small>
            </span>
            <ArrowRight aria-hidden="true" />
          </button>
        </div>
        <div v-else class="approval-empty-inline">
          <LayoutTemplate class="h-5 w-5" aria-hidden="true" />
          <span>暂无可发起的已发布表单</span>
          <button v-if="canManageSelectedCategory" type="button" class="approval-link-button" @click="emitNewTemplate('')">创建表单</button>
        </div>
      </section>

      <section class="approval-section-band" aria-labelledby="approval-recent-title">
        <div class="approval-section-heading">
          <div>
            <h2 id="approval-recent-title">最近发起</h2>
            <p>查看最近提交的审批</p>
          </div>
          <button type="button" class="approval-link-button" @click="emit('navigate', '/approval-center/approvals/?tab=initiated')">查看全部</button>
        </div>
        <div v-if="recentApplications.length" class="approval-compact-list">
          <button
            v-for="item in recentApplications"
            :key="rowId(item)"
            type="button"
            class="approval-compact-row"
            @click="openRow(item)"
          >
            <span class="approval-record-icon"><FileCheck2 aria-hidden="true" /></span>
            <span class="min-w-0 flex-1 text-left">
              <strong>{{ rowTitle(item) }}</strong>
              <small>{{ rowNumber(item) }} · {{ formatDate(item.updatedAt || item.createdAt) }}</small>
            </span>
            <span class="approval-status" :class="statusClassFor(applicationStatusValue(item))">{{ applicationStatusLabel(item) }}</span>
          </button>
        </div>
        <div v-else class="approval-empty-inline">暂无最近发起的审批</div>
      </section>
    </template>

    <template v-else>
      <nav v-if="page === 'approvals'" class="approval-tabs" aria-label="审批中心分类">
        <button
          v-for="tab in approvalTabs"
          :key="tab.id"
          type="button"
          :class="{ active: currentTab === tab.id }"
          :aria-current="currentTab === tab.id ? 'page' : undefined"
          @click="switchTab(tab.id)"
        >
          <component :is="tab.icon" aria-hidden="true" />
          {{ tab.label }}
        </button>
      </nav>

      <template v-if="page === 'templates'">
        <section class="approval-template-management" aria-label="表单分类管理">
          <aside class="approval-category-sidebar" aria-label="审批分类">
            <div class="approval-category-sidebar-head">
              <div class="min-w-0">
                <h2>审批分类</h2>
                <p>按分类维护表单和管理权限</p>
              </div>
              <button
                v-if="canManageCategories"
                type="button"
                class="approval-icon-button"
                data-ai-action="approval.category.create"
                aria-label="新增审批分类"
                title="新增分类"
                @click="openCategoryCreate"
              >
                <FolderPlus aria-hidden="true" />
              </button>
            </div>

            <div v-if="categoryError && !categories.length" class="approval-category-notice is-warning" role="alert">
              <span>{{ categoryError }}</span>
              <button type="button" class="approval-link-button" @click="refreshPageData">重试</button>
            </div>
            <div v-if="categoryLoading" class="approval-category-loading" role="status">
              <LoaderCircle class="animate-spin" aria-hidden="true" />正在加载分类...
            </div>
            <nav v-else-if="categories.length" ref="categoryListRef" class="approval-category-list" aria-label="审批分类列表">
              <button
                v-for="category in categories"
                :key="category.id"
                type="button"
                class="approval-category-item"
                :class="{ 'is-active': selectedCategoryId === category.id }"
                :aria-current="selectedCategoryId === category.id ? 'page' : undefined"
                :data-category-id="category.id"
                @click="selectCategory(category.id)"
              >
                <span class="approval-category-item-icon"><FolderOpen aria-hidden="true" /></span>
                <span class="min-w-0 flex-1 text-left">
                  <strong>{{ category.name }}</strong>
                  <small>{{ category.templateCount }} 个表单</small>
                </span>
                <span v-if="category.permissionCount" class="approval-category-permission-count" :aria-label="`${category.permissionCount} 条管理权限`">
                  <UsersRound aria-hidden="true" />{{ category.permissionCount }}
                </span>
              </button>
            </nav>
            <div v-else class="approval-category-list-empty">尚未创建分类</div>

            <div v-if="selectedCategory && canManageCategories" class="approval-category-sidebar-actions">
              <button
                type="button"
                class="approval-table-action"
                :disabled="categoryMoveDisabled(selectedCategory, -1)"
                :aria-label="`上移分类${selectedCategory.name}`"
                @click="moveCategory(selectedCategory, -1)"
              ><ChevronUp aria-hidden="true" />上移</button>
              <button
                type="button"
                class="approval-table-action"
                :disabled="categoryMoveDisabled(selectedCategory, 1)"
                :aria-label="`下移分类${selectedCategory.name}`"
                @click="moveCategory(selectedCategory, 1)"
              ><ChevronDown aria-hidden="true" />下移</button>
            </div>
          </aside>

          <aside class="approval-group-details" aria-label="分组设置">
            <section class="approval-group-detail-section approval-group-name-section">
              <header class="approval-group-detail-heading">
                <h2>分组名称</h2>
                <button
                  v-if="selectedCategory && canManageCategories"
                  type="button"
                  class="approval-button approval-button-primary approval-group-save-action"
                  :disabled="groupSaveDisabled"
                  :aria-busy="groupSaveBusy ? 'true' : undefined"
                  data-ai-action="approval.category.settings.save"
                  @click="saveGroupSettings"
                >
                  <LoaderCircle v-if="groupSaveBusy" class="animate-spin" aria-hidden="true" />
                  {{ groupSaveBusy ? "保存中..." : "保存" }}
                </button>
              </header>
              <div v-if="selectedCategory" class="approval-group-name-editor">
                <label class="approval-group-name-field">
                  <span class="sr-only">分类名称</span>
                  <input
                    v-model="categoryNameDraft"
                    type="text"
                    maxlength="64"
                    :readonly="!canManageCategories"
                    :disabled="groupSaveBusy"
                    :aria-invalid="categoryNameError ? 'true' : undefined"
                    :aria-describedby="categoryNameError ? 'approval-category-name-error' : undefined"
                    aria-label="分类名称"
                    @input="handleCategoryNameInput"
                  />
                </label>
              </div>
              <p v-else class="approval-group-detail-empty">尚未选择分组</p>
              <p
                v-if="categoryNameError"
                id="approval-category-name-error"
                class="approval-group-name-error"
                role="alert"
              >{{ categoryNameError }}</p>
            </section>

            <p v-if="groupSaveError" class="approval-group-save-error" role="alert">
              {{ groupSaveError }}
            </p>

            <AdminPermissionSettings
              v-if="selectedCategory && canManageCategories"
              ref="categoryPermissionEditorRef"
              :key="`category-permissions:${selectedCategoryId}`"
              class="approval-group-permission-editor"
              :compact="true"
              :category-id="selectedCategoryId"
              :external-save="true"
              @dirty-change="handleCategoryPermissionDirty"
              @ready-change="handleCategoryPermissionReady"
              @confirm-open-change="handleCategoryPermissionConfirmOpenChange"
              @saved="handleCategoryPermissionSaved"
            />
            <section v-else-if="selectedCategory" class="approval-group-detail-section approval-group-permission-section">
              <p class="approval-group-detail-empty">仅应用管理员可查看管理权限</p>
            </section>
          </aside>

          <section
            class="approval-category-content"
            :aria-labelledby="`template-category-title-${selectedCategory?.id || 'empty'}`"
            :aria-busy="templateRefreshing ? 'true' : undefined"
          >
            <header class="approval-category-content-head">
              <div class="min-w-0">
                <h2 :id="`template-category-title-${selectedCategory?.id || 'empty'}`">表单</h2>
                <p>{{ selectedCategory ? `维护“${selectedCategory.name}”分组下的审批表单、字段和审批流程` : "请先创建审批分类" }}</p>
              </div>
              <div class="approval-page-actions">
                <button
                  v-if="canManageSelectedCategory"
                  type="button"
                  class="approval-button approval-button-primary"
                  data-ai-action="approval.template.create.in-category"
                  @click="emitNewTemplate('')"
                ><Plus aria-hidden="true" />新建表单</button>
                <button
                  type="button"
                  class="approval-icon-button"
                  :aria-label="templateRefreshing ? '正在刷新表单和分类' : '刷新表单和分类'"
                  title="刷新"
                  :disabled="templateRefreshing"
                  @click="refreshPageData"
                ><RotateCcw :class="{ 'animate-spin': templateRefreshVisible }" aria-hidden="true" /></button>
                <span v-if="templateRefreshVisible && templateRowsCurrent" class="sr-only" role="status">正在更新表单...</span>
              </div>
            </header>

            <div v-if="categoryError && categories.length" class="approval-category-notice is-warning" role="alert">
              <span>{{ categoryError }}</span>
            </div>

            <template v-if="selectedCategory">
              <form class="approval-toolbar" role="search" @submit.prevent="submitSearch">
                <label class="approval-search-control">
                  <span class="sr-only">搜索表单管理</span>
                  <Search aria-hidden="true" />
                  <input v-model="searchDraft" type="search" name="q" placeholder="搜索表单名称" />
                </label>
                <ApprovalFilterSelect
                  :model-value="String(query.status || '')"
                  :options="templateStatusOptions"
                  aria-label="表单状态筛选"
                  @change="changeStatus"
                />
                <button type="submit" class="approval-button approval-button-secondary">查询</button>
                <button v-if="query.q" type="button" class="approval-link-button" @click="clearSearch">清除</button>
              </form>
              <p v-if="templateOrderingFiltered" class="approval-ordering-note" role="status">清除搜索和状态筛选后可调整表单顺序。</p>

              <div v-if="!templateRowsCurrent && errorMessage" class="approval-empty-state approval-template-load-state">
                <span class="approval-empty-icon"><CircleAlert aria-hidden="true" /></span>
                <h3>表单加载失败</h3>
                <p>请重试加载当前分类的表单。</p>
              </div>
              <div v-else-if="!templateRowsCurrent" class="approval-template-loading-state" role="status">
                <LoaderCircle class="animate-spin" aria-hidden="true" />
                <span>正在更新表单...</span>
              </div>
              <template v-else>
                <div v-if="!rows.length && canManageSelectedCategory && !templateOrderingFiltered && !errorMessage" class="approval-starter-section">
                  <div class="approval-section-heading">
                    <div>
                      <h3>在“{{ selectedCategory.name }}”中创建</h3>
                      <p>创建后可继续配置字段和审批流程，保存后仍为未发布草稿。</p>
                    </div>
                  </div>
                  <div class="approval-starter-grid">
                    <button v-for="starter in starterTemplates" :key="starter.id" type="button" class="approval-starter-card" @click="emitNewTemplate(starter.id)">
                      <span class="approval-template-icon"><component :is="starter.icon" aria-hidden="true" /></span>
                      <span class="min-w-0 flex-1 text-left">
                        <span class="approval-eyebrow">{{ starter.category }} · 起步模板</span>
                        <strong>{{ starter.name }}</strong>
                        <small>{{ starter.description }}</small>
                      </span>
                      <ArrowRight aria-hidden="true" />
                    </button>
                  </div>
                </div>

                <div class="approval-table-scroll">
                  <table v-if="rows.length" class="approval-table approval-template-table">
                  <caption class="sr-only">{{ selectedCategory.name }}表单数据</caption>
                  <thead>
                    <tr>
                      <th scope="col" class="approval-template-index-cell">序号</th>
                      <th scope="col">表单名称</th>
                      <th scope="col">状态</th>
                      <th scope="col">版本</th>
                      <th scope="col">更新时间</th>
                      <th scope="col" class="approval-cell-action">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(template, index) in rows" :key="template.id">
                      <td class="approval-template-index-cell">{{ templateRowNumber(index) }}</td>
                      <td>
                        <div class="approval-primary-cell">
                          <span class="approval-record-icon"><LayoutTemplate aria-hidden="true" /></span>
                          <span class="min-w-0"><strong>{{ template.name || "未命名表单" }}</strong><small>{{ template.description || "暂无说明" }}</small></span>
                        </div>
                      </td>
                      <td><span class="approval-status" :class="statusClassFor(template.status)">{{ templateStatusLabel(template) }}</span></td>
                      <td>{{ template.publishedVersion || template.currentVersion || template.version ? `v${template.publishedVersion || template.currentVersion || template.version}` : "-" }}</td>
                      <td>{{ formatDate(template.updatedAt || template.updated_at) }}</td>
                      <td class="approval-cell-action approval-cell-actions">
                        <span class="approval-order-actions" aria-label="调整表单顺序">
                          <button type="button" class="approval-icon-button" :disabled="templateMoveDisabled(template, -1)" :aria-label="`上移${template.name || '表单'}`" title="上移" @click="moveTemplate(template, -1)"><ChevronUp aria-hidden="true" /></button>
                          <button type="button" class="approval-icon-button" :disabled="templateMoveDisabled(template, 1)" :aria-label="`下移${template.name || '表单'}`" title="下移" @click="moveTemplate(template, 1)"><ChevronDown aria-hidden="true" /></button>
                        </span>
                        <a v-if="editorHref(template)" class="approval-table-action" :href="editorHref(template)" :aria-label="`编辑${template.name || '表单'}`" :aria-disabled="templateRefreshing || undefined" :tabindex="templateRefreshing ? -1 : undefined" @click="templateRefreshing && $event.preventDefault()"><FilePenLine aria-hidden="true" />编辑</a>
                        <button v-else type="button" class="approval-table-action" :disabled="templateRefreshing" :aria-label="`编辑${template.name || '表单'}`" @click="emit('edit-template', template.id, { categoryId: template.categoryId })"><FilePenLine aria-hidden="true" />编辑</button>
                      </td>
                    </tr>
                  </tbody>
                  </table>

                  <div v-else-if="templateOrderingFiltered" class="approval-empty-state">
                    <span class="approval-empty-icon"><Search aria-hidden="true" /></span>
                    <h3>没有匹配的结果</h3>
                    <p>请调整搜索或筛选条件后重试。</p>
                  </div>
                  <div v-else-if="!canManageSelectedCategory" class="approval-empty-state">
                    <span class="approval-empty-icon"><LayoutTemplate aria-hidden="true" /></span>
                    <h3>该分类暂无可管理表单</h3>
                    <p>请联系分类管理员申请管理权限。</p>
                  </div>
                </div>

                <footer v-if="rows.length" class="approval-pagination" aria-label="表单分页">
                  <span>共 {{ total }} 条</span>
                  <div>
                    <button type="button" class="approval-icon-button" aria-label="上一页" :disabled="pageNumber <= 1 || templateRefreshing" @click="changePage(pageNumber - 1)"><ChevronLeft aria-hidden="true" /></button>
                    <span>第 {{ pageNumber }} / {{ pageCount }} 页</span>
                    <button type="button" class="approval-icon-button" aria-label="下一页" :disabled="pageNumber >= pageCount || templateRefreshing" @click="changePage(pageNumber + 1)"><ChevronRight aria-hidden="true" /></button>
                  </div>
                </footer>
              </template>
            </template>

            <div v-else class="approval-empty-state approval-category-empty-state">
              <span class="approval-empty-icon"><FolderPlus aria-hidden="true" /></span>
              <h3>{{ categoryError ? "分类加载失败" : canManageCategories ? "暂无审批分类" : "暂无可管理分类" }}</h3>
              <p>{{ categoryError ? "请重试加载分类。" : canManageCategories ? "请先新增分类，再创建审批表单。" : "请联系审批管理员分配分类管理权限。" }}</p>
            </div>
          </section>
        </section>

        <div v-if="categoryDialogOpen" class="approval-dialog-backdrop" role="presentation" v-backdrop-dismiss="closeCategoryDialog">
          <section ref="categoryDialogRef" class="approval-dialog approval-category-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-category-dialog-title" tabindex="-1">
            <header class="approval-dialog-header">
              <h2 id="approval-category-dialog-title">新增审批分类</h2>
              <button type="button" class="approval-icon-button" aria-label="关闭新增分类" :disabled="categoryDialogBusy" @click="closeCategoryDialog"><X aria-hidden="true" /></button>
            </header>
            <form class="approval-dialog-body" @submit.prevent="saveCategory">
              <label class="approval-field"><span>分类名称 <b>*</b></span><input ref="categoryNameInputRef" v-model="categoryDraft.name" maxlength="64" required placeholder="例如：人事" :aria-invalid="Boolean(categoryDialogError)" :aria-describedby="categoryDialogError ? 'approval-category-create-error' : undefined" @input="categoryDialogError = ''" /></label>
              <p v-if="categoryDialogError" id="approval-category-create-error" class="approval-field-error" role="alert">{{ categoryDialogError }}</p>
              <footer class="approval-dialog-footer"><button type="button" class="approval-button approval-button-secondary" :disabled="categoryDialogBusy" @click="closeCategoryDialog">取消</button><button type="submit" class="approval-button approval-button-primary" :disabled="categoryDialogBusy">{{ categoryDialogBusy ? "创建中..." : "创建" }}</button></footer>
            </form>
          </section>
        </div>

      </template>

      <section v-else class="approval-list-panel" :aria-labelledby="`${page}-list-title`">
        <h2 :id="`${page}-list-title`" class="sr-only">{{ pageTitle }}列表</h2>
        <form class="approval-toolbar" role="search" @submit.prevent="submitSearch">
          <label class="approval-search-control">
            <span class="sr-only">搜索{{ pageTitle }}</span>
            <Search aria-hidden="true" />
            <input
              v-model="searchDraft"
              type="search"
              name="q"
              :placeholder="page === 'templates' ? '搜索表单名称' : page === 'drafts' ? '搜索草稿标题或表单名称' : '搜索编号、标题或发起人'"
            />
          </label>
          <select
            v-if="['approvals', 'templates', 'data'].includes(page)"
            class="approval-select-control"
            :aria-label="page === 'templates' ? '表单状态筛选' : '申请状态筛选'"
            :value="query.status || ''"
            @change="changeStatus($event.target.value)"
          >
            <option value="">全部状态</option>
            <template v-if="page === 'templates'">
              <option value="draft">草稿</option>
              <option value="published">已发布</option>
            </template>
            <template v-else>
              <option value="pending">审批中</option>
              <option value="approved">已通过</option>
              <option value="rejected">已拒绝</option>
              <option value="returned">已退回</option>
              <option value="withdrawn">已撤回</option>
            </template>
          </select>
          <button type="submit" class="approval-button approval-button-secondary">查询</button>
          <button v-if="query.q" type="button" class="approval-link-button" @click="clearSearch">清除</button>
        </form>

        <div v-if="page === 'templates' && !rows.length && canManage" class="approval-starter-section">
          <div class="approval-section-heading">
            <div>
              <h3>从起步模板创建</h3>
              <p>这些模板仅提供初始字段和流程，创建后仍为未发布草稿。</p>
            </div>
          </div>
          <div class="approval-starter-grid">
            <button
              v-for="starter in starterTemplates"
              :key="starter.id"
              type="button"
              class="approval-starter-card"
              @click="emit('new-template', starter.id)"
            >
              <span class="approval-template-icon"><component :is="starter.icon" aria-hidden="true" /></span>
              <span class="min-w-0 flex-1 text-left">
                <span class="approval-eyebrow">{{ starter.category }} · 起步模板</span>
                <strong>{{ starter.name }}</strong>
                <small>{{ starter.description }}</small>
              </span>
              <ArrowRight aria-hidden="true" />
            </button>
          </div>
        </div>

        <div class="approval-table-scroll">
          <table v-if="rows.length" class="approval-table">
            <caption class="sr-only">{{ pageTitle }}数据</caption>
            <thead>
              <tr v-if="page === 'templates'">
                <th scope="col">表单名称</th>
                <th scope="col">分类</th>
                <th scope="col">状态</th>
                <th scope="col">版本</th>
                <th scope="col">更新时间</th>
                <th scope="col" class="approval-cell-action">操作</th>
              </tr>
              <tr v-else-if="isTaskView">
                <th scope="col">审批事项</th>
                <th scope="col">发起人</th>
                <th scope="col">审批节点</th>
                <th scope="col">处理结果</th>
                <th scope="col">申请状态</th>
                <th scope="col">{{ currentTab === 'processed' ? '处理时间' : '更新时间' }}</th>
                <th scope="col" class="approval-cell-action">操作</th>
              </tr>
              <tr v-else-if="page === 'drafts'">
                <th scope="col">草稿</th>
                <th scope="col">审批表单</th>
                <th scope="col">更新时间</th>
                <th scope="col" class="approval-cell-action">操作</th>
              </tr>
              <tr v-else>
                <th scope="col">审批事项</th>
                <th scope="col">发起人</th>
                <th scope="col">当前节点</th>
                <th scope="col">申请状态</th>
                <th scope="col">更新时间</th>
                <th scope="col" class="approval-cell-action">操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="page === 'templates'">
                <tr v-for="template in rows" :key="template.id">
                  <td>
                    <div class="approval-primary-cell">
                      <span class="approval-record-icon"><LayoutTemplate aria-hidden="true" /></span>
                      <span class="min-w-0"><strong>{{ template.name || "未命名表单" }}</strong><small>{{ template.description || "暂无说明" }}</small></span>
                    </div>
                  </td>
                  <td>{{ template.category || "未分类" }}</td>
                  <td><span class="approval-status" :class="statusClassFor(template.status)">{{ templateStatusLabel(template) }}</span></td>
                  <td>{{ template.publishedVersion || template.currentVersion || template.version ? `v${template.publishedVersion || template.currentVersion || template.version}` : "-" }}</td>
                  <td>{{ formatDate(template.updatedAt || template.updated_at) }}</td>
                  <td class="approval-cell-action">
                    <a v-if="editorHref(template)" class="approval-table-action" :href="editorHref(template)" :aria-label="`编辑${template.name || '表单'}`" :aria-disabled="templateRefreshing || undefined" :tabindex="templateRefreshing ? -1 : undefined" @click="templateRefreshing && $event.preventDefault()">
                      <FilePenLine aria-hidden="true" />编辑
                    </a>
                    <button v-else type="button" class="approval-table-action" :aria-label="`编辑${template.name || '表单'}`" @click="emit('edit-template', template.id, { categoryId: template.categoryId })">
                      <FilePenLine aria-hidden="true" />编辑
                    </button>
                  </td>
                </tr>
              </template>
              <template v-else-if="isTaskView">
                <tr v-for="item in rows" :key="item.id || rowId(item)">
                  <td>
                    <div class="approval-primary-cell">
                      <span class="approval-record-icon"><FileCheck2 aria-hidden="true" /></span>
                      <span class="min-w-0"><strong>{{ rowTitle(item) }}</strong><small>{{ rowNumber(item) }}</small></span>
                    </div>
                  </td>
                  <td><span class="approval-person"><UserRound aria-hidden="true" />{{ rowInitiator(item) }}</span></td>
                  <td>{{ rowNode(item) }}</td>
                  <td><span class="approval-status" :class="statusClassFor(item.status)">{{ taskStatusLabel(item) }}</span></td>
                  <td><span class="approval-status" :class="statusClassFor(applicationStatusValue(item))">{{ applicationStatusLabel(item) }}</span></td>
                  <td>{{ formatDate(item.actedAt || item.updatedAt || item.activatedAt || item.createdAt) }}</td>
                  <td class="approval-cell-action">
                    <button type="button" class="approval-table-action" @click="openRow(item)">查看</button>
                  </td>
                </tr>
              </template>
              <template v-else-if="page === 'drafts'">
                <tr v-for="item in rows" :key="item.id">
                  <td><div class="approval-primary-cell"><span class="approval-record-icon"><FileClock aria-hidden="true" /></span><span class="min-w-0"><strong>{{ item.title || '未命名草稿' }}</strong><small>草稿 #{{ item.id }}</small></span></div></td>
                  <td>{{ item.templateName || "-" }}</td>
                  <td>{{ formatDate(item.updatedAt || item.createdAt) }}</td>
                  <td class="approval-cell-action approval-cell-actions">
                    <button type="button" class="approval-table-action" @click="openDraft(item)">继续填写</button>
                    <button type="button" class="approval-table-action is-danger" :aria-label="`删除草稿${item.title || item.id}`" @click="requestDeleteDraft(item)"><Trash2 aria-hidden="true" />删除</button>
                  </td>
                </tr>
              </template>
              <template v-else>
                <tr v-for="item in rows" :key="item.id || rowId(item)">
                  <td><div class="approval-primary-cell"><span class="approval-record-icon"><FileCheck2 aria-hidden="true" /></span><span class="min-w-0"><strong>{{ rowTitle(item) }}</strong><small>{{ rowNumber(item) }}</small></span></div></td>
                  <td><span class="approval-person"><UserRound aria-hidden="true" />{{ rowInitiator(item) }}</span></td>
                  <td>{{ rowNode(item) }}</td>
                  <td><span class="approval-status" :class="statusClassFor(applicationStatusValue(item))">{{ applicationStatusLabel(item) }}</span></td>
                  <td>{{ formatDate(item.updatedAt || item.createdAt) }}</td>
                  <td class="approval-cell-action"><button type="button" class="approval-table-action" @click="openRow(item)">查看</button></td>
                </tr>
              </template>
            </tbody>
          </table>

          <div v-else-if="!(page === 'templates' && canManage)" class="approval-empty-state">
            <span class="approval-empty-icon">
              <Database v-if="page === 'data'" aria-hidden="true" />
              <FileClock v-else-if="page === 'drafts'" aria-hidden="true" />
              <LayoutTemplate v-else-if="page === 'templates'" aria-hidden="true" />
              <Inbox v-else aria-hidden="true" />
            </span>
            <h3>{{ query.q || query.status ? "没有匹配的结果" : `暂无${pageTitle}数据` }}</h3>
            <p v-if="query.q || query.status">请调整搜索或筛选条件后重试。</p>
            <button v-if="query.q || query.status" type="button" class="approval-button approval-button-secondary" @click="emit('navigate', pagePath({ q: '', status: '', page: '' }), { replace: true })">清除筛选</button>
          </div>
        </div>

        <footer v-if="rows.length" class="approval-pagination" aria-label="分页">
          <span>共 {{ total }} 条</span>
          <div>
            <button type="button" class="approval-icon-button" aria-label="上一页" :disabled="pageNumber <= 1" @click="changePage(pageNumber - 1)"><ChevronLeft aria-hidden="true" /></button>
            <span>第 {{ pageNumber }} / {{ pageCount }} 页</span>
            <button type="button" class="approval-icon-button" aria-label="下一页" :disabled="pageNumber >= pageCount" @click="changePage(pageNumber + 1)"><ChevronRight aria-hidden="true" /></button>
          </div>
        </footer>
      </section>
    </template>

    <UnsavedChangesDialog
      :open="Boolean(deleteDraftTarget)"
      title="删除这份草稿？"
      :message="deleteDraftTarget ? `“${deleteDraftTarget.title || '未命名草稿'}”删除后无法恢复。` : ''"
      cancel-text="保留草稿"
      :confirm-text="deletingDraft ? '删除中...' : '确认删除'"
      :busy="deletingDraft"
      :error="deleteDraftError"
      @cancel="cancelDeleteDraft"
      @confirm="confirmDeleteDraft"
    />
  </div>
</template>
