<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import {
  Banknote,
  Check,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  Gift,
  HandCoins,
  LoaderCircle,
  Plus,
  Save,
  Search,
  Send,
  ShieldCheck,
  Star,
  Tags,
  Trash2,
  UserRoundCheck,
  Users,
} from "@lucide/vue";
import { collectionRows, normalizeDatabaseId, serviceApi } from "@/serviceApi";
import { matchesSearch } from "@/productSearch";
import AttachmentPanel from "@/components/AttachmentPanel.vue";
import ModalShell from "@/components/ModalShell.vue";
import GlobalNotice from "@/components/GlobalNotice.vue";

const props = defineProps({
  resource: { type: String, required: true },
});

const CONFIG = {
  team: { title: "服务团队", subtitle: "按地区、节点能力和状态查找可派单人员。", icon: Users, create: "" },
  rewards: { title: "服务奖励", subtitle: "审核奖励来源，记录奖品、发放状态和物流凭证。", icon: Gift, create: "" },
  settlements: { title: "结算中心", subtitle: "从服务项目生成客户承担或公司承担的结算记录。", icon: Banknote, create: "生成结算" },
};

const config = computed(() => CONFIG[props.resource]);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const success = ref("");
const rows = ref([]);
const settlementSources = ref([]);
const selectedId = ref("");
const selectedDetail = ref(null);
const keyword = ref("");
const status = ref("");
const region = ref("");
const skill = ref("");
const teamNode = ref("");
const capabilityGroups = ref([]);
const capabilityOpen = ref(false);
const capabilityNodeValue = ref("");
const capabilityDraft = ref([]);
const capabilitySaving = ref(false);
const createOpen = ref(false);
const actionNote = ref("");
const trackingNo = ref("");
const settlementEdit = reactive({ received_amount: "", invoice_amount: "", invoice_type: "", invoice_number: "", subject_name: "", remark: "" });

const form = reactive({
  source_node_id: "",
  source_assignment_id: "",
  bearer: "customer",
  subject_type: "company",
  subject_name: "",
  received_amount: "",
  invoice_type: "",
  invoice_number: "",
  remark: "",
});

const selected = computed(() => selectedDetail.value || rows.value.find((item) => String(item.id) === String(selectedId.value)) || null);
const rewardStatus = computed(() => selected.value?.status || "");
const selectedSettlementSource = computed(() => settlementSources.value.find((item) => String(item.sourceNodeId || item.id) === String(form.source_node_id)) || null);
const settlementAssignmentOptions = computed(() => selectedSettlementSource.value?.assignmentOptions || []);
const settlementOrderAmount = computed(() => {
  const source = selectedSettlementSource.value;
  if (!source) return "";
  if (form.bearer === "company") return source.actualFee || "0.00";
  return source.externalQuote || source.actualFee || "0.00";
});
const attachmentTargetType = computed(() => {
  if (props.resource === "team") return "provider_application";
  return "";
});
const attachmentTargetId = computed(() => normalizeDatabaseId(selected.value?.id));
const attachmentCategories = computed(() => (
  props.resource === "team"
    ? [{ value: "qualification", label: "资质证明" }, { value: "general", label: "其他附件" }]
    : [{ value: "general", label: "附件" }]
));
const regionOptions = computed(() => [...new Set(rows.value.flatMap((item) => item.regions || [item.city]).filter(Boolean))]);
const teamNodeOptions = computed(() => capabilityGroups.value.flatMap((group) => (
  (group.nodes || []).map((node) => ({
    ...node,
    serviceType: group.serviceType,
    serviceTypeLabel: group.serviceTypeLabel,
    value: `${group.serviceType}:${node.nodeKey}`,
  }))
)));
const selectedCapabilityNode = computed(() => teamNodeOptions.value.find((node) => node.value === teamNode.value) || null);
const editedCapabilityNode = computed(() => teamNodeOptions.value.find((node) => node.value === capabilityNodeValue.value) || null);
const skillOptions = computed(() => {
  if (selectedCapabilityNode.value) return selectedCapabilityNode.value.abilities || [];
  return [...new Set(rows.value.flatMap((item) => item.skills || item.abilities || []).filter(Boolean))];
});
const filteredRows = computed(() => {
  return rows.value.filter((item) => {
    const itemRegions = item.regions || [item.city];
    const itemSkills = item.skills || item.abilities || [];
    const fields = Object.values(item).filter((value) => typeof value === "string" || typeof value === "number");
    return matchesSearch(keyword.value, fields)
      && (!status.value || [item.status, item.status_code, item.state].includes(status.value))
      && (props.resource !== "team" || !region.value || itemRegions.includes(region.value))
      && (props.resource !== "team" || !skill.value || itemSkills.includes(skill.value));
  });
});
const statusOptions = computed(() => {
  const options = rows.value.map((item) => ({
    value: item.status || item.certificationStatus || item.status_code || item.state,
    label: item.statusLabel || item.certificationStatusLabel || item.status_display || item.statusDisplay || item.status || item.certificationStatus,
  })).filter((item) => item.value);
  return [...new Map(options.map((item) => [item.value, item])).values()];
});

function display(item, ...keys) {
  for (const key of keys) {
    const value = item?.[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return "-";
}

function listTitle(item) {
  if (props.resource === "team") return display(item, "name");
  if (props.resource === "rewards") return display(item, "prize_name", "prizeName", "prize", "title");
  if (props.resource === "settlements") return display(item, "project_name", "projectName", "project", "id");
  return display(item, "title", "name", "id");
}

function listMeta(item) {
  if (props.resource === "team") return `${display(item, "roleLabel", "role_display", "roleDisplay", "role")} · ${(item.regions || [item.city]).filter(Boolean).join("、") || "未设置地区"}`;
  if (props.resource === "rewards") return `${display(item, "providerName", "recipient_name", "recipientName", "installer")} · ${display(item, "projectName", "project_name", "project")}`;
  if (props.resource === "settlements") return `${display(item, "serviceTypeLabel", "service_type_display", "serviceTypeDisplay", "service_type", "serviceType")} · ${display(item, "customer", "customer_name", "customerName")}`;
  return `${display(item, "updatedAt", "updated_at", "time")} · ${display(item, "statusLabel", "status_display", "status")}`;
}

function rowStatus(item) {
  return display(item, "statusLabel", "certificationStatusLabel", "status_display", "statusDisplay", "status", "state_display", "stateDisplay");
}

function unwrap(payload) {
  return payload?.item || payload?.result || payload?.data || payload;
}

function showSuccess(message) {
  success.value = message;
  window.setTimeout(() => { if (success.value === message) success.value = ""; }, 2600);
}

async function loadCapabilityCatalog() {
  const response = await serviceApi.capabilityCatalog();
  capabilityGroups.value = Array.isArray(response?.groups) ? response.groups : [];
  if (teamNode.value && !teamNodeOptions.value.some((node) => node.value === teamNode.value)) {
    teamNode.value = "";
    skill.value = "";
  }
}

function handleTeamNodeChange() {
  skill.value = "";
}

function syncCapabilityDraft() {
  const node = editedCapabilityNode.value;
  capabilityDraft.value = (node?.abilities || []).map((name) => String(name));
}

async function openCapabilityManager() {
  error.value = "";
  try {
    if (!capabilityGroups.value.length) await loadCapabilityCatalog();
    capabilityNodeValue.value = teamNode.value || teamNodeOptions.value[0]?.value || "";
    syncCapabilityDraft();
    capabilityOpen.value = true;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "能力标签加载失败";
  }
}

function changeCapabilityNode() {
  syncCapabilityDraft();
}

function addCapabilityTag() {
  capabilityDraft.value.push("");
}

function removeCapabilityTag(index) {
  if (capabilityDraft.value.length <= 1) {
    error.value = "每个业务节点至少保留一个能力标签";
    return;
  }
  capabilityDraft.value.splice(index, 1);
}

async function saveCapabilityTags() {
  const node = editedCapabilityNode.value;
  if (!node || capabilitySaving.value) return;
  const names = capabilityDraft.value.map((name) => String(name).trim()).filter(Boolean);
  if (!names.length) {
    error.value = "每个业务节点至少保留一个能力标签";
    return;
  }
  if (new Set(names.map((name) => name.toLocaleLowerCase())).size !== names.length) {
    error.value = "同一节点下的能力标签不能重复";
    return;
  }
  capabilitySaving.value = true;
  error.value = "";
  try {
    const response = await serviceApi.updateCapabilityCatalog({
      serviceType: node.serviceType,
      nodeKey: node.nodeKey,
      names,
    });
    capabilityGroups.value = Array.isArray(response?.groups) ? response.groups : [];
    if (teamNode.value === node.value && !names.includes(skill.value)) skill.value = "";
    capabilityOpen.value = false;
    showSuccess(`${node.nodeName}能力标签已保存`);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "能力标签保存失败";
  } finally {
    capabilitySaving.value = false;
  }
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    let response;
    const baseParams = { search: keyword.value.trim(), page_size: 200 };
    if (props.resource === "team") {
      if (!capabilityGroups.value.length) await loadCapabilityCatalog();
      response = await serviceApi.listTeamMembers({ ...baseParams, region: region.value, skill: skill.value, status: status.value });
    }
    if (props.resource === "rewards") response = await serviceApi.listRewards({ ...baseParams, status: status.value });
    if (props.resource === "settlements") response = await serviceApi.listSettlements({ ...baseParams, status: status.value });
    rows.value = collectionRows(response);
    if (!rows.value.some((item) => String(item.id) === String(selectedId.value))) selectedId.value = rows.value[0]?.id || "";
    selectedDetail.value = null;
    if (selectedId.value && ["team", "settlements"].includes(props.resource)) await selectRow(rows.value.find((item) => String(item.id) === String(selectedId.value)));
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "列表加载失败";
  } finally {
    loading.value = false;
  }
}

async function selectRow(item) {
  if (!item) return;
  selectedId.value = item.id;
  selectedDetail.value = null;
  try {
    if (props.resource === "team") selectedDetail.value = unwrap(await serviceApi.getTeamMember(item.id));
    if (props.resource === "settlements") fillSettlementEdit(item);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "详情加载失败";
  }
}

function resetForm() {
  Object.assign(form, {
    source_node_id: "", source_assignment_id: "", bearer: "customer", subject_type: "company", subject_name: "",
    received_amount: "", invoice_type: "", invoice_number: "", remark: "",
  });
}

async function openCreate() {
  resetForm();
  createOpen.value = true;
  try {
    if (props.resource === "settlements") {
      settlementSources.value = collectionRows(await serviceApi.listSettlementSources({ state: "available", page_size: 200 }));
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "项目与人员选项加载失败";
  }
}

function applySettlementSource() {
  const source = selectedSettlementSource.value;
  form.source_assignment_id = source?.assignmentOptions?.length === 1 ? source.assignmentOptions[0].id : "";
  form.subject_type = form.bearer === "customer" ? "customer" : "company";
  form.subject_name = form.bearer === "customer" ? source?.customer || "" : "";
}

function fillSettlementEdit(item = selected.value) {
  Object.assign(settlementEdit, {
    received_amount: item?.receivedAmount || "",
    invoice_amount: item?.invoicedAmount || "",
    invoice_type: item?.invoiceType || "",
    invoice_number: item?.invoiceNumber || "",
    subject_name: item?.subjectName || "",
    remark: item?.remark || "",
  });
}

async function createRecord() {
  saving.value = true;
  error.value = "";
  try {
    if (props.resource === "settlements") {
      if (!form.source_node_id) throw new Error("请选择已完成的收费节点");
      await serviceApi.createSettlement({
        source_node_id: form.source_node_id,
        source_assignment_id: form.source_assignment_id || null,
        bearer: form.bearer,
        subject_type: form.subject_type,
        subject_name: form.subject_name.trim(),
        received_amount: form.bearer === "customer" ? form.received_amount || 0 : 0,
        invoice_amount: form.bearer === "customer" ? form.invoice_amount || 0 : 0,
        invoice_type: form.bearer === "customer" ? form.invoice_type : "",
        invoice_number: form.bearer === "customer" ? form.invoice_number : "",
        remark: form.remark.trim(),
      });
    }
    createOpen.value = false;
    showSuccess("记录已创建");
    await load();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "创建失败";
  } finally {
    saving.value = false;
  }
}

async function saveSettlement(nextStatus = "") {
  if (!selected.value?.id) return;
  if (nextStatus === "cancelled" && !window.confirm("确认取消这条结算记录？取消后将不能继续处理。")) return;
  saving.value = true;
  error.value = "";
  try {
    await serviceApi.updateSettlement(selected.value.id, {
      received_amount: selected.value.bearer === "customer" ? settlementEdit.received_amount || 0 : 0,
      invoice_amount: selected.value.bearer === "customer" ? settlementEdit.invoice_amount || 0 : 0,
      invoice_type: selected.value.bearer === "customer" ? settlementEdit.invoice_type : "",
      invoice_number: selected.value.bearer === "customer" ? settlementEdit.invoice_number : "",
      subject_name: settlementEdit.subject_name,
      remark: settlementEdit.remark,
      status: nextStatus || undefined,
    });
    showSuccess(nextStatus === "settled" ? "结算已结清" : nextStatus === "cancelled" ? "结算已取消" : nextStatus === "pending" ? "结算已提交" : "财务信息已保存");
    await load();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "结算更新失败";
  } finally { saving.value = false; }
}

async function reviewProvider(certificationStatus) {
  if (!selected.value?.id) return;
  saving.value = true;
  error.value = "";
  try {
    await serviceApi.updateTeamMember(selected.value.id, { certificationStatus });
    showSuccess(certificationStatus === "certified" ? "人员认证已通过" : "人员服务状态已暂停");
    await load();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "人员状态更新失败";
  } finally { saving.value = false; }
}

async function processReward(actionName) {
  if (!selected.value?.id) return;
  saving.value = true;
  try {
    await serviceApi.rewardAction(selected.value.id, actionName, { tracking_no: trackingNo.value.trim(), note: actionNote.value.trim() });
    trackingNo.value = "";
    actionNote.value = "";
    showSuccess(actionName === "approve" ? "奖励已审核，进入待发放" : "奖励已标记发放");
    await load();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "奖励发放失败";
  } finally { saving.value = false; }
}

watch(() => props.resource, () => { status.value = ""; keyword.value = ""; load(); });
watch(() => form.bearer, (value) => {
  if (props.resource !== "settlements" || !selectedSettlementSource.value) return;
  form.subject_type = value === "customer" ? "customer" : "company";
  form.subject_name = value === "customer" ? selectedSettlementSource.value.customer || "" : "";
  if (value === "company") {
    form.received_amount = "";
    form.invoice_amount = "";
    form.invoice_type = "";
    form.invoice_number = "";
  }
});
onMounted(load);
</script>

<template>
  <div class="as-page as-resource-page">
    <header class="as-page-head">
      <div><p class="as-eyebrow">业务协同</p><h1>{{ config.title }}</h1><p>{{ config.subtitle }}</p></div>
      <div v-if="config.create" class="as-head-actions"><button type="button" class="as-button as-button--primary" @click="openCreate"><Plus />{{ config.create }}</button></div>
    </header>

    <GlobalNotice v-model:error="error" v-model:success="success" />

    <div class="as-resource-layout">
      <section class="as-panel as-resource-list">
        <div class="as-filter-row" :class="{ 'as-team-filter': resource === 'team' }">
          <label class="as-search"><Search /><input v-model="keyword" type="search" :placeholder="resource === 'team' ? '搜索姓名、电话或能力' : '搜索当前列表'" @keyup.enter="load"></label>
          <template v-if="resource === 'team'">
            <select v-model="region" class="as-select" aria-label="服务区域" @change="load"><option value="">全部地区</option><option v-for="item in regionOptions" :key="item">{{ item }}</option></select>
            <select v-model="teamNode" class="as-select" aria-label="业务节点" @change="handleTeamNodeChange"><option value="">全部节点</option><optgroup v-for="group in capabilityGroups" :key="group.serviceType" :label="group.serviceTypeLabel"><option v-for="node in group.nodes" :key="`${group.serviceType}:${node.nodeKey}`" :value="`${group.serviceType}:${node.nodeKey}`">{{ node.nodeName }}</option></optgroup></select>
            <select v-model="skill" class="as-select" aria-label="能力标签" @change="load"><option value="">全部能力</option><option v-for="item in skillOptions" :key="item">{{ item }}</option></select>
            <button type="button" class="as-icon-button as-capability-manage" title="编辑能力标签" aria-label="编辑能力标签" @click="openCapabilityManager"><Tags /></button>
          </template>
          <select v-else v-model="status" class="as-select"><option value="">全部状态</option><option v-for="item in statusOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select>
        </div>
        <div class="as-panel-head"><div><h2>记录列表</h2><p>{{ filteredRows.length }} 条</p></div><component :is="config.icon" /></div>
        <div class="as-record-list">
          <div v-if="loading" class="as-empty"><LoaderCircle class="as-spin" /> 正在加载...</div>
          <div v-else-if="!filteredRows.length" class="as-empty">暂无符合条件的记录</div>
          <button v-for="item in filteredRows" :key="item.id" type="button" class="as-resource-row" :class="{ active: String(item.id) === String(selectedId) }" @click="selectRow(item)">
            <span v-if="resource === 'team'" class="as-avatar">{{ String(item.name || '服').slice(0, 1) }}</span>
            <span v-else class="as-resource-icon"><component :is="config.icon" /></span>
            <span><strong>{{ listTitle(item) }}</strong><small>{{ listMeta(item) }}</small><em v-if="resource === 'team'">{{ (item.skills || item.abilities || []).slice(0, 3).join(' · ') }}</em></span>
            <span class="as-status">{{ rowStatus(item) }}</span><ChevronRight />
          </button>
        </div>
      </section>

      <section class="as-panel as-resource-detail">
        <div v-if="!selected" class="as-empty as-empty--large"><component :is="config.icon" /> 选择一条记录查看详情</div>
        <template v-else>
          <div class="as-detail-head as-detail-head--resource"><div><span class="as-code">{{ selected.id }}</span><h2>{{ listTitle(selected) }}</h2><p>{{ listMeta(selected) }}</p></div><span class="as-status">{{ rowStatus(selected) }}</span></div>

          <template v-if="resource === 'team'">
            <dl class="as-info-grid"><div><dt><UserRoundCheck />服务身份</dt><dd>{{ display(selected, 'roleLabel', 'role_display', 'roleDisplay', 'role') }}</dd></div><div><dt><ShieldCheck />认证状态</dt><dd>{{ rowStatus(selected) }}</dd></div><div><dt><Star />服务评分</dt><dd>{{ display(selected, 'score', 'rating') }}</dd></div><div><dt><ClipboardCheck />累计订单</dt><dd>{{ display(selected, 'totalOrders', 'total_orders') }}</dd></div></dl>
            <div class="as-detail-section"><h3>地区与能力</h3><div class="as-tag-list"><span v-for="item in (selected.regions || [selected.city]).filter(Boolean)" :key="item">{{ item }}</span><span v-for="item in (selected.skills || selected.abilities || [])" :key="item" class="is-skill">{{ item }}</span></div></div>
            <div class="as-detail-section"><h3>认证处理</h3><div class="as-node-actions"><button v-if="selected.certificationStatus !== 'certified'" type="button" class="as-button as-button--primary" :disabled="saving" @click="reviewProvider('certified')"><ShieldCheck />认证通过</button><button v-else type="button" class="as-button as-button--danger" :disabled="saving" @click="reviewProvider('paused')"><CircleAlert />暂停服务</button></div></div>
            <div class="as-detail-section"><h3>近期服务记录</h3><div v-if="!(selected.projects || selected.service_records || []).length" class="as-empty as-empty--compact">暂无服务记录</div><div v-for="(item, index) in (selected.projects || selected.service_records || [])" :key="item.id || index" class="as-simple-row"><strong>{{ Array.isArray(item) ? item[0] : display(item, 'project_name', 'projectName', 'title') }}</strong><span>{{ Array.isArray(item) ? item[1] : display(item, 'time', 'status') }}</span></div></div>
          </template>

          <template v-else-if="resource === 'rewards'">
            <dl class="as-info-grid"><div><dt>获得人员</dt><dd>{{ display(selected, 'providerName', 'recipient_name', 'recipientName', 'installer') }}</dd></div><div><dt>获得时间</dt><dd>{{ display(selected, 'createdAt', 'created_at', 'time') }}</dd></div><div><dt>来源类型</dt><dd>{{ display(selected, 'rewardTypeLabel', 'source_display', 'sourceDisplay', 'source') }}</dd></div><div><dt>关联项目</dt><dd>{{ display(selected, 'projectName', 'project_name', 'project') }}</dd></div></dl>
            <div class="as-detail-section"><h3>获得原因</h3><p class="as-long-copy">{{ display(selected, 'reason', 'description') }}</p></div>
            <div class="as-detail-section"><h3>发放处理</h3><template v-if="['pending', 'approved'].includes(rewardStatus)"><div class="as-form-grid"><label v-if="rewardStatus === 'approved'" class="as-field"><span>快递单号 / 凭证</span><input v-model="trackingNo" placeholder="填写发放凭证"></label><label class="as-field"><span>处理备注</span><input v-model="actionNote" placeholder="审核或行政发放说明"></label></div><button v-if="rewardStatus === 'pending'" class="as-button as-button--primary" :disabled="saving" @click="processReward('approve')"><Check />审核通过</button><button v-else class="as-button as-button--primary" :disabled="saving" @click="processReward('issue')"><Send />确认发放</button></template><div v-else class="as-empty as-empty--compact">当前奖励无需发放操作</div></div>
          </template>

          <template v-else-if="resource === 'settlements'">
            <dl class="as-info-grid"><div><dt>来源收费节点</dt><dd>{{ display(selected, 'sourceNodeName', 'sourceNodeKey') }}</dd></div><div><dt>承担方式</dt><dd>{{ display(selected, 'bearerLabel', 'bearer') }}</dd></div><div><dt>结算 / 订单金额</dt><dd>{{ display(selected, 'finalAmount') }} / {{ display(selected, 'orderAmount') }}</dd></div><div><dt>未收 / 未开票</dt><dd>{{ display(selected, 'remainingReceivable') }} / {{ display(selected, 'remainingInvoice') }}</dd></div><div><dt>来源服务人员</dt><dd>{{ display(selected, 'sourceProviderName') }}</dd></div><div><dt>结算主体</dt><dd>{{ display(selected, 'subjectName') }}</dd></div></dl>
            <div class="as-detail-section"><h3>服务内容</h3><p class="as-long-copy">{{ display(selected, 'serviceContent') }}</p></div>
            <div v-if="!['settled', 'cancelled'].includes(selected.status)" class="as-detail-section"><h3>财务处理</h3><div class="as-form-grid"><label class="as-field"><span>结算主体</span><input v-model="settlementEdit.subject_name" placeholder="客户、公司或个人"></label><template v-if="selected.bearer === 'customer'"><label class="as-field"><span>已收金额</span><input v-model="settlementEdit.received_amount" type="number" min="0" :max="selected.orderAmount"></label><label class="as-field"><span>已开票金额</span><input v-model="settlementEdit.invoice_amount" type="number" min="0" :max="selected.invoiceDueAmount"></label><label class="as-field"><span>发票类型</span><input v-model="settlementEdit.invoice_type" placeholder="普票 / 专票"></label><label class="as-field"><span>发票号码</span><input v-model="settlementEdit.invoice_number"></label></template><label class="as-field as-field--wide"><span>结算说明</span><textarea v-model="settlementEdit.remark" rows="3"></textarea></label></div><div class="as-node-actions"><button type="button" class="as-button as-button--secondary" :disabled="saving" @click="saveSettlement()"><HandCoins />保存财务信息</button><button type="button" class="as-button as-button--danger" :disabled="saving" @click="saveSettlement('cancelled')">取消结算</button><button v-if="selected.status === 'draft'" type="button" class="as-button as-button--primary" :disabled="saving" @click="saveSettlement('pending')">提交结算</button><button v-else-if="selected.status === 'pending'" type="button" class="as-button as-button--primary" :disabled="saving" @click="saveSettlement('settled')"><Check />确认结清</button></div></div>
          </template>

          <AttachmentPanel v-if="attachmentTargetType && attachmentTargetId" :target-type="attachmentTargetType" :target-id="attachmentTargetId" :categories="attachmentCategories" @error="error = $event" />
        </template>
      </section>
    </div>

    <ModalShell :open="createOpen" title="生成结算记录" wide @close="createOpen = false">
      <div class="as-form-grid">
        <template v-if="resource === 'settlements'">
          <label class="as-field as-field--wide"><span>来源收费节点 *</span><select v-model="form.source_node_id" @change="applySettlementSource"><option value="">请选择已完成且待结算的节点</option><option v-for="source in settlementSources" :key="source.sourceNodeId" :value="source.sourceNodeId">{{ source.projectCode }} · {{ source.projectName }} · {{ source.nodeName }} · ¥{{ source.actualFee }}</option></select></label>
          <template v-if="selectedSettlementSource">
            <label class="as-field"><span>承担方式</span><select v-model="form.bearer"><option value="customer">客户承担</option><option value="company">公司承担</option></select></label>
            <label class="as-field"><span>来源服务人员</span><select v-model="form.source_assignment_id"><option value="">不指定人员</option><option v-for="assignment in settlementAssignmentOptions" :key="assignment.id" :value="assignment.id">{{ assignment.providerName }} · {{ assignment.role }}</option></select></label>
            <label class="as-field"><span>项目 / 客户</span><input :value="`${selectedSettlementSource.projectName} / ${selectedSettlementSource.customer}`" readonly></label>
            <label class="as-field"><span>服务类型 / 节点</span><input :value="`${selectedSettlementSource.serviceTypeLabel} / ${selectedSettlementSource.nodeName}`" readonly></label>
            <label class="as-field"><span>预计 / 实际费用</span><input :value="`${selectedSettlementSource.estimatedFee || '-'} / ${selectedSettlementSource.actualFee}`" readonly></label>
            <label class="as-field"><span>{{ form.bearer === 'customer' ? '订单金额' : '结算金额' }}</span><input :value="settlementOrderAmount" readonly></label>
            <label class="as-field"><span>主体类型</span><select v-model="form.subject_type"><option value="customer">客户</option><option value="company">公司</option><option value="person">个人</option></select></label>
            <label class="as-field"><span>结算主体</span><input v-model="form.subject_name" placeholder="客户、公司或个人"></label>
            <template v-if="form.bearer === 'customer'"><label class="as-field"><span>已收金额</span><input v-model="form.received_amount" type="number" min="0" :max="settlementOrderAmount"></label><label class="as-field"><span>已开票金额</span><input v-model="form.invoice_amount" type="number" min="0" :max="settlementOrderAmount"></label><label class="as-field"><span>发票类型</span><input v-model="form.invoice_type" placeholder="普票 / 专票"></label><label class="as-field"><span>发票号码</span><input v-model="form.invoice_number"></label></template>
            <label class="as-field as-field--wide"><span>结算说明</span><textarea v-model="form.remark" rows="3" placeholder="记录承担口径、核销或收款说明"></textarea></label>
          </template>
          <div v-else-if="!settlementSources.length" class="as-empty as-empty--compact as-field--wide">暂无可生成结算的已完成收费节点</div>
        </template>
      </div>
      <template #footer><button class="as-button as-button--secondary" @click="createOpen = false">取消</button><button class="as-button as-button--primary" :disabled="saving" @click="createRecord"><LoaderCircle v-if="saving" class="as-spin" /><Plus v-else />确认提交</button></template>
    </ModalShell>

    <ModalShell :open="capabilityOpen" title="编辑能力标签" :description="editedCapabilityNode ? `${editedCapabilityNode.serviceTypeLabel} · ${editedCapabilityNode.nodeName}` : '按业务节点维护能力选项'" @close="capabilityOpen = false">
      <div class="as-capability-editor">
        <label class="as-field"><span>一级业务节点</span><select v-model="capabilityNodeValue" @change="changeCapabilityNode"><optgroup v-for="group in capabilityGroups" :key="group.serviceType" :label="group.serviceTypeLabel"><option v-for="node in group.nodes" :key="`${group.serviceType}:${node.nodeKey}`" :value="`${group.serviceType}:${node.nodeKey}`">{{ node.nodeName }}</option></optgroup></select></label>
        <div class="as-capability-list">
          <div v-for="(_name, index) in capabilityDraft" :key="index" class="as-capability-row"><input v-model="capabilityDraft[index]" maxlength="128" :aria-label="`能力标签 ${index + 1}`"><button type="button" class="as-icon-button" title="删除能力标签" aria-label="删除能力标签" :disabled="capabilityDraft.length <= 1" @click="removeCapabilityTag(index)"><Trash2 /></button></div>
        </div>
        <button type="button" class="as-button as-button--secondary as-capability-add" :disabled="capabilityDraft.length >= 50" @click="addCapabilityTag"><Plus />添加能力</button>
      </div>
      <template #footer><button type="button" class="as-button as-button--secondary" :disabled="capabilitySaving" @click="capabilityOpen = false">取消</button><button type="button" class="as-button as-button--primary" :disabled="capabilitySaving" @click="saveCapabilityTags"><LoaderCircle v-if="capabilitySaving" class="as-spin" /><Save v-else />保存能力</button></template>
    </ModalShell>
  </div>
</template>

<style scoped>
.as-team-filter { grid-template-columns: minmax(190px, 1fr) minmax(100px, .55fr) minmax(125px, .72fr) minmax(110px, .62fr) 34px; }
.as-capability-manage { align-self: center; }
.as-capability-editor { display: grid; gap: 14px; }
.as-capability-list { display: grid; gap: 8px; }
.as-capability-row { display: grid; grid-template-columns: minmax(0, 1fr) 34px; gap: 8px; align-items: center; }
.as-capability-row input { width: 100%; min-width: 0; height: 38px; border: 1px solid var(--as-border); border-radius: 6px; padding: 0 10px; color: var(--as-text); outline: 0; }
.as-capability-row input:focus { border-color: var(--as-primary); box-shadow: 0 0 0 2px rgb(21 94 239 / 9%); }
.as-capability-row .as-icon-button { color: var(--as-danger); }
.as-capability-add { width: fit-content; }
@media (max-width: 980px) {
  .as-team-filter { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .as-team-filter .as-search { grid-column: 1 / -1; }
}
@media (max-width: 620px) {
  .as-team-filter { grid-template-columns: minmax(0, 1fr) 34px; }
  .as-team-filter > .as-select { grid-column: 1 / -1; }
}
</style>
