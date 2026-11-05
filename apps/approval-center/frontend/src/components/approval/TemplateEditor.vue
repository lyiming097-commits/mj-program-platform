<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Building2,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Copy,
  FileText,
  GripVertical,
  Hash,
  ListChecks,
  ListFilter,
  LoaderCircle,
  MessageSquareText,
  Plus,
  Save,
  Send,
  Settings2,
  TextCursorInput,
  Trash2,
  UserRound,
  UsersRound,
  XCircle,
} from "@lucide/vue";

import { approvalApi, itemOf, itemsOf } from "@/approvalApi";

const props = defineProps({
  templateId: { type: [String, Number], default: "" },
  starterKey: { type: String, default: "" },
  step: { type: String, default: "basic" },
  categoryId: { type: [String, Number], default: "" },
  canManageApp: { type: Boolean, default: false },
  managedCategoryIds: { type: Array, default: () => [] },
});

const emit = defineEmits(["navigate", "dirty-change", "saved", "published", "close", "success-notice"]);

const loading = ref(Boolean(props.templateId));
const saving = ref(false);
const publishing = ref(false);
const errorMessage = ref("");
const nameError = ref("");
const templateNameInputRef = ref(null);
const published = ref(false);
const directoryLoading = ref(false);
const directoryReady = ref(false);
const directoryErrorMessage = ref("");
const currentId = ref(String(props.templateId || ""));
const employees = ref([]);
const categories = ref([]);
const categoryLoading = ref(false);
const categoryErrorMessage = ref("");
const selectedFieldId = ref("");
const selectedNodeKey = ref("");
const snapshot = ref("");
const revision = ref("");
let sequence = 0;

const steps = [
  { id: "basic", label: "基础设置", icon: Settings2 },
  { id: "form", label: "表单设计", icon: FileText },
  { id: "flow", label: "流程设置", icon: ClipboardCheck },
  { id: "publish", label: "预览发布", icon: Send },
];

const MAX_TEXT_ROWS = 20;
const TEXT_PREVIEW_MAX_ROWS = 6;
const TEXT_PREVIEW_LINE_HEIGHT = 18;
const TEXT_PREVIEW_VERTICAL_PADDING = 14;
const choiceFieldTypes = new Set(["select", "multiselect"]);
const legacyFieldTypeMap = {
  textarea: "text",
  amount: "number",
  radio: "select",
  checkbox: "multiselect",
};

const fieldTypes = [
  { type: "text", label: "文本", icon: TextCursorInput },
  { type: "number", label: "数字", icon: Hash },
  { type: "date", label: "日期", icon: CalendarDays },
  { type: "dateRange", label: "日期区间", icon: CalendarDays },
  { type: "select", label: "下拉单选", icon: ListFilter },
  { type: "multiselect", label: "下拉多选", icon: ListChecks },
  { type: "user", label: "人员", icon: UserRound },
  { type: "department", label: "部门", icon: Building2 },
  { type: "description", label: "说明文字", icon: MessageSquareText },
];

const draft = ref(blankDraft());

const normalizedStep = computed(() => (
  steps.some((item) => item.id === props.step) ? props.step : "basic"
));
const fields = computed(() => draft.value.formSchema.fields);
const nodes = computed(() => draft.value.flowSchema.nodes);
const selectedField = computed(() => fields.value.find((field) => field.id === selectedFieldId.value) || null);
const selectedNode = computed(() => nodes.value.find((node) => node.key === selectedNodeKey.value) || null);
const dirty = computed(() => !loading.value && snapshot.value !== serializeDraft(draft.value));
const pageTitle = computed(() => currentId.value ? `编辑表单：${draft.value.name || "未命名表单"}` : "新建审批表单");
watch(pageTitle, (title) => { document.title = `${title} - 审批中心`; }, { immediate: true });
const choiceValidationItems = computed(() => fields.value.flatMap((item, index) => {
  if (!choiceFieldTypes.has(item.type)) return [];
  const options = normalizedOptions(item);
  const fieldName = String(item.label || "").trim() || `第 ${index + 1} 个字段`;
  return [
    {
      id: `${item.id}-options-required`,
      label: `“${fieldName}”至少配置 1 个有效选项`,
      valid: options.length > 0,
    },
    {
      id: `${item.id}-options-unique`,
      label: `“${fieldName}”的选项内容不重复`,
      valid: new Set(options).size === options.length,
    },
  ];
}));
const validationItems = computed(() => [
  { id: "name", label: "已填写表单名称", valid: Boolean(draft.value.name.trim()) },
  { id: "fields", label: "已添加表单字段", valid: fields.value.length > 0 },
  { id: "field-labels", label: "字段名称完整", valid: fields.value.every((item) => String(item.label || "").trim()) },
  ...choiceValidationItems.value,
  { id: "directory", label: "组织架构人员已加载", valid: directoryReady.value },
  { id: "approver", label: "已配置审批节点", valid: nodes.value.some((node) => node.type === "approver") },
  {
    id: "assignees",
    label: "节点审批人完整",
    valid: nodes.value.every((node) => node.assigneeType !== "user" || node.assigneeIds.length > 0),
  },
]);
const canPublish = computed(() => validationItems.value.every((item) => item.valid));
const selectedFieldIndex = computed(() => fields.value.findIndex((field) => field.id === selectedFieldId.value));
const selectedNodeIndex = computed(() => nodes.value.findIndex((node) => node.key === selectedNodeKey.value));
const selectedFieldOptionError = computed(() => {
  if (!selectedField.value || !choiceFieldTypes.has(selectedField.value.type)) return "";
  const options = normalizedOptions(selectedField.value);
  if (!options.length) return "至少添加 1 个有效选项";
  if (new Set(options).size !== options.length) return "选项内容不能重复";
  return "";
});

function uniqueId(prefix) {
  sequence += 1;
  return `${prefix}_${Date.now().toString(36)}_${sequence.toString(36)}`;
}

function normalizedOptions(item) {
  return (Array.isArray(item?.options) ? item.options : [])
    .map((option) => String(option || "").trim())
    .filter(Boolean);
}

function normalizeTextRows(value, fallback = 1) {
  if (value === "" || value === null || value === undefined) return fallback;
  const rows = Number(value);
  if (!Number.isFinite(rows)) return fallback;
  return Math.min(MAX_TEXT_ROWS, Math.max(1, Math.trunc(rows)));
}

function textPreviewStyle(item) {
  if (item?.type !== "text") return undefined;
  const rows = normalizeTextRows(item.rows);
  if (rows <= 1) return undefined;
  const previewRows = Math.min(rows, TEXT_PREVIEW_MAX_ROWS);
  return {
    minHeight: `${TEXT_PREVIEW_VERTICAL_PADDING + previewRows * TEXT_PREVIEW_LINE_HEIGHT}px`,
  };
}

function blankDraft() {
  return {
    name: "",
    description: "",
    category: "通用",
    categoryId: "",
    icon: "clipboard-check",
    color: "blue",
    formSchema: { fields: [] },
    flowSchema: { nodes: [] },
    settings: {
      allowWithdraw: true,
      requireApprovalComment: false,
      requireRejectComment: true,
      requireReturnComment: true,
    },
  };
}

function field(type, label, options = {}) {
  const nextField = {
    id: uniqueId("field"),
    type,
    label,
    required: Boolean(options.required),
    placeholder: options.placeholder || "",
    options: Array.isArray(options.options) ? options.options : [],
  };
  if (type === "text") nextField.rows = normalizeTextRows(options.rows);
  return nextField;
}

function starterDraft(key) {
  const base = blankDraft();
  if (key === "procurement") {
    return {
      ...base,
      name: "采购申请",
      category: "采购",
      description: "采购事项审批表单",
      formSchema: { fields: [
        field("text", "采购事由", { required: true, placeholder: "请填写采购事由", rows: 4 }),
        field("number", "预算金额", { required: true }),
        field("date", "期望到货日期", { required: true }),
      ] },
    };
  }
  if (key === "payment") {
    return {
      ...base,
      name: "付款申请",
      category: "财务",
      description: "付款事项审批表单",
      formSchema: { fields: [
        field("text", "收款方", { required: true }),
        field("number", "付款金额", { required: true }),
        field("select", "付款类型", { required: true, options: ["对公付款", "费用报销"] }),
        field("text", "付款说明", { required: true, rows: 4 }),
      ] },
    };
  }
  if (key === "contract") {
    return {
      ...base,
      name: "合同审批",
      category: "合同",
      description: "合同签署审批表单",
      formSchema: { fields: [
        field("text", "合同名称", { required: true }),
        field("text", "合同相对方", { required: true }),
        field("number", "合同金额", { required: true }),
        field("dateRange", "合同期限"),
      ] },
    };
  }
  return base;
}

function normalizeField(item, index) {
  const sourceType = String(item?.type || "");
  const mappedType = legacyFieldTypeMap[sourceType] || sourceType;
  const type = fieldTypes.some((candidate) => candidate.type === mappedType) ? mappedType : "text";
  const normalizedField = {
    id: String(item?.id || item?.key || `field_${index + 1}`),
    type,
    label: String(item?.label || item?.name || fieldTypes.find((candidate) => candidate.type === type)?.label || "字段"),
    required: Boolean(item?.required),
    placeholder: String(item?.placeholder || ""),
    options: Array.isArray(item?.options)
      ? item.options.map((option) => String(option?.label || option?.value || option).trim()).filter(Boolean)
      : [],
  };
  if (type === "text") {
    normalizedField.rows = normalizeTextRows(item?.rows, sourceType === "textarea" ? 4 : 1);
  }
  return normalizedField;
}

function normalizeNode(item, index) {
  const type = item?.type === "cc" ? "cc" : "approver";
  const ids = Array.isArray(item?.assigneeIds) ? item.assigneeIds : [];
  const assigneeNames = item?.assigneeNames && typeof item.assigneeNames === "object"
    ? { ...item.assigneeNames }
    : {};
  (Array.isArray(item?.assignees) ? item.assignees : []).forEach((assignee) => {
    const id = String(assignee?.userId || assignee?.id || "");
    if (id) assigneeNames[id] = String(assignee?.name || id);
  });
  return {
    key: String(item?.key || `node_${index + 1}`),
    type,
    name: String(item?.name || (type === "cc" ? "抄送人" : "审批人")),
    assigneeType: item?.assigneeType === "initiator" ? "initiator" : "user",
    assigneeIds: ids.map(String).filter(Boolean),
    assigneeNames,
    approvalMode: item?.approvalMode === "any" ? "any" : "all",
  };
}

function normalizeTemplate(payload) {
  const item = itemOf(payload, ["template"]);
  const sourceSettings = item?.settings && typeof item.settings === "object" ? item.settings : {};
  const settings = { ...sourceSettings };
  delete settings.notifyInitiator;
  return {
    name: String(item?.name || ""),
    description: String(item?.description || ""),
    category: String(item?.category || "通用"),
    categoryId: String(item?.categoryId ?? item?.category_id ?? ""),
    icon: String(item?.icon || "clipboard-check"),
    color: String(item?.color || "blue"),
    formSchema: {
      fields: (Array.isArray(item?.formSchema?.fields) ? item.formSchema.fields : []).map(normalizeField),
    },
    flowSchema: {
      nodes: (Array.isArray(item?.flowSchema?.nodes) ? item.flowSchema.nodes : []).map(normalizeNode),
    },
    settings: {
      ...blankDraft().settings,
      ...settings,
    },
  };
}

function serializeDraft(value) {
  return JSON.stringify(value);
}

function payloadForSave() {
  const payload = JSON.parse(serializeDraft(draft.value));
  delete payload.settings.notifyInitiator;
  if (payload.categoryId) payload.categoryId = String(payload.categoryId);
  else delete payload.categoryId;
  payload.formSchema.fields = payload.formSchema.fields.map((item) => {
    const nextField = {
      ...item,
      options: choiceFieldTypes.has(item.type) ? normalizedOptions(item) : [],
    };
    if (item.type === "text") nextField.rows = normalizeTextRows(item.rows);
    else delete nextField.rows;
    return nextField;
  });
  payload.flowSchema.nodes = payload.flowSchema.nodes.map((node) => ({
    ...node,
    assignees: node.assigneeType === "user"
      ? node.assigneeIds.map((id) => ({ userId: id, name: node.assigneeNames?.[id] || employeeName(id) }))
      : [],
  }));
  if (currentId.value && revision.value) payload.revision = revision.value;
  return payload;
}

function fieldType(type) {
  return fieldTypes.find((item) => item.type === type) || fieldTypes[0];
}

function employeeName(id) {
  return employees.value.find((employee) => employee.id === String(id))?.name || String(id);
}

function normalizeEmployee(item) {
  const id = String(item?.userId ?? item?.id ?? "").trim();
  return {
    id,
    name: String(item?.name ?? item?.rawName ?? id).trim() || id,
    department: Array.isArray(item?.departments)
      ? item.departments.map((department) => String(department?.name || department)).filter(Boolean).join(" / ")
      : "",
  };
}

async function loadEmployeeDirectory() {
  if (directoryLoading.value) return;
  directoryLoading.value = true;
  directoryReady.value = false;
  directoryErrorMessage.value = "";
  try {
    const result = await approvalApi.employeeDirectory(props.categoryId || draft.value.categoryId || "");
    employees.value = itemsOf(result, ["employees"]).map(normalizeEmployee).filter((item) => item.id);
    directoryReady.value = true;
  } catch (error) {
    employees.value = [];
    const detail = error instanceof Error ? error.message : "组织架构不可用";
    directoryErrorMessage.value = `组织架构人员加载失败：${detail}`;
  } finally {
    directoryLoading.value = false;
  }
}

function normalizeCategory(item) {
  const id = String(item?.id ?? item?.categoryId ?? "").trim();
  if (!id) return null;
  return {
    id,
    name: String(item?.name ?? item?.label ?? id).trim() || id,
    description: String(item?.description || ""),
    canManage: Boolean(item?.canManage),
  };
}

async function loadCategories() {
  categoryLoading.value = true;
  categoryErrorMessage.value = "";
  try {
    const result = await approvalApi.categories({ scope: "manage" });
    categories.value = itemsOf(result, ["categories", "items"]).map(normalizeCategory).filter(Boolean);
  } catch (error) {
    categories.value = [];
    categoryErrorMessage.value = error instanceof Error ? error.message : "分类加载失败";
  } finally {
    categoryLoading.value = false;
  }
}

async function loadEditor() {
  loading.value = true;
  errorMessage.value = "";
  const categoryPromise = loadCategories();
  try {
    if (currentId.value) {
      const templateResult = await approvalApi.template(currentId.value, { scope: "manage" });
      draft.value = normalizeTemplate(templateResult);
      const templateItem = itemOf(templateResult, ["template"]);
      revision.value = String(templateItem?.revision || "");
      published.value = templateItem?.status === "published";
    } else {
      draft.value = starterDraft(props.starterKey);
      draft.value.categoryId = String(props.categoryId || "");
      revision.value = "";
      published.value = false;
    }
    await categoryPromise;
    let selectedCategoryId = String(draft.value.categoryId || props.categoryId || "");
    if (!selectedCategoryId) {
      selectedCategoryId = categories.value.find((item) => item.name === draft.value.category)?.id || "";
    }
    if (selectedCategoryId) draft.value.categoryId = selectedCategoryId;
    const selectedCategory = categories.value.find((item) => item.id === String(draft.value.categoryId));
    if (selectedCategory) draft.value.category = selectedCategory.name;
    const directoryPromise = loadEmployeeDirectory();
    await directoryPromise;
    selectedFieldId.value = fields.value[0]?.id || "";
    selectedNodeKey.value = nodes.value[0]?.key || "";
    snapshot.value = serializeDraft(draft.value);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "表单加载失败";
  } finally {
    loading.value = false;
  }
}

function stepPath(step) {
  const base = currentId.value
    ? `/approval-center/templates/${encodeURIComponent(currentId.value)}/edit/`
    : "/approval-center/templates/new/";
  const params = new URLSearchParams({ step });
  if (!currentId.value && props.starterKey) params.set("starter", props.starterKey);
  if (props.categoryId) params.set("categoryId", String(props.categoryId));
  const returnPath = new URLSearchParams(window.location.search).get("return");
  if (returnPath) params.set("return", returnPath);
  return `${base}?${params.toString()}`;
}

function goToStep(step) {
  emit("navigate", stepPath(step), { bypassGuard: true, replace: true });
}

function addField(type) {
  const config = fieldType(type);
  const next = field(type, config.label, {
    options: choiceFieldTypes.has(type) ? ["选项一", "选项二"] : [],
  });
  fields.value.push(next);
  selectedFieldId.value = next.id;
}

function duplicateField(fieldItem) {
  const index = fields.value.findIndex((item) => item.id === fieldItem.id);
  const copy = { ...JSON.parse(JSON.stringify(fieldItem)), id: uniqueId("field"), label: `${fieldItem.label}副本` };
  fields.value.splice(index + 1, 0, copy);
  selectedFieldId.value = copy.id;
}

function removeField(fieldItem) {
  const index = fields.value.findIndex((item) => item.id === fieldItem.id);
  if (index < 0) return;
  fields.value.splice(index, 1);
  selectedFieldId.value = fields.value[Math.min(index, fields.value.length - 1)]?.id || "";
}

function moveField(delta) {
  const index = selectedFieldIndex.value;
  const target = index + delta;
  if (index < 0 || target < 0 || target >= fields.value.length) return;
  const [item] = fields.value.splice(index, 1);
  fields.value.splice(target, 0, item);
}

function updateSelectedField(key, value) {
  if (!selectedField.value) return;
  selectedField.value[key] = value;
}

function updateSelectedFieldType(type) {
  if (!selectedField.value || !fieldTypes.some((item) => item.type === type)) return;
  selectedField.value.type = type;
  if (type === "text") selectedField.value.rows = normalizeTextRows(selectedField.value.rows);
  else delete selectedField.value.rows;
  if (choiceFieldTypes.has(type) && !normalizedOptions(selectedField.value).length) {
    selectedField.value.options = ["选项一", "选项二"];
  } else if (!choiceFieldTypes.has(type)) {
    selectedField.value.options = [];
  }
}

function updateSelectedTextRows(value) {
  if (!selectedField.value || selectedField.value.type !== "text") return;
  selectedField.value.rows = normalizeTextRows(value);
}

function updateOptions(event) {
  updateSelectedField("options", String(event.target.value || "").split("\n").map((item) => item.trim()).filter(Boolean));
}

function addNode(type) {
  const node = {
    key: uniqueId("node"),
    type,
    name: type === "cc" ? "抄送人" : "审批人",
    assigneeType: "user",
    assigneeIds: [],
    approvalMode: "all",
  };
  nodes.value.push(node);
  selectedNodeKey.value = node.key;
}

function removeNode(node) {
  const index = nodes.value.findIndex((item) => item.key === node.key);
  if (index < 0) return;
  nodes.value.splice(index, 1);
  selectedNodeKey.value = nodes.value[Math.min(index, nodes.value.length - 1)]?.key || "";
}

function moveNode(delta) {
  const index = selectedNodeIndex.value;
  const target = index + delta;
  if (index < 0 || target < 0 || target >= nodes.value.length) return;
  const [item] = nodes.value.splice(index, 1);
  nodes.value.splice(target, 0, item);
}

function updateNodeAssignees(event) {
  if (!selectedNode.value) return;
  selectedNode.value.assigneeIds = [...event.target.selectedOptions].map((option) => option.value);
}

async function saveDraft({ quiet = false } = {}) {
  if (!draft.value.name.trim()) {
    nameError.value = "请先填写表单名称";
    goToStep("basic");
    await nextTick();
    templateNameInputRef.value?.focus();
    return null;
  }
  saving.value = true;
  errorMessage.value = "";
  nameError.value = "";
  try {
    const result = currentId.value
      ? await approvalApi.updateTemplate(currentId.value, payloadForSave())
      : await approvalApi.createTemplate(payloadForSave());
    const saved = itemOf(result, ["template"]);
    const savedId = String(saved?.id || result?.id || currentId.value || "");
    if (!savedId) throw new Error("表单保存结果缺少编号");
    currentId.value = savedId;
    if (saved) {
      draft.value = normalizeTemplate(saved);
      revision.value = String(saved.revision || revision.value || "");
    }
    snapshot.value = serializeDraft(draft.value);
    published.value = saved?.status === "published";
    if (!quiet) emit("success-notice", "草稿已保存");
    emit("saved", { id: savedId, template: saved || draft.value });
    return savedId;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "表单保存失败";
    return null;
  } finally {
    saving.value = false;
  }
}

async function publish() {
  if (!canPublish.value || publishing.value) return;
  publishing.value = true;
  errorMessage.value = "";
  try {
    const id = await saveDraft({ quiet: true });
    if (!id) return;
    const result = await approvalApi.publishTemplate(id, { revision: revision.value });
    const publishedTemplate = itemOf(result, ["template"]);
    revision.value = String(publishedTemplate?.revision || revision.value || "");
    snapshot.value = serializeDraft(draft.value);
    published.value = true;
    emit("success-notice", "表单已发布");
    emit("published", { id, result });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "表单发布失败";
  } finally {
    publishing.value = false;
  }
}

watch(dirty, (value) => emit("dirty-change", value), { immediate: true });

onMounted(loadEditor);
</script>

<template>
  <div class="template-editor-shell">
    <header class="template-editor-header">
      <button type="button" class="approval-icon-button" aria-label="返回表单管理" @click="emit('close', { categoryId: draft.categoryId || props.categoryId })">
        <ArrowLeft aria-hidden="true" />
      </button>
      <div class="min-w-0 flex-1">
        <h1>{{ pageTitle }}</h1>
        <div class="template-editor-save-state" :class="{ 'is-dirty': dirty }">
          {{ dirty ? "有未保存修改" : published ? "表单已发布" : "所有修改已保存" }}
        </div>
      </div>
      <button
        type="button"
        class="approval-button approval-button-secondary"
        :disabled="loading || saving || publishing || !dirty"
        :aria-busy="saving"
        data-ai-action="approval.template.save"
        @click="saveDraft()"
      >
        <LoaderCircle v-if="saving" class="animate-spin" aria-hidden="true" />
        <Save v-else aria-hidden="true" />
        {{ saving ? "保存中..." : "保存草稿" }}
      </button>
      <button
        v-if="normalizedStep === 'publish'"
        type="button"
        class="approval-button approval-button-primary"
        :disabled="loading || saving || publishing || !canPublish"
        :aria-busy="publishing"
        data-ai-action="approval.template.publish"
        @click="publish"
      >
        <LoaderCircle v-if="publishing" class="animate-spin" aria-hidden="true" />
        <Send v-else aria-hidden="true" />
        {{ publishing ? "发布中..." : "发布表单" }}
      </button>
    </header>

    <nav class="template-step-nav" aria-label="表单配置步骤">
      <button
        v-for="(item, index) in steps"
        :key="item.id"
        type="button"
        :class="{ active: normalizedStep === item.id }"
        :aria-current="normalizedStep === item.id ? 'step' : undefined"
        @click="goToStep(item.id)"
      >
        <span class="template-step-number">{{ index + 1 }}</span>
        <component :is="item.icon" aria-hidden="true" />
        <span>{{ item.label }}</span>
        <ChevronRight v-if="index < steps.length - 1" class="template-step-arrow" aria-hidden="true" />
      </button>
    </nav>

    <div v-if="errorMessage" class="approval-alert is-error" role="alert">
      <XCircle aria-hidden="true" />{{ errorMessage }}
    </div>
    <div v-if="categoryErrorMessage" class="approval-alert is-error" role="alert">
      <XCircle aria-hidden="true" />
      <span class="flex-1">分类加载失败：{{ categoryErrorMessage }}</span>
      <button type="button" class="approval-link-button" :disabled="categoryLoading" @click="loadCategories">
        <LoaderCircle v-if="categoryLoading" class="animate-spin" aria-hidden="true" />
        {{ categoryLoading ? "重试中..." : "重新加载" }}
      </button>
    </div>
    <div v-if="directoryErrorMessage" class="approval-alert is-error" role="alert">
      <XCircle aria-hidden="true" />
      <span class="flex-1">{{ directoryErrorMessage }}</span>
      <button type="button" class="approval-link-button" :disabled="directoryLoading" @click="loadEmployeeDirectory">
        <LoaderCircle v-if="directoryLoading" class="animate-spin" aria-hidden="true" />
        {{ directoryLoading ? "重试中..." : "重新加载" }}
      </button>
    </div>
    <div v-if="loading" class="approval-status-panel" role="status">
      <LoaderCircle class="animate-spin text-blue-600" aria-hidden="true" />
      正在加载表单配置...
    </div>

    <main v-else class="template-editor-main">
      <section v-if="normalizedStep === 'basic'" class="template-settings-page" aria-labelledby="template-basic-title">
        <div class="template-settings-heading">
          <h2 id="template-basic-title">基础设置</h2>
        </div>
        <div class="template-settings-form">
          <label class="approval-field approval-field-wide">
            <span>表单名称 <b aria-hidden="true">*</b></span>
            <input ref="templateNameInputRef" v-model.trim="draft.name" type="text" maxlength="80" required data-ai-field="approval.template.name" :aria-invalid="Boolean(nameError)" :aria-describedby="nameError ? 'approval-template-name-error' : undefined" @input="nameError = ''" />
            <small v-if="nameError" id="approval-template-name-error" class="approval-field-error" role="alert">{{ nameError }}</small>
          </label>
          <label class="approval-field">
            <span>所属分类</span>
            <select
              v-if="categories.length"
              v-model="draft.categoryId"
              aria-label="所属分类"
              :aria-describedby="categoryErrorMessage ? 'approval-template-category-error' : undefined"
              :disabled="Boolean(props.categoryId) || (!props.canManageApp && props.managedCategoryIds.length <= 1)"
              @change="draft.category = categories.find((item) => item.id === String(draft.categoryId))?.name || draft.category"
            >
              <option v-for="item in categories" :key="item.id" :value="item.id">{{ item.name }}</option>
            </select>
            <input v-else v-model.trim="draft.category" type="text" maxlength="40" aria-label="所属分类" placeholder="请输入分类名称" :aria-describedby="categoryErrorMessage ? 'approval-template-category-error' : undefined" />
            <small v-if="categoryErrorMessage" id="approval-template-category-error" class="approval-field-hint is-error">{{ categoryErrorMessage }}</small>
          </label>
          <label class="approval-field approval-field-wide">
            <span>表单说明</span>
            <textarea v-model.trim="draft.description" rows="4" maxlength="300" />
          </label>
        </div>
        <div class="template-step-footer">
          <span />
          <button type="button" class="approval-button approval-button-primary" @click="goToStep('form')">下一步：表单设计<ChevronRight aria-hidden="true" /></button>
        </div>
      </section>

      <section v-else-if="normalizedStep === 'form'" class="form-designer" aria-labelledby="template-form-title">
        <aside class="form-control-palette">
          <header><h2 id="template-form-title">字段控件</h2></header>
          <div class="form-control-grid">
            <button v-for="item in fieldTypes" :key="item.type" type="button" @click="addField(item.type)">
              <component :is="item.icon" aria-hidden="true" />
              <span>{{ item.label }}</span>
              <Plus aria-hidden="true" />
            </button>
          </div>
        </aside>

        <div class="form-canvas-column">
          <header class="form-canvas-header">
            <div><strong>{{ draft.name || "未命名表单" }}</strong><small>{{ fields.length }} 个字段</small></div>
          </header>
          <div class="form-canvas" aria-label="表单字段预览">
            <div
              v-for="(item, index) in fields"
              :key="item.id"
              class="form-preview-field"
              :class="{ active: selectedFieldId === item.id }"
            >
              <GripVertical class="form-field-grip" aria-hidden="true" />
              <span class="form-field-index">{{ index + 1 }}</span>
              <button type="button" class="form-preview-body form-preview-select" @click="selectedFieldId = item.id">
                <span class="form-preview-label">{{ item.label || "未命名字段" }} <b v-if="item.required" aria-hidden="true">*</b></span>
                <span v-if="item.type === 'description'" class="form-preview-description">{{ item.placeholder || "说明文字" }}</span>
                <span v-else-if="choiceFieldTypes.has(item.type)" class="form-preview-dropdown">
                  <span>{{ item.placeholder || (item.type === 'multiselect' ? `请选择（已配置 ${normalizedOptions(item).length} 项）` : '请选择') }}</span>
                  <ChevronDown aria-hidden="true" />
                </span>
                <span
                  v-else
                  class="form-preview-input"
                  :class="{ 'is-multiline': item.type === 'text' && normalizeTextRows(item.rows) > 1 }"
                  :style="textPreviewStyle(item)"
                >{{ item.placeholder || fieldType(item.type).label }}</span>
              </button>
              <span class="form-field-actions">
                <button type="button" :aria-label="`上移${item.label}`" :disabled="index === 0" @click.stop="selectedFieldId = item.id; moveField(-1)"><ArrowUp aria-hidden="true" /></button>
                <button type="button" :aria-label="`下移${item.label}`" :disabled="index === fields.length - 1" @click.stop="selectedFieldId = item.id; moveField(1)"><ArrowDown aria-hidden="true" /></button>
                <button type="button" :aria-label="`复制${item.label}`" @click.stop="duplicateField(item)"><Copy aria-hidden="true" /></button>
                <button type="button" :aria-label="`删除${item.label}`" @click.stop="removeField(item)"><Trash2 aria-hidden="true" /></button>
              </span>
            </div>
            <div v-if="!fields.length" class="approval-empty-state is-compact">
              <FileText aria-hidden="true" />
              <h3>暂无表单字段</h3>
            </div>
          </div>
        </div>

        <aside class="form-property-panel">
          <header><h2>字段设置</h2></header>
          <div v-if="selectedField" class="form-property-body">
            <label class="approval-field">
              <span>字段名称 <b aria-hidden="true">*</b></span>
              <input :value="selectedField.label" type="text" maxlength="60" required @input="updateSelectedField('label', $event.target.value)" />
            </label>
            <label class="approval-field">
              <span>字段类型</span>
              <select :value="selectedField.type" @change="updateSelectedFieldType($event.target.value)">
                <option v-for="item in fieldTypes" :key="item.type" :value="item.type">{{ item.label }}</option>
              </select>
            </label>
            <label v-if="selectedField.type === 'text'" class="approval-field">
              <span>行数</span>
              <input
                :value="normalizeTextRows(selectedField.rows)"
                type="number"
                min="1"
                :max="MAX_TEXT_ROWS"
                step="1"
                @input="updateSelectedTextRows($event.target.value)"
              />
            </label>
            <label class="approval-field">
              <span>{{ selectedField.type === 'description' ? '说明内容' : '输入提示' }}</span>
              <textarea :value="selectedField.placeholder" rows="3" maxlength="160" @input="updateSelectedField('placeholder', $event.target.value)" />
            </label>
            <label v-if="choiceFieldTypes.has(selectedField.type)" class="approval-field">
              <span>选项（每行一个）</span>
              <textarea :value="selectedField.options.join('\n')" rows="6" :aria-invalid="Boolean(selectedFieldOptionError)" @input="updateOptions" />
              <small v-if="selectedFieldOptionError" class="approval-field-error" role="alert">{{ selectedFieldOptionError }}</small>
            </label>
            <label v-if="selectedField.type !== 'description'" class="approval-checkbox-row">
              <input :checked="selectedField.required" type="checkbox" @change="updateSelectedField('required', $event.target.checked)" />
              <span>必填字段</span>
            </label>
          </div>
          <div v-else class="approval-empty-state is-compact"><Settings2 aria-hidden="true" /><h3>未选择字段</h3></div>
        </aside>
      </section>

      <section v-else-if="normalizedStep === 'flow'" class="flow-designer" aria-labelledby="template-flow-title">
        <div class="flow-toolbar">
          <div><h2 id="template-flow-title">流程设置</h2></div>
          <div>
            <button type="button" class="approval-button approval-button-secondary" @click="addNode('approver')"><Plus aria-hidden="true" />审批节点</button>
            <button type="button" class="approval-button approval-button-secondary" @click="addNode('cc')"><Plus aria-hidden="true" />抄送节点</button>
          </div>
        </div>
        <div class="flow-workspace">
          <div class="flow-canvas" aria-label="审批流程">
            <div class="flow-node is-start">
              <span><UserRound aria-hidden="true" /></span>
              <div><strong>发起人</strong><small>提交审批申请</small></div>
            </div>
            <template v-for="(node, index) in nodes" :key="node.key">
              <div class="flow-connector"><i /></div>
              <button type="button" class="flow-node" :class="[{ active: selectedNodeKey === node.key }, `is-${node.type}`]" @click="selectedNodeKey = node.key">
                <span><UsersRound v-if="node.type === 'cc'" aria-hidden="true" /><ClipboardCheck v-else aria-hidden="true" /></span>
                <div>
                  <strong>{{ node.name || (node.type === 'cc' ? '抄送人' : '审批人') }}</strong>
                  <small v-if="node.assigneeType === 'initiator'">发起人本人</small>
                  <small v-else-if="node.assigneeIds.length">{{ node.assigneeIds.map((id) => node.assigneeNames?.[id] || employeeName(id)).join('、') }}</small>
                  <small v-else>未配置人员</small>
                </div>
                <em>{{ index + 1 }}</em>
              </button>
            </template>
            <div class="flow-connector"><i /></div>
            <div class="flow-node is-end"><span><Check aria-hidden="true" /></span><div><strong>流程结束</strong><small>记录最终审批结果</small></div></div>
          </div>
          <aside class="flow-property-panel">
            <header><h3>节点设置</h3></header>
            <div v-if="selectedNode" class="form-property-body">
              <label class="approval-field"><span>节点名称</span><input v-model.trim="selectedNode.name" type="text" maxlength="60" /></label>
              <label class="approval-field"><span>节点类型</span><select v-model="selectedNode.type"><option value="approver">审批节点</option><option value="cc">抄送节点</option></select></label>
              <label class="approval-field"><span>人员来源</span><select v-model="selectedNode.assigneeType"><option value="user">指定人员</option><option value="initiator">发起人本人</option></select></label>
              <label v-if="selectedNode.assigneeType === 'user'" class="approval-field">
                <span>指定人员 <b aria-hidden="true">*</b></span>
                <select multiple size="7" :value="selectedNode.assigneeIds" aria-label="选择节点人员" @change="updateNodeAssignees">
                  <option v-for="employee in employees" :key="employee.id" :value="employee.id">{{ employee.name }}{{ employee.department ? ` · ${employee.department}` : '' }}</option>
                </select>
                <small v-if="!employees.length">组织架构中暂无可选人员</small>
              </label>
              <label v-if="selectedNode.type === 'approver' && selectedNode.assigneeType === 'user' && selectedNode.assigneeIds.length > 1" class="approval-field">
                <span>多人审批方式</span>
                <select v-model="selectedNode.approvalMode"><option value="all">会签（全部同意）</option><option value="any">或签（一人同意）</option></select>
              </label>
              <div class="flow-node-actions">
                <button type="button" class="approval-icon-button" aria-label="上移节点" :disabled="selectedNodeIndex <= 0" @click="moveNode(-1)"><ArrowUp aria-hidden="true" /></button>
                <button type="button" class="approval-icon-button" aria-label="下移节点" :disabled="selectedNodeIndex < 0 || selectedNodeIndex >= nodes.length - 1" @click="moveNode(1)"><ArrowDown aria-hidden="true" /></button>
                <button type="button" class="approval-button approval-button-danger-text" @click="removeNode(selectedNode)"><Trash2 aria-hidden="true" />删除节点</button>
              </div>
            </div>
            <div v-else class="approval-empty-state is-compact"><ClipboardCheck aria-hidden="true" /><h3>未选择流程节点</h3></div>
          </aside>
        </div>
      </section>

      <section v-else class="publish-page" aria-labelledby="template-publish-title">
        <div class="publish-column">
          <div class="publish-panel">
            <header><h2 id="template-publish-title">发布检查</h2></header>
            <ul class="publish-check-list">
              <li v-for="item in validationItems" :key="item.id" :class="{ valid: item.valid }">
                <CheckCircle2 v-if="item.valid" aria-hidden="true" />
                <XCircle v-else aria-hidden="true" />
                <span>{{ item.label }}</span>
              </li>
            </ul>
          </div>
          <div class="publish-panel">
            <header><h2>审批规则</h2></header>
            <div class="publish-settings">
              <label class="approval-checkbox-row"><input v-model="draft.settings.allowWithdraw" type="checkbox" /><span>审批中允许发起人撤回</span></label>
              <label class="approval-checkbox-row"><input v-model="draft.settings.requireApprovalComment" type="checkbox" /><span>同意时必须填写意见</span></label>
              <label class="approval-checkbox-row"><input v-model="draft.settings.requireRejectComment" type="checkbox" /><span>拒绝时必须填写意见</span></label>
              <label class="approval-checkbox-row"><input v-model="draft.settings.requireReturnComment" type="checkbox" /><span>退回时必须填写意见</span></label>
            </div>
          </div>
        </div>
        <div class="publish-preview">
          <header><span>电脑端预览</span></header>
          <div class="publish-preview-sheet">
            <div class="publish-preview-title"><span class="approval-template-icon"><FileText aria-hidden="true" /></span><div><h2>{{ draft.name || "未命名表单" }}</h2><p>{{ draft.description || "暂无表单说明" }}</p></div></div>
            <div v-for="item in fields" :key="item.id" class="publish-preview-field">
              <label>{{ item.label || "未命名字段" }} <b v-if="item.required" aria-hidden="true">*</b></label>
              <div
                :class="{ 'is-multiline': item.type === 'text' && normalizeTextRows(item.rows) > 1 }"
                :style="textPreviewStyle(item)"
              >{{ item.placeholder || fieldType(item.type).label }}</div>
            </div>
            <div v-if="!fields.length" class="approval-empty-inline">暂无表单字段</div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>
