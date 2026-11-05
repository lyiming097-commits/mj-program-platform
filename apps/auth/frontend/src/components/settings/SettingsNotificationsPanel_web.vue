<script setup>
import { PlatformAttachmentField, PlatformDateField, PlatformDetailDrawer, PlatformDetailEditPicker, PlatformRichTextEditor, matchesDirectorySearchKeyword, sanitizeRichHtml } from "@platform-ui";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  Bell,
  Building2,
  CalendarDays,
  Paperclip,
  Tag,
  Check,
  ChevronLeft,
  ChevronRight,
  FileText,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Send,
  Trash2,
  Users,
  X,
} from "@lucide/vue";
import { apiDelete, apiGet, apiPatch, apiPost, apiPut, apiUpload } from "@/api";
import { SETTINGS_NOTIFICATIONS_PATH } from "@/config";
import SettingsOrganizationPermissionsPanel from "@/components/settings/SettingsOrganizationPermissionsPanel.vue";
import SettingsUnsavedChangesDialog from "@/components/settings/SettingsUnsavedChangesDialog.vue";
import { useSettingsFeedback } from "./useSettingsFeedback";
import RobotMessageContent from "./RobotMessageContent.vue";
import NotificationConfirmationRecord from "./NotificationConfirmationRecord.vue";
import { notificationLevels, notificationLevel } from "@platform-ui/notification-levels.js";

const emit = defineEmits(["dirty-change", "saving-change"]);
const BASE = "/api/org/notices";
const PAGE_SIZE = 20;
const tabs = [
  { id: "notices", label: "通知列表" },
  { id: "history", label: "我的通知" },
  { id: "categories", label: "分类管理" },
  { id: "permissions", label: "权限管理" },
];

const notificationRoles = [
  {
    id: "admin",
    label: "通知管理员",
    note: "管理所有通知、分类和通知角色。后台管理员自动具备此权限。",
  },
  {
    id: "publisher",
    label: "通知发布者",
    note: "创建和管理本人通知，查看接收人的已读、未读情况。",
  },
];

const loading = ref(true);
const capability = ref(null);
const categories = ref([]);
const notices = ref([]);
const total = ref(0);
const historyRows = ref([]);
const currentTab = ref("notices");
const permissionRole = ref("admin");
const adminPermissionsPanel = ref(null);
const publisherPermissionsPanel = ref(null);
const adminPermissionsDirty = ref(false);
const publisherPermissionsDirty = ref(false);
const adminPermissionsSaving = ref(false);
const publisherPermissionsSaving = ref(false);
const errorMessage = ref("");
const showFeedback = useSettingsFeedback();
const busy = ref(false);
const categoryBusy = ref(false);
const categoryName = ref("");
const editingCategoryId = ref("");
const listKeyword = ref(new URLSearchParams(window.location.search).get("q") || "");
const listCategory = ref(new URLSearchParams(window.location.search).get("categoryId") || "");
const listDateFrom = ref(new URLSearchParams(window.location.search).get("dateFrom") || "");
const listDateTo = ref(new URLSearchParams(window.location.search).get("dateTo") || "");
const listStatus = ref(new URLSearchParams(window.location.search).get("status") || "all");
const listRecipientUserId = ref(new URLSearchParams(window.location.search).get("recipientUserId") || "");
const listUnreadUserId = ref(new URLSearchParams(window.location.search).get("unreadUserId") || "");
const listPage = ref(Math.max(1, Number(new URLSearchParams(window.location.search).get("page") || 1)));
const listRequestPending = ref(false);
const dirty = ref(false);
const saving = ref(false);
const editorOpen = ref(false);
const editorMode = ref("create");
const editorNoticeId = ref("");
const editorTitle = ref("");
const editorCategoryId = ref("");
const editorLevel = ref("ordinary");
const originalLevel = ref("ordinary");
const levelChanged = computed(() => audienceLocked.value && editorLevel.value !== originalLevel.value);
const editorExpiresAt = ref("");
const editorHtml = ref("");
const editorAttachments = ref([]);
const editorFrozenRecipientCount = ref(0);
const newFiles = ref([]);
const editorPeople = ref([]);
const editorDepartments = ref([]);
const directoryEmployees = ref([]);
const directoryDepartments = ref([]);
const enabledDepartmentIds = ref(new Set());
const editorError = ref("");
const detailEditButton = ref(null);
const fieldErrors = ref({});
const uploadStatus = ref("");
const readersLoading = ref(false);
const readersError = ref("");
let readersRequestSequence = 0;
const detailNotice = ref(null);
const detailTab = ref("detail");
const detailError = ref("");
let detailRequestSequence = 0;
const readers = ref([]);
const readersTotal = ref(0);
const readerStatus = ref("unread");
const confirmation = ref(null);
let confirmationResolver = null;
const readerPage = ref(1);
let searchTimer = null;
let listRequestSequence = 0;
const lastSavedForm = ref("");

const canManage = computed(() => capability.value?.canManage === true);
const canPublish = computed(() => capability.value?.canPublish === true);
const isRegularUser = computed(() => capability.value && !capability.value.canPublish);
const audienceLocked = computed(() => editorMode.value === "existing");
const visibleTabs = computed(() => tabs.filter((tab) => {
  if (tab.id === "notices") return canPublish.value;
  if (tab.id === "categories" || tab.id === "permissions") return canManage.value;
  return true;
}));
const currentTabLabel = computed(() => tabs.find((tab) => tab.id === currentTab.value)?.label || "通知");
const categoryOptions = computed(() => categories.value.map(item => ({ value: String(item.id), label: item.name })));
const departmentOptions = computed(() => flattenDepartments(directoryDepartments.value).map(item => ({
  ...item, value: item.id, label: item.name, description: item.path,
  toggleChecked: editorDepartments.value.find(selected => selected.id === item.id)?.includeSubDepartments === true,
})));
const employeeOptions = computed(() => directoryEmployees.value.map(item => ({ ...item, value: item.userId, selectedLabel: item.name, label: `${item.name} · ${item.departments.map(dept => dept.name).join(' / ')}` })));
const selectedDepartmentIds = computed({
  get: () => editorDepartments.value.map(item => item.id),
  set: ids => { editorDepartments.value = ids.map(id => {
    const existing = editorDepartments.value.find(item => item.id === id);
    const department = flattenDepartments(directoryDepartments.value).find(item => item.id === id);
    return existing || { ...department, includeSubDepartments: true, scopeIds: [id, ...flattenDepartmentIds(department?.children, id)] };
  }); },
});
const selectedPeopleIds = computed({
  get: () => editorPeople.value.map(item => item.userId),
  set: ids => { editorPeople.value = ids.map(id => directoryEmployees.value.find(item => item.userId === id)).filter(Boolean); },
});
const attachmentFiles = computed({
  get: () => [...editorAttachments.value, ...newFiles.value],
  set: files => { newFiles.value = files.filter(item => !item.id); },
});
const managementList = computed(() => currentTab.value === "notices" && canPublish.value);
// The API includes recipientSelection only when this user may manage this notice.
const canManageDetail = computed(() => canPublish.value && detailNotice.value?.recipientSelection != null);
const detailTabs = computed(() => [
  { id: "detail", label: "通知详情" },
  ...(canManageDetail.value ? [{ id: "readers", label: detailNotice.value?.level === "confirm" ? "确认情况" : detailNotice.value?.level === "accept" ? "接受情况" : "已读情况" }] : []),
]);
function matchDirectoryOption(keyword, option) {
  return matchesDirectorySearchKeyword(keyword, { names: [option.name, option.label, option.path], ids: option.value, pinyin: option.pinyin, pinyinInitials: option.pinyinInitials });
}
function setDepartmentIncludeSubDepartments({ value, checked }) {
  if (audienceLocked.value) return;
  const department = flattenDepartments(directoryDepartments.value).find(item => item.id === value);
  if (!department) return;
  const selected = {
    ...department,
    includeSubDepartments: checked,
    scopeIds: checked ? [value, ...flattenDepartmentIds(department.children, value)] : [value],
  };
  const index = editorDepartments.value.findIndex(item => item.id === value);
  if (index >= 0) editorDepartments.value.splice(index, 1, selected);
  else if (checked) editorDepartments.value.push(selected);
}
const selectedRecipientCount = computed(() => {
  if (audienceLocked.value) return editorFrozenRecipientCount.value;
  const recipients = new Set(editorPeople.value.map((person) => person.userId));
  editorDepartments.value.forEach((department) => {
    directoryEmployees.value.forEach((person) => {
      if (person.departments.some((item) => department.scopeIds.includes(item.id))) recipients.add(person.userId);
    });
  });
  return recipients.size;
});
const maxPage = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)));
const visibleListPages = computed(() => {
  if (maxPage.value <= 7) return Array.from({ length: maxPage.value }, (_, index) => index + 1);
  const candidates = [...new Set([1, maxPage.value, listPage.value - 1, listPage.value, listPage.value + 1])]
    .filter(page => page >= 1 && page <= maxPage.value).sort((left, right) => left - right);
  return candidates.flatMap((page, index) => index && page - candidates[index - 1] > 1 ? [`ellipsis-${page}`, page] : [page]);
});

function goToListPage(page) {
  if (loading.value || listRequestPending.value || !Number.isInteger(page) || page < 1 || page > maxPage.value || page === listPage.value) return;
  window.clearTimeout(searchTimer);
  listPage.value = page;
  void loadList();
}
const isFormDirty = computed(() => editorOpen.value && lastSavedForm.value !== formSnapshot());
const permissionDirty = computed(() => permissionRole.value === "admin"
  ? adminPermissionsDirty.value
  : publisherPermissionsDirty.value);
const permissionSaving = computed(() => permissionRole.value === "admin"
  ? adminPermissionsSaving.value
  : publisherPermissionsSaving.value);

function formSnapshot() {
  return JSON.stringify({
    title: editorTitle.value,
    categoryId: String(editorCategoryId.value || ""),
    level: editorLevel.value,
    expiresAt: editorExpiresAt.value,
    contentHtml: sanitizeRichHtml(editorHtml.value || ""),
    people: editorPeople.value.map((item) => item.userId).sort(),
    departments: editorDepartments.value.map((item) => ({
      id: item.id,
      includeSubDepartments: item.includeSubDepartments,
    })).sort((left, right) => left.id.localeCompare(right.id)),
    attachments: editorAttachments.value.map((item) => item.id).sort(),
    newFiles: newFiles.value.map((item) => `${item.name}:${item.size}:${item.lastModified}`).sort(),
  });
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function calendarDate(value = new Date()) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date);
  const part = type => parts.find(item => item.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function expirationDate(value) {
  if (!value) return "";
  return calendarDate(new Date(value).getTime() - 1);
}

function validExpirationDate(value) {
  if (!value) return true;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value && value >= calendarDate();
}

function currentFilterParams(page = listPage.value) {
  return {
    page,
    pageSize: PAGE_SIZE,
    keyword: listKeyword.value.trim(),
    categoryId: listCategory.value,
    dateFrom: listDateFrom.value,
    dateTo: listDateTo.value,
    status: listStatus.value === "all" ? "" : listStatus.value,
    recipientUserId: managementList.value ? listRecipientUserId.value : "",
    unreadUserId: managementList.value ? listUnreadUserId.value : "",
  };
}

function updateListUrl() {
  const url = new URL(window.location.href);
  const values = currentFilterParams();
  url.searchParams.delete("q");
  url.searchParams.delete("categoryId");
  url.searchParams.delete("dateFrom");
  url.searchParams.delete("dateTo");
  url.searchParams.delete("status");
  url.searchParams.delete("recipientUserId");
  url.searchParams.delete("unreadUserId");
  url.searchParams.delete("page");
  if (values.keyword) url.searchParams.set("q", values.keyword);
  if (values.categoryId) url.searchParams.set("categoryId", values.categoryId);
  if (values.dateFrom) url.searchParams.set("dateFrom", values.dateFrom);
  if (values.dateTo) url.searchParams.set("dateTo", values.dateTo);
  if (values.status) url.searchParams.set("status", values.status);
  if (values.recipientUserId) url.searchParams.set("recipientUserId", values.recipientUserId);
  if (values.unreadUserId) url.searchParams.set("unreadUserId", values.unreadUserId);
  if (listPage.value > 1) url.searchParams.set("page", String(listPage.value));
  window.history.replaceState({}, "", `${SETTINGS_NOTIFICATIONS_PATH}${url.search}${url.hash}`);
}

async function loadCategories() {
  const data = await apiGet(`${BASE}/categories`);
  categories.value = Array.isArray(data?.items) ? data.items : [];
}

async function loadDirectory() {
  const [treeData, employeeData, enabledData] = await Promise.all([
    apiGet("/api/org/departments/tree"),
    apiGet("/api/org/employees", { status: "active", includeDepartments: "true" }),
    apiGet("/api/org/enabled-departments"),
  ]);
  const enabled = new Set((enabledData?.departmentIds || []).map((item) => String(item)));
  enabledDepartmentIds.value = enabled;
  const departmentIndex = new Map();
  const walk = (nodes, parents = [], parentId = "") => (nodes || []).flatMap((node) => {
    const id = String(node.deptId ?? node.dept_id ?? node.id ?? "");
    if (!id) return [];
    const path = [...parents, String(node.name || id)];
    const children = walk(node.children || [], path, id);
    if (!enabled.has(id)) return children;
    const item = { id, parentId, name: String(node.name || id), pinyin: node.pinyin || "", pinyinInitials: node.pinyinInitials || "", path: path.join(" / "), children };
    departmentIndex.set(id, item);
    return [item];
  });
  directoryDepartments.value = walk(treeData?.items || []);
  const employees = Array.isArray(employeeData?.items) ? employeeData.items : [];
  directoryEmployees.value = employees.map((item) => {
    const departments = (item.departments || item.departmentIds || []).map((department) => {
      const id = String(typeof department === "object" ? department.deptId ?? department.dept_id ?? department.id : department);
      const found = departmentIndex.get(id);
      return found ? { id, name: found.name, path: found.path } : null;
    }).filter(Boolean);
    return {
      userId: String(item.userId ?? item.user_id ?? item.id ?? ""),
      name: String(item.name ?? item.rawName ?? item.userId ?? ""),
      pinyin: item.pinyin || "",
      pinyinInitials: item.pinyinInitials || "",
      departments,
    };
  }).filter((item) => item.userId && item.departments.length);
}

async function loadList({ page = listPage.value, reset = false } = {}) {
  if (!capability.value) return;
  const sequence = ++listRequestSequence;
  listRequestPending.value = true;
  if (reset) loading.value = true;
  errorMessage.value = "";
  try {
    updateListUrl();
    if (managementList.value) {
      const data = await apiGet(BASE, currentFilterParams(page));
      if (sequence !== listRequestSequence) return;
      notices.value = Array.isArray(data?.items) ? data.items : [];
      total.value = Number(data?.total || 0);
    } else {
      const data = await apiGet(`${BASE}/history`, currentFilterParams(page));
      if (sequence !== listRequestSequence) return;
      historyRows.value = Array.isArray(data?.items) ? data.items : [];
      total.value = Number(data?.total || 0);
    }
    if (listPage.value > maxPage.value) {
      listPage.value = maxPage.value;
      await loadList();
    }
  } catch (error) {
    if (sequence === listRequestSequence) errorMessage.value = error instanceof Error ? error.message : "通知记录加载失败";
  } finally {
    if (sequence === listRequestSequence) {
      loading.value = false;
      listRequestPending.value = false;
    }
  }
}

async function initialize() {
  loading.value = true;
  errorMessage.value = "";
  try {
    capability.value = await apiGet(`${BASE}/capabilities`);
    if (!visibleTabs.value.some((tab) => tab.id === currentTab.value)) {
      currentTab.value = canPublish.value ? "notices" : "history";
    }
    await Promise.all([loadCategories(), canPublish.value ? loadDirectory() : Promise.resolve()]);
    await loadList({ reset: false });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "通知模块加载失败";
  } finally {
    loading.value = false;
  }
}

function scheduleFilterLoad() {
  listPage.value = 1;
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => loadList({ page: 1 }), 220);
}

function resetFilters() {
  listKeyword.value = "";
  listCategory.value = "";
  listDateFrom.value = "";
  listDateTo.value = "";
  listStatus.value = "all";
  listRecipientUserId.value = "";
  listUnreadUserId.value = "";
  listPage.value = 1;
  void loadList({ page: 1 });
}

async function setTab(nextTab) {
  if (nextTab === currentTab.value || busy.value || saving.value || permissionSaving.value) return;
  if (permissionDirty.value && !await askConfirmation(
    "当前权限配置尚未保存，切换页面后本次修改不会保留。",
    { title: "是否放弃修改", confirmText: "确认放弃" },
  )) return;
  currentTab.value = nextTab;
  errorMessage.value = "";
  if (["notices", "history"].includes(nextTab)) {
    window.clearTimeout(searchTimer);
    listPage.value = 1;
    void loadList();
  }
}

async function handleTabKeydown(event, index) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const nextIndex = event.key === "Home" ? 0
    : event.key === "End" ? visibleTabs.value.length - 1
      : (index + (event.key === "ArrowRight" ? 1 : -1) + visibleTabs.value.length) % visibleTabs.value.length;
  await setTab(visibleTabs.value[nextIndex].id);
  await nextTick();
  document.getElementById(`notification-tab-${currentTab.value}`)?.focus();
}

function recipientSelection() {
  return {
    departments: editorDepartments.value.map((item) => ({
      deptId: Number(item.id),
      includeSubDepartments: item.includeSubDepartments,
    })),
    people: editorPeople.value.map((item) => item.userId),
  };
}

function flattenDepartmentIds(children = [], parentId) {
  // Match the API: disabled ancestors split the enabled department hierarchy.
  return children.filter(item => item.parentId === parentId)
    .flatMap(item => [item.id, ...flattenDepartmentIds(item.children || [], item.id)]);
}

function askConfirmation(message, { title = "请确认", confirmText = "确认", confirmTone = "danger" } = {}) {
  if (confirmationResolver) confirmationResolver(false);
  confirmation.value = { title, message, confirmText, confirmTone };
  return new Promise((resolve) => { confirmationResolver = resolve; });
}

function resolveConfirmation(accepted) {
  const resolve = confirmationResolver;
  confirmationResolver = null;
  confirmation.value = null;
  resolve?.(accepted);
}

async function switchPermissionRole(nextRole) {
  if (nextRole === permissionRole.value || permissionSaving.value) return;
  const activePanel = permissionRole.value === "admin"
    ? adminPermissionsPanel.value
    : publisherPermissionsPanel.value;
  const hasPendingChanges = activePanel?.hasPendingChanges?.()
    ?? (permissionRole.value === "admin" ? adminPermissionsDirty.value : publisherPermissionsDirty.value);
  if (hasPendingChanges && !await askConfirmation(
    "切换角色会丢弃当前尚未保存的权限修改，确定继续吗？",
    { title: "是否放弃修改", confirmText: "确认放弃" },
  )) return;
  permissionRole.value = nextRole;
  await nextTick();
  const nextPanel = nextRole === "admin" ? adminPermissionsPanel.value : publisherPermissionsPanel.value;
  nextPanel?.focusRoleSelection?.();
}

async function removeAttachment(attachment) {
  if (!await askConfirmation(`确定删除附件“${attachment.name}”吗？`, { title: "删除附件" })) return;
  busy.value = true;
  editorError.value = "";
  try {
    await apiDelete(`${BASE}/attachments/${attachment.id}`);
    editorAttachments.value = editorAttachments.value.filter((item) => item.id !== attachment.id);
    if (detailNotice.value?.id === editorNoticeId.value) {
      detailNotice.value = { ...detailNotice.value, attachments: editorAttachments.value };
    }
    dirty.value = true;
  } catch (error) {
    editorError.value = error instanceof Error ? error.message : "附件删除失败";
  } finally {
    busy.value = false;
  }
}

function noticeFormPayload() {
  return {
    title: editorTitle.value.trim(),
    categoryId: Number(editorCategoryId.value),
    level: audienceLocked.value ? originalLevel.value : editorLevel.value,
    expiresAt: editorExpiresAt.value,
    contentHtml: sanitizeRichHtml(editorHtml.value || ""),
    recipientSelection: recipientSelection(),
  };
}

function validateEditor() {
  const errors = {};
  if (!editorTitle.value.trim()) errors.title = "请填写通知标题";
  if (!editorCategoryId.value) errors.category = "请选择通知分类";
  if (!notificationLevels.some(item => item.value === editorLevel.value)) errors.level = "请选择通知等级";
  if (!validExpirationDate(editorExpiresAt.value)) errors.expires = "到期日期不能早于今天";
  const body = document.createElement("template");
  body.innerHTML = sanitizeRichHtml(editorHtml.value || "");
  if (!body.content.textContent.trim() && !body.content.querySelector("img")) errors.body = "请填写通知正文";
  if (!selectedRecipientCount.value) errors.audience = "请至少选择一个通知部门或人员";
  fieldErrors.value = errors;
  return Object.values(errors)[0] || "";
}

function resetEditor() {
  editorNoticeId.value = "";
  editorTitle.value = "";
  editorCategoryId.value = "";
  editorLevel.value = "ordinary";
  originalLevel.value = "ordinary";
  editorExpiresAt.value = "";
  editorHtml.value = "";
  editorAttachments.value = [];
  editorFrozenRecipientCount.value = 0;
  newFiles.value = [];
  editorPeople.value = [];
  editorDepartments.value = [];
  editorError.value = "";
  fieldErrors.value = {};
  uploadStatus.value = "";
  dirty.value = false;
  lastSavedForm.value = formSnapshot();
}

async function openCreateEditor() {
  if (!categories.value.length) {
    errorMessage.value = "请先由通知管理员创建分类，再发布通知";
    return;
  }
  resetDetail();
  editorMode.value = "create";
  resetEditor();
  editorCategoryId.value = String(categories.value[0]?.id || "");
  lastSavedForm.value = formSnapshot();
  editorOpen.value = true;
  await nextTick();
  document.getElementById("notification-title-input")?.focus({ preventScroll: true });
}

async function openEditEditor(notice) {
  if (busy.value || saving.value) return;
  editorMode.value = notice.status === "draft" ? "draft" : "existing";
  editorNoticeId.value = notice.id;
  editorError.value = "";
  busy.value = true;
  try {
    const data = await apiGet(`${BASE}/${notice.id}`);
    await loadDirectory();
    editorTitle.value = data.title || "";
    editorCategoryId.value = String(data.category?.id || "");
    editorLevel.value = data.level || "ordinary";
    originalLevel.value = editorLevel.value;
    editorExpiresAt.value = data.expiresOn || expirationDate(data.expiresAt);
    editorHtml.value = data.contentHtml || "";
    editorAttachments.value = data.attachments || [];
    editorFrozenRecipientCount.value = Number(data.recipientCount || 0);
    const selection = data.recipientSelection || { departments: [], people: [] };
    editorDepartments.value = (selection.departments || []).map((item) => {
      const id = String(item.deptId ?? item.id);
      const department = flattenDepartments(directoryDepartments.value).find((entry) => entry.id === id);
      return department ? {
        ...department,
        includeSubDepartments: item.includeSubDepartments !== false,
        scopeIds: item.includeSubDepartments === false ? [id] : [id, ...flattenDepartmentIds(department.children, id)],
      } : null;
    }).filter(Boolean);
    const peopleById = new Map(directoryEmployees.value.map((item) => [item.userId, item]));
    editorPeople.value = (selection.people || []).map((id) => peopleById.get(String(id))).filter(Boolean);
    newFiles.value = [];
    editorMode.value = data.status === "draft" ? "draft" : "existing";
    detailNotice.value = { ...detailNotice.value, ...data };
    lastSavedForm.value = formSnapshot();
    dirty.value = false;
    fieldErrors.value = {};
    editorOpen.value = true;
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : "通知详情加载失败";
  } finally {
    busy.value = false;
    if (editorOpen.value) {
      await nextTick();
      document.getElementById("notification-title-input")?.focus({ preventScroll: true });
    }
  }
}

function flattenDepartments(nodes = []) {
  return nodes.flatMap((item) => [item, ...flattenDepartments(item.children || [])]);
}

async function requestCloseEditor() {
  if (busy.value || saving.value) return;
  if (isFormDirty.value) {
    const accepted = await askConfirmation("通知内容尚未保存，确认放弃修改吗？", { title: "是否放弃修改", confirmText: "确认放弃" });
    if (!accepted) return;
  }
  editorOpen.value = false;
  dirty.value = false;
  await nextTick();
  detailEditButton.value?.focus();
}

async function saveEditor({ publishNow = false } = {}) {
  if (busy.value || saving.value) return;
  if (levelChanged.value && !publishNow) {
    editorError.value = "修改通知等级后，请保存并重新发布。";
    return;
  }
  const invalid = validateEditor();
  if (invalid) {
    editorError.value = invalid;
    await nextTick();
    document.querySelector('[data-notification-editor] input[aria-invalid="true"], [data-notification-editor] [role="textbox"][aria-invalid="true"]')?.focus();
    return;
  }
  const resetRead = publishNow && audienceLocked.value;
  if (resetRead && !await askConfirmation("将清空所有接收人的已读、确认或接受状态，按原接收名单重新提醒。确定保存并重新发布吗？", {
    title: "重新发布通知", confirmText: "保存并重新发布",
  })) return;
  saving.value = true;
  busy.value = true;
  editorError.value = "";
  emit("saving-change", true);
  try {
    let data;
    if (editorNoticeId.value) {
      data = await apiPatch(`${BASE}/${editorNoticeId.value}`, noticeFormPayload());
      if (detailNotice.value?.id === data.id) detailNotice.value = { ...detailNotice.value, ...data };
    } else {
      data = await apiPost(BASE, noticeFormPayload());
      editorNoticeId.value = data.id;
    }
    if (newFiles.value.length) {
      uploadStatus.value = `正在上传 ${newFiles.value.length} 个附件…`;
      const formData = new FormData();
      newFiles.value.forEach((file) => formData.append("files", file, file.name));
      const uploaded = await apiUpload(`${BASE}/${editorNoticeId.value}/attachments`, formData);
      editorAttachments.value = [...editorAttachments.value, ...(uploaded.items || [])];
      if (detailNotice.value?.id === data.id) detailNotice.value = { ...detailNotice.value, attachments: editorAttachments.value };
      newFiles.value = [];
      uploadStatus.value = "附件上传完成";
    }
    if (publishNow) {
      const published = await apiPost(`${BASE}/${editorNoticeId.value}/publish`, resetRead ? { resetRead: true, level: editorLevel.value } : {});
      data = { ...data, ...published };
      showFeedback(resetRead ? "通知已重新发布，完成状态已重置" : "通知已发布，接收人名单已固定");
    } else {
      showFeedback(editorMode.value === "create" ? "通知草稿已保存" : "通知已保存");
    }
    if (detailNotice.value || publishNow) {
      detailNotice.value = { ...detailNotice.value, ...data, attachments: editorAttachments.value };
      detailTab.value = publishNow ? "readers" : "detail";
      resetReaders();
      readerStatus.value = "unread";
      readerPage.value = 1;
    }
    editorOpen.value = false;
    dirty.value = false;
    await loadList();
    if (publishNow && data?.id) void loadReaders();
  } catch (error) {
    editorError.value = error instanceof Error ? error.message : "通知保存失败，请重试";
    uploadStatus.value = newFiles.value.length ? "附件尚未上传完成，请重试保存" : "";
  } finally {
    busy.value = false;
    saving.value = false;
    emit("saving-change", false);
    if (!editorOpen.value && detailNotice.value) {
      await nextTick();
      detailEditButton.value?.focus();
    }
  }
}

async function publishNotice(notice) {
  const resetRead = notice.status !== "draft";
  if (!await askConfirmation(resetRead
    ? `确定重新发布“${notice.title}”吗？将清空已读、确认或接受状态，按原接收名单重新提醒。`
    : `确定发布“${notice.title}”吗？发布时会按当前部门成员生成固定接收名单。`, {
    title: resetRead ? "重新发布通知" : "发布通知", confirmText: resetRead ? "重新发布" : "发布", confirmTone: resetRead ? "danger" : "primary",
  })) return;
  busy.value = true;
  errorMessage.value = "";
  detailError.value = "";
  try {
    const result = await apiPost(`${BASE}/${notice.id}/publish`, resetRead ? { resetRead: true } : {});
    detailNotice.value = { ...detailNotice.value, ...result };
    showFeedback(resetRead ? "通知已重新发布，完成状态已重置" : "通知已发布，接收人名单已固定");
    await loadList();
    void openReaderList(result, "unread");
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : "通知发布失败";
  } finally {
    busy.value = false;
  }
}

async function withdrawNotice(notice) {
  if (!await askConfirmation(`确定撤回“${notice.title}”吗？撤回后将不再弹窗提醒。`, { title: "撤回通知", confirmText: "撤回" })) return;
  busy.value = true;
  detailError.value = "";
  try {
    const result = await apiPost(`${BASE}/${notice.id}/withdraw`, {});
    detailNotice.value = { ...detailNotice.value, ...result };
    showFeedback("通知已撤回");
    await loadList();
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : "通知撤回失败";
  } finally {
    busy.value = false;
  }
}

async function deleteNotice(notice) {
  if (!await askConfirmation(`确定永久删除“${notice.title}”及其附件、接收和已读记录吗？`, { title: "删除通知", confirmText: "永久删除" })) return;
  busy.value = true;
  detailError.value = "";
  try {
    await apiDelete(`${BASE}/${notice.id}`);
    resetDetail();
    showFeedback("通知已删除");
    await loadList();
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : "通知删除失败";
  } finally {
    busy.value = false;
  }
}

function resetReaders() {
  readersRequestSequence++;
  readers.value = [];
  readersTotal.value = 0;
  readersError.value = "";
  readersLoading.value = false;
}

function resetDetail() {
  detailRequestSequence++;
  resetReaders();
  detailNotice.value = null;
  detailTab.value = "detail";
  detailError.value = "";
}

function closeDetail() {
  if (busy.value || confirmation.value) return;
  resetDetail();
}

async function openDetail(notice, tab = "detail", status = "unread") {
  const sequence = ++detailRequestSequence;
  resetReaders();
  detailError.value = "";
  try {
    const data = await apiGet(`${BASE}/${notice.id}`);
    if (sequence !== detailRequestSequence) return;
    detailNotice.value = data;
    detailTab.value = tab === "readers" && canManageDetail.value ? "readers" : "detail";
    readerStatus.value = status;
    readerPage.value = 1;
    if (detailTab.value === "readers") await loadReaders();
  } catch (error) {
    if (sequence !== detailRequestSequence) return;
    const message = error instanceof Error ? error.message : "通知详情加载失败";
    if (detailNotice.value) detailError.value = message;
    else errorMessage.value = message;
  }
}

async function openReaderList(notice, status = "unread") {
  await openDetail(notice, "readers", status);
}

function selectDetailTab(tab) {
  if (busy.value || detailTab.value === tab || !detailTabs.value.some(item => item.id === tab)) return;
  detailTab.value = tab;
  resetReaders();
  if (tab === "readers") {
    readerStatus.value = "unread";
    readerPage.value = 1;
    void loadReaders();
  }
}

async function handleDetailTabKeydown(event, index) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const count = detailTabs.value.length;
  const next = event.key === "Home" ? 0 : event.key === "End" ? count - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + count) % count;
  selectDetailTab(detailTabs.value[next].id);
  await nextTick();
  document.getElementById(`notification-detail-tab-${detailTab.value}`)?.focus();
}

function selectReaderStatus(status) {
  if (readerStatus.value === status) return;
  readerStatus.value = status;
  readerPage.value = 1;
  void loadReaders();
}

async function loadReaders() {
  if (!canManageDetail.value || detailTab.value !== "readers") return;
  const sequence = ++readersRequestSequence;
  readersLoading.value = true;
  readersError.value = "";
  try {
    const data = await apiGet(`${BASE}/${detailNotice.value.id}/recipients`, { status: readerStatus.value, page: readerPage.value, pageSize: PAGE_SIZE });
    if (sequence !== readersRequestSequence) return;
    readers.value = data.items || [];
    readersTotal.value = Number(data.total || 0);
  } catch (error) {
    if (sequence === readersRequestSequence) readersError.value = error instanceof Error ? error.message : "阅读名单加载失败";
  } finally {
    if (sequence === readersRequestSequence) readersLoading.value = false;
  }
}

function startTableDrag(event) {
  const element = event.currentTarget;
  element.dataset.dragged = "false";
  if (event.button !== 0 || event.target.closest('button,a,input,select,textarea,[contenteditable="true"]')) return;
  element.dataset.isDown = "true";
  element.dataset.startX = String(event.pageX);
  element.dataset.scrollLeft = String(element.scrollLeft);
}

function moveTableDrag(event) {
  const element = event.currentTarget;
  if (element.dataset.isDown !== "true") return;
  const walk = (event.pageX - Number(element.dataset.startX)) * 1.2;
  if (Math.abs(walk) > 5) {
    element.dataset.dragged = "true";
    event.preventDefault();
  }
  element.scrollLeft = Number(element.dataset.scrollLeft) - walk;
}

function endTableDrag(event) {
  event.currentTarget.dataset.isDown = "false";
}

function suppressDraggedClick(event) {
  if (event.currentTarget.dataset.dragged !== "true") return;
  event.currentTarget.dataset.dragged = "false";
  event.preventDefault();
  event.stopPropagation();
}

function scrollTableByKeyboard(event) {
  if (event.target !== event.currentTarget || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  event.currentTarget.scrollLeft += event.key === "ArrowRight" ? 120 : -120;
}

function openNoticeRow(event, notice) {
  if (busy.value || event.target.closest("button,a")) return;
  // The title button remains the native keyboard entry; clicking any other cell opens the same detail.
  event.currentTarget.querySelector(".notification-title-link")?.focus();
  void openDetail(notice);
}

async function saveCategory() {
  const name = categoryName.value.trim();
  if (!name || categoryBusy.value) return;
  categoryBusy.value = true;
  errorMessage.value = "";
  try {
    if (editingCategoryId.value) {
      await apiPatch(`${BASE}/categories/${editingCategoryId.value}`, { name });
      showFeedback("通知分类已改名");
    } else {
      await apiPost(`${BASE}/categories`, { name });
      showFeedback("通知分类已添加");
    }
    categoryName.value = "";
    editingCategoryId.value = "";
    await loadCategories();
  } catch (error) {
    showFeedback(error instanceof Error ? error.message : "通知分类保存失败", "error");
  } finally {
    categoryBusy.value = false;
  }
}

function editCategory(category) {
  editingCategoryId.value = String(category.id);
  categoryName.value = category.name;
}

async function deleteCategory(category) {
  if (!await askConfirmation(`确定删除分类“${category.name}”吗？`, { title: "删除分类", confirmText: "删除分类" })) return;
  categoryBusy.value = true;
  try {
    await apiDelete(`${BASE}/categories/${category.id}`);
    await loadCategories();
    showFeedback("通知分类已删除");
  } catch (error) {
    showFeedback(error instanceof Error ? error.message : "分类删除失败", "error");
  } finally {
    categoryBusy.value = false;
  }
}

watch([editorTitle, editorCategoryId, editorExpiresAt, editorHtml, selectedRecipientCount, editorLevel], ([title, category, expires, html, recipients, level]) => {
  const previous = Object.values(fieldErrors.value);
  if (!previous.length) return;
  const errors = { ...fieldErrors.value };
  if (title.trim()) delete errors.title;
  if (category) delete errors.category;
  if (notificationLevels.some(item => item.value === level)) delete errors.level;
  if (validExpirationDate(expires)) delete errors.expires;
  const body = document.createElement("template");
  body.innerHTML = sanitizeRichHtml(html || "");
  if (body.content.textContent.trim() || body.content.querySelector("img")) delete errors.body;
  if (recipients) delete errors.audience;
  fieldErrors.value = errors;
  if (previous.includes(editorError.value)) editorError.value = Object.values(errors)[0] || "";
});

watch(isFormDirty, (value) => {
  dirty.value = value;
});
watch([dirty, permissionDirty], ([formDirty, permissionsDirty]) => {
  emit("dirty-change", formDirty || permissionsDirty);
}, { immediate: true });
watch([saving, permissionSaving], ([editorSaving, permissionsBusy]) => {
  emit("saving-change", editorSaving || permissionsBusy);
}, { immediate: true });
watch([listKeyword, listCategory, listDateFrom, listDateTo, listStatus, listRecipientUserId, listUnreadUserId], scheduleFilterLoad);
onMounted(initialize);
onBeforeUnmount(() => {
  window.clearTimeout(searchTimer);
  detailRequestSequence++;
  readersRequestSequence++;
  emit("dirty-change", false);
  emit("saving-change", false);
});

defineExpose({
  hasPendingChanges: () => isFormDirty.value || permissionDirty.value,
  isSaveInProgress: () => busy.value || saving.value || permissionSaving.value,
});
</script>

<template>
  <div class="notification-workspace flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-slate-100 text-slate-900">
    <h1 class="sr-only">通知</h1>
    <nav class="notification-subnav flex h-12 shrink-0 items-center border-b border-slate-200 bg-white" aria-label="通知模块页面">
      <div class="flex w-full gap-2 overflow-x-auto px-3 sm:px-4" role="tablist" aria-label="通知模块页面">
        <button
          v-for="(tab, index) in visibleTabs"
          :id="`notification-tab-${tab.id}`"
          :key="tab.id"
          type="button"
          role="tab"
          class="notification-tab inline-flex h-8 shrink-0 items-center whitespace-nowrap rounded-md px-3 text-sm font-medium transition-colors"
          :class="currentTab === tab.id ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'"
          :aria-selected="currentTab === tab.id"
          :aria-controls="`notification-panel-${tab.id}`"
          :tabindex="currentTab === tab.id ? 0 : -1"
          :disabled="busy || saving || permissionSaving"
          @click="setTab(tab.id)"
          @keydown="handleTabKeydown($event, index)"
        >{{ tab.label }}</button>
      </div>
    </nav>

    <section
      :id="`notification-panel-${currentTab}`"
      class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-3 sm:p-4"
      role="tabpanel"
      :aria-labelledby="`notification-tab-${currentTab}`"
    >
      <div class="notification-panel flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <header class="notification-toolbar flex min-h-12 shrink-0 items-center justify-between gap-3 border-b border-slate-200 px-3 py-2">
          <h2 class="min-w-0 truncate text-sm font-semibold text-slate-800">{{ currentTabLabel }}</h2>
          <div v-if="['notices', 'history'].includes(currentTab)" class="notification-list-tools">
            <button v-if="listKeyword || listCategory || listDateFrom || listDateTo || listStatus !== 'all' || (managementList && (listRecipientUserId || listUnreadUserId))" type="button" class="notification-text-button" :disabled="loading" @click="resetFilters">清除筛选</button>
            <button type="button" class="notification-icon-button" aria-label="刷新通知记录" :disabled="loading" @click="loadList({ reset: true })"><RefreshCw :size="15" aria-hidden="true" /></button>
            <button v-if="canPublish && currentTab === 'notices'" type="button" class="notification-primary" data-ai-action="notifications.create" :disabled="busy || loading" @click="openCreateEditor"><Plus :size="16" aria-hidden="true" />新建通知</button>
          </div>
        </header>

    <div v-if="errorMessage" class="notification-alert" role="alert">{{ errorMessage }} <button type="button" @click="initialize">重新加载</button></div>
    <div v-if="loading" class="notification-state" role="status"><LoaderCircle class="animate-spin" :size="17" />正在加载通知…</div>
    <div v-else-if="!capability" class="notification-state"><button type="button" class="notification-button" @click="initialize">重新加载</button></div>

    <template v-else-if="['notices', 'history'].includes(currentTab)">
      <section class="flex min-h-0 flex-1 flex-col overflow-hidden" :aria-label="currentTab === 'notices' ? '通知列表记录' : '我的历史通知'">
        <div class="notification-table-scroll" tabindex="0" role="region" aria-label="通知记录表格，可横向滚动"
          @mousedown="startTableDrag" @mousemove="moveTableDrag" @mouseup="endTableDrag" @mouseleave="endTableDrag"
          @click.capture="suppressDraggedClick" @keydown="scrollTableByKeyboard">
          <table class="notification-table" :class="{ 'is-management': managementList }" :aria-busy="listRequestPending">
            <caption class="sr-only">{{ currentTab === 'notices' ? '通知列表记录' : '我的通知历史' }}</caption>
            <colgroup>
              <col class="notification-col-sequence" /><col /><col class="notification-col-category" /><col class="notification-col-time" /><col class="notification-col-expiry" />
              <template v-if="managementList"><col class="notification-col-status" /><col class="notification-col-recipients" /><col class="notification-col-unread" /></template>
            </colgroup>
            <thead>
              <tr><th scope="col" class="notification-sequence-cell">序号</th><th scope="col">标题</th><th scope="col">分类</th><th scope="col">发布时间</th><th scope="col">到期日期</th><th v-if="managementList" scope="col">状态</th><th v-if="managementList" scope="col">接收人</th><th v-if="managementList" scope="col">未完成</th></tr>
              <tr class="notification-column-filters" aria-label="通知列表列筛选">
                <td class="notification-sequence-cell"></td>
                <td><label class="notification-search"><Search :size="15" aria-hidden="true" /><span class="sr-only">按通知标题搜索</span><input v-model="listKeyword" type="search" placeholder="搜索通知标题" /></label></td>
                <td><PlatformDetailEditPicker v-model="listCategory" class="notification-filter-select" :options="categoryOptions" aria-label="通知分类" placeholder="全部分类" search-placeholder="搜索通知分类" menu-width-class="w-[220px]" /></td>
                <td><div class="notification-filter-dates" role="group" aria-label="发布时间范围">
                  <PlatformDateField id="notice-filter-from" v-model="listDateFrom" class="notification-filter-date" name="dateFrom" type="date" aria-label="开始日期" placeholder="开始日期" />
                  <span class="notification-date-separator" aria-hidden="true">至</span>
                  <PlatformDateField id="notice-filter-to" v-model="listDateTo" class="notification-filter-date" name="dateTo" type="date" aria-label="结束日期" placeholder="结束日期" />
                </div></td>
                <td></td>
                <td v-if="managementList"><PlatformDetailEditPicker v-model="listStatus" class="notification-filter-select" :options="[{ value: 'all', label: '全部状态' }, { value: 'published', label: '已发布' }, { value: 'draft', label: '草稿' }, { value: 'withdrawn', label: '已撤回' }, { value: 'expired', label: '已失效' }]" aria-label="发布状态" placeholder="全部状态" :searchable="false" menu-width-class="w-[180px]" /></td>
                <td v-if="managementList"><PlatformDetailEditPicker v-model="listRecipientUserId" class="notification-filter-select" :options="employeeOptions" :match-option="matchDirectoryOption" aria-label="接收人筛选" placeholder="搜索接收人" search-placeholder="搜索接收人姓名、ID 或拼音" menu-width-class="w-72" align-right /></td>
                <td v-if="managementList"><PlatformDetailEditPicker v-model="listUnreadUserId" class="notification-filter-select" :options="employeeOptions" :match-option="matchDirectoryOption" aria-label="未完成人员筛选" placeholder="搜索未完成人员" search-placeholder="搜索未完成人员姓名、ID 或拼音" menu-width-class="w-72" align-right /></td>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(notice, index) in (managementList ? notices : historyRows)" :key="notice.id" class="notification-record-row" @click="openNoticeRow($event, notice)">
                <td class="notification-sequence-cell">{{ (listPage - 1) * PAGE_SIZE + index + 1 }}</td>
                <td><button type="button" class="notification-title-link" :data-notice-id="notice.id" @click.stop="openDetail(notice)">{{ notice.title }}</button><span v-if="notice.readAt" class="notification-read-tag">{{ notificationLevel(notice.level).completed }}</span><span v-else-if="currentTab === 'history'" class="notification-unread-tag">{{ notificationLevel(notice.level).pending }}</span><span v-if="notice.level && notice.level !== 'ordinary'" class="notification-category-badge">{{ notificationLevel(notice.level).label }}</span></td>
                <td>{{ notice.category?.name || '—' }}</td><td>{{ formatTime(notice.publishedAt || notice.createdAt) }}</td><td>{{ notice.expiresOn || expirationDate(notice.expiresAt) || '长期有效' }}</td>
                <td v-if="managementList"><span class="notification-status" :class="`status-${notice.status}`">{{ ({ published: '已发布', draft: '草稿', withdrawn: '已撤回', expired: '已失效' })[notice.status] || notice.status }}</span></td>
                <td v-if="managementList"></td><td v-if="managementList"></td>
              </tr>
              <tr v-if="(managementList ? notices : historyRows).length === 0"><td :colspan="managementList ? 8 : 5" class="notification-empty">{{ managementList ? '没有符合筛选条件的通知' : '你还没有收到通知' }}</td></tr>
            </tbody>
          </table>
        </div>
        <footer class="notification-pagination">
          <span class="notification-pagination-total">共 <strong>{{ total }}</strong> 条 · 每页 {{ PAGE_SIZE }} 条</span>
          <nav class="notification-page-controls" aria-label="通知列表分页" :aria-busy="listRequestPending">
            <button type="button" :disabled="listPage <= 1 || loading || listRequestPending" @click="goToListPage(listPage - 1)">上一页</button>
            <template v-for="page in visibleListPages" :key="page">
              <span v-if="typeof page === 'string'" class="notification-page-ellipsis" aria-hidden="true">...</span>
              <button v-else type="button" class="notification-page-number" :aria-label="`第 ${page} 页`" :aria-current="page === listPage ? 'page' : undefined" :disabled="loading || listRequestPending" @click="goToListPage(page)">{{ page }}</button>
            </template>
            <button type="button" :disabled="listPage >= maxPage || loading || listRequestPending" @click="goToListPage(listPage + 1)">下一页</button>
          </nav>
          <span class="sr-only" role="status">第 {{ listPage }} / {{ maxPage }} 页</span>
        </footer>
      </section>
    </template>

    <section v-else-if="currentTab === 'categories' && canManage" class="notification-admin-section">
      <div class="notification-section-heading"><div><h3>通知分类</h3><p>每条通知都必须选择一个分类。已使用分类可以改名。</p></div></div>
      <form class="notification-category-form" @submit.prevent="saveCategory"><label for="notification-category-name">分类名称</label><input id="notification-category-name" v-model="categoryName" maxlength="80" required placeholder="输入分类名称" /><button type="submit" class="notification-primary" :disabled="categoryBusy"><LoaderCircle v-if="categoryBusy" class="animate-spin" :size="15" /><Check v-else-if="editingCategoryId" :size="15" /><Plus v-else :size="15" />{{ editingCategoryId ? '保存修改' : '添加分类' }}</button><button v-if="editingCategoryId" type="button" class="notification-button" @click="editingCategoryId = ''; categoryName = ''">取消</button></form>
      <div class="notification-category-list"><div v-for="category in categories" :key="category.id" class="notification-category-row"><span>{{ category.name }}</span><div><button type="button" class="notification-icon-button" :aria-label="`编辑分类${category.name}`" @click="editCategory(category)"><Pencil :size="15" /></button><button type="button" class="notification-icon-button danger" :aria-label="`删除分类${category.name}`" :disabled="categoryBusy" @click="deleteCategory(category)"><Trash2 :size="15" /></button></div></div><p v-if="categories.length === 0" class="notification-empty">暂无通知分类</p></div>
    </section>

    <section v-else-if="currentTab === 'permissions' && canManage" class="flex min-h-0 flex-1 flex-col overflow-hidden">
      <SettingsOrganizationPermissionsPanel
        v-if="permissionRole === 'admin'"
        ref="adminPermissionsPanel"
        api-path="/api/org/notices/permissions/admin"
        permission-label="通知管理员权限"
        member-label="通知管理员"
        permission-note="可管理通知、分类和角色；后台管理员始终保留此能力。"
        :role-options="notificationRoles"
        :active-role-id="permissionRole"
        @role-select="switchPermissionRole"
        @dirty-change="adminPermissionsDirty = Boolean($event)"
        @saving-change="adminPermissionsSaving = Boolean($event)"
      />
      <SettingsOrganizationPermissionsPanel
        v-else
        ref="publisherPermissionsPanel"
        api-path="/api/org/notices/permissions/publisher"
        permission-label="通知发布者权限"
        member-label="通知发布者"
        permission-note="可以发布通知并管理自己创建的通知，不包含分类和角色管理权限。"
        :role-options="notificationRoles"
        :active-role-id="permissionRole"
        @role-select="switchPermissionRole"
        @dirty-change="publisherPermissionsDirty = Boolean($event)"
        @saving-change="publisherPermissionsSaving = Boolean($event)"
      />
    </section>

      </div>
    </section>

    <PlatformDetailDrawer :open="editorOpen || Boolean(detailNotice)"
      :labelled-by="editorOpen ? 'notification-editor-title' : 'notification-detail-title'"
      :suspended="Boolean(confirmation)" :close-on-backdrop="!busy" :close-on-escape="!busy"
      @close="editorOpen ? requestCloseEditor() : closeDetail()">
      <template v-if="editorOpen">
        <header class="notice-drawer-header" data-notification-editor>
          <div class="notice-drawer-heading"><span class="notice-drawer-icon"><Bell :size="20" aria-hidden="true" /></span><div><h2 id="notification-editor-title">{{ editorNoticeId ? '编辑通知' : '新建通知' }}</h2><div class="notice-drawer-meta"><span class="notice-meta-badge">{{ editorNoticeId ? `通知 #${editorNoticeId}` : '待保存' }}</span><span class="notice-meta-badge is-blue">{{ audienceLocked ? '接收名单已固定' : '草稿' }}</span></div></div></div>
          <button type="button" class="notice-drawer-close" aria-label="关闭通知编辑器" :disabled="busy" @click="requestCloseEditor"><X :size="20" /></button>
        </header>
        <form id="notification-editor-form" class="notice-drawer-body" data-notification-editor :inert="busy ? true : undefined" novalidate @submit.prevent="saveEditor()">
          <section class="notice-info-section" aria-labelledby="notice-basic-heading">
            <h3 id="notice-basic-heading" class="notice-section-title">通知信息</h3>
            <div class="notice-form-grid">
              <div class="notice-field"><p class="notice-field-label"><Tag :size="14" aria-hidden="true" />分类 <b>*</b></p><PlatformDetailEditPicker v-model="editorCategoryId" :options="categoryOptions" required aria-label="通知分类" placeholder="请选择分类" search-placeholder="搜索分类" menu-width-class="w-full" :invalid="Boolean(fieldErrors.category)" :described-by="fieldErrors.category ? 'notice-category-error' : ''" /><p v-if="fieldErrors.category" id="notice-category-error" class="notice-field-error">{{ fieldErrors.category }}</p></div>
              <div class="notice-field"><label for="notice-expires-at"><CalendarDays :size="14" aria-hidden="true" />到期日期</label><PlatformDateField id="notice-expires-at" v-model="editorExpiresAt" class="notice-expiry-field" name="expiresAt" type="date" :invalid="Boolean(fieldErrors.expires)" :described-by="fieldErrors.expires ? 'notice-expiry-error' : 'notice-expiry-note'" /><p id="notice-expiry-note" class="notice-field-note">留空则长期有效；所选日期当天仍有效，次日北京时间零点停止提醒。</p><p v-if="fieldErrors.expires" id="notice-expiry-error" class="notice-field-error">{{ fieldErrors.expires }}</p></div>
              <div class="notice-field notice-field-full"><p class="notice-field-label"><Bell :size="14" aria-hidden="true" />通知等级 <b>*</b></p><PlatformDetailEditPicker v-model="editorLevel" :options="notificationLevels" required :searchable="false" aria-label="通知等级" placeholder="请选择通知等级" menu-width-class="w-full" :invalid="Boolean(fieldErrors.level)" :described-by="fieldErrors.level ? 'notice-level-error' : 'notice-level-note'" /><p id="notice-level-note" class="notice-field-note">{{ levelChanged ? '修改通知等级后，请保存并重新发布。' : editorLevel === 'ordinary' ? '接收人点击已读即可完成。' : '接收人填写与声明完全一致的内容后完成确认，支持复制粘贴纯文本。' }}</p><p v-if="editorLevel !== 'ordinary'" class="notice-field-note">确认声明：{{ notificationLevel(editorLevel).statement }}</p><p v-if="fieldErrors.level" id="notice-level-error" class="notice-field-error">{{ fieldErrors.level }}</p></div>
              <div class="notice-field notice-field-full"><p id="notice-audience-heading" class="notice-field-label"><Users :size="14" aria-hidden="true" />通知对象 <b>*</b><span class="notice-audience-count">{{ selectedRecipientCount }} 人</span></p><p id="notice-audience-note" class="notice-field-note">{{ audienceLocked ? '已发布通知使用发布时固定的接收名单。' : '部门默认包含下级部门，发布时固化名单并自动去重。' }}</p></div>
              <div class="notice-field notice-field-full"><p class="notice-field-label"><Building2 :size="14" aria-hidden="true" />部门</p><PlatformDetailEditPicker v-model="selectedDepartmentIds" :options="departmentOptions" :match-option="matchDirectoryOption" option-toggle-label="包含所有下级部门" option-toggle-badge-label="含下级" @option-toggle="setDepartmentIncludeSubDepartments" multiple :disabled="audienceLocked" :invalid="Boolean(fieldErrors.audience)" aria-label="通知部门" placeholder="请选择部门" search-placeholder="搜索部门名称、ID 或拼音" menu-width-class="w-full" described-by="notice-audience-note" /></div>
              <div class="notice-field notice-field-full"><p class="notice-field-label"><Users :size="14" aria-hidden="true" />人员</p><PlatformDetailEditPicker v-model="selectedPeopleIds" :options="employeeOptions" :match-option="matchDirectoryOption" multiple :disabled="audienceLocked" :invalid="Boolean(fieldErrors.audience)" aria-label="通知人员" placeholder="请选择人员" search-placeholder="搜索人员姓名、ID 或拼音" menu-width-class="w-full" :described-by="fieldErrors.audience ? 'notice-audience-error' : 'notice-audience-note'" /><p v-if="fieldErrors.audience" id="notice-audience-error" class="notice-field-error">{{ fieldErrors.audience }}</p></div>
            </div>
          </section>
          <section class="notice-info-section" aria-labelledby="notice-content-heading">
            <h3 id="notice-content-heading" class="notice-section-title">通知内容</h3>
            <div class="notice-form-grid">
              <div class="notice-field notice-field-full"><label for="notification-title-input"><FileText :size="14" aria-hidden="true" />标题 <b>*</b></label><input id="notification-title-input" v-model="editorTitle" aria-label="通知标题" class="notice-text-input" maxlength="200" autocomplete="off" required :aria-invalid="Boolean(fieldErrors.title)" :aria-describedby="fieldErrors.title ? 'notice-title-error' : undefined" data-ai-field="notifications.title" /><p v-if="fieldErrors.title" id="notice-title-error" class="notice-field-error">{{ fieldErrors.title }}</p></div>
              <div class="notice-field notice-field-full"><label for="notification-rich-body"><FileText :size="14" aria-hidden="true" />正文 <b>*</b></label><PlatformRichTextEditor v-model="editorHtml" editor-id="notification-rich-body" aria-label="通知正文" placeholder="请输入通知正文" :show-toolbar="true" :disabled="busy" :invalid="Boolean(fieldErrors.body)" :aria-describedby="fieldErrors.body ? 'notice-body-error' : ''" /><p v-if="fieldErrors.body" id="notice-body-error" class="notice-field-error">{{ fieldErrors.body }}</p></div>
              <div class="notice-field notice-field-full"><label for="notification-attachments"><Paperclip :size="14" aria-hidden="true" />附件</label><p class="notice-field-note">最多10个附件，每个不超过20 MB。</p><PlatformAttachmentField id="notification-attachments" v-model="attachmentFiles" :disabled="busy" :max-files="10" :max-file-size="20 * 1024 * 1024" :status-text="uploadStatus" @remove-persisted="removeAttachment" @error="editorError = $event" /></div>
            </div>
          </section>
        </form>
        <div v-if="editorError" class="notice-drawer-error" role="alert">{{ editorError }}</div>
        <footer class="notice-drawer-footer"><p role="status">{{ busy ? (uploadStatus || '正在保存…') : `${audienceLocked ? '固定接收' : '预计接收'} ${selectedRecipientCount} 人` }}</p><div><button type="button" class="notification-button" :disabled="busy" @click="requestCloseEditor">取消</button><button type="submit" form="notification-editor-form" class="notification-button" :disabled="busy || levelChanged">保存</button><button type="button" class="notification-primary" data-ai-action="notifications.publish" :disabled="busy" @click="saveEditor({ publishNow: true })"><LoaderCircle v-if="busy" class="animate-spin" :size="15" /><Send v-else :size="15" />{{ busy ? '正在提交' : audienceLocked ? '保存并重新发布' : '保存并发布' }}</button></div></footer>
      </template>
      <template v-else-if="detailNotice">
        <header class="notice-drawer-header"><div class="notice-drawer-heading"><span class="notice-drawer-icon"><Bell :size="20" aria-hidden="true" /></span><div><h2 id="notification-detail-title">{{ detailNotice.title }}</h2><div class="notice-drawer-meta"><span class="notice-meta-badge">通知 #{{ detailNotice.id }}</span><span class="notification-status" :class="`status-${detailNotice.status}`">{{ ({ published: '已发布', draft: '草稿', withdrawn: '已撤回', expired: '已失效' })[detailNotice.status] || detailNotice.status }}</span></div></div></div><button type="button" class="notice-drawer-close" aria-label="关闭通知详情" :disabled="busy" @click="closeDetail"><X :size="20" /></button></header>
        <div class="shrink-0 border-b border-slate-200 bg-white" role="tablist" aria-label="通知详情页签">
          <div class="flex gap-2 overflow-x-auto px-3 py-2 sm:px-4">
            <button v-for="(tab, index) in detailTabs" :id="`notification-detail-tab-${tab.id}`" :key="tab.id"
              type="button" role="tab" class="notification-tab inline-flex h-8 shrink-0 items-center whitespace-nowrap rounded-md px-3 text-sm font-medium transition-colors"
              :class="detailTab === tab.id ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'"
              :aria-selected="detailTab === tab.id" :aria-controls="`notification-detail-panel-${tab.id}`"
              :tabindex="detailTab === tab.id ? 0 : -1" :disabled="busy"
              @click="selectDetailTab(tab.id)" @keydown="handleDetailTabKeydown($event, index)">{{ tab.label }}</button>
          </div>
        </div>
        <div v-if="detailTab === 'detail'" id="notification-detail-panel-detail" class="notice-drawer-body" role="tabpanel" aria-labelledby="notification-detail-tab-detail" tabindex="0">
          <section class="notice-info-section"><h3 class="notice-section-title">通知信息</h3><dl class="notice-form-grid notice-detail-fields"><div><dt><CalendarDays :size="14" />发布时间</dt><dd>{{ formatTime(detailNotice.publishedAt || detailNotice.createdAt) }}</dd></div><div><dt><CalendarDays :size="14" />到期日期</dt><dd>{{ detailNotice.expiresOn || expirationDate(detailNotice.expiresAt) || '长期有效' }}</dd></div><div><dt><Tag :size="14" />分类</dt><dd>{{ detailNotice.category?.name }}</dd></div><div><dt><Bell :size="14" />通知等级</dt><dd>{{ notificationLevel(detailNotice.level).label }}</dd></div></dl></section>
          <section class="notice-info-section" aria-labelledby="notice-detail-content-heading">
            <h3 id="notice-detail-content-heading" class="notice-section-title">通知内容</h3>
            <dl class="notice-form-grid notice-detail-fields notice-detail-content">
              <div class="notice-field-full"><dt><FileText :size="14" aria-hidden="true" />标题</dt><dd class="notice-content-title">{{ detailNotice.title }}</dd></div>
              <div class="notice-field-full"><dt><FileText :size="14" aria-hidden="true" />正文</dt><dd><RobotMessageContent :html="detailNotice.contentHtml" inline-images /></dd></div>
              <div class="notice-field-full"><dt><Paperclip :size="14" aria-hidden="true" />附件</dt><dd><ul class="notice-detail-attachments"><li v-for="attachment in detailNotice.attachments || []" :key="attachment.id"><Paperclip :size="14" aria-hidden="true" /><a :href="attachment.url" target="_blank" rel="noopener noreferrer">{{ attachment.name }}</a><span>{{ Math.ceil(attachment.size / 1024) }} KB</span></li><li v-if="!detailNotice.attachments?.length" class="notice-field-note">暂无附件</li></ul></dd></div>
            </dl>
          </section>
          <section v-if="detailNotice.confirmation?.statement" class="notice-info-section"><h3 class="notice-section-title">我的确认记录</h3><NotificationConfirmationRecord :record="detailNotice.confirmation" /></section>
        </div>
        <div v-else-if="canManageDetail && detailTab === 'readers'" id="notification-detail-panel-readers" class="notice-drawer-body" role="tabpanel" aria-labelledby="notification-detail-tab-readers" tabindex="0">
          <section class="notice-info-section notice-readers-section"><h3 class="notice-section-title">接收名单<span>{{ notificationLevel(detailNotice.level).pending }} {{ detailNotice.unreadCount || 0 }} / 接收 {{ detailNotice.recipientCount || 0 }} 人</span></h3>
            <div class="notice-reader-toolbar"><div role="group" aria-label="阅读状态"><button v-for="status in [{ id: 'unread', label: notificationLevel(detailNotice.level).pending }, { id: 'read', label: notificationLevel(detailNotice.level).completed }, { id: 'all', label: '全部' }]" :key="status.id" type="button" :aria-pressed="readerStatus === status.id" @click="selectReaderStatus(status.id)">{{ status.label }}</button></div><span>共 {{ readersTotal }} 人</span></div>
            <div v-if="readersLoading" class="notification-state" role="status"><LoaderCircle class="animate-spin" :size="16" />正在加载阅读名单…</div>
            <div v-else-if="readersError" class="notice-drawer-error" role="alert">{{ readersError }} <button type="button" class="notification-text-button" @click="loadReaders">重试</button></div>
            <table v-else class="notice-readers-table"><caption class="sr-only">通知接收人的阅读情况</caption><thead><tr><th scope="col">姓名</th><th scope="col">部门</th><th scope="col">完成状态</th></tr></thead><tbody><tr v-for="person in readers" :key="person.userId"><td>{{ person.name }}</td><td>{{ person.departmentNames.join(' / ') || '未分配部门' }}</td><td><span :class="person.readAt ? 'notification-read-tag' : 'notification-unread-tag'">{{ person.readAt ? `${notificationLevel(detailNotice.level).completed} ${formatTime(person.readAt)}` : notificationLevel(detailNotice.level).pending }}</span><NotificationConfirmationRecord v-if="person.readAt && person.confirmation?.statement" :record="person.confirmation" /></td></tr><tr v-if="!readers.length"><td colspan="3" class="notification-empty">没有符合条件的人员</td></tr></tbody></table>
          </section>
        </div>
        <div v-if="detailError" class="notice-drawer-error" role="alert">{{ detailError }}</div>
        <footer v-if="canManageDetail || detailNotice.readAt" class="notice-drawer-footer">
          <div v-if="detailTab === 'readers'" role="group" aria-label="阅读名单分页"><button type="button" class="notification-button" :disabled="readerPage <= 1 || readersLoading || Boolean(readersError)" @click="readerPage -= 1; loadReaders()"><ChevronLeft :size="15" />上一页</button><span>第 {{ readerPage }} / {{ Math.max(1, Math.ceil(readersTotal / PAGE_SIZE)) }} 页</span><button type="button" class="notification-button" :disabled="readerPage * PAGE_SIZE >= readersTotal || readersLoading || Boolean(readersError)" @click="readerPage += 1; loadReaders()">下一页<ChevronRight :size="15" /></button></div>
          <p v-else-if="detailNotice.readAt">{{ notificationLevel(detailNotice.level).completed }}于 {{ formatTime(detailNotice.readAt) }}</p>
          <div v-if="canManageDetail" role="group" aria-label="通知操作">
            <button v-if="detailNotice.status === 'published'" type="button" class="notification-button danger" :disabled="busy" @click="withdrawNotice(detailNotice)">撤回</button>
            <button v-if="['draft', 'withdrawn', 'expired'].includes(detailNotice.status)" type="button" class="notification-primary" :disabled="busy" @click="publishNotice(detailNotice)"><Send :size="15" />{{ detailNotice.status === 'draft' ? '发布' : '重新发布' }}</button>
            <button type="button" class="notification-primary danger" :disabled="busy" @click="deleteNotice(detailNotice)"><Trash2 :size="15" />删除</button>
            <button ref="detailEditButton" type="button" class="notification-primary" :disabled="busy" @click="openEditEditor(detailNotice)"><Pencil :size="15" />编辑</button>
          </div>
        </footer>
      </template>
    </PlatformDetailDrawer>

    <SettingsUnsavedChangesDialog
      :open="Boolean(confirmation)"
      :title="confirmation?.title"
      :message="confirmation?.message"
      :confirm-text="confirmation?.confirmText"
      :confirm-tone="confirmation?.confirmTone"
      @cancel="resolveConfirmation(false)"
      @confirm="resolveConfirmation(true)"
    />
  </div>
</template>

<style scoped>
.notification-workspace{--notification-tab-height:32px;--notification-subnav-height:48px;--notification-control-height:36px;--notification-filter-height:32px;--notification-label-size:14px;--notification-table-size:13px;--notification-sequence-width:48px}
.notification-subnav{min-height:var(--notification-subnav-height)}
.notification-tab{height:var(--notification-tab-height,32px);font-size:var(--notification-label-size,14px);cursor:pointer}
.notification-tab:disabled{cursor:not-allowed;opacity:.55}
.notification-toolbar{background:linear-gradient(180deg,#fff,#f8fafc)}
.notification-toolbar .notification-primary{min-height:var(--notification-control-height);font-size:var(--notification-label-size)}
.notification-panel .notification-search{height:var(--notification-filter-height)}
.notification-panel .notification-search input{height:100%}
.notification-panel .notification-table{font-size:var(--notification-table-size)}
.notification-primary,.notification-button,.notification-icon-button,.notification-text-button,.notification-danger-link,.notification-title-link{display:inline-flex;align-items:center;justify-content:center;gap:6px;border-radius:8px;font:inherit;cursor:pointer}
.notification-primary{min-height:36px;padding:0 12px;border:1px solid #2563eb;background:#2563eb;color:#fff;font-size:14px;font-weight:600}.notification-primary:hover{background:#1d4ed8}.notification-primary:disabled,.notification-button:disabled,.notification-icon-button:disabled,.notification-text-button:disabled,.notification-danger-link:disabled{cursor:not-allowed;opacity:.55}
.notification-primary.danger{border-color:var(--mj-danger,#dc2626);background:var(--mj-danger,#dc2626)}.notification-primary.danger:hover:not(:disabled){border-color:#b91c1c;background:#b91c1c}
.notification-button{min-height:36px;padding:0 10px;border:1px solid #dbe3ed;background:#fff;color:#334155;font-size:14px}.notification-button:hover:not(:disabled),.notification-icon-button:hover:not(:disabled){border-color:#93c5fd;background:#eff6ff;color:#1d4ed8}
.notification-button.danger{border-color:#fecaca;color:#dc2626}.notification-button.danger:hover:not(:disabled){border-color:#f87171;background:#fef2f2;color:#b91c1c}
.notification-icon-button{width:32px;height:32px;border:1px solid #e2e8f0;background:#fff;color:#64748b}.notification-icon-button.danger{color:#dc2626}.notification-text-button{border:0;background:transparent;color:#2563eb;font-size:12px;padding:4px}.notification-danger-link{border:0;background:transparent;color:#dc2626;font-size:12px;padding:4px}.notification-text-button:hover,.notification-danger-link:hover{text-decoration:underline}
.notification-alert{margin:10px 14px 0;padding:9px 12px;border:1px solid #fecaca;border-radius:6px;background:#fff1f2;color:#b91c1c;font-size:12px}.notification-alert button{margin-left:8px;color:#1d4ed8;text-decoration:underline}
.notification-state{display:flex;min-height:160px;flex:1;align-items:center;justify-content:center;gap:9px;color:#64748b;font-size:13px}.notification-category-form input,.notification-field input,.notification-field select,.notification-search input{height:34px;min-width:0;border:1px solid #dbe3ed;border-radius:6px;background:#fff;padding:0 9px;color:#334155;font:inherit;font-size:12px}.notification-search{display:flex;height:34px;min-width:180px;align-items:center;gap:7px;border:1px solid #dbe3ed;border-radius:6px;background:#fff;padding:0 9px;color:#64748b}.notification-search input{height:31px;flex:1;border:0;padding:0;outline:0}.notification-date-separator{color:#94a3b8;font-size:12px}.notification-table-scroll{min-height:0;flex:1;overflow:auto;scrollbar-width:none}.notification-table-scroll:focus-visible{outline:2px solid #2563eb;outline-offset:-2px}.notification-table{width:100%;min-width:868px;table-layout:fixed;border-collapse:separate;border-spacing:0;white-space:nowrap;font-size:12px}.notification-table thead{position:sticky;top:0;z-index:2}.notification-table th{height:36px;border-bottom:1px solid #e2e8f0;background:#f1f5f9;padding:0 11px;text-align:left;color:#475569;font-weight:600}.notification-table td{height:42px;border-bottom:1px solid #edf1f5;padding:6px 11px;color:#334155}.notification-table tbody tr:nth-child(even){background:#fafcff}.notification-table tbody tr:hover{background:#eff6ff}.notification-table th:nth-child(2),.notification-table td:nth-child(2){min-width:210px}.notification-title-link{border:0;background:transparent;padding:3px 0;color:#0f172a;font-weight:600;text-align:left}.notification-title-link:hover{color:#2563eb;text-decoration:underline}.notification-record-row{cursor:pointer}.notification-status,.notification-read-tag,.notification-unread-tag,.notification-category-badge{display:inline-flex;align-items:center;border-radius:4px;padding:3px 6px;font-size:11px}.notification-status.status-published,.notification-read-tag{background:#ecfdf5;color:#047857}.notification-status.status-draft{background:#f1f5f9;color:#64748b}.notification-status.status-withdrawn,.notification-status.status-expired{background:#fff7ed;color:#b45309}.notification-unread-tag{background:#fff1f2;color:#be123c}.notification-category-badge{background:#eff6ff;color:#1d4ed8}.notification-empty{padding:30px 12px!important;text-align:center;color:#94a3b8!important}.notification-pagination{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);min-height:44px;flex-shrink:0;align-items:center;gap:12px;border-top:1px solid var(--mj-border,#e2e8f0);padding:6px 14px;color:var(--mj-muted,#64748b);font-size:12px}
.notification-pagination-total{grid-column:1;white-space:nowrap}.notification-pagination-total strong{color:var(--mj-body,#475569);font-weight:500}
.notification-page-controls{grid-column:2;display:flex;align-items:center;gap:4px;border:1px solid var(--mj-border,#e2e8f0);border-radius:6px;background:var(--mj-surface-soft,#f8fafc);padding:2px}
.notification-page-controls button{min-height:28px;flex-shrink:0;border:0;border-radius:4px;background:transparent;padding:4px 10px;color:var(--mj-body,#475569);font:inherit;cursor:pointer}
.notification-page-controls button:hover{background:var(--mj-surface,#fff);color:var(--mj-primary,#2563eb)}.notification-page-controls button:disabled{cursor:not-allowed;opacity:.4}
.notification-page-controls .notification-page-number{min-width:28px;padding:4px 6px;font-weight:500}.notification-page-controls [aria-current=page]{background:var(--mj-surface,#fff);color:var(--mj-primary,#2563eb);box-shadow:0 1px 2px rgb(0 0 0 / 5%),0 0 0 1px var(--mj-border,#e2e8f0)}
.notification-page-ellipsis{padding:4px 6px;color:var(--mj-muted,#64748b)}.notification-admin-section{min-height:0;flex:1;overflow:auto;padding:18px}.notification-section-heading h3{margin:0;color:#0f172a;font-size:15px}.notification-section-heading p{margin:4px 0 0;color:#64748b;font-size:12px;line-height:1.6}.notification-category-form{display:flex;align-items:center;gap:9px;margin:18px 0;padding:13px;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc}.notification-category-form label{color:#475569;font-size:12px}.notification-category-form input{width:min(420px,55vw)}.notification-category-list{max-width:760px;border-top:1px solid #e2e8f0}.notification-category-row{display:flex;min-height:46px;align-items:center;justify-content:space-between;border-bottom:1px solid #e2e8f0;padding:0 9px;color:#334155;font-size:13px}.notification-category-row>div{display:flex;gap:6px}
.notification-list-tools{display:flex;flex-shrink:0;align-items:center;gap:8px}
.notification-table thead .notification-column-filters td{height:42px;border-bottom:1px solid #e2e8f0;background:#fff;padding:4px 11px}
.notification-table.is-management{min-width:1338px}
.notification-col-sequence{width:var(--notification-sequence-width)}
.notification-table .notification-sequence-cell{position:sticky;left:0;z-index:1;width:var(--notification-sequence-width);min-width:0;border-right:1px solid var(--mj-border,#e2e8f0);padding-left:4px;padding-right:4px;background:var(--mj-surface,#fff);text-align:center;font-variant-numeric:tabular-nums;color:var(--mj-muted,#64748b);font-size:12px;font-weight:600}
.notification-table thead .notification-sequence-cell{z-index:3}.notification-table thead th.notification-sequence-cell{background:var(--mj-workspace,#f1f5f9)}
.notification-table tbody tr:nth-child(even) .notification-sequence-cell{background:#fafcff}.notification-table tbody tr:hover .notification-sequence-cell{background:var(--mj-primary-soft,#eff6ff)}
.notification-col-category{width:160px}.notification-col-time{width:310px}.notification-col-expiry{width:130px}.notification-col-status{width:150px}.notification-col-recipients,.notification-col-unread{width:160px}
.notification-table .notification-title-link{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;vertical-align:middle}
.notification-column-filters .notification-search{width:100%;min-width:0;height:var(--notification-filter-height);box-sizing:border-box}
.notification-column-filters .notification-search:focus-within{border-color:#60a5fa;box-shadow:0 0 0 2px #dbeafe}
.notification-column-filters .notification-search input{width:100%;font-size:12px}
.notification-filter-dates{display:flex;min-width:286px;align-items:center;gap:6px}
.notification-filter-dates .notification-filter-date{width:132px;flex:1}
.notification-filter-dates :deep(.platform-date-field>span){font-size:12px;font-weight:400}
.notification-filter-select{width:100%;min-width:128px}.notification-filter-select :deep(.starter-detail-combo){height:32px;min-height:32px}.notification-filter-date{width:140px}
.notice-drawer-header{z-index:10;display:flex;flex-shrink:0;align-items:flex-start;justify-content:space-between;gap:16px;border-bottom:1px solid #f3f4f6;background:#fff;padding:20px 24px;box-shadow:0 4px 20px -8px rgb(0 0 0 / 5%)}
.notice-drawer-heading{display:flex;min-width:0;align-items:center;gap:12px}.notice-drawer-heading>div{min-width:0}.notice-drawer-heading h2{margin:0;color:#111827;font-size:16px;font-weight:700;line-height:1.4;overflow-wrap:anywhere}
.notice-drawer-icon{display:flex;width:40px;height:40px;flex-shrink:0;align-items:center;justify-content:center;border:1px solid rgb(219 234 254 / 50%);border-radius:50%;background:#eff6ff;color:#2563eb;box-shadow:0 1px 2px rgb(0 0 0 / 5%)}
.notice-drawer-meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}.notice-meta-badge{border:1px solid #e5e7eb;border-radius:6px;background:#f9fafb;padding:2px 8px;color:#6b7280;font-size:11px;font-weight:600}.notice-meta-badge.is-blue{border-color:#dbeafe;background:#eff6ff;color:#2563eb}
.notice-drawer-close{display:flex;width:36px;height:36px;flex-shrink:0;align-items:center;justify-content:center;margin-right:-8px;border:0;border-radius:50%;background:transparent;color:#9ca3af;cursor:pointer}.notice-drawer-close:hover{background:#f3f4f6;color:#374151}.notice-drawer-close:disabled{cursor:not-allowed;opacity:.55}
.notice-drawer-body{display:flex;min-height:0;min-width:0;flex:1;flex-direction:column;gap:20px;overflow:auto;margin:0;background:#f8fafc;padding:24px;scrollbar-width:none}
.notice-info-section{min-width:0;flex-shrink:0;border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:20px;box-shadow:0 1px 2px rgb(0 0 0 / 5%)}
.notice-section-title{display:flex;align-items:center;gap:8px;margin:0 0 20px;color:#111827;font-size:13px;font-weight:600}.notice-section-title::before{width:4px;height:14px;flex-shrink:0;border-radius:2px;background:#2563eb;content:''}.notice-section-title>b,.notice-field b{color:#ef4444}.notice-section-title>span{margin-left:auto;color:#64748b;font-size:12px;font-weight:400}.notice-section-note{margin:-8px 0 16px;color:#64748b;font-size:12px;line-height:1.6}.notice-drawer-heading .notice-section-note{margin:4px 0 0}
.notice-form-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px 24px}.notice-field{display:flex;min-width:0;flex-direction:column;gap:6px}.notice-field-full{grid-column:1/-1}.notice-field>label,.notice-field-label,.notice-detail-fields dt{display:flex;align-items:center;gap:8px;margin:0;color:#9ca3af;font-size:12px;line-height:16px}.notice-text-input{box-sizing:border-box;min-width:0;width:100%;height:36px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:0 10px;color:#0f172a;font-family:inherit;font-weight:600;font-size:14px;outline:0}.notice-text-input:focus{border-color:#60a5fa;box-shadow:0 0 0 2px #dbeafe}.notice-text-input[aria-invalid=true]{border-color:#f87171}.notice-expiry-field{max-width:none;height:36px;border-radius:8px}
.notice-audience-count{margin-left:auto;color:var(--mj-muted,#64748b)}
.notice-field-note{margin:0;color:#64748b;font-size:12px;line-height:1.6}.notice-field-error{margin:4px 0 0;color:#dc2626;font-size:12px;line-height:1.5}.notice-drawer-error{flex-shrink:0;border-top:1px solid #fecaca;background:#fef2f2;padding:10px 24px;color:#b91c1c;font-size:13px;line-height:1.6}
.notice-drawer-footer{display:flex;flex-shrink:0;flex-direction:column;align-items:center;justify-content:center;gap:8px;border-top:1px solid #e5e7eb;background:#fff;padding:12px 24px;color:#64748b;font-size:12px}.notice-drawer-footer>p{margin:0}.notice-drawer-footer>div{display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap}.notice-drawer-footer .notification-button,.notice-drawer-footer .notification-primary{min-height:36px;border-radius:8px;padding:0 16px;font-size:14px}
.notice-detail-fields{margin:0}.notice-detail-fields dd{margin:6px 0 0;color:#1f2937;font-size:14px;font-weight:600}.notice-detail-attachments{margin:0;padding:0;list-style:none}.notice-detail-attachments li{display:flex;min-width:0;align-items:center;gap:8px;border-bottom:1px solid #f3f4f6;padding:8px 0;color:#64748b;font-size:12px}.notice-detail-attachments li:last-child{border:0}.notice-detail-attachments a{min-width:0;flex:1;color:#2563eb;overflow-wrap:anywhere}.notice-detail-attachments svg,.notice-detail-attachments span{flex-shrink:0}
.notice-detail-content dd{font-weight:400;overflow-wrap:anywhere}.notice-detail-content .notice-content-title{font-weight:600}
.notice-reader-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px;color:#64748b;font-size:12px}.notice-reader-toolbar>div{display:flex;gap:8px}.notice-reader-toolbar button{height:32px;border:0;border-radius:6px;background:#f1f5f9;padding:0 12px;color:#475569;font-size:14px;cursor:pointer}.notice-reader-toolbar button[aria-pressed=true]{background:#0f172a;color:#fff}
.notice-readers-table{width:100%;border-collapse:collapse;text-align:left;font-size:13px}.notice-readers-table th{height:36px;border-bottom:1px solid #e2e8f0;background:#f1f5f9;padding:0 10px;color:#475569;font-weight:600}.notice-readers-table td{border-bottom:1px solid #edf1f5;padding:10px;color:#334155;overflow-wrap:anywhere}.notice-readers-table tbody tr:nth-child(even){background:#fafcff}
@media (min-width:768px) and (max-width:1100px){.notice-drawer-body{padding:16px}.notice-info-section{padding:16px}.notice-form-grid{grid-template-columns:minmax(0,1fr)}.notice-drawer-header{padding:16px}.notice-section-title>span{font-size:12px}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
</style>
