<script setup>
import { computed, onMounted, ref, watch } from "vue";
import {
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  FileCheck2,
  FileText,
  LoaderCircle,
  Save,
  Send,
  UsersRound,
  X,
} from "@lucide/vue";
import { PlatformDetailDrawer } from "@platform-ui";

import { approvalApi, itemOf } from "@/approvalApi";
import ApprovalMultiSelect from "@/components/approval/ApprovalMultiSelect.vue";

const props = defineProps({
  open: { type: Boolean, default: false },
  templateId: { type: [String, Number], default: "" },
  draftId: { type: [String, Number], default: "" },
  initialDraft: { type: Object, default: null },
});

const emit = defineEmits(["close", "submitted", "dirty-change", "success-notice"]);

const loading = ref(false);
const savingDraft = ref(false);
const submitting = ref(false);
const errorMessage = ref("");
const template = ref(null);
const title = ref("");
const values = ref({});
const fieldErrors = ref({});
const currentDraftId = ref("");
const snapshot = ref("");
const employees = ref([]);
const availableDepartments = ref([]);

const fields = computed(() => Array.isArray(template.value?.formSchema?.fields) ? template.value.formSchema.fields : []);
const nodes = computed(() => Array.isArray(template.value?.flowSchema?.nodes) ? template.value.flowSchema.nodes : []);
const departments = computed(() => {
  const names = new Set(availableDepartments.value.map((department) => (
    String(department?.name || department?.departmentName || department || "").trim()
  )).filter(Boolean));
  employees.value.forEach((employee) => {
    (Array.isArray(employee?.departments) ? employee.departments : []).forEach((department) => {
      const name = String(department?.name || department || "").trim();
      if (name) names.add(name);
    });
  });
  return [...names].sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
});
const dirty = computed(() => Boolean(props.open && snapshot.value !== JSON.stringify({ title: title.value, values: values.value })));
const drawerTitle = computed(() => template.value?.name ? `发起${template.value.name}` : "发起审批");

const MAX_TEXT_ROWS = 20;

function normalizeTemplate(payload) {
  const item = itemOf(payload, ["template"]);
  return item && typeof item === "object" ? item : null;
}

function initialValue(field) {
  if (["checkbox", "multiselect", "dateRange", "attachment"].includes(field?.type)) return [];
  return "";
}

function resetValues(source = {}) {
  const next = {};
  fields.value.forEach((field, index) => {
    const key = String(field?.key || field?.id || `field_${index + 1}`);
    next[key] = Object.hasOwn(source || {}, key) ? source[key] : initialValue(field);
  });
  values.value = next;
}

function fieldKey(field, index) {
  return String(field?.key || field?.id || `field_${index + 1}`);
}

function fieldLabel(field) {
  return String(field?.label || field?.name || "未命名字段");
}

function fieldRows(field) {
  const fallback = field?.type === "textarea" ? 4 : 1;
  if (field?.rows === "" || field?.rows === null || field?.rows === undefined) return fallback;
  const rows = Number(field.rows);
  if (!Number.isFinite(rows)) return fallback;
  return Math.min(MAX_TEXT_ROWS, Math.max(1, Math.trunc(rows)));
}

function isMultilineText(field) {
  return field?.type === "textarea" || (field?.type === "text" && fieldRows(field) > 1);
}

function fieldErrorId(index) {
  return `approval-application-field-${index + 1}-error`;
}

function fieldOptions(field) {
  return (Array.isArray(field?.options) ? field.options : []).map((option) => ({
    label: String(option?.label || option?.value || option),
    value: String(option?.value || option?.label || option),
  })).filter((option) => option.value);
}

function assigneeNames(node) {
  const rows = Array.isArray(node?.assignees) ? node.assignees : [];
  if (rows.length) return rows.map((item) => item?.name || item?.userId || item?.id).filter(Boolean).join("、");
  const names = node?.assigneeNames;
  if (names && typeof names === "object") return Object.values(names).filter(Boolean).join("、");
  if (node?.assigneeType === "initiator") return "发起人本人";
  return "人员将在提交时确定";
}

function updateCheckbox(key, option, checked) {
  const current = Array.isArray(values.value[key]) ? values.value[key] : [];
  values.value[key] = checked
    ? [...new Set([...current, option])]
    : current.filter((value) => value !== option);
}

function validate() {
  const errors = {};
  fields.value.forEach((field, index) => {
    if (!field?.required || ["description", "divider"].includes(field?.type)) return;
    const key = fieldKey(field, index);
    const value = values.value[key];
    if (value === "" || value === null || value === undefined || (Array.isArray(value) && !value.length)) {
      errors[key] = `${fieldLabel(field)}不能为空`;
    }
  });
  fieldErrors.value = errors;
  return !Object.keys(errors).length;
}

async function load() {
  if (!props.open || !props.templateId) return;
  loading.value = true;
  errorMessage.value = "";
  fieldErrors.value = {};
  template.value = null;
  currentDraftId.value = "";
  title.value = "";
  values.value = {};
  snapshot.value = JSON.stringify({ title: "", values: {} });
  employees.value = [];
  availableDepartments.value = [];
  try {
    const [result, draftResult] = await Promise.all([
      approvalApi.template(props.templateId),
      props.draftId && !props.initialDraft
        ? approvalApi.draft(props.draftId)
        : Promise.resolve(null),
    ]);
    template.value = normalizeTemplate(result);
    if (!template.value) throw new Error("审批表单不存在");
    const loadedDraft = props.initialDraft || itemOf(draftResult, ["draft"]);
    if (props.draftId && !loadedDraft) throw new Error("申请草稿不存在或无权访问");
    const draftTemplateId = String(loadedDraft?.templateId ?? loadedDraft?.template?.id ?? "");
    const expectedTemplateId = String(template.value.id ?? props.templateId);
    if (loadedDraft && (!draftTemplateId || draftTemplateId !== expectedTemplateId)) {
      throw new Error("草稿与当前审批表单不匹配，无法继续提交");
    }

    const needsDirectory = fields.value.some((field) => ["user", "department"].includes(field?.type));
    let directoryResult = { employees: [], departments: [] };
    if (needsDirectory) {
      try {
        directoryResult = await approvalApi.formOptions(props.templateId);
      } catch (error) {
        const detail = error instanceof Error ? error.message : "组织架构不可用";
        throw new Error(`人员和部门选项加载失败：${detail}`);
      }
    }
    employees.value = Array.isArray(directoryResult?.employees)
      ? directoryResult.employees
      : (Array.isArray(directoryResult?.items) ? directoryResult.items : []);
    availableDepartments.value = Array.isArray(directoryResult?.departments) ? directoryResult.departments : [];
    title.value = String(loadedDraft?.title || "");
    currentDraftId.value = String(loadedDraft?.id || props.draftId || "");
    resetValues(loadedDraft?.values || {});
    snapshot.value = JSON.stringify({ title: title.value, values: values.value });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "审批表单加载失败";
    template.value = null;
  } finally {
    loading.value = false;
  }
}

async function saveAsDraft() {
  if (!template.value || savingDraft.value) return;
  savingDraft.value = true;
  errorMessage.value = "";
  try {
    const payload = { templateId: template.value.id, title: title.value.trim(), values: values.value };
    const result = currentDraftId.value
      ? await approvalApi.updateDraft(currentDraftId.value, payload)
      : await approvalApi.createDraft(payload);
    const item = itemOf(result, ["draft"]);
    currentDraftId.value = String(item?.id || currentDraftId.value || "");
    snapshot.value = JSON.stringify({ title: title.value, values: values.value });
    emit("success-notice", "草稿已保存");
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "草稿保存失败";
  } finally {
    savingDraft.value = false;
  }
}

async function submit() {
  if (!template.value || loading.value || !validate() || submitting.value) return;
  submitting.value = true;
  errorMessage.value = "";
  try {
    const result = await approvalApi.createApplication({
      templateId: template.value.id,
      title: title.value.trim(),
      values: values.value,
      ...(currentDraftId.value ? { draftId: currentDraftId.value } : {}),
    });
    currentDraftId.value = "";
    snapshot.value = JSON.stringify({ title: title.value, values: values.value });
    emit("submitted", itemOf(result, ["application"]));
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "审批提交失败";
  } finally {
    submitting.value = false;
  }
}

function requestClose() {
  emit("close", { dirty: dirty.value });
}

watch(() => [props.open, props.templateId, props.draftId], load);
watch(dirty, (value) => emit("dirty-change", value), { immediate: true });
onMounted(load);
</script>

<template>
  <PlatformDetailDrawer :open="open" labelled-by="approval-application-form-title" :suspended="submitting || savingDraft" @close="requestClose">
    <header class="approval-drawer-header">
      <div class="approval-drawer-title">
        <span class="approval-record-icon"><FileCheck2 aria-hidden="true" /></span>
        <div><h2 id="approval-application-form-title">{{ drawerTitle }}</h2><p>填写申请内容并确认预计流程</p></div>
      </div>
      <button type="button" class="approval-icon-button" aria-label="关闭发起审批" @click="requestClose"><X aria-hidden="true" /></button>
    </header>

    <div v-if="errorMessage" class="approval-alert is-error approval-drawer-alert" role="alert">{{ errorMessage }}</div>

    <div v-if="loading" class="approval-status-panel approval-drawer-status" role="status"><LoaderCircle class="animate-spin text-blue-600" aria-hidden="true" />正在加载审批表单...</div>

    <form v-else-if="template" class="approval-drawer-content" @submit.prevent="submit">
      <section class="approval-form-section" aria-labelledby="approval-form-content-title">
        <div class="approval-form-section-title"><span /><h3 id="approval-form-content-title">申请内容</h3></div>
        <label class="approval-field">
          <span>申请标题</span>
          <input v-model.trim="title" type="text" maxlength="200" :placeholder="`${template.name || '审批'} - 可选填写`" />
        </label>

        <div v-for="(field, index) in fields" :key="fieldKey(field, index)" class="approval-dynamic-field">
          <div v-if="field.type === 'divider'" class="approval-form-divider" />
          <div v-else-if="field.type === 'description'" class="approval-form-description"><FileText aria-hidden="true" /><span>{{ field.placeholder || fieldLabel(field) }}</span></div>
          <fieldset v-else-if="['radio', 'checkbox'].includes(field.type)" class="approval-field approval-choice-field" :aria-invalid="Boolean(fieldErrors[fieldKey(field, index)])" :aria-describedby="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : undefined">
            <legend>{{ fieldLabel(field) }} <b v-if="field.required" aria-hidden="true">*</b></legend>
            <label v-for="option in fieldOptions(field)" :key="option.value" class="approval-choice">
              <input
                v-if="field.type === 'radio'"
                v-model="values[fieldKey(field, index)]"
                type="radio"
                :name="fieldKey(field, index)"
                :value="option.value"
              />
              <input
                v-else
                type="checkbox"
                :checked="values[fieldKey(field, index)]?.includes(option.value)"
                @change="updateCheckbox(fieldKey(field, index), option.value, $event.target.checked)"
              />
              <span>{{ option.label }}</span>
            </label>
            <small v-if="fieldErrors[fieldKey(field, index)]" :id="fieldErrorId(index)" class="approval-field-error" role="alert">{{ fieldErrors[fieldKey(field, index)] }}</small>
          </fieldset>
          <div v-else-if="field.type === 'attachment'" class="approval-unsupported-field" role="note">
            <span>{{ fieldLabel(field) }} <b v-if="field.required" aria-hidden="true">*</b></span>
            <p>当前版本暂不支持附件提交，请联系表单管理员移除此字段后再发起。</p>
          </div>
          <div v-else-if="field.type === 'multiselect'" class="approval-field">
            <span>{{ fieldLabel(field) }} <b v-if="field.required" aria-hidden="true">*</b></span>
            <ApprovalMultiSelect
              v-model="values[fieldKey(field, index)]"
              :options="fieldOptions(field)"
              :aria-label="fieldLabel(field)"
              :described-by="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : ''"
              :invalid="Boolean(fieldErrors[fieldKey(field, index)])"
              :required="field.required"
            />
            <small
              v-if="fieldErrors[fieldKey(field, index)]"
              :id="fieldErrorId(index)"
              class="approval-field-error"
              role="alert"
            >{{ fieldErrors[fieldKey(field, index)] }}</small>
          </div>
          <label v-else class="approval-field">
            <span>{{ fieldLabel(field) }} <b v-if="field.required" aria-hidden="true">*</b></span>
            <textarea
              v-if="isMultilineText(field)"
              v-model="values[fieldKey(field, index)]"
              :rows="fieldRows(field)"
              :required="field.required"
              :placeholder="field.placeholder"
              :aria-invalid="Boolean(fieldErrors[fieldKey(field, index)])"
              :aria-describedby="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : undefined"
            />
            <input
              v-else-if="['number', 'amount'].includes(field.type)"
              v-model="values[fieldKey(field, index)]"
              type="number"
              step="0.01"
              :required="field.required"
              :placeholder="field.placeholder"
              :aria-invalid="Boolean(fieldErrors[fieldKey(field, index)])"
              :aria-describedby="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : undefined"
            />
            <input
              v-else-if="field.type === 'date'"
              v-model="values[fieldKey(field, index)]"
              type="date"
              :required="field.required"
              :aria-invalid="Boolean(fieldErrors[fieldKey(field, index)])"
              :aria-describedby="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : undefined"
            />
            <span v-else-if="field.type === 'dateRange'" class="approval-date-range">
              <input type="date" :value="values[fieldKey(field, index)]?.[0] || ''" :required="field.required" aria-label="开始日期" :aria-invalid="Boolean(fieldErrors[fieldKey(field, index)])" :aria-describedby="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : undefined" @input="values[fieldKey(field, index)] = [$event.target.value, values[fieldKey(field, index)]?.[1] || '']" />
              <span>至</span>
              <input type="date" :value="values[fieldKey(field, index)]?.[1] || ''" :required="field.required" aria-label="结束日期" :aria-invalid="Boolean(fieldErrors[fieldKey(field, index)])" :aria-describedby="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : undefined" @input="values[fieldKey(field, index)] = [values[fieldKey(field, index)]?.[0] || '', $event.target.value]" />
            </span>
            <select v-else-if="field.type === 'user'" v-model="values[fieldKey(field, index)]" :required="field.required" :aria-invalid="Boolean(fieldErrors[fieldKey(field, index)])" :aria-describedby="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : undefined">
              <option value="">请选择人员</option><option v-for="employee in employees" :key="employee.userId || employee.id" :value="employee.userId || employee.id">{{ employee.name || employee.rawName || employee.userId || employee.id }}</option>
            </select>
            <select v-else-if="field.type === 'department'" v-model="values[fieldKey(field, index)]" :required="field.required" :aria-invalid="Boolean(fieldErrors[fieldKey(field, index)])" :aria-describedby="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : undefined">
              <option value="">请选择部门</option><option v-for="department in departments" :key="department" :value="department">{{ department }}</option>
            </select>
            <select v-else-if="field.type === 'select'" v-model="values[fieldKey(field, index)]" :required="field.required" :aria-invalid="Boolean(fieldErrors[fieldKey(field, index)])" :aria-describedby="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : undefined">
              <option value="">请选择</option><option v-for="option in fieldOptions(field)" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <input v-else v-model="values[fieldKey(field, index)]" type="text" :required="field.required" :placeholder="field.placeholder" :aria-invalid="Boolean(fieldErrors[fieldKey(field, index)])" :aria-describedby="fieldErrors[fieldKey(field, index)] ? fieldErrorId(index) : undefined" />
            <small v-if="fieldErrors[fieldKey(field, index)]" :id="fieldErrorId(index)" class="approval-field-error" role="alert">{{ fieldErrors[fieldKey(field, index)] }}</small>
          </label>
        </div>
      </section>

      <section class="approval-form-section" aria-labelledby="approval-form-flow-title">
        <div class="approval-form-section-title"><span /><h3 id="approval-form-flow-title">预计审批流程</h3></div>
        <div class="approval-flow-preview">
          <div class="approval-flow-preview-node"><span><Send aria-hidden="true" /></span><div><strong>提交申请</strong><small>由当前用户发起</small></div></div>
          <template v-for="node in nodes" :key="node.key || node.id">
            <ChevronRight aria-hidden="true" />
            <div class="approval-flow-preview-node"><span><UsersRound aria-hidden="true" /></span><div><strong>{{ node.name || (node.type === 'cc' ? '抄送人' : '审批人') }}</strong><small>{{ assigneeNames(node) }}</small></div></div>
          </template>
          <ChevronRight aria-hidden="true" />
          <div class="approval-flow-preview-node"><span><CheckCircle2 aria-hidden="true" /></span><div><strong>流程结束</strong><small>保留完整审批记录</small></div></div>
        </div>
      </section>

      <footer class="approval-drawer-footer">
        <button type="button" class="approval-button approval-button-secondary" :disabled="savingDraft || submitting || (currentDraftId && !dirty)" @click="saveAsDraft"><LoaderCircle v-if="savingDraft" class="animate-spin" aria-hidden="true" /><Save v-else aria-hidden="true" />{{ savingDraft ? "保存中..." : currentDraftId && !dirty ? "已保存" : "保存草稿" }}</button>
        <button type="submit" class="approval-button approval-button-primary" :disabled="submitting || savingDraft || fields.some((field) => field.type === 'attachment')" :aria-busy="submitting" data-ai-action="approval.application.submit"><LoaderCircle v-if="submitting" class="animate-spin" aria-hidden="true" /><Send v-else aria-hidden="true" />{{ submitting ? "提交中..." : "提交审批" }}</button>
      </footer>
    </form>

    <div v-else-if="!loading" class="approval-empty-state"><FileCheck2 aria-hidden="true" /><h3>无法打开审批表单</h3></div>
  </PlatformDetailDrawer>
</template>
