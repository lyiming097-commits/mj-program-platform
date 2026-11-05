<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { Check, Clock3, FileText, LoaderCircle, Search } from "@lucide/vue";
import { collectionRows, serviceApi } from "@/serviceApi";
import { matchesDirectorySearchKeyword } from "@platform-ui/directory-search.js";
import { ElOption, ElSelect } from "element-plus/es/components/select/index.mjs";
import "element-plus/es/components/select/style/css";
import ProjectDetailDrawer from "@/components/ProjectDetailDrawer.vue";
import GlobalNotice from "@/components/GlobalNotice.vue";
import UnsavedChangesDialog from "@/components/UnsavedChangesDialog.vue";
import { ElDialog } from "element-plus/es/components/dialog/index.mjs";
import "element-plus/es/components/dialog/style/css";
import PersonnelSelectButton from "@/components/PersonnelSelectButton.vue";
import SettlementLedger from "@/components/SettlementLedger.vue";
import ListPagination from "@/components/ListPagination.vue";

const props = defineProps({
  focusProjectId: { type: [String, Number], default: "" },
  focusSourceNodeId: { type: [String, Number], default: "" },
});
const emit = defineEmits(["dirty-change", "busy-change"]);
const SERVICE_TYPES = [{ value: "midsales", label: "售中" }, { value: "aftersales", label: "售后" }];
const INVOICE_TYPES = ["13%增值税", "6%增值税", "收据"];
const loading = ref(false), saving = ref(false), detailLoading = ref(false);
const detailFailed = ref(false);
const error = ref(""), success = ref(""), detailError = ref("");
const activeTab = ref("all"), sourceFilter = ref("all"), nodeFilter = ref("all"), bearerFilter = ref("all");
const projectKeyword = ref(""), customerKeyword = ref(""), ownerKeyword = ref("");
const sources = ref([]), feeNodeOptions = ref([]), page = ref(1), total = ref(0), totalPages = ref(1);
const pageSize = ref(20);
const selectedSource = ref(null), selectedRecord = ref(null), drawerOpen = ref(false);
const detailTab = ref("details"), detailTabs = ref(null);
const baseline = ref(""), conflictRecord = ref(null);
const correctionReason = ref(""), cancellationRequested = ref(false), serverRequiresReason = ref(false), reasonInput = ref(null);
const companies = ref([]), employees = ref([]), companyKeyword = ref(""), directoryError = ref(""), directoryLoading = ref(false);
const personOpen = ref(false), personKeyword = ref(""), personInput = ref(null);
const projectOptions = ref([]), projectSearch = ref(""), projectPage = ref(1), projectPages = ref(1), projectLoading = ref(false), projectError = ref("");
const historyRecords = ref([]), historyPage = ref(1), historyPages = ref(1), historyRecord = ref(null);
const discardOpen = ref(false);
let pendingDiscard = null, listEpoch = 0, detailEpoch = 0, projectEpoch = 0, searchTimer = 0, projectTimer = 0, disposed = false;
let detailScroll = { details: 0, history: 0 };
const form = reactive({ bearer: "customer", subjectType: "company", subjectId: "", subjectName: "", receivedAmount: "", invoicedAmount: "", invoiceType: INVOICE_TYPES[0], invoiceNumber: "", relatedProjectId: "", remark: "" });
const amountEntry = reactive({ receivedAmount: "total", invoicedAmount: "total" });
const editable = computed(() => !saving.value && !detailLoading.value && !detailFailed.value && selectedRecord.value?.status !== "cancelled");
const quote = computed(() => selectedRecord.value ? selectedRecord.value.externalQuote : selectedSource.value?.externalQuote);
const orderAmount = computed(() => selectedRecord.value?.orderAmount ?? (form.bearer === "customer" ? quote.value : selectedSource.value?.actualFee));
const invoiceDue = computed(() => form.bearer === "customer" ? number(selectedRecord.value?.invoiceDueAmount ?? orderAmount.value) : 0);
const displayedReceived = computed(() => cents(form.receivedAmount) / 100);
const displayedInvoiced = computed(() => cents(form.invoicedAmount) / 100);
// Both amount inputs write the same cumulative value, so editing either never adds a payment twice.
function additionInput(field) {
  return computed({
    get: () => Math.max(0, cents(form[field]) - cents(selectedRecord.value?.[field])) / 100 || "",
    set: value => { amountEntry[field] = "addition"; form[field] = (cents(selectedRecord.value?.[field]) + cents(value)) / 100; },
  });
}
const receiptAddition = additionInput("receivedAmount"), invoiceAddition = additionInput("invoicedAmount");
const receiptShortfall = computed(() => form.bearer === "customer" ? Math.max(0, cents(orderAmount.value) - cents(displayedReceived.value)) / 100 : 0);
const invoiceShortfall = computed(() => Math.max(0, cents(invoiceDue.value) - cents(displayedInvoiced.value)) / 100);
const reopensSettlement = computed(() => selectedRecord.value?.status === "settled" && form.bearer === "customer" && receiptShortfall.value > 0);
const saveStatus = computed(() => cancellationRequested.value ? "cancelled" : reopensSettlement.value ? "pending" : selectedRecord.value?.status || "pending");
const requiresReason = computed(() => {
  const record = selectedRecord.value;
  if (!record || record.status === "cancelled") return false;
  const values = financialPayload();
  const reducing = ["receivedAmount", "invoicedAmount"].some(field => cents(values[field]) < cents(record[field]));
  const invoiceCorrection = ["invoiceType", "invoiceNumber"].some(field => record[field] && values[field] !== record[field]) && cents(values.invoicedAmount) <= cents(record.invoicedAmount);
  const settledChange = record.status === "settled" && Object.keys(values).some(field => !["invoiceType", "invoiceNumber", "invoicedAmount"].includes(field) && payloadDiffers(field, values[field], record[field]));
  return serverRequiresReason.value || reducing || invoiceCorrection || settledChange || cancellationRequested.value || reopensSettlement.value;
});
const customerQuoteMissing = computed(() => form.bearer === "customer" && number(orderAmount.value) <= 0);
const dirty = computed(() => drawerOpen.value && !detailLoading.value && !detailFailed.value && baseline.value !== snapshot());
const filteredEmployees = computed(() => employees.value.filter(item => matchesDirectorySearchKeyword(personKeyword.value, {
  names: [item.name, ...(item.departments || []).map(dept => dept.name)], ids: [item.userId],
  pinyin: [item.pinyin, ...(item.departments || []).map(dept => dept.pinyin)],
  pinyinInitials: [item.pinyinInitials, ...(item.departments || []).map(dept => dept.pinyinInitials)],
})));
const filteredCompanies = computed(() => companies.value.filter(item => matchesDirectorySearchKeyword(companyKeyword.value, {
  names: item.companyName, ids: item.id, pinyin: item.pinyin, pinyinInitials: item.pinyinInitials,
})));
const tabTitle = computed(() => ({ all: "全部结算服务", available: "可结算服务", unsettled: "未结算服务", settled: "已结算服务" })[activeTab.value]);
const statusLabels = { draft: "草稿", pending: "待结算", settled: "已结算", cancelled: "已撤销" };
function unwrap(response) { return response?.item || response; }
function number(value) { return Number(String(value ?? "").replace(/[￥,]/g, "")) || 0; }
function cents(value) { return Math.round(number(value) * 100); }
function money(value, fallback = "￥0") { return value === "" || value == null ? fallback : "￥" + number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function key(source) { return String(source.sourceNodeId || source.id); }
function snapshot() { return JSON.stringify([form, correctionReason.value, cancellationRequested.value]); }
function payloadDiffers(field, left, right) {
  return ["receivedAmount", "invoicedAmount"].includes(field) ? cents(left) !== cents(right) : String(left ?? "") !== String(right ?? "");
}
function resetBaseline() { baseline.value = snapshot(); }
function statusLabel(record) { return statusLabels[record?.status] || "待结算"; }
function recordFor(source) { return source.settlement; }
function bearerLabel(source) { return source.settlement ? source.settlement.bearer === "company" ? "公司承担" : "客户承担" : "待选择"; }
function changeDetailTab(tab, focus = false) {
  const scroller = detailTabs.value?.closest(".el-drawer__body");
  if (scroller) detailScroll[detailTab.value] = scroller.scrollTop;
  detailTab.value = tab;
  void nextTick(() => {
    if (detailTab.value !== tab) return;
    if (scroller?.isConnected) scroller.scrollTop = detailScroll[tab];
    if (focus) detailTabs.value?.querySelector(`[data-detail-tab="${tab}"]`)?.focus({ preventScroll: true });
  });
}
function handleDetailTabKey(event) {
  const tabs = ["details", "history"];
  const index = tabs.indexOf(detailTab.value);
  const next = { ArrowRight: tabs[(index + 1) % tabs.length], ArrowLeft: tabs[(index + tabs.length - 1) % tabs.length], Home: tabs[0], End: tabs.at(-1) }[event.key];
  if (!next || saving.value) return;
  event.preventDefault();
  changeDetailTab(next, true);
}
function guard(action) {
  if (saving.value || detailLoading.value) return false;
  if (!dirty.value) { action(); return true; }
  pendingDiscard = action;
  discardOpen.value = true;
  return false;
}
function confirmDiscard() { discardOpen.value = false; const action = pendingDiscard; pendingDiscard = null; action?.(); }
function guardClose() { return guard(() => { drawerOpen.value = false; }); }
function closeDetail() { drawerOpen.value = false; }
function syncForm(record = selectedRecord.value) {
  Object.assign(form, {
    bearer: record?.bearer || "customer", subjectType: record?.subjectType || "company", subjectId: String(record?.subjectId || ""), subjectName: record?.subjectName || "",
    receivedAmount: record?.receivedAmount || "", invoicedAmount: record?.invoicedAmount || "", invoiceType: record?.invoiceType || INVOICE_TYPES[0],
    invoiceNumber: record?.invoiceNumber || "", relatedProjectId: record?.relatedProjectId ? String(record.relatedProjectId) : "", remark: record?.remark || "",
  });
  amountEntry.receivedAmount = "total"; amountEntry.invoicedAmount = "total";
  correctionReason.value = ""; cancellationRequested.value = false; serverRequiresReason.value = false; conflictRecord.value = null;
  projectOptions.value = record?.relatedProjectId ? [{ id: record.relatedProjectId, name: record.relatedProjectName }] : [];
  resetBaseline();
}
async function load() {
  const epoch = ++listEpoch;
  loading.value = true;
  try {
    const payload = await serviceApi.listSettlementSources({
      state: activeTab.value, type: sourceFilter.value === "all" ? "" : sourceFilter.value,
      nodeName: nodeFilter.value === "all" ? "" : nodeFilter.value, bearer: bearerFilter.value === "all" ? "" : bearerFilter.value,
      projectSearch: projectKeyword.value.trim(), customerSearch: customerKeyword.value.trim(), ownerSearch: ownerKeyword.value.trim(),
      page: page.value, pageSize: pageSize.value,
    });
    if (disposed || epoch !== listEpoch) return;
    sources.value = collectionRows(payload); total.value = payload.total; page.value = payload.page; totalPages.value = payload.totalPages;
    feeNodeOptions.value = payload.nodeNames || [];
    error.value = "";
  } catch (reason) { if (epoch === listEpoch) error.value = reason.message || "结算数据加载失败"; }
  finally { if (epoch === listEpoch) loading.value = false; }
}
async function selectSource(source) {
  guard(() => { void openSource(source); });
}
async function openSource(source) {
  const epoch = ++detailEpoch;
  drawerOpen.value = true; selectedSource.value = source; selectedRecord.value = source.settlement || null;
  detailTab.value = "details";
  detailScroll = { details: 0, history: 0 };
  historyRecord.value = null; historyRecords.value = []; historyPage.value = 1; detailError.value = "";
  detailLoading.value = true; detailFailed.value = false;
  try {
    if (source.settlement?.id) selectedRecord.value = unwrap(await serviceApi.getSettlement(source.settlement.id));
    if (epoch !== detailEpoch || disposed) return;
    syncForm();
    await loadHistory();
  } catch (reason) { detailFailed.value = true; detailError.value = reason.message || "结算详情加载失败"; }
  finally { if (epoch === detailEpoch) detailLoading.value = false; }
}
async function loadHistory() {
  if (!selectedSource.value?.sourceNodeId) return;
  const sourceId = selectedSource.value.sourceNodeId;
  const payload = await serviceApi.listSettlements({ sourceNodeId: sourceId, page: historyPage.value, pageSize: 10 });
  if (String(selectedSource.value?.sourceNodeId) !== String(sourceId) || disposed) return;
  historyRecords.value = collectionRows(payload).filter(item => item.status === "cancelled"); historyPages.value = payload.totalPages || 1;
}
async function openHistory(record) {
  try { historyRecord.value = unwrap(await serviceApi.getSettlement(record.id)); }
  catch (reason) { detailError.value = reason.message; }
}
async function focusRequested() {
  if (!props.focusSourceNodeId && !props.focusProjectId) return;
  try {
    const payload = await serviceApi.listSettlementSources({ state: "all", sourceNodeId: props.focusSourceNodeId, projectId: props.focusProjectId, pageSize: 1 });
    const source = collectionRows(payload)[0];
    if (source) selectSource(source);
  } catch (reason) { error.value = reason.message; }
}
function financialPayload() {
  const values = {
    receivedAmount: form.bearer === "customer" ? displayedReceived.value : 0,
    invoicedAmount: form.bearer === "customer" ? displayedInvoiced.value : 0,
    invoiceType: form.bearer === "customer" ? form.invoiceType : "", invoiceNumber: form.bearer === "customer" ? form.invoiceNumber : "",
    subjectType: form.bearer === "customer" ? "customer" : form.subjectType,
    subjectId: form.bearer === "customer" ? "" : form.subjectId, subjectName: form.bearer === "customer" ? selectedSource.value?.customer || "" : form.subjectName,
    relatedProjectId: form.bearer === "company" ? form.relatedProjectId || null : null, remark: form.remark.trim(),
  };
  // Invoice registration must not silently normalize a historical customer's identity fields.
  if (selectedRecord.value && form.bearer === "customer") {
    ["subjectType", "subjectId", "subjectName", "relatedProjectId"].forEach(field => delete values[field]);
  }
  return values;
}
async function save(nextStatus) {
  if (!editable.value || conflictRecord.value) return;
  if (requiresReason.value && !correctionReason.value.trim()) { detailError.value = cancellationRequested.value ? "请填写撤销原因" : "请填写更正原因"; void focusReason(); return; }
  saving.value = true; detailError.value = "";
  try {
    const values = financialPayload();
    let response;
    if (selectedRecord.value) {
      response = await serviceApi.updateSettlement(selectedRecord.value.id, {
        ...values, expectedRevision: selectedRecord.value.revision,
        correctionReason: correctionReason.value.trim(),
        status: nextStatus || saveStatus.value,
      });
    } else {
      response = await serviceApi.createSettlement({ ...values, bearer: form.bearer, sourceNodeId: selectedSource.value.sourceNodeId, status: nextStatus || "pending" });
    }
    selectedRecord.value = unwrap(response);
    selectedSource.value.settlement = selectedRecord.value;
    syncForm();
    success.value = selectedRecord.value.status === "settled" ? "结算已保存，发票可继续补录" : selectedRecord.value.status === "cancelled" ? "结算已撤销，历史记录已保留" : "结算已保存";
    await load(); await loadHistory();
  } catch (reason) {
    detailError.value = reason.message || "结算保存失败";
    if (reason.code === "SETTLEMENT_REVISION_CONFLICT") {
      try { conflictRecord.value = unwrap(await serviceApi.getSettlement(selectedRecord.value.id)); }
      catch { detailError.value += " 最新记录读取失败，请重试保存以重新核对。"; }
    }
    if (reason.code === "SETTLEMENT_SOURCE_CONFLICT") detailError.value += " 请关闭详情后重新打开原结算记录。";
    if (reason.code === "SETTLEMENT_CORRECTION_REASON_REQUIRED") { serverRequiresReason.value = true; void focusReason(); }
  } finally { saving.value = false; }
}
const conflictDifferences = computed(() => {
  if (!conflictRecord.value) return [];
  const values = financialPayload();
  const compared = { ...values, status: saveStatus.value };
  return Object.keys(compared).filter(field => payloadDiffers(field, compared[field], conflictRecord.value[field])).map(field => ({
    field, mine: field === "status" ? statusLabels[compared[field]] : compared[field], latest: field === "status" ? statusLabels[conflictRecord.value[field]] : conflictRecord.value[field],
  }));
});
const payloadLabels = { receivedAmount: "累计已收", invoicedAmount: "累计已开票", invoiceType: "开票类型", invoiceNumber: "票据单号", subjectType: "主体类型", subjectId: "主体 ID", subjectName: "主体名称", relatedProjectId: "关联项目", remark: "说明", status: "结算状态" };
function reconcileConflict(keepChanges) {
  const latest = conflictRecord.value;
  if (!latest) return;
  const oldRecord = selectedRecord.value, edited = { ...form };
  const chosenProject = projectOptions.value.find(item => String(item.id) === form.relatedProjectId);
  const entry = { ...amountEntry }, reason = correctionReason.value, cancelling = cancellationRequested.value;
  selectedRecord.value = latest; syncForm(latest);
  if (keepChanges) {
    Object.keys(edited).forEach(field => {
      if (!payloadDiffers(field, edited[field], oldRecord[field])) return;
      // New registrations keep their cumulative target without reducing a higher balance saved by someone else.
      form[field] = entry[field] === "addition" ? Math.max(cents(edited[field]), cents(latest[field])) / 100 : edited[field];
    });
    Object.assign(amountEntry, entry); correctionReason.value = reason; cancellationRequested.value = cancelling;
    if (chosenProject && form.relatedProjectId === String(chosenProject.id) && !projectOptions.value.some(item => String(item.id) === form.relatedProjectId)) projectOptions.value.push(chosenProject);
  }
  detailError.value = ""; conflictRecord.value = null;
}
async function loadDirectories() {
  directoryLoading.value = true; directoryError.value = "";
  const results = await Promise.allSettled([serviceApi.settlementCompanies(), serviceApi.employeeDirectory()]);
  if (disposed) return;
  if (results[0].status === "fulfilled") companies.value = collectionRows(results[0].value);
  if (results[1].status === "fulfilled") employees.value = collectionRows(results[1].value);
  directoryError.value = results.filter(result => result.status === "rejected").map(result => result.reason.message).join("；");
  directoryLoading.value = false;
}
function chooseCompany(id) {
  form.subjectId = String(id || ""); form.subjectName = companies.value.find(item => String(item.id) === form.subjectId)?.companyName || "";
  form.relatedProjectId = ""; projectOptions.value = []; projectEpoch++; projectPage.value = 1; projectSearch.value = "";
}
async function openPerson() { personOpen.value = true; personKeyword.value = ""; await nextTick(); personInput.value?.focus(); }
function choosePerson(person) { form.subjectId = person.userId; form.subjectName = person.name; form.relatedProjectId = ""; projectOptions.value = []; personOpen.value = false; projectPage.value = 1; void loadProjects(); }
function changeSubjectType() { form.subjectId = ""; form.subjectName = ""; form.relatedProjectId = ""; projectOptions.value = []; projectPage.value = 1; projectSearch.value = ""; projectEpoch++; }
function changeBearer() { changeSubjectType(); form.subjectType = "company"; form.receivedAmount = ""; form.invoicedAmount = ""; }
async function loadProjects() {
  if (form.subjectType === "person" && !form.subjectId) return;
  const epoch = ++projectEpoch;
  projectLoading.value = true; projectError.value = "";
  try {
    const payload = await serviceApi.settlementProjects({ userId: form.subjectType === "person" ? form.subjectId : "", search: projectSearch.value, page: projectPage.value, pageSize: 20 });
    if (epoch !== projectEpoch || disposed) return;
    const selected = projectOptions.value.find(item => String(item.id) === form.relatedProjectId);
    const rows = collectionRows(payload);
    projectOptions.value = selected && !rows.some(item => String(item.id) === form.relatedProjectId) ? [selected, ...rows] : rows;
    projectPages.value = payload.totalPages || 1;
  } catch (reason) { if (epoch === projectEpoch) projectError.value = reason.message; }
  finally { if (epoch === projectEpoch) projectLoading.value = false; }
}
function searchProjects(value) { projectSearch.value = value; projectPage.value = 1; window.clearTimeout(projectTimer); projectTimer = window.setTimeout(loadProjects, 250); }
async function focusReason() { changeDetailTab("details"); await nextTick(); reasonInput.value?.focus(); reasonInput.value?.scrollIntoView({ block: "center", behavior: "smooth" }); }
function requestCancel() { cancellationRequested.value = true; void focusReason(); }
function changePage(value) {
  if (loading.value || value < 1 || value > totalPages.value || value === page.value) return;
  window.clearTimeout(searchTimer); page.value = value; void load();
}
watch([activeTab, sourceFilter, nodeFilter, bearerFilter, pageSize], () => { page.value = 1; window.clearTimeout(searchTimer); void load(); });
watch([projectKeyword, customerKeyword, ownerKeyword], () => {
  page.value = 1; listEpoch++; loading.value = true;
  window.clearTimeout(searchTimer); searchTimer = window.setTimeout(load, 300);
}, { flush: "sync" });
watch(dirty, value => emit("dirty-change", value), { immediate: true });
watch(saving, value => emit("busy-change", value), { immediate: true });
watch(() => [props.focusProjectId, props.focusSourceNodeId], focusRequested);
onMounted(() => { void load(); void loadDirectories(); void focusRequested(); });
onBeforeUnmount(() => { disposed = true; listEpoch++; detailEpoch++; projectEpoch++; window.clearTimeout(searchTimer); window.clearTimeout(projectTimer); emit("dirty-change", false); emit("busy-change", false); });
</script>

<template>
  <div class="as-page as-settlement-page">
    <GlobalNotice v-model:error="error" v-model:success="success" />
    <section class="as-panel as-settlement-list-card">
      <div class="as-panel-head"><div><h2>{{ tabTitle }}</h2><p>服务进度与结算分别管理，部分收款可先保存，结清后可继续补票。</p></div><button v-if="error" type="button" class="as-button" @click="load">重试加载</button></div>
      <div class="as-settlement-table-scroll">
        <table class="as-settlement-table" aria-label="结算服务列表" :aria-busy="loading">
          <thead>
            <tr><th>项目名称</th><th>客户名称</th><th>服务类型</th><th>收费节点</th><th>负责人</th><th>预算</th><th>决算</th><th>费用承担</th><th>状态</th></tr>
            <tr class="as-settlement-table-filter-row">
              <th><label class="as-search"><Search /><input v-model="projectKeyword" type="search" aria-label="搜索结算项目名称" placeholder="搜索项目名称"></label></th>
              <th><label class="as-search"><Search /><input v-model="customerKeyword" type="search" aria-label="搜索结算客户名称" placeholder="搜索客户名称"></label></th>
              <th><ElSelect v-model="sourceFilter" class="as-table-select" popper-class="as-table-select-popper" aria-label="结算服务类型筛选"><ElOption label="全部服务" value="all" /><ElOption v-for="item in SERVICE_TYPES" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></th>
              <th><ElSelect v-model="nodeFilter" class="as-table-select" popper-class="as-table-select-popper" aria-label="收费节点筛选"><ElOption label="全部节点" value="all" /><ElOption v-for="item in feeNodeOptions" :key="item" :label="item" :value="item" /></ElSelect></th>
              <th><label class="as-search"><Search /><input v-model="ownerKeyword" type="search" aria-label="搜索结算负责人" placeholder="搜索负责人"></label></th><th></th><th></th>
              <th><ElSelect v-model="bearerFilter" class="as-table-select" popper-class="as-table-select-popper" aria-label="费用承担筛选"><ElOption label="全部承担" value="all" /><ElOption label="客户承担" value="customer" /><ElOption label="公司承担" value="company" /><ElOption label="待选择" value="unselected" /></ElSelect></th>
              <th><ElSelect v-model="activeTab" class="as-table-select" popper-class="as-table-select-popper" aria-label="结算状态筛选"><ElOption label="全部状态" value="all" /><ElOption label="已结算服务" value="settled" /><ElOption label="可结算服务" value="available" /><ElOption label="未结算服务" value="unsettled" /></ElSelect></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading"><td colspan="9" class="as-settlement-table-empty"><LoaderCircle class="as-spin" /> 正在加载费用...</td></tr>
            <tr v-else-if="!sources.length"><td colspan="9" class="as-settlement-table-empty">{{ error ? '加载失败，请重试' : '没有找到匹配的结算服务' }}</td></tr>
            <tr v-for="source in sources" v-else :key="key(source)" tabindex="0" :class="{ active: selectedSource && key(source) === key(selectedSource) }" @click="selectSource(source)" @keydown.enter="selectSource(source)" @keydown.space.prevent="selectSource(source)">
              <td><strong>{{ source.projectName }}</strong><small>{{ source.projectCode }}</small></td><td>{{ source.customer }}</td><td><span class="as-settlement-type">{{ source.serviceTypeLabel }}</span></td><td>{{ source.nodeName }}</td><td>{{ source.ownerName || '待指定人员' }}</td><td>{{ money(source.estimatedFee) }}</td><td>{{ money(source.actualFee) }}</td><td>{{ bearerLabel(source) }}</td><td><span class="as-status" :class="{ 'is-done': recordFor(source)?.status === 'settled' }">{{ statusLabel(recordFor(source)) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <ListPagination v-model:page-size="pageSize" class="as-settlement-desktop-pagination" :page="page" :total="total" :total-pages="totalPages" :loading="loading" label="结算分页" size-label="每页结算数" @change="changePage" />
      <nav class="as-settlement-pagination" aria-label="结算分页"><span>共 {{ total }} 项 · 第 {{ page }} / {{ totalPages }} 页</span><button type="button" class="as-button as-button--secondary" :disabled="loading || page <= 1" @click="changePage(page - 1)">上一页</button><button type="button" class="as-button as-button--secondary" :disabled="loading || page >= totalPages" @click="changePage(page + 1)">下一页</button></nav>
    </section>

    <ProjectDetailDrawer :open="drawerOpen" title="结算详情" :close-guard="guardClose" @close="closeDetail">
      <section class="as-panel as-settlement-detail-card">
        <div v-if="detailLoading" class="as-empty"><LoaderCircle class="as-spin" /> 正在读取结算详情...</div>
        <template v-else-if="selectedSource">
          <div class="as-detail-head as-settlement-detail-head"><div><span class="as-settlement-avatar">结</span><div><span class="as-code">{{ selectedRecord?.code || selectedSource.projectCode }}</span><h2>{{ selectedSource.projectName }}</h2><p>{{ selectedSource.serviceTypeLabel }} · {{ selectedSource.customer }}</p></div></div><span class="as-status">{{ statusLabel(selectedRecord) }}</span></div>
          <div class="as-project-sticky-tabs">
            <nav ref="detailTabs" class="as-project-detail-tabs as-mall-tabbar" role="tablist" aria-label="结算详情视图" @keydown="handleDetailTabKey">
              <button id="settlement-details-tab" type="button" role="tab" data-detail-tab="details" aria-controls="settlement-details-panel" :aria-selected="detailTab === 'details'" :tabindex="detailTab === 'details' ? 0 : -1" :class="{ active: detailTab === 'details' }" :disabled="saving" @click="changeDetailTab('details')"><FileText aria-hidden="true" />结算详情</button>
              <button id="settlement-history-tab" type="button" role="tab" data-detail-tab="history" aria-controls="settlement-history-panel" :aria-selected="detailTab === 'history'" :tabindex="detailTab === 'history' ? 0 : -1" :class="{ active: detailTab === 'history' }" :disabled="saving" @click="changeDetailTab('history')"><Clock3 aria-hidden="true" />版本与留痕<span>{{ selectedRecord?.events?.length || 0 }}</span></button>
            </nav>
          </div>
          <div id="settlement-details-panel" v-show="detailTab === 'details'" class="as-settlement-detail-body" role="tabpanel" aria-labelledby="settlement-details-tab" tabindex="0">
            <section class="as-settlement-form-panel"><div class="as-settlement-section-title"><h2>费用来源</h2></div><div class="as-settlement-form-grid">
              <div class="as-field as-settlement-readonly-field"><span>收费节点</span><strong>{{ selectedSource.nodeName }}</strong></div>
              <div class="as-field as-field--wide as-settlement-readonly-field"><span>服务内容</span><strong>{{ selectedRecord?.serviceContent || selectedSource.serviceContent }}</strong></div>
              <div class="as-field as-settlement-readonly-field"><span>费用预算</span><strong>{{ money(selectedRecord?.budgetAmount ?? selectedSource.estimatedFee) }}</strong></div>
              <div class="as-field as-settlement-readonly-field"><span>费用决算（实际成本）</span><strong>{{ money(selectedRecord?.finalAmount ?? selectedSource.actualFee) }}</strong></div>
              <div class="as-field as-settlement-readonly-field"><span>对外报价</span><strong>{{ money(quote, '未填写') }}</strong></div>
            </div></section>
            <section v-if="!selectedRecord" class="as-settlement-conditional-panel"><label class="as-field"><span>费用承担方式</span><select v-model="form.bearer" :disabled="!editable" @change="changeBearer"><option value="customer">客户承担</option><option value="company">公司承担</option></select></label></section>
            <section v-if="form.bearer === 'customer'" class="as-settlement-conditional-panel"><div class="as-settlement-section-title"><h2>客户承担</h2><span>收款与开票</span></div>
              <p class="as-settlement-help">金额与票据信息可直接修改。本次收款、开票与累计金额同步更新，保存后生效。</p>
              <div class="as-settlement-customer-money-grid">
                <label class="as-field"><span>对外订单金额</span><input :value="money(orderAmount)" readonly></label>
                <label class="as-field"><span>累计已收金额</span><input v-model="form.receivedAmount" type="number" min="0" step="0.01" :max="number(orderAmount)" :disabled="!editable || customerQuoteMissing" @input="amountEntry.receivedAmount = 'total'"></label>
                <label class="as-field"><span>未收金额</span><input :value="money(receiptShortfall)" readonly></label>
                <label class="as-field"><span>应开票金额</span><input :value="money(invoiceDue)" readonly></label>
                <label class="as-field"><span>累计已开票金额</span><input v-model="form.invoicedAmount" type="number" min="0" step="0.01" :max="invoiceDue" :disabled="!editable || customerQuoteMissing" @input="amountEntry.invoicedAmount = 'total'"></label>
                <label class="as-field"><span>未开票金额</span><input :value="money(invoiceShortfall)" readonly></label>
              </div>
              <div v-if="selectedRecord && selectedRecord.status !== 'cancelled' && !cancellationRequested" class="as-settlement-inline-fields">
                <label v-if="selectedRecord.status !== 'settled'" class="as-field"><span>本次收款金额</span><input v-model="receiptAddition" type="number" min="0" step="0.01" :max="number(selectedRecord.remainingReceivable)" :disabled="!editable" placeholder="填写本次新增收款"></label>
                <label class="as-field"><span>本次开票金额</span><input v-model="invoiceAddition" type="number" min="0" step="0.01" :max="number(selectedRecord.remainingInvoice)" :disabled="!editable" placeholder="填写本次新增开票"></label>
              </div>
              <div class="as-settlement-inline-fields">
                <label class="as-field"><span>开票类型</span><select v-model="form.invoiceType" :disabled="!editable"><option v-for="type in INVOICE_TYPES" :key="type">{{ type }}</option></select></label>
                <label class="as-field"><span>票据单号</span><input v-model="form.invoiceNumber" :disabled="!editable" placeholder="可选"></label>
              </div>
              <p v-if="customerQuoteMissing" class="as-settlement-receipt-warning">请先在来源节点的费用信息中填写对外报价。</p>
              <p v-else-if="reopensSettlement && !cancellationRequested" class="as-settlement-receipt-warning">修改后还有 {{ money(receiptShortfall) }} 未收，保存时将恢复为待结算。</p>
              <p v-else-if="receiptShortfall > 0" class="as-settlement-help">还有 {{ money(receiptShortfall) }} 未收，可先保存待结算记录。</p>
            </section>
            <section v-else class="as-settlement-conditional-panel"><div class="as-settlement-section-title"><h2>公司承担</h2><span>成本归集</span></div>
              <p class="as-settlement-help">公司承担金额为实际成本 {{ money(selectedRecord?.finalAmount ?? selectedSource.actualFee) }}。</p>
              <p v-if="directoryError" role="alert">{{ directoryError }} <button type="button" class="as-button" @click="loadDirectories">重试目录</button></p>
              <div class="as-settlement-company-grid">
                <label class="as-field"><span>承担主体类型</span><select v-model="form.subjectType" :disabled="!editable" @change="changeSubjectType"><option value="company">公司</option><option value="person">个人</option></select></label>
                <label v-if="form.subjectType === 'company'" class="as-field"><span>具体公司</span><ElSelect v-model="form.subjectId" class="as-searchable-select" popper-class="as-searchable-select-popper" filterable clearable :filter-method="value => companyKeyword = value" :loading="directoryLoading" :disabled="!editable" placeholder="选择平台公司主体" aria-label="具体公司" @change="chooseCompany"><ElOption v-if="form.subjectId && !companies.some(item => String(item.id) === form.subjectId)" :label="form.subjectName + '（历史主体，待核实）'" :value="form.subjectId" disabled /><ElOption v-for="item in filteredCompanies" :key="item.id" :label="item.companyName" :value="String(item.id)" /></ElSelect><small v-if="form.subjectName && !form.subjectId" class="as-settlement-history-label">历史主体：{{ form.subjectName }}（待重新选择）</small></label>
                <div v-else class="as-field"><span>具体个人</span><PersonnelSelectButton :name="form.subjectName" label="承担人员" :detail="form.subjectId ? '钉钉人员 · ' + form.subjectId : '请选择人员后再选择关联项目'" :disabled="!editable" @select="openPerson" /></div>
                <label class="as-field as-field--wide"><span>关联项目</span><ElSelect v-model="form.relatedProjectId" class="as-searchable-select" popper-class="as-searchable-select-popper" filterable remote clearable :remote-method="searchProjects" :loading="projectLoading" :disabled="!editable || (form.subjectType === 'person' && !form.subjectId)" aria-label="关联项目" :placeholder="form.subjectType === 'person' ? '先选择人员，再搜索其关联项目（可选）' : '搜索关联项目（可选）'" @visible-change="open => open && loadProjects()"><ElOption v-for="item in projectOptions" :key="item.id" :label="(item.serviceTypeLabel || '') + ' · ' + item.name + ' · ' + (item.customer || '')" :value="String(item.id)" /><template #footer><div class="as-settlement-history-list"><button type="button" class="as-button" :disabled="projectLoading || projectPage <= 1" @click.stop="projectPage--; loadProjects()">上一页</button><span>{{ projectPage }} / {{ projectPages }}</span><button type="button" class="as-button" :disabled="projectLoading || projectPage >= projectPages" @click.stop="projectPage++; loadProjects()">下一页</button></div></template></ElSelect><small v-if="projectError" role="alert">{{ projectError }} <button type="button" @click="loadProjects">重试</button></small></label>
              </div>
            </section>
            <section class="as-settlement-conditional-panel"><label class="as-field"><span>结算说明</span><textarea v-model="form.remark" rows="3" :disabled="!editable" placeholder="记录费用归集或补充说明"></textarea></label></section>
            <section v-if="requiresReason || correctionReason" class="as-settlement-conditional-panel">
              <div class="as-settlement-section-title"><h2>{{ cancellationRequested ? '撤销结算' : '修改说明' }}</h2><button v-if="cancellationRequested" type="button" class="as-button as-button--secondary" :disabled="!editable" @click="cancellationRequested = false">取消撤销</button><span v-else>原记录及变化金额保留</span></div>
              <label class="as-field as-settlement-reason-field"><span>{{ cancellationRequested ? '撤销原因' : '更正原因' }}</span><textarea ref="reasonInput" v-model="correctionReason" rows="3" :disabled="!editable" maxlength="2000" :placeholder="cancellationRequested ? '填写撤销原因' : '说明本次修改的原因'"></textarea></label>
              <p class="as-settlement-help">{{ cancellationRequested ? '请将累计已收、已开票金额调整为 0 后确认撤销，历史留痕保留。' : '减少金额、修改已有票据或调整已结清信息时需填写原因，保存后保留修改留痕。' }}</p>
            </section>
          </div>
          <div id="settlement-history-panel" v-show="detailTab === 'history'" class="as-settlement-detail-body" role="tabpanel" aria-labelledby="settlement-history-tab" tabindex="0">
            <div v-if="historyRecords.length || historyPages > 1" class="as-settlement-record-picker" aria-label="选择结算留痕记录">
              <span>结算记录</span>
              <div class="as-settlement-history-list">
                <button type="button" class="as-button as-button--secondary" :aria-pressed="!historyRecord" @click="historyRecord = null">当前结算</button>
                <button v-for="record in historyRecords" :key="record.id" type="button" class="as-button as-button--secondary" :aria-pressed="historyRecord?.id === record.id" @click="openHistory(record)">{{ record.code }} · 已撤销</button>
                <button v-if="historyPage > 1" type="button" class="as-button as-button--secondary" @click="historyPage--; loadHistory()">上一页</button>
                <button v-if="historyPage < historyPages" type="button" class="as-button as-button--secondary" @click="historyPage++; loadHistory()">下一页</button>
              </div>
            </div>
            <SettlementLedger :key="historyRecord?.id || selectedRecord?.id || 'new'" :record="historyRecord || selectedRecord" :people="employees" :archived="!!historyRecord" />
          </div>
        </template>
      </section>
      <template #footer><div class="as-settlement-detail-footer">
        <p v-if="detailError" role="alert">{{ detailError }} <button v-if="detailFailed" type="button" class="as-button" @click="openSource(selectedSource)">重试详情</button></p>
        <div v-if="conflictRecord" class="as-settlement-conflict" role="region" aria-label="结算版本核对"><p>记录已更新，请核对后继续。本次登记按累计目标合并，不会重复增加金额；直接修改的累计值会保留，低于最新余额时需填写原因。未改动的字段采用最新记录。</p><table><thead><tr><th>字段</th><th>本次累计目标 / 填写</th><th>服务器最新</th></tr></thead><tbody><tr v-for="item in conflictDifferences" :key="item.field"><td>{{ payloadLabels[item.field] }}</td><td>{{ item.mine ?? '—' }}</td><td>{{ item.latest ?? '—' }}</td></tr></tbody></table><div class="as-settlement-action-row"><button type="button" class="as-button" @click="reconcileConflict(false)">以最新记录重新填写</button><button type="button" class="as-button as-button--secondary" @click="reconcileConflict(true)">已核对，保留本次修改</button></div></div>
        <div v-else-if="selectedSource && !detailLoading && detailTab === 'details'" class="as-settlement-action-row">
          <template v-if="selectedRecord?.status !== 'cancelled'">
            <button v-if="selectedRecord && !cancellationRequested" type="button" class="as-button as-button--danger" :disabled="!editable" @click="requestCancel">撤销记录</button>
            <button type="button" class="as-button" :class="cancellationRequested ? 'as-button--danger' : 'as-button--primary'" :disabled="!editable || customerQuoteMissing" @click="save()"><LoaderCircle v-if="saving" class="as-spin" /><Check v-else />{{ cancellationRequested ? '确认撤销' : selectedRecord ? '保存修改' : '保存待结算' }}</button>
            <button v-if="!cancellationRequested && selectedRecord?.status !== 'settled'" type="button" class="as-button as-button--primary" :disabled="!editable || customerQuoteMissing || receiptShortfall > 0" @click="save('settled')">确认结清</button>
          </template>
        </div>
        <div v-else-if="selectedSource && !detailLoading" class="as-settlement-history-footer"><span v-if="dirty">结算详情中有未保存的修改</span><button type="button" class="as-button as-button--secondary" @click="changeDetailTab('details', true)">返回结算详情</button></div>
      </div></template>
    </ProjectDetailDrawer>

    <ElDialog v-model="personOpen" title="选择承担人员" width="min(760px, calc(100vw - 32px))" :z-index="3200" append-to-body destroy-on-close @opened="personInput?.focus()">
      <p class="as-settlement-help">先选择钉钉人员，再选择与其关联的项目。</p>
      <label class="as-search"><Search /><input ref="personInput" v-model="personKeyword" type="search" aria-label="搜索承担人员" placeholder="姓名、部门、拼音或用户 ID"></label>
      <p v-if="directoryLoading" role="status">正在加载通讯录...</p><p v-if="directoryError" role="alert">{{ directoryError }} <button type="button" class="as-button" @click="loadDirectories">重试</button></p>
      <div class="as-member-picker"><button v-for="person in filteredEmployees" :key="person.userId" type="button" @click="choosePerson(person)"><span class="as-avatar">{{ person.name.slice(0, 1) }}</span><span><strong>{{ person.name }}</strong><small>{{ (person.departments || []).map(item => item.name).join('、') || '未设置部门' }} · {{ person.userId }}</small></span><Check v-if="form.subjectId === person.userId" /></button><p v-if="!directoryLoading && !filteredEmployees.length" class="as-empty">没有匹配的人员</p></div>
    </ElDialog>
    <UnsavedChangesDialog :open="discardOpen" :layer="3300" @cancel="discardOpen = false; pendingDiscard = null" @confirm="confirmDiscard" />
  </div>
</template>

<style scoped>
.as-settlement-page { max-width: 1680px; }
.as-settlement-layout { display: block; width: 100%; min-width: 0; }
.as-settlement-list-card { display: flex; min-height: calc(100vh - 165px); flex-direction: column; overflow: hidden; }
.as-settlement-list-card .as-panel-head { border-bottom: 1px solid var(--as-border); }
.as-settlement-tabs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; border-bottom: 1px solid var(--as-border); background: #fff; padding: 12px 14px; }
.as-settlement-tabs button { display: inline-flex; min-height: 38px; align-items: center; justify-content: center; gap: 6px; border: 1px solid #d7e2ec; border-radius: 7px; background: #f6f9fc; color: #526273; font-size: 11px; font-weight: 800; }
.as-settlement-tabs button.active { border-color: var(--as-primary); background: #eaf3ff; color: var(--as-primary); box-shadow: inset 0 0 0 1px rgb(21 94 239 / 12%); }
.as-settlement-tabs button span { min-width: 20px; border-radius: 999px; background: #fff; padding: 2px 6px; color: inherit; font-size: 9px; }
.as-settlement-filter-row { display: grid; grid-template-columns: 118px minmax(0, 1fr); gap: 9px; border-bottom: 1px solid var(--as-border); background: #fbfdff; padding: 12px; }
.as-settlement-table-scroll { min-height: 0; flex: 1; overflow: auto; }
.as-settlement-table { width: 100%; min-width: 1180px; border-collapse: separate; border-spacing: 0; table-layout: fixed; text-align: center; }
.as-settlement-table th { position: sticky; top: 0; z-index: 2; height: 42px; border-right: 1px solid #e4ecf4; border-bottom: 1px solid #cfdeec; background: #f1f6fb; padding: 0 12px; color: #3f5874; font-size: 11px; font-weight: 800; }
.as-settlement-table th:first-child { width: 20%; }
.as-settlement-table th:nth-child(2) { width: 13%; }
.as-settlement-table th:nth-child(3), .as-settlement-table th:nth-child(4) { width: 9%; }
.as-settlement-table th:nth-child(5) { width: 13%; }
.as-settlement-table th:nth-child(6), .as-settlement-table th:nth-child(7) { width: 9%; }
.as-settlement-table th:nth-child(8), .as-settlement-table th:nth-child(9) { width: 9%; }
.as-settlement-table th:nth-child(9) { border-right: 0; }
.as-settlement-table-filter-row th { top: 42px; height: 44px; padding: 6px 8px; background: #fff; }
.as-settlement-table-filter-row .as-search input { height: 28px; padding-left: 29px; font-size: 11px; }
.as-settlement-table td { height: 62px; border-right: 1px solid #e8eef5; border-bottom: 1px solid #e8eef5; padding: 9px 12px; color: #334155; font-size: 11px; text-align: center; vertical-align: middle; }
.as-settlement-table-filter-row :is(input, .el-select__selected-item) { text-align: left; }
.as-settlement-table td:last-child { border-right: 0; }
.as-settlement-table tbody tr { cursor: pointer; background: #fff; }
.as-settlement-table tbody tr:nth-child(even) { background: #fbfdff; }
.as-settlement-table tbody tr:hover, .as-settlement-table tbody tr.active { background: #eef6ff; }
.as-settlement-table td strong, .as-settlement-table td small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.as-settlement-table td strong { color: #155eef; font-size: 12px; }
.as-settlement-table td small { margin-top: 3px; color: #7b8da3; font-size: 9px; }
.as-settlement-table-empty { height: 180px !important; color: #94a3b8 !important; text-align: center; cursor: default; }
.as-settlement-type { display: inline-flex; min-height: 23px; align-items: center; border: 1px solid #cfe0f5; border-radius: 5px; background: #f4f8fd; padding: 0 7px; color: #315a88; font-size: 10px; font-weight: 700; }
.as-settlement-bearer { display: inline-flex; min-height: 23px; align-items: center; border: 1px solid #dbe5ef; border-radius: 5px; background: #f8fafc; padding: 0 7px; color: #526273; font-size: 10px; font-weight: 700; white-space: nowrap; }
.as-settlement-source-list { min-height: 0; flex: 1; overflow-y: auto; align-content: start; padding-right: 4px; }
.as-settlement-source-row { display: grid; width: 100%; min-width: 0; grid-template-columns: minmax(0, 1fr) 15px; gap: 7px 9px; border: 0; border-bottom: 1px solid #edf0f2; background: #fff; padding: 11px 12px; color: #344054; text-align: left; }
.as-settlement-source-row:hover { background: #f8fbff; }
.as-settlement-source-row.active { background: #edf4ff; box-shadow: inset 3px 0 0 var(--as-primary); }
.as-settlement-source-row > svg { grid-column: 2; grid-row: 1 / span 3; align-self: center; width: 15px; height: 15px; color: #98a2b3; }
.as-settlement-source-row__head { display: flex; min-width: 0; align-items: flex-start; justify-content: space-between; gap: 8px; }
.as-settlement-source-row__head strong { min-width: 0; overflow: hidden; color: #243145; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.as-settlement-source-row__head .as-status { min-height: 20px; padding: 0 6px; font-size: 9px; }
.as-settlement-source-row__meta { min-width: 0; overflow: hidden; color: #7c8797; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.as-settlement-source-row__chips { display: flex; min-width: 0; flex-wrap: wrap; gap: 5px; }
.as-settlement-source-row__chips em { overflow: hidden; max-width: 100%; border-radius: 999px; background: #f1f5f8; padding: 3px 7px; color: #526273; font-size: 9px; font-style: normal; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.as-settlement-detail-card { min-width: 0; min-height: 100%; overflow: auto; border: 0; border-radius: 0; padding: 0; box-shadow: none; }
.as-settlement-detail-head { min-height: 88px; align-items: center; padding: 14px 16px; }
.as-settlement-detail-head > div:first-child { display: flex; min-width: 0; align-items: center; gap: 10px; }
.as-settlement-detail-head > div:first-child > div { min-width: 0; }
.as-settlement-avatar { display: flex; width: 36px; height: 36px; flex: 0 0 auto; align-items: center; justify-content: center; border-radius: 7px; background: #e8f1ff; color: var(--as-primary); font-size: 15px; font-weight: 850; }
.as-settlement-detail-head h2 { overflow: hidden; margin: 3px 0 0; color: #182230; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }
.as-settlement-detail-head p { overflow: hidden; margin: 3px 0 0; color: var(--as-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.as-settlement-detail-body { display: grid; min-height: 0; flex: 1; align-content: start; gap: 12px; overflow-y: auto; padding: 14px 16px 16px; }
.as-settlement-form-panel, .as-settlement-conditional-panel { border: 1px solid var(--as-border); border-radius: 8px; background: #fff; padding: 14px; }
.as-settlement-section-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
.as-settlement-section-title h2 { margin: 0; font-size: 15px; line-height: 20px; }
.as-settlement-section-title span { color: var(--as-muted); font-size: 10px; font-weight: 800; }
.as-settlement-form-grid { display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 12px; }
.as-settlement-form-grid .as-field--wide { grid-column: 1 / -1; }
.as-settlement-customer-money-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.as-settlement-inline-fields, .as-settlement-company-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 11px; }
.as-settlement-company-grid .as-field--wide { grid-column: 1 / -1; }
.as-settlement-action-row { display: flex; justify-content: flex-end; gap: 8px; }
.as-settlement-detail-card { overflow: visible; background: #f4f7fb; padding: 14px 16px 18px; }
.as-settlement-detail-head { flex: 0 0 auto; min-height: 104px; margin-bottom: 12px; border: 1px solid #dbe5ef; border-radius: 8px; background: #fff; padding: 16px 18px; }
.as-settlement-detail-head h2 { font-size: 19px; line-height: 25px; }
.as-settlement-detail-head p { font-size: 11px; line-height: 18px; }
.as-settlement-avatar { width: 42px; height: 42px; border-radius: 8px; font-size: 17px; }
.as-settlement-detail-body { display: grid; grid-template-columns: minmax(0, 1fr); align-items: start; gap: 12px; overflow: visible; padding: 0; }
.as-settlement-form-panel, .as-settlement-conditional-panel { overflow: hidden; padding: 0; border-color: #dbe5ef; background: #fff; }
.as-settlement-section-title { min-height: 58px; margin: 0; border-bottom: 1px solid #dbe5ef; background: #fbfdff; padding: 10px 14px; }
.as-settlement-section-title h2 { color: #172033; font-size: 14px; }
.as-settlement-form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; padding: 14px; }
.as-settlement-readonly-field { display: grid; min-width: 0; align-content: start; gap: 6px; }
.as-settlement-readonly-field > small { color: #8490a2; font-size: 9px; line-height: 14px; }
.as-settlement-help { margin: 0; padding: 0 14px; color: #667085; font-size: 10px; line-height: 1.6; }
.as-settlement-reason-field { padding: var(--as-section-gap, 16px); }
.as-settlement-receipt-warning { margin: 0; border-top: 1px solid #f1d7a5; background: #fff9eb; padding: 8px 14px; color: #9a6700; font-size: 10px; font-weight: 750; }
.as-settlement-readonly-field > strong { display: flex; min-width: 0; min-height: 40px; align-items: center; overflow: hidden; border: 1px solid #dbe3ec; border-radius: 6px; background: #f7f9fc; padding: 9px 11px; color: #344054; font-size: 11px; font-weight: 650; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.as-settlement-readonly-field--copy > strong { min-height: 74px; align-items: flex-start; overflow: visible; white-space: pre-wrap; }
.as-settlement-config-grid { display: grid; grid-template-columns: minmax(180px, 320px); padding: 14px; }
.as-settlement-customer-money-grid { gap: 10px; padding: 14px 14px 0; }
.as-settlement-inline-fields { margin-top: 0; padding: 10px 14px 14px; }
.as-settlement-company-grid { margin-top: 0; padding: 14px; }
.as-settlement-action-row { grid-column: 1; border: 1px solid #dbe5ef; border-radius: 8px; background: #fff; padding: 12px 14px; }
@media (max-width: 1180px) {
  .as-settlement-layout { grid-template-columns: minmax(0, 1fr); }
  .as-settlement-list-card, .as-settlement-detail-card { min-height: auto; max-height: none; }
  .as-settlement-detail-card { min-height: 600px; }
}
@media (max-width: 720px) {
  .as-settlement-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .as-settlement-filter-row, .as-settlement-form-grid { grid-template-columns: minmax(0, 1fr); }
  .as-settlement-form-grid .as-field--wide { grid-column: auto; }
  .as-settlement-customer-money-grid, .as-settlement-inline-fields, .as-settlement-company-grid { grid-template-columns: minmax(0, 1fr); }
  .as-settlement-company-grid .as-field--wide { grid-column: auto; }
}

.as-settlement-pagination { display:flex; align-items:center; justify-content:flex-end; gap:12px; padding:12px 16px; border-top:1px solid var(--as-border); background:#fff; color:var(--as-muted); font-size:13px; }
@media (min-width: 768px) {
  .as-settlement-pagination { display: none; }
}
@media (max-width: 767px) {
  .as-settlement-desktop-pagination { display: none; }
}
.as-settlement-detail-card .as-project-sticky-tabs { margin-bottom: 0; }
.as-settlement-detail-body:focus-visible { outline: 2px solid var(--as-primary); outline-offset: 2px; }
.as-settlement-record-picker { display: grid; min-width: 0; gap: var(--as-group-gap); border-bottom: 1px solid var(--as-border); padding-bottom: var(--as-group-gap); }
.as-settlement-record-picker > span { color: var(--as-muted); font-size: 12px; }
.as-settlement-record-picker button[aria-pressed=true] { border-color: var(--as-primary); background: var(--as-soft); color: var(--as-primary); }
.as-settlement-history-footer { display: flex; align-items: center; justify-content: flex-end; gap: var(--as-group-gap); color: var(--as-muted); font-size: 13px; }
.as-settlement-detail-footer {
  --settlement-footer-inset: var(--as-section-gap, 16px);
  display: grid;
  min-height: calc(var(--as-control-height, 36px) + var(--settlement-footer-inset) * 2);
  align-content: center;
  gap: var(--as-group-gap, 12px);
  padding: var(--settlement-footer-inset);
}
.as-settlement-detail-footer .as-settlement-action-row { align-items:center; margin:0; border:0; padding:0; flex-wrap:wrap; }
.as-settlement-detail-footer > [role=alert] { margin:0; }
.as-settlement-detail-footer [role=alert] { color:#b45309; font-size:13px; }
.as-settlement-conflict { border:1px solid var(--as-border); padding:12px; background:var(--as-surface,#fff); }
.as-settlement-conflict table { width:100%; font-size:12px; }
.as-settlement-history-list { display:flex; gap:8px; flex-wrap:wrap; }
.as-settlement-history-label { color:var(--as-muted); font-size:12px; }
.as-settlement-inline-button { display:flex; align-items:end; gap:8px; }
.as-settlement-conditional-panel > .as-field { margin:14px; }
@media (min-width: 721px) {
  .as-settlement-list-card { height:calc(100dvh - var(--platform-shell-top-inset, 0px) - 36px); min-height:0; }
  .as-settlement-list-card > .as-panel-head, .as-settlement-pagination { flex-shrink:0; }
}
</style>
