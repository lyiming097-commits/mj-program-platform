<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import {
  Check,
  CircleAlert,
  Headphones,
  LoaderCircle,
  MessageSquareText,
  Search,
  Send,
  X,
} from "@lucide/vue";
import AttachmentPanel from "@/components/AttachmentPanel.vue";
import GlobalNotice from "@/components/GlobalNotice.vue";
import ListPagination from "@/components/ListPagination.vue";
import { useLocalPagination } from "@/composables/useLocalPagination";
import ProjectDetailDrawer from "@/components/ProjectDetailDrawer.vue";
import { collectionRows, allCollectionRows, serviceApi } from "@/serviceApi";
import { matchesSearch } from "@/productSearch";
import { ElOption, ElSelect } from "element-plus/es/components/select/index.mjs";
import "element-plus/es/components/select/style/css";

const props = defineProps({
  focusTicketId: { type: [String, Number], default: "" },
  session: { type: Object, default: null },
});
const canReviewFeedback = computed(() => Boolean(props.session?.canManageBusiness || props.session?.canManageSettings));

const activeView = ref("tickets");
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const success = ref("");
const tickets = ref([]);
const feedback = ref([]);
const employees = ref([]);
const ticketSearch = ref("");
const feedbackSearch = ref("");
const ticketFilters = reactive({ project: "", node: "", reporter: "", owner: "" });
const feedbackFilters = reactive({ project: "", node: "", type: "", provider: "" });
const ticketStatus = ref("all");
const feedbackStatus = ref("all");
const selectedTicketId = ref("");
const selectedFeedbackId = ref("");
const ticketDetail = ref(null);
const ticketMessage = ref("");
const feedbackReviewNote = ref("");
const rewardPrizes = ref([]);
const feedbackPrizeId = ref("");
const prizeLoadError = ref("");
const canGrantReward = computed(() => Boolean(props.session?.canManageService || props.session?.canManageSettings));
async function loadRewardPrizes() {
  prizeLoadError.value = "";
  try { rewardPrizes.value = collectionRows(await serviceApi.rewardPrizeOptions()); }
  catch (reason) { prizeLoadError.value = reason instanceof Error ? reason.message : "奖品加载失败"; }
}
watch(selectedFeedbackId, () => {
  feedbackPrizeId.value = "";
  if (selectedFeedbackId.value && canGrantReward.value) void loadRewardPrizes();
});
const assignmentForm = reactive({ ownerUserId: "" });

const ticketStatusOptions = [
  ["all", "全部状态"],
  ["open", "待分配"],
  ["assigned", "已指派"],
  ["in_progress", "正在执行"],
  ["pending_review", "待审核"],
  ["completed", "已完成"],
  ["rejected", "已驳回"],
];
const feedbackStatusOptions = [
  ["all", "全部状态"],
  ["submitted", "待审核"],
  ["under_review", "审核中"],
  ["accepted", "已采纳"],
  ["rejected", "未采纳"],
];

const filteredTickets = computed(() => {
  return tickets.value.filter((ticket) => {
    if (ticketStatus.value !== "all" && ticket.status !== ticketStatus.value) return false;
    return matchesSearch(ticketSearch.value, ticket.code, ticket.title)
      && matchesSearch(ticketFilters.project, ticket.projectCode, ticket.projectName)
      && matchesSearch(ticketFilters.node, nodeName(ticket))
      && matchesSearch(ticketFilters.reporter, ticket.reporterName)
      && matchesSearch(ticketFilters.owner, ticket.ownerName);
  });
});
const filteredFeedback = computed(() => {
  return feedback.value.filter((item) => {
    if (feedbackStatus.value !== "all" && item.status !== feedbackStatus.value) return false;
    return matchesSearch(feedbackSearch.value, item.title || "现场反馈")
      && matchesSearch(feedbackFilters.project, item.projectCode, item.projectName)
      && matchesSearch(feedbackFilters.node, nodeName(item))
      && matchesSearch(feedbackFilters.type, item.feedbackTypeLabel || item.feedbackType)
      && matchesSearch(feedbackFilters.provider, item.providerName);
  });
});
const ticketPagination = useLocalPagination(filteredTickets);
const feedbackPagination = useLocalPagination(filteredFeedback);
const selectedTicket = computed(() => ticketDetail.value
  || tickets.value.find((item) => String(item.id) === String(selectedTicketId.value))
  || null);
const selectedFeedback = computed(() => feedback.value.find((item) => (
  String(item.id) === String(selectedFeedbackId.value)
)) || null);
const selectedEmployee = computed(() => employees.value.find((employee) => (
  String(employee.userId) === String(assignmentForm.ownerUserId)
)) || null);
function dateTime(value) {
  return value ? String(value).replace("T", " ").slice(0, 16) : "-";
}

function nodeName(item) {
  return item?.nodeName || item?.nodeKey || "-";
}

function showSuccess(message) {
  success.value = message;
}

function ticketStatusClass(ticket) {
  if (ticket?.status === "completed") return "is-done";
  if (ticket?.status === "rejected") return "is-danger";
  return "";
}

function feedbackStatusClass(item) {
  if (item?.status === "accepted") return "is-done";
  if (item?.status === "rejected") return "is-danger";
  return "";
}

function ticketActions(ticket) {
  if (!ticket?.permissions?.canProcess) return [];
  const actions = {
    open: [["in_progress", "开始处理"]],
    assigned: [["in_progress", "开始处理"], ["rejected", "驳回工单"]],
    in_progress: [["completed", "完成工单"], ["rejected", "驳回工单"]],
    pending_review: [["completed", "审核完成"], ["in_progress", "退回处理"], ["rejected", "驳回工单"]],
    rejected: [["in_progress", "重新处理"]],
  };
  return actions[ticket?.status] || [];
}

async function loadTicketDetail(id = selectedTicketId.value) {
  if (!id) {
    ticketDetail.value = null;
    return;
  }
  try {
    const response = await serviceApi.getTicket(id);
    ticketDetail.value = response?.item || response;
    assignmentForm.ownerUserId = ticketDetail.value?.ownerUserId || "";
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "工单详情加载失败";
  }
}

async function loadTickets({ preserveSelection = true } = {}) {
  const rows = await allCollectionRows(serviceApi.listTickets);
  tickets.value = rows;
  const selectedId = preserveSelection && rows.some((item) => String(item.id) === String(selectedTicketId.value))
    ? selectedTicketId.value
    : "";
  selectedTicketId.value = selectedId;
  await loadTicketDetail(selectedId);
}

async function loadFeedback({ preserveSelection = true } = {}) {
  const rows = await allCollectionRows(serviceApi.listFeedback);
  feedback.value = rows;
  const selectedId = preserveSelection && rows.some((item) => String(item.id) === String(selectedFeedbackId.value))
    ? selectedFeedbackId.value
    : "";
  selectedFeedbackId.value = selectedId;
  feedbackReviewNote.value = selectedFeedback.value?.reviewNote || "";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    await Promise.all([loadTickets(), loadFeedback()]);
    try {
      employees.value = collectionRows(await serviceApi.employeeDirectory());
    } catch {
      employees.value = [];
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "工单与反馈加载失败";
  } finally {
    loading.value = false;
  }
}

async function chooseTicket(ticket) {
  selectedTicketId.value = ticket.id;
  ticketDetail.value = null;
  ticketMessage.value = "";
  assignmentForm.ownerUserId = ticket.ownerUserId || "";
  await loadTicketDetail(ticket.id);
}

function chooseFeedback(item) {
  selectedFeedbackId.value = item.id;
  feedbackReviewNote.value = item.reviewNote || "";
}

function closeTicketDetail() {
  selectedTicketId.value = "";
  ticketDetail.value = null;
  ticketMessage.value = "";
  assignmentForm.ownerUserId = "";
}

function closeFeedbackDetail() {
  selectedFeedbackId.value = "";
  feedbackReviewNote.value = "";
}

async function openFocusedTicket() {
  const ticketId = String(props.focusTicketId || "").trim();
  if (!ticketId) return;
  const ticket = tickets.value.find((item) => String(item.id) === ticketId);
  if (ticket) {
    activeView.value = "tickets";
    await chooseTicket(ticket);
  }
}

async function assignTicket() {
  const ticket = selectedTicket.value;
  const employee = selectedEmployee.value;
  if (!ticket || !employee) return;
  const previousOwnerUserId = ticket.ownerUserId || "";
  saving.value = true;
  error.value = "";
  try {
    await serviceApi.updateTicket(ticket.id, {
      projectId: ticket.projectId,
      nodeKey: ticket.nodeKey,
      title: ticket.title,
      ticketType: ticket.ticketType,
      priority: ticket.priority,
      ownerUserId: employee.userId,
      ownerName: employee.name,
      description: ticket.description,
      businessData: ticket.businessData || {},
    });
    if (ticket.status === "open") {
      await serviceApi.ticketAction(ticket.id, "assigned", { note: `分派给${employee.name}` });
    }
    await loadTickets();
    showSuccess("工单已分派");
  } catch (reason) {
    assignmentForm.ownerUserId = previousOwnerUserId;
    error.value = reason instanceof Error ? reason.message : "工单分派失败";
  } finally {
    saving.value = false;
  }
}

async function transitionTicket(status, label) {
  const ticket = selectedTicket.value;
  if (!ticket) return;
  const note = ticketMessage.value.trim();
  if (["completed", "rejected"].includes(status) && !note) {
    error.value = `${label}前请填写处理说明`;
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await serviceApi.ticketAction(ticket.id, status, { note });
    ticketMessage.value = "";
    await loadTickets();
    showSuccess(`工单已更新为${label}`);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "工单状态更新失败";
  } finally {
    saving.value = false;
  }
}

async function addTicketRecord() {
  const ticket = selectedTicket.value;
  const content = ticketMessage.value.trim();
  if (!ticket || !content) return;
  saving.value = true;
  error.value = "";
  try {
    await serviceApi.addTicketMessage(ticket.id, content);
    ticketMessage.value = "";
    await loadTicketDetail(ticket.id);
    showSuccess("处理记录已添加");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "处理记录保存失败";
  } finally {
    saving.value = false;
  }
}

async function reviewFeedback(status) {
  const item = selectedFeedback.value;
  if (!item) return;
  const note = feedbackReviewNote.value.trim();
  if (status === "rejected" && !note) {
    error.value = "未采纳时请填写审核意见";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await serviceApi.updateFeedback(item.id, {
      status, reviewNote: note,
      ...(status === "accepted" && canGrantReward.value && feedbackPrizeId.value
        ? { reward: { rewardType: "prize", prizeId: feedbackPrizeId.value } } : {}),
    });
    await loadFeedback();
    showSuccess(status === "accepted" ? "反馈已采纳" : "反馈未采纳");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "反馈审核失败";
  } finally {
    saving.value = false;
  }
}

watch(() => props.focusTicketId, () => { void openFocusedTicket(); });
onMounted(async () => {
  await load();
  await openFocusedTicket();
});
</script>

<template>
  <section class="as-page as-collaboration-panel">
    <GlobalNotice v-model:error="error" v-model:success="success" />
    <div class="as-collaboration-tabs as-mall-tabbar" role="tablist" aria-label="工单与反馈类型">
      <button type="button" role="tab" :aria-selected="activeView === 'tickets'" :class="{ active: activeView === 'tickets' }" @click="activeView = 'tickets'"><Headphones />工单<span>{{ tickets.length }}</span></button>
      <button type="button" role="tab" :aria-selected="activeView === 'feedback'" :class="{ active: activeView === 'feedback' }" @click="activeView = 'feedback'"><MessageSquareText />反馈<span>{{ feedback.length }}</span></button>
    </div>
    <header class="as-collaboration-head">
      <div><p class="as-eyebrow">现场协同</p><h3>{{ activeView === 'tickets' ? '工单' : '反馈' }}</h3><span>{{ activeView === 'tickets' ? '集中查看现场提交的服务工单、分派处理人和处理记录。' : '集中查看现场反馈、审核意见和后续处理结果。' }}</span></div>
    </header>

    <div v-if="loading" class="as-empty as-empty--large"><LoaderCircle class="as-spin" /> 正在加载现场协同记录...</div>

    <template v-else-if="activeView === 'tickets'">
      <div class="as-collaboration-table-wrap"><table class="as-collaboration-table" aria-label="工单列表"><thead>
        <tr><th>工单</th><th>所属项目</th><th>节点</th><th>优先级</th><th>提交人</th><th>处理人</th><th>状态</th></tr>
        <tr class="as-collaboration-table-filter-row">
          <th><label class="as-search"><Search /><input v-model="ticketSearch" type="search" aria-label="搜索工单" placeholder="搜索工单标题或编号"></label></th>
          <th><label class="as-search"><Search /><input v-model="ticketFilters.project" type="search" aria-label="搜索工单所属项目" placeholder="搜索所属项目"></label></th>
          <th><label class="as-search"><Search /><input v-model="ticketFilters.node" type="search" aria-label="搜索工单节点" placeholder="搜索节点"></label></th><th></th>
          <th><label class="as-search"><Search /><input v-model="ticketFilters.reporter" type="search" aria-label="搜索工单提交人" placeholder="搜索提交人"></label></th>
          <th><label class="as-search"><Search /><input v-model="ticketFilters.owner" type="search" aria-label="搜索工单处理人" placeholder="搜索处理人"></label></th>
          <th><ElSelect v-model="ticketStatus" class="as-table-select" popper-class="as-table-select-popper" placeholder="全部状态" aria-label="工单状态筛选"><ElOption v-for="option in ticketStatusOptions" :key="option[0]" :label="option[1]" :value="option[0]" /></ElSelect></th>
        </tr>
      </thead><tbody><tr v-if="!filteredTickets.length"><td colspan="7" class="as-collaboration-empty">没有符合条件的工单</td></tr><tr v-for="ticket in ticketPagination.rows" v-else :key="ticket.id" tabindex="0" :class="{ active: String(ticket.id) === String(selectedTicketId) }" @click="chooseTicket(ticket)" @keydown.enter="chooseTicket(ticket)"><td><strong>{{ ticket.title }}</strong><small>{{ ticket.code }}</small></td><td><strong>{{ ticket.projectName || '-' }}</strong><small>{{ ticket.projectCode || '-' }}</small></td><td>{{ nodeName(ticket) }}</td><td>{{ ticket.priorityLabel || ticket.priority }}</td><td>{{ ticket.reporterName || '-' }}</td><td>{{ ticket.ownerName || '待分配' }}</td><td><span class="as-status" :class="ticketStatusClass(ticket)">{{ ticket.statusLabel || ticket.status }}</span></td></tr></tbody></table></div>
      <ListPagination v-model:page-size="ticketPagination.pageSize" :page="ticketPagination.page" :total="ticketPagination.total" :total-pages="ticketPagination.totalPages" :loading="loading" label="工单分页" @change="ticketPagination.page = $event" />
    </template>

    <template v-else>
      <div class="as-collaboration-table-wrap"><table class="as-collaboration-table" aria-label="反馈列表"><thead>
        <tr><th>反馈</th><th>所属项目</th><th>节点</th><th>类型</th><th>提交人</th><th>状态</th></tr>
        <tr class="as-collaboration-table-filter-row">
          <th><label class="as-search"><Search /><input v-model="feedbackSearch" type="search" aria-label="搜索反馈" placeholder="搜索反馈标题"></label></th>
          <th><label class="as-search"><Search /><input v-model="feedbackFilters.project" type="search" aria-label="搜索反馈所属项目" placeholder="搜索所属项目"></label></th>
          <th><label class="as-search"><Search /><input v-model="feedbackFilters.node" type="search" aria-label="搜索反馈节点" placeholder="搜索节点"></label></th>
          <th><label class="as-search"><Search /><input v-model="feedbackFilters.type" type="search" aria-label="搜索反馈类型" placeholder="搜索反馈类型"></label></th>
          <th><label class="as-search"><Search /><input v-model="feedbackFilters.provider" type="search" aria-label="搜索反馈提交人" placeholder="搜索提交人"></label></th>
          <th><ElSelect v-model="feedbackStatus" class="as-table-select" popper-class="as-table-select-popper" placeholder="全部状态" aria-label="反馈状态筛选"><ElOption v-for="option in feedbackStatusOptions" :key="option[0]" :label="option[1]" :value="option[0]" /></ElSelect></th>
        </tr>
      </thead><tbody><tr v-if="!filteredFeedback.length"><td colspan="6" class="as-collaboration-empty">没有符合条件的反馈</td></tr><tr v-for="item in feedbackPagination.rows" v-else :key="item.id" tabindex="0" :class="{ active: String(item.id) === String(selectedFeedbackId) }" @click="chooseFeedback(item)" @keydown.enter="chooseFeedback(item)"><td><strong>{{ item.title || '现场反馈' }}</strong><small>{{ dateTime(item.createdAt) }}</small></td><td><strong>{{ item.projectName || '-' }}</strong><small>{{ item.projectCode || '-' }}</small></td><td>{{ nodeName(item) }}</td><td>{{ item.feedbackTypeLabel || item.feedbackType }}</td><td>{{ item.providerName || '-' }}</td><td><span class="as-status" :class="feedbackStatusClass(item)">{{ item.statusLabel || item.status }}</span></td></tr></tbody></table></div>
      <ListPagination v-model:page-size="feedbackPagination.pageSize" :page="feedbackPagination.page" :total="feedbackPagination.total" :total-pages="feedbackPagination.totalPages" :loading="loading" label="反馈分页" @change="feedbackPagination.page = $event" />
    </template>

    <ProjectDetailDrawer
      :open="Boolean(selectedTicket)"
      :title="selectedTicket ? '工单详情 · ' + selectedTicket.code : '工单详情'"
      size="58%"
      @close="closeTicketDetail"
    >
      <section v-if="selectedTicket" class="as-panel as-collaboration-detail as-collaboration-detail--drawer">
        <header><div><p class="as-eyebrow">工单详情</p><h4>{{ selectedTicket.title }}</h4><span>{{ selectedTicket.code }} · {{ selectedTicket.ticketType }} · {{ dateTime(selectedTicket.updatedAt) }}</span></div><span class="as-status" :class="ticketStatusClass(selectedTicket)">{{ selectedTicket.statusLabel || selectedTicket.status }}</span></header>
        <div class="as-collaboration-facts">
          <div><span>所属项目</span><strong>{{ selectedTicket.projectName || '-' }}</strong></div>
          <div><span>关联节点</span><strong>{{ nodeName(selectedTicket) }}</strong></div>
          <div><span>提交人</span><strong>{{ selectedTicket.reporterName || '-' }}</strong></div>
          <div>
            <span>处理人</span>
            <ElSelect v-if="selectedTicket.status !== 'completed' && selectedTicket.permissions?.canManage" v-model="assignmentForm.ownerUserId" class="as-searchable-select" popper-class="as-searchable-select-popper" filterable :disabled="saving" placeholder="选择处理人" no-data-text="未找到匹配的人员" aria-label="分派处理人" @change="assignTicket">
              <ElOption v-if="selectedTicket.ownerUserId && !employees.some(employee => String(employee.userId) === String(selectedTicket.ownerUserId))" :label="selectedTicket.ownerName || '原处理人'" :value="selectedTicket.ownerUserId" disabled />
              <ElOption v-for="employee in employees" :key="employee.userId" :label="`${employee.name} · ${employee.departmentName || employee.department || '未分组'}`" :value="employee.userId" />
            </ElSelect>
            <strong v-else>{{ selectedTicket.ownerName || '待分配' }}</strong>
          </div>
        </div>
        <div class="as-collaboration-copy"><strong>问题描述</strong><p>{{ selectedTicket.description }}</p></div>
        <div v-if="selectedTicket.resolution" class="as-collaboration-copy"><strong>处理结果</strong><p>{{ selectedTicket.resolution }}</p></div>
        <AttachmentPanel target-type="ticket" :target-id="selectedTicket.id" title="工单附件" :editable="false" compact @error="error = $event" />
        <label v-if="selectedTicket.status !== 'completed' && selectedTicket.permissions?.canMessage" class="as-collaboration-note"><span>处理说明 / 记录</span><textarea v-model="ticketMessage" rows="3" placeholder="填写处理进展、完成结果或驳回原因"></textarea></label>
        <div v-if="selectedTicket.status !== 'completed' && selectedTicket.permissions?.canMessage" class="as-collaboration-actions"><button type="button" class="as-button as-button--secondary" :disabled="saving || !ticketMessage.trim()" @click="addTicketRecord"><Send />添加处理记录</button><button v-for="action in ticketActions(selectedTicket)" :key="action[0]" type="button" class="as-button" :class="action[0] === 'rejected' ? 'as-button--danger' : 'as-button--primary'" :disabled="saving" @click="transitionTicket(action[0], action[1])"><LoaderCircle v-if="saving" class="as-spin" /><Check v-else />{{ action[1] }}</button></div>
        <div class="as-collaboration-records"><h5>处理记录</h5><div v-if="!(selectedTicket.messages || []).length" class="as-empty as-empty--compact">暂无处理记录</div><article v-for="message in (selectedTicket.messages || [])" v-else :key="message.id"><span><strong>{{ message.authorName || '系统' }}</strong><time>{{ dateTime(message.createdAt) }}</time></span><p>{{ message.content }}</p></article></div>
      </section>
    </ProjectDetailDrawer>

    <ProjectDetailDrawer
      :open="Boolean(selectedFeedback)"
      title="反馈详情"
      size="58%"
      @close="closeFeedbackDetail"
    >
      <section v-if="selectedFeedback" class="as-panel as-collaboration-detail as-collaboration-detail--drawer">
        <header><div><p class="as-eyebrow">反馈详情</p><h4>{{ selectedFeedback.title || '现场反馈' }}</h4><span>{{ selectedFeedback.feedbackTypeLabel || selectedFeedback.feedbackType }}</span></div><span class="as-status" :class="feedbackStatusClass(selectedFeedback)">{{ selectedFeedback.statusLabel || selectedFeedback.status }}</span></header>
        <div class="as-collaboration-facts"><div><span>所属项目</span><strong>{{ selectedFeedback.projectName || '-' }}</strong></div><div><span>关联节点</span><strong>{{ nodeName(selectedFeedback) }}</strong></div><div><span>提交人</span><strong>{{ selectedFeedback.providerName || '-' }}</strong></div><div><span>提交时间</span><strong>{{ dateTime(selectedFeedback.createdAt) }}</strong></div></div>
        <div class="as-collaboration-copy"><strong>反馈内容</strong><p>{{ selectedFeedback.content }}</p></div>
        <AttachmentPanel target-type="feedback" :target-id="selectedFeedback.id" title="反馈附件" :editable="false" compact @error="error = $event" />
        <label class="as-collaboration-note"><span>审核意见</span><textarea v-model="feedbackReviewNote" rows="3" :readonly="!canReviewFeedback || !['submitted', 'under_review'].includes(selectedFeedback.status)" placeholder="填写采纳结论或未采纳原因"></textarea></label>
        <label v-if="canGrantReward && ['submitted', 'under_review'].includes(selectedFeedback.status)" class="as-field"><span>实物奖励（选填）</span><ElSelect v-model="feedbackPrizeId" clearable filterable placeholder="不发放奖励" aria-label="反馈实物奖励" :disabled="saving"><ElOption v-for="prize in rewardPrizes" :key="prize.id" :label="prize.name" :value="prize.id" /></ElSelect><small>选择后随采纳生成奖励；未选择时只记录审核结果。</small></label>
        <div v-if="prizeLoadError" role="alert">{{ prizeLoadError }}<button type="button" class="as-button as-button--secondary" @click="loadRewardPrizes">重新加载奖品</button></div>
        <div v-if="canReviewFeedback && ['submitted', 'under_review'].includes(selectedFeedback.status)" class="as-collaboration-actions"><button type="button" class="as-button as-button--danger" :disabled="saving" @click="reviewFeedback('rejected')"><X />不采纳</button><button type="button" class="as-button as-button--primary" :disabled="saving" @click="reviewFeedback('accepted')"><Check />采纳反馈</button></div>
        <div v-else class="as-collaboration-review-result"><CircleAlert /><span><strong>{{ selectedFeedback.statusLabel || selectedFeedback.status }}</strong><small>{{ selectedFeedback.reviewNote || '未填写审核意见' }} · {{ dateTime(selectedFeedback.reviewedAt) }}</small></span></div>
      </section>
    </ProjectDetailDrawer>
  </section>
</template>

<style scoped>
.as-collaboration-panel { display: grid; gap: 12px; min-width: 0; padding: 14px; }
.as-collaboration-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.as-collaboration-head h3 { margin: 2px 0 0; font-size: 17px; }
.as-collaboration-head > div > span { display: block; margin-top: 3px; color: #667085; font-size: 10px; }
.as-collaboration-tabs { display: flex; min-height: 38px; border-bottom: 1px solid #dfe4eb; gap: 4px; }
.as-collaboration-tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; border-bottom: 2px solid transparent; background: transparent; padding: 0 12px; color: #667085; font-size: 11px; font-weight: 700; cursor: pointer; }
.as-collaboration-tabs button.active { border-bottom-color: #155eef; color: #155eef; }
.as-collaboration-tabs svg { width: 15px; height: 15px; }
.as-collaboration-tabs span { min-width: 26px; border-radius: 4px; background: #eef2f7; padding: 2px 5px; color: #526174; font-size: 9px; text-align: center; }
.as-collaboration-facts .as-searchable-select { width: 100%; margin-top: 3px; }
.as-collaboration-table-wrap { max-height: calc(100vh - 290px); overflow: auto; }
.as-collaboration-table { width: 100%; min-width: 980px; table-layout: fixed; }
.as-collaboration-table th { position: sticky; z-index: 1; top: 0; height: 34px; background: #f7f9fb; padding: 7px 10px; color: #667085; font-size: 9px; text-align: left; }
.as-collaboration-table-filter-row th { top: 42px; z-index: 2; }
.as-collaboration-table-filter-row .as-search input { padding-left: 29px; }
.as-collaboration-table td { height: 48px; border-top: 1px solid #edf0f4; padding: 8px 10px; color: #475467; }
.as-collaboration-table tbody tr { cursor: pointer; }
.as-collaboration-table tbody tr:hover, .as-collaboration-table tbody tr.active { background: #f4f7fc; }
.as-collaboration-table td strong, .as-collaboration-table td small { display: block; }
.as-collaboration-table td strong { color: #27364a; font-size: 10px; }
.as-collaboration-table td small { margin-top: 2px; color: #8a96a7; font-size: 8px; }
.as-collaboration-empty { height: 80px !important; color: #8a96a7 !important; text-align: center; }
.as-collaboration-detail { display: grid; gap: 12px; border-top: 1px solid #dfe5ec; padding-top: 14px; }
.as-collaboration-detail--drawer { min-height: calc(100vh - 100px); border-top: 0; padding: 16px; }
.as-collaboration-detail > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.as-collaboration-detail h4 { margin: 2px 0 0; color: #172033; font-size: 14px; }
.as-collaboration-detail header > div > span { display: block; margin-top: 3px; color: #7b8798; font-size: 9px; }
.as-collaboration-facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid #e0e5ec; border-radius: 7px; background: #fafbfc; }
.as-collaboration-facts > div { min-width: 0; border-right: 1px solid #e5e9ef; padding: 9px 10px; }
.as-collaboration-facts > div:last-child { border-right: 0; }
.as-collaboration-facts > div > span, .as-collaboration-facts > div > strong { display: block; }
.as-collaboration-facts > div > span { color: #7b8798; font-size: 8px; }
.as-collaboration-facts > div > strong { overflow: hidden; margin-top: 3px; color: #344054; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.as-collaboration-copy { border-left: 3px solid #c5d1e0; padding-left: 10px; }
.as-collaboration-copy strong { color: #344054; font-size: 10px; }
.as-collaboration-copy p { margin: 4px 0 0; color: #526174; font-size: 10px; line-height: 1.6; white-space: pre-wrap; }
.as-collaboration-note { display: grid; gap: 5px; }
.as-collaboration-note > span { color: #526174; font-size: 10px; font-weight: 700; }
.as-collaboration-note textarea { width: 100%; resize: vertical; border: 1px solid #d3dbe6; border-radius: 6px; padding: 9px 10px; color: #344054; font: inherit; font-size: 10px; line-height: 1.55; }
.as-collaboration-note textarea:read-only { background: #f7f9fb; }
.as-collaboration-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.as-collaboration-records { display: grid; gap: 7px; border-top: 1px solid #e5e9ef; padding-top: 11px; }
.as-collaboration-records h5 { margin: 0; color: #344054; font-size: 11px; }
.as-collaboration-records article { display: grid; gap: 3px; border-left: 2px solid #cad4e0; padding-left: 8px; }
.as-collaboration-records article > span { display: flex; justify-content: space-between; gap: 10px; }
.as-collaboration-records article strong, .as-collaboration-records article time { color: #667085; font-size: 8px; }
.as-collaboration-records article p { margin: 0; color: #344054; font-size: 10px; line-height: 1.5; }
.as-collaboration-review-result { display: flex; align-items: center; gap: 8px; border-left: 3px solid #7f92aa; background: #f7f9fb; padding: 9px 10px; }
.as-collaboration-review-result svg { width: 17px; height: 17px; color: #60738d; }
.as-collaboration-review-result strong, .as-collaboration-review-result small { display: block; }
.as-collaboration-review-result strong { color: #344054; font-size: 10px; }
.as-collaboration-review-result small { margin-top: 2px; color: #667085; font-size: 9px; }

@media (max-width: 720px) {
  .as-collaboration-panel { padding: 11px; }
  .as-collaboration-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .as-collaboration-facts > div:nth-child(2) { border-right: 0; }
  .as-collaboration-facts > div:nth-child(-n+2) { border-bottom: 1px solid #e5e9ef; }
  .as-collaboration-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
