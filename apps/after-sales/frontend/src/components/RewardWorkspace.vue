<script setup>
import { computed, onMounted, ref } from "vue";
import {
  Check,
  Gift,
  LoaderCircle,
  PackageCheck,
  Plus,
  Search,
  ShieldAlert,
} from "@lucide/vue";
import { collectionRows, allCollectionRows, serviceApi } from "@/serviceApi";
import { matchesSearch } from "@/productSearch";
import { ElOption, ElSelect } from "element-plus/es/components/select/index.mjs";
import "element-plus/es/components/select/style/css";
import ProjectDetailDrawer from "@/components/ProjectDetailDrawer.vue";
import CreateRewardModal from "@/components/CreateRewardModal.vue";
import GlobalNotice from "@/components/GlobalNotice.vue";
import ListPagination from "@/components/ListPagination.vue";
import { useLocalPagination } from "@/composables/useLocalPagination";
import ModalShell from "@/components/ModalShell.vue";

const rewards = ref([]);
const projects = ref([]);
const providers = ref([]);
const prizeOptions = ref([]);
const prizeLoading = ref(false);
const prizeError = ref("");
const loading = ref(false);
const saving = ref(false);
const createLoading = ref(false);
const projectLoading = ref(false);
const createSaving = ref(false);
const error = ref("");
const success = ref("");
const activeState = ref("all");
const province = ref("all");
const year = ref("all");
const prizeKeyword = ref("");
const projectKeyword = ref("");
const providerKeyword = ref("");
const sourceFilter = ref("all");
const selectedId = ref("");
const drawerOpen = ref(false);
const createOpen = ref(false);
const processOpen = ref(false);
const trackingNote = ref("");
let projectRequestId = 0;

const selectedReward = computed(() => rewards.value.find((reward) => String(reward.id) === String(selectedId.value)) || null);
const provinceOptions = computed(() => [...new Set(rewards.value.map(rewardProvince).filter(Boolean))]);
const yearOptions = computed(() => [...new Set(rewards.value.map(rewardYear).filter(Boolean))].sort().reverse());
const filteredRewards = computed(() => {
  return rewards.value.filter((reward) => {
    return (activeState.value === "all" || rewardState(reward) === activeState.value)
      && (province.value === "all" || rewardProvince(reward) === province.value)
      && (year.value === "all" || rewardYear(reward) === year.value)
      && matchesSearch(prizeKeyword.value, rewardPrize(reward))
      && matchesSearch(projectKeyword.value, reward.projectName || reward.project_name)
      && matchesSearch(providerKeyword.value, reward.providerName, reward.provider_name)
      && (sourceFilter.value === "all" || rewardSource(reward) === sourceFilter.value);
  });
});
const pagination = useLocalPagination(filteredRewards);
const sourceOptions = computed(() => [...new Set(rewards.value.map(rewardSource).filter(Boolean))]);
function display(item, ...keys) {
  for (const key of keys) {
    const value = item?.[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return "-";
}

function rewardState(reward) {
  if (reward?.status === "issued" || reward?.statusLabel === "已发放") return "completed";
  if (reward?.status === "approved" || reward?.statusLabel === "待发放") return "running";
  return "other";
}

function rewardStatusLabel(reward) {
  const labels = { pending: "待审核", approved: "待发放", issued: "已发放", rejected: "已驳回" };
  return reward?.statusLabel || labels[reward?.status] || reward?.status || "待审核";
}

function rewardStatusClass(reward) {
  return { "is-done": rewardState(reward) === "completed", "is-danger": reward?.status === "rejected" };
}

function rewardSource(reward) {
  const data = reward?.businessData || reward?.business_data || {};
  return data.source || data.origin || reward?.source || reward?.rewardTypeLabel || reward?.reward_type_label || reward?.rewardType || reward?.reward_type || "服务贡献奖励";
}

function rewardPrize(reward) {
  return reward?.prize || reward?.title || "服务奖励";
}

function rewardProvince(reward) {
  const data = reward?.businessData || reward?.business_data || {};
  return reward?.province || reward?.projectProvince || reward?.project_province || data.province
    || reward?.providerCity || reward?.provider_city || "";
}

function rewardYear(reward) {
  const value = reward?.year || reward?.createdAt || reward?.created_at || reward?.issuedAt || reward?.issued_at || "";
  return String(value).slice(0, 4);
}

function rewardTime(reward) {
  return formatDateTime(reward?.createdAt || reward?.created_at || reward?.issuedAt || reward?.issued_at);
}

function rewardReason(reward) {
  return reward?.reason || reward?.description || reward?.transitionNote || reward?.transition_note || "暂无奖励原因";
}

function formatDateTime(value) {
  if (!value) return "-";
  return String(value).replace("T", " ").slice(0, 16);
}

function showSuccess(message) {
  success.value = message;
  window.setTimeout(() => { if (success.value === message) success.value = ""; }, 2600);
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const rewardPayload = await allCollectionRows(serviceApi.listRewards);
    rewards.value = collectionRows(rewardPayload);
    const next = rewards.value.find((reward) => String(reward.id) === String(selectedId.value)) || null;
    if (drawerOpen.value && next) selectedId.value = next.id;
    else { selectedId.value = ""; drawerOpen.value = false; }
    trackingNote.value = "";
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "服务奖励加载失败";
  } finally {
    loading.value = false;
  }
}

function chooseReward(reward) {
  selectedId.value = reward.id;
  drawerOpen.value = true;
  processOpen.value = false;
  trackingNote.value = "";
}

function closeRewardDetail() {
  drawerOpen.value = false;
  processOpen.value = false;
  selectedId.value = "";
  trackingNote.value = "";
}

async function openCreateReward() {
  createOpen.value = true;
  projects.value = [];
  projectLoading.value = false;
  projectRequestId += 1;
  void loadPrizeOptions();
  if (providers.value.length) return;
  createLoading.value = true;
  error.value = "";
  try {
    const providerPayload = await allCollectionRows(serviceApi.listTeamMembers);
    providers.value = collectionRows(providerPayload);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "奖励选项加载失败";
  } finally {
    createLoading.value = false;
  }
}

async function loadPrizeOptions() {
  prizeLoading.value = true;
  prizeError.value = "";
  prizeOptions.value = [];
  try {
    const response = await serviceApi.rewardPrizeOptions();
    prizeOptions.value = Array.isArray(response?.items) ? response.items : [];
  } catch (reason) {
    prizeError.value = reason instanceof Error ? reason.message : "实物奖品加载失败";
  } finally {
    prizeLoading.value = false;
  }
}

async function loadProviderProjects(providerId) {
  const normalizedId = String(providerId || "");
  const requestId = ++projectRequestId;
  projects.value = [];
  if (!normalizedId) return;
  projectLoading.value = true;
  error.value = "";
  try {
    const payload = await allCollectionRows(serviceApi.listProjects, { providerId: normalizedId });
    if (requestId === projectRequestId) projects.value = collectionRows(payload);
  } catch (reason) {
    if (requestId === projectRequestId) {
      error.value = reason instanceof Error ? reason.message : "关联项目加载失败";
    }
  } finally {
    if (requestId === projectRequestId) projectLoading.value = false;
  }
}

async function createReward(payload) {
  if (createSaving.value) return;
  createSaving.value = true;
  error.value = "";
  try {
    const response = await serviceApi.createReward(payload);
    const created = response?.item || response;
    rewards.value = [created, ...rewards.value.filter((reward) => String(reward.id) !== String(created.id))];
    activeState.value = "all";
    createOpen.value = false;
    chooseReward(created);
    showSuccess("奖励已创建，当前状态为待审核");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "奖励创建失败";
  } finally {
    createSaving.value = false;
  }
}

function processReward() {
  if (!selectedReward.value) return showSuccess("请先选择奖励记录");
  trackingNote.value = "";
  processOpen.value = true;
}

async function transitionReward(actionName) {
  if (!selectedReward.value || saving.value) return;
  saving.value = true;
  error.value = "";
  try {
    const response = await serviceApi.rewardAction(selectedReward.value.id, actionName, { note: trackingNote.value.trim() });
    const updated = response?.item || response;
    rewards.value = rewards.value.map((reward) => String(reward.id) === String(updated.id) ? updated : reward);
    trackingNote.value = "";
    await load();
    processOpen.value = false;
    showSuccess(actionName === "approve" ? "审核已通过，奖励进入待发放" : actionName === "reject" ? "奖励已驳回" : "奖品已标记为已发放");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "奖励状态更新失败";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="as-page as-reward-page">
    <GlobalNotice v-model:error="error" v-model:success="success" />

    <div class="as-reward-layout">
      <section class="as-panel as-reward-list-card">
        <div class="as-panel-head"><div><h2>服务奖励列表</h2><p>按奖品、项目和获得人员分别搜索，可结合地区、年份与状态筛选。</p></div><div class="as-head-actions"><button type="button" class="as-button as-button--primary" @click="openCreateReward"><Plus />新增奖励</button></div></div>
        <div class="as-reward-table-scroll"><table class="as-reward-table" aria-label="服务奖励列表"><thead>
          <tr><th>奖品名称</th><th>项目名称</th><th>获得人员</th><th>地区</th><th>年份</th><th>来源类型</th><th>状态</th></tr>
          <tr class="as-reward-table-filter-row">
            <th><label class="as-search"><Search /><input v-model="prizeKeyword" type="search" aria-label="搜索奖品名称" placeholder="搜索奖品名称"></label></th>
            <th><label class="as-search"><Search /><input v-model="projectKeyword" type="search" aria-label="搜索奖励项目名称" placeholder="搜索项目名称"></label></th>
            <th><label class="as-search"><Search /><input v-model="providerKeyword" type="search" aria-label="搜索获得人员" placeholder="搜索获得人员"></label></th>
            <th><ElSelect v-model="province" class="as-table-select" popper-class="as-table-select-popper" placeholder="全部省份" aria-label="奖励省份"><ElOption label="全部省份" value="all" /><ElOption v-for="item in provinceOptions" :key="item" :label="item" :value="item" /></ElSelect></th>
            <th><ElSelect v-model="year" class="as-table-select" popper-class="as-table-select-popper" placeholder="全部年份" aria-label="奖励年份"><ElOption label="全部年份" value="all" /><ElOption v-for="item in yearOptions" :key="item" :label="item" :value="item" /></ElSelect></th>
            <th><ElSelect v-model="sourceFilter" class="as-table-select" popper-class="as-table-select-popper" placeholder="全部来源" aria-label="奖励来源"><ElOption label="全部来源" value="all" /><ElOption v-for="item in sourceOptions" :key="item" :label="item" :value="item" /></ElSelect></th>
            <th><ElSelect v-model="activeState" class="as-table-select" popper-class="as-table-select-popper" placeholder="全部状态" aria-label="奖励状态"><ElOption label="全部状态" value="all" /><ElOption label="待发放" value="running" /><ElOption label="已发放" value="completed" /></ElSelect></th>
          </tr>
        </thead><tbody>
          <tr v-if="loading"><td colspan="7" class="as-reward-table-empty"><LoaderCircle class="as-spin" /> 正在加载奖励...</td></tr>
          <tr v-else-if="!filteredRewards.length"><td colspan="7" class="as-reward-table-empty">没有找到匹配的服务奖励记录</td></tr>
          <tr v-for="reward in pagination.rows" v-else :key="reward.id" tabindex="0" :class="{ active: String(reward.id) === String(selectedId) }" @click="chooseReward(reward)" @keydown.enter="chooseReward(reward)"><td><strong>{{ rewardPrize(reward) }}</strong><small>{{ rewardReason(reward) }}</small></td><td>{{ display(reward, 'projectName', 'project_name') }}</td><td>{{ display(reward, 'providerName', 'provider_name') }}</td><td>{{ rewardProvince(reward) || '未设置地区' }}</td><td>{{ rewardYear(reward) || '-' }}</td><td>{{ rewardSource(reward) }}</td><td><span class="as-status" :class="rewardStatusClass(reward)">{{ rewardStatusLabel(reward) }}</span></td></tr>
        </tbody></table></div>
      <ListPagination v-model:page-size="pagination.pageSize" :page="pagination.page" :total="pagination.total" :total-pages="pagination.totalPages" :loading="loading" label="奖励分页" @change="pagination.page = $event" />
      </section>
      <ProjectDetailDrawer :open="drawerOpen" title="奖励详情" @close="closeRewardDetail">

      <aside class="as-panel as-reward-detail">
        <div v-if="!selectedReward" class="as-empty as-empty--large"><Gift /> 选择一条奖励记录查看详情</div>
        <template v-else>
          <div class="as-reward-detail-head"><span class="as-reward-avatar">{{ String(rewardPrize(selectedReward)).slice(0, 1) }}</span><div><h2>{{ rewardPrize(selectedReward) }}</h2><p>{{ display(selectedReward, 'projectName', 'project_name') }} · {{ rewardSource(selectedReward) }}</p></div></div>
          <div class="as-reward-detail-actions"><button type="button" class="as-button as-button--primary" @click="processReward"><PackageCheck />处理发放</button></div>
          <dl class="as-reward-info-grid"><div><dt>获得人员</dt><dd>{{ display(selectedReward, 'providerName', 'provider_name') }}</dd></div><div><dt>发放状态</dt><dd>{{ rewardStatusLabel(selectedReward) }}</dd></div><div><dt>获得时间</dt><dd>{{ rewardTime(selectedReward) }}</dd></div><div><dt>来源类型</dt><dd>{{ rewardSource(selectedReward) }}</dd></div><div v-if="selectedReward.rewardType === 'prize'"><dt>实物奖品</dt><dd>{{ selectedReward.prize || '未指定' }}</dd></div></dl>
          <section class="as-reward-detail-section"><h3>获得原因</h3><div class="as-reward-event"><strong>{{ rewardReason(selectedReward) }}</strong><span>该原因会同步到手机端“我的奖品记录”详情。</span></div></section>
        </template>
      </aside>
      </ProjectDetailDrawer>
    </div>

    <CreateRewardModal :open="createOpen" :projects="projects" :providers="providers" :prizes="prizeOptions" :prize-loading="prizeLoading" :prize-error="prizeError" :loading="createLoading" :project-loading="projectLoading" :saving="createSaving" @close="createOpen = false" @provider-change="loadProviderProjects" @retry-prizes="loadPrizeOptions" @submit="createReward" />

    <ModalShell :open="processOpen" title="处理发放" :description="selectedReward ? `${rewardPrize(selectedReward)} · ${display(selectedReward, 'providerName', 'provider_name')}` : ''" @close="processOpen = false">
      <template v-if="selectedReward">
        <dl class="as-reward-modal-grid as-reward-modal-grid--process">
          <div><dt>当前状态</dt><dd><span class="as-status" :class="rewardStatusClass(selectedReward)">{{ rewardStatusLabel(selectedReward) }}</span></dd></div>
          <div><dt>奖励编号</dt><dd>{{ display(selectedReward, 'code') }}</dd></div>
          <div><dt>奖品名称</dt><dd>{{ rewardPrize(selectedReward) }}</dd></div>
          <div><dt>获得人员</dt><dd>{{ display(selectedReward, 'providerName', 'provider_name') }}</dd></div>
        </dl>
        <label v-if="['pending', 'approved'].includes(selectedReward.status)" class="as-field as-reward-process-note"><span>处理备注</span><textarea v-model="trackingNote" rows="4" :disabled="saving" :placeholder="selectedReward.status === 'approved' ? '填写快递单号或发放备注' : '填写审核说明或处理备注'"></textarea></label>
        <section v-else class="as-reward-modal-section"><h3>处理结果</h3><p>{{ display(selectedReward, 'transitionNote', 'transition_note') }}</p><small v-if="selectedReward.status === 'issued'">发放时间：{{ formatDateTime(selectedReward.issuedAt || selectedReward.issued_at) }}</small></section>
      </template>
      <template #footer>
        <button type="button" class="as-button as-button--secondary" :disabled="saving" @click="processOpen = false">关闭</button>
        <button v-if="selectedReward && ['pending', 'approved'].includes(selectedReward.status)" type="button" class="as-button as-button--danger" :disabled="saving" @click="transitionReward('reject')"><ShieldAlert />驳回奖励</button>
        <button v-if="selectedReward?.status === 'pending'" type="button" class="as-button as-button--primary" :disabled="saving" @click="transitionReward('approve')"><Check />审核通过</button>
        <button v-if="selectedReward?.status === 'approved'" type="button" class="as-button as-button--primary" :disabled="saving" @click="transitionReward('issue')"><Check />确认已发放</button>
      </template>
    </ModalShell>
  </div>
</template>

<style scoped>
.as-reward-page { max-width: 1680px; }
.as-reward-layout { display: block; }
.as-reward-list-card { min-width: 0; min-height: calc(100vh - 165px); overflow: hidden; }
.as-reward-list-card { display: flex; flex-direction: column; }
.as-reward-filter-bar { display: grid; grid-template-columns: 170px 100px 100px minmax(160px, 1fr); gap: 9px; align-items: center; border-bottom: 1px solid var(--as-border); background: #fbfdff; padding: 12px; }
.as-reward-state-tabs { display: inline-grid; grid-template-columns: repeat(2, minmax(75px, 1fr)); overflow: hidden; border: 1px solid var(--as-border); border-radius: 7px; background: #fff; }
.as-reward-state-tabs button { min-height: 34px; border: 0; border-right: 1px solid var(--as-border); background: #fff; color: #526273; font-size: 10px; font-weight: 800; }
.as-reward-state-tabs button:last-child { border-right: 0; }
.as-reward-state-tabs button.active { background: #eaf3ff; color: var(--as-primary); }
.as-reward-table-scroll { min-height: 0; flex: 1; overflow: auto; }
.as-reward-table { width: 100%; min-width: 980px; border-collapse: separate; border-spacing: 0; table-layout: fixed; text-align: left; }
.as-reward-table th { position: sticky; top: 0; z-index: 2; height: 42px; border-right: 1px solid #e4ecf4; border-bottom: 1px solid #cfdeec; background: #f1f6fb; padding: 0 12px; color: #3f5874; font-size: 11px; font-weight: 800; }
.as-reward-table th:first-child { width: 22%; }
.as-reward-table th:nth-child(2) { width: 20%; }
.as-reward-table th:nth-child(3) { width: 14%; }
.as-reward-table th:nth-child(4), .as-reward-table th:nth-child(5) { width: 9%; }
.as-reward-table th:nth-child(6) { width: 16%; }
.as-reward-table th:nth-child(7) { width: 10%; border-right: 0; }
.as-reward-table-filter-row th { top: 42px; height: 44px; padding: 6px 8px; background: #fff; }
.as-reward-table-filter-row .as-search input { height: 28px; padding-left: 29px; font-size: 11px; }
.as-reward-table td { height: 62px; border-right: 1px solid #e8eef5; border-bottom: 1px solid #e8eef5; padding: 9px 12px; color: #334155; font-size: 11px; vertical-align: middle; }
.as-reward-table td:last-child { border-right: 0; }
.as-reward-table tbody tr { cursor: pointer; background: #fff; }
.as-reward-table tbody tr:nth-child(even) { background: #fbfdff; }
.as-reward-table tbody tr:hover, .as-reward-table tbody tr.active { background: #eef6ff; }
.as-reward-table td strong, .as-reward-table td small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.as-reward-table td strong { color: #155eef; font-size: 12px; }
.as-reward-table td small { margin-top: 3px; color: #7b8da3; font-size: 9px; }
.as-reward-table-empty { height: 180px !important; color: #94a3b8 !important; text-align: center; cursor: default; }
.as-reward-row { display: grid; width: 100%; min-width: 0; grid-template-columns: minmax(0, 1fr); gap: 6px; border: 0; border-bottom: 1px solid #edf0f2; background: #fff; padding: 12px 13px; color: #344054; text-align: left; }
.as-reward-row:hover { background: #f8fbff; }
.as-reward-row.active { background: #edf4ff; box-shadow: inset 3px 0 0 var(--as-primary); }
.as-reward-row__head { display: flex; min-width: 0; align-items: flex-start; justify-content: space-between; gap: 8px; }
.as-reward-row__head strong { min-width: 0; overflow: hidden; color: #243145; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.as-reward-row__head .as-status { min-height: 20px; padding: 0 6px; font-size: 9px; }
.as-reward-row__head .as-status.is-danger { border-color: #efb2b7; background: #fff1f2; color: #b4232f; }
.as-reward-row__meta { overflow: hidden; color: #7c8797; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.as-reward-detail { min-width: 0; min-height: 100%; overflow-y: auto; border: 0; border-radius: 0; padding: 0; box-shadow: none; }
.as-reward-detail-head { display: flex; min-height: 78px; align-items: center; gap: 10px; border-bottom: 1px solid var(--as-border); padding: 14px; }
.as-reward-detail-head > div { min-width: 0; }
.as-reward-detail-head h2 { overflow: hidden; margin: 0; color: #182230; font-size: 17px; text-overflow: ellipsis; white-space: nowrap; }
.as-reward-detail-head p { overflow: hidden; margin: 3px 0 0; color: var(--as-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.as-reward-avatar { display: flex; width: 38px; height: 38px; flex: 0 0 auto; align-items: center; justify-content: center; border-radius: 8px; background: #fff2cf; color: #a36a00; font-size: 15px; font-weight: 850; }
.as-reward-detail-actions { display: flex; gap: 8px; border-bottom: 1px solid var(--as-border); padding: 10px 14px; }
.as-reward-detail-actions .as-button { min-height: 32px; font-size: 10px; }
.as-reward-info-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; border-bottom: 1px solid var(--as-border); }
.as-reward-info-grid > div { min-width: 0; min-height: 62px; border-right: 1px solid #edf0f2; border-bottom: 1px solid #edf0f2; padding: 10px 12px; }
.as-reward-info-grid > div:nth-child(2n) { border-right: 0; }
.as-reward-info-grid dt { color: var(--as-muted); font-size: 9px; }
.as-reward-info-grid dd { overflow: hidden; margin: 4px 0 0; color: #344054; font-size: 10px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.as-reward-detail-section { border-bottom: 1px solid #edf0f2; padding: 13px 14px; }
.as-reward-detail-section:last-child { border-bottom: 0; }
.as-reward-detail-section h3 { margin: 0 0 9px; color: #344054; font-size: 11px; }
.as-reward-event { display: grid; gap: 4px; border-left: 3px solid #c5d8f7; background: #f7faff; padding: 9px 10px; }
.as-reward-event strong { color: #344054; font-size: 10px; line-height: 15px; }
.as-reward-event span { color: var(--as-muted); font-size: 9px; line-height: 14px; }
.as-reward-modal-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); overflow: hidden; border: 1px solid #dce5ef; border-radius: 7px; background: #fff; margin: 0 0 14px; }
.as-reward-modal-grid > div { min-width: 0; min-height: 66px; border-right: 1px solid #e6edf4; border-bottom: 1px solid #e6edf4; padding: 10px 12px; }
.as-reward-modal-grid > div:nth-child(2n) { border-right: 0; }
.as-reward-modal-grid > div:nth-last-child(-n + 2) { border-bottom: 0; }
.as-reward-modal-grid dt { color: #718096; font-size: 10px; }
.as-reward-modal-grid dd { overflow: hidden; margin: 6px 0 0; color: #26364a; font-size: 12px; font-weight: 750; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.as-reward-modal-section { border: 1px solid #dce5ef; border-radius: 7px; background: #f8fbff; padding: 12px 13px; }
.as-reward-modal-section + .as-reward-modal-section { margin-top: 10px; }
.as-reward-modal-section h3 { margin: 0 0 7px; color: #344054; font-size: 11px; }
.as-reward-modal-section p { margin: 0; color: #526273; font-size: 11px; line-height: 19px; white-space: pre-wrap; }
.as-reward-modal-section small { display: block; margin-top: 8px; color: #7b8da3; font-size: 9px; }
.as-reward-process-note { border-top: 1px solid #e6edf4; padding-top: 13px; }
@media (max-width: 1180px) { .as-reward-layout { grid-template-columns: minmax(0, 1fr); } .as-reward-list-card, .as-reward-detail { min-height: auto; max-height: none; } .as-reward-list-card { max-height: 520px; } }
@media (max-width: 720px) { .as-reward-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .as-reward-filter-bar { grid-template-columns: repeat(2, minmax(0, 1fr)); } .as-reward-filter-bar .as-search { grid-column: 1 / -1; } }
@media (max-width: 480px) { .as-reward-filter-bar, .as-reward-modal-grid { grid-template-columns: minmax(0, 1fr); } .as-reward-filter-bar .as-search { grid-column: auto; } .as-reward-modal-grid > div { border-right: 0; } .as-reward-modal-grid > div:nth-last-child(-n + 2) { border-bottom: 1px solid #e6edf4; } .as-reward-modal-grid > div:last-child { border-bottom: 0; } }
</style>
