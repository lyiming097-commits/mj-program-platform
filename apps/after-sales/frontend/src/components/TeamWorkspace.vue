<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import {
  Check,
  ClipboardCheck,
  LoaderCircle,
  Map,
  MessageCircle,
  Phone,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  Star,
  Tags,
  Users,
  X,
} from "@lucide/vue";
import { collectionRows, allCollectionRows, serviceApi } from "@/serviceApi";
import { matchesSearch } from "@/productSearch";
import { ElOption, ElSelect } from "element-plus/es/components/select/index.mjs";
import "element-plus/es/components/select/style/css";
import ModalShell from "@/components/ModalShell.vue";
import ProjectDetailDrawer from "@/components/ProjectDetailDrawer.vue";
import GlobalNotice from "@/components/GlobalNotice.vue";
import ListPagination from "@/components/ListPagination.vue";
import { useLocalPagination } from "@/composables/useLocalPagination";
import AttachmentPanel from "@/components/AttachmentPanel.vue";
import {
  normalizeProviderTags,
  PROVIDER_TAGS_UPDATED_EVENT,
  readProviderTags,
  SETTINGS_STORAGE_KEY,
} from "@/data/providerTagLibrary";

const ServiceCoverageMap = defineAsyncComponent({
  loader: () => import("@/components/ServiceCoverageMap.vue"),
  delay: 200,
  timeout: 30_000,
});

const props = defineProps({ canManage: { type: Boolean, default: false } });

const PROVIDER_ARCHIVE_CATEGORIES = Object.freeze([
  { value: "qualification", label: "资质证明" },
  { value: "general", label: "其他档案" },
]);
const providers = ref([]);
const providerDetail = ref(null);
const rewards = ref([]);
const capabilityGroups = ref([]);
const providerTagLibrary = ref(readProviderTags());
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const success = ref("");
const activeView = shallowRef("list");
const keyword = ref("");
const region = ref("all");
const nodeFilter = ref("");
const skill = ref("all");
const certificationFilter = ref("all");
const selectedId = ref("");
const drawerOpen = ref(false);
const contactOpen = ref(false);
const archiveOpen = ref(false);
const capabilityOpen = ref(false);
const capabilitySaving = ref(false);
const capabilityNodeValue = ref("");
const capabilityDraft = ref([]);

const selectedProvider = computed(() => providerDetail.value || providers.value.find((item) => String(item.id) === String(selectedId.value)) || null);
const selectedScoreSummary = computed(() => {
  const source = selectedProvider.value?.scoreSummary || {};
  return {
    average: source.average ?? selectedProvider.value?.score ?? "0.00",
    count: Number(source.count ?? selectedProvider.value?.scoreRatingCount ?? 0),
    source: source.source ?? selectedProvider.value?.scoreSource ?? "none",
    items: Array.isArray(source.items) ? source.items : [],
  };
});
const totalProviders = computed(() => providers.value.length);
const certifiedProviders = computed(() => providers.value.filter((item) => (item.certificationStatus || item.certification_status) === "certified").length);
const monthOrders = computed(() => providers.value.reduce((sum, item) => sum + Number(item.monthOrders ?? item.month_orders ?? 0), 0));
const averageScore = computed(() => {
  const rated = providers.value
    .filter((item) => Number(item.scoreRatingCount ?? item.score_rating_count ?? 0) > 0)
    .map((item) => Number(item.score ?? item.rating ?? 0))
    .filter((value) => Number.isFinite(value) && value > 0);
  if (!rated.length) return "0.0";
  return (rated.reduce((sum, value) => sum + value, 0) / rated.length).toFixed(1);
});
const regionOptions = computed(() => [...new Set(providers.value.flatMap((item) => item.regions || [item.city]).filter(Boolean))]);
const nodeOptions = computed(() => capabilityGroups.value.flatMap((group) => (group.nodes || []).map((node) => ({
  ...node,
  serviceType: group.serviceType,
  serviceTypeLabel: group.serviceTypeLabel,
  value: `${group.serviceType}:${node.nodeKey}`,
}))).filter((item) => item.value));
const selectedNode = computed(() => nodeOptions.value.find((item) => item.value === nodeFilter.value) || null);
const skillOptions = computed(() => [...new Set([
  ...providerTagLibrary.value,
  ...(selectedNode.value?.abilities || []),
  ...providers.value.flatMap((item) => item.skills || item.abilities || []),
].filter(Boolean))]);
const filteredProviders = computed(() => {
  return providers.value.filter((provider) => {
    const regions = provider.regions || [provider.city];
    const skills = provider.skills || provider.abilities || [];
    const status = provider.certificationStatus || provider.certification_status || "";
    return matchesSearch(keyword.value, provider.name, provider.phone)
      && (region.value === "all" || regions.includes(region.value))
      && (skill.value === "all" || skills.includes(skill.value))
      && (certificationFilter.value === "all" || status === certificationFilter.value);
  });
});
const pagination = useLocalPagination(filteredProviders);
const selectedServiceRecords = computed(() => {
  const records = selectedProvider.value?.serviceRecords || selectedProvider.value?.service_records || selectedProvider.value?.projects || [];
  return records.slice(0, 20);
});
const selectedRewards = computed(() => rewards.value.filter((item) => String(item.providerId ?? item.provider_id ?? "") === String(selectedProvider.value?.id ?? "")));
const personOptions = computed(() => [...new Set(providers.value.map((item) => item.name).filter(Boolean))]);
const editedCapabilityNode = computed(() => nodeOptions.value.find((node) => node.value === capabilityNodeValue.value) || null);

function display(item, ...keys) {
  for (const key of keys) {
    const value = item?.[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return "-";
}

function providerStatus(provider) {
  return provider?.certificationStatusLabel || provider?.certification_status_label || provider?.statusLabel || provider?.status_display || provider?.certificationStatus || provider?.certification_status || "待审核";
}

function providerStatusClass(provider) {
  const status = provider?.certificationStatus || provider?.certification_status;
  return { "is-done": status === "certified", "is-danger": status === "paused" };
}

function formatScore(value) {
  const score = Number(value);
  return Number.isFinite(score) ? score.toFixed(1) : "0.0";
}

function initials(name) {
  return String(name || "服").slice(0, 1);
}

function recordTitle(item) {
  if (Array.isArray(item)) return item[0] || "服务记录";
  return display(item, "projectName", "project_name", "title", "name");
}

function recordMeta(item) {
  if (Array.isArray(item)) return item[1] || "";
  return [display(item, "serviceTypeLabel", "service_type_label", "serviceType"), display(item, "nodeName", "node_name"), display(item, "statusLabel", "status_label", "status")].filter((value) => value !== "-").join(" · ");
}

function showSuccess(message) {
  success.value = message;
  window.setTimeout(() => { if (success.value === message) success.value = ""; }, 2600);
}

function syncProviderTagLibrary(tags) {
  providerTagLibrary.value = normalizeProviderTags(tags);
  if (skill.value !== "all" && !skillOptions.value.includes(skill.value)) skill.value = "all";
}

function handleProviderTagsUpdated(event) {
  syncProviderTagLibrary(event?.detail?.tags || readProviderTags());
}

function handleSettingsStorage(event) {
  if (event.key !== SETTINGS_STORAGE_KEY) return;
  syncProviderTagLibrary(readProviderTags());
}

async function loadCapabilities() {
  const response = await serviceApi.capabilityCatalog();
  capabilityGroups.value = Array.isArray(response?.groups) ? response.groups : [];
}

async function loadProviderTagLibrary() {
  try {
    const response = await serviceApi.providerTagCatalog();
    if (Array.isArray(response?.items) && response.items.length) syncProviderTagLibrary(response.items);
  } catch {
    // Keep the local fallback while the central catalog is unavailable.
  }
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [providerPayload, rewardPayload] = await Promise.all([
      allCollectionRows(serviceApi.listTeamMembers),
      props.canManage ? allCollectionRows(serviceApi.listRewards) : Promise.resolve([]),
    ]);
    providers.value = collectionRows(providerPayload);
    rewards.value = collectionRows(rewardPayload);
    const selected = providers.value.find((item) => String(item.id) === String(selectedId.value));
    if (drawerOpen.value && selected) await selectProvider(selected, { open: false });
    else { selectedId.value = ""; providerDetail.value = null; drawerOpen.value = false; }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "服务团队加载失败";
  } finally {
    loading.value = false;
  }
}

async function selectProvider(provider, { open = true } = {}) {
  if (!provider) return;
  selectedId.value = provider.id;
  if (open) drawerOpen.value = true;
  providerDetail.value = null;
  try {
    const response = await serviceApi.getTeamMember(provider.id);
    providerDetail.value = response?.item || response;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "人员档案加载失败";
  }
}

function closeProviderDetail() {
  archiveOpen.value = false;
  drawerOpen.value = false;
  selectedId.value = "";
  providerDetail.value = null;
}

function openContact() {
  if (!selectedProvider.value) return;
  contactOpen.value = true;
}

function auditProvider() {
  if (selectedProvider.value) archiveOpen.value = true;
}

function syncCapabilityDraft() {
  capabilityDraft.value = (editedCapabilityNode.value?.abilities || []).map((name) => String(name));
}

async function openCapabilityManager() {
  if (!props.canManage) return;
  error.value = "";
  try {
    if (!capabilityGroups.value.length) await loadCapabilities();
    capabilityNodeValue.value = nodeFilter.value || nodeOptions.value[0]?.value || "";
    syncCapabilityDraft();
    capabilityOpen.value = true;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "能力标签加载失败";
  }
}

function handleSkillChange() {
  if (skill.value !== "__manage_team_abilities__") return;
  skill.value = "all";
  openCapabilityManager();
}

function addCapabilityTag() { capabilityDraft.value.push(""); }

function removeCapabilityTag(index) {
  if (capabilityDraft.value.length <= 1) return;
  capabilityDraft.value.splice(index, 1);
}

async function saveCapabilityTags() {
  if (!props.canManage) return;
  const node = editedCapabilityNode.value;
  const names = capabilityDraft.value.map((name) => String(name).trim()).filter(Boolean);
  if (!node || !names.length) {
    error.value = "每个业务节点至少保留一个能力标签";
    return;
  }
  capabilitySaving.value = true;
  error.value = "";
  try {
    const response = await serviceApi.updateCapabilityCatalog({ serviceType: node.serviceType, nodeKey: node.nodeKey, names });
    capabilityGroups.value = Array.isArray(response?.groups) ? response.groups : capabilityGroups.value;
    capabilityOpen.value = false;
    showSuccess(`${node.nodeName}能力标签已保存`);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "能力标签保存失败";
  } finally {
    capabilitySaving.value = false;
  }
}

async function updateCertification(status) {
  if (!props.canManage || !selectedProvider.value || saving.value) return;
  const previousStatus = selectedProvider.value.certificationStatus || selectedProvider.value.certification_status;
  saving.value = true;
  error.value = "";
  try {
    await serviceApi.updateTeamMember(selectedProvider.value.id, { certificationStatus: status });
    showSuccess(status === "paused" ? "人员服务已暂停" : previousStatus === "paused" ? "人员服务已恢复" : "人员审核已通过");
    await load();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "人员状态更新失败";
  } finally {
    saving.value = false;
  }
}

watch(nodeFilter, () => { skill.value = "all"; });
watch(() => props.canManage, () => {
  capabilityOpen.value = false;
  rewards.value = [];
  load();
});
onMounted(async () => {
  window.addEventListener(PROVIDER_TAGS_UPDATED_EVENT, handleProviderTagsUpdated);
  window.addEventListener("storage", handleSettingsStorage);
  await loadProviderTagLibrary();
  await loadCapabilities().catch(() => {});
  await load();
});
onBeforeUnmount(() => {
  window.removeEventListener(PROVIDER_TAGS_UPDATED_EVENT, handleProviderTagsUpdated);
  window.removeEventListener("storage", handleSettingsStorage);
});
</script>

<template>
  <div class="as-page as-team-page">
    <GlobalNotice v-model:error="error" v-model:success="success" />

    <nav class="as-project-detail-tabs as-team-view-tabs as-mall-tabbar" role="tablist" aria-label="服务团队视图">
      <button id="as-team-list-tab" type="button" role="tab" aria-controls="as-team-list-panel" :aria-selected="activeView === 'list'" :class="{ active: activeView === 'list' }" @click="activeView = 'list'"><Users />人员列表</button>
      <button id="as-team-coverage-tab" type="button" role="tab" aria-controls="as-team-coverage-panel" :aria-selected="activeView === 'coverage'" :class="{ active: activeView === 'coverage' }" @click="activeView = 'coverage'"><Map />服务覆盖</button>
    </nav>

    <section v-if="activeView === 'coverage'" id="as-team-coverage-panel" class="as-team-tab-panel as-team-coverage-view" role="tabpanel" aria-labelledby="as-team-coverage-tab">
      <section class="as-team-metrics" aria-label="关键指标"><article><span>安装人员总数</span><strong>{{ totalProviders }}</strong><small>覆盖浙江省内主要城市</small></article><article><span>已实名认证</span><strong>{{ certifiedProviders }}</strong><small>可直接参与派单</small></article><article><span>本月完成安装</span><strong>{{ monthOrders }}</strong><small>按本月完成服务节点实时统计</small></article><article><span>平均服务评分</span><strong>{{ averageScore }}</strong><small>管理端完成节点评分的平均分</small></article></section>

      <ServiceCoverageMap :providers="providers" />
    </section>

    <section v-show="activeView === 'list'" id="as-team-list-panel" class="as-team-tab-panel" role="tabpanel" aria-labelledby="as-team-list-tab">
      <div class="as-team-layout">
      <section class="as-panel as-team-main-column">
        <div class="as-panel-head"><div><h2>服务团队列表</h2><p>微信用户注册后自动进入待审核列表；审核通过后可参与售中、售后派单。</p></div></div>
        <div class="as-team-toolbar"><label class="as-search"><Search /><input v-model="keyword" type="search" placeholder="搜索姓名或手机号" aria-label="搜索服务人员"></label><select v-model="region" class="as-select" aria-label="服务区域"><option value="">全部区域</option><option v-for="item in regionOptions" :key="item">{{ item }}</option></select><select v-model="nodeFilter" class="as-select" aria-label="服务节点"><option value="">全部节点</option><optgroup v-for="group in capabilityGroups" :key="group.serviceType" :label="group.serviceTypeLabel"><option v-for="node in group.nodes" :key="`${group.serviceType}:${node.nodeKey}`" :value="`${group.serviceType}:${node.nodeKey}`">{{ node.nodeName }}</option></optgroup></select><select v-model="skill" class="as-select" aria-label="技能标签" @change="handleSkillChange"><option value="">全部能力</option><option v-for="item in skillOptions" :key="item">{{ item }}</option><option v-if="canManage" value="__manage_team_abilities__">编辑能力...</option></select><div class="as-team-status-tabs" aria-label="认证状态"><button type="button" :class="{ active: certificationFilter === '' }" @click="certificationFilter = ''">全部</button><button type="button" :class="{ active: certificationFilter === 'certified' }" @click="certificationFilter = 'certified'">已认证</button><button type="button" :class="{ active: certificationFilter === 'pending' }" @click="certificationFilter = 'pending'">待审核</button><button type="button" :class="{ active: certificationFilter === 'paused' }" @click="certificationFilter = 'paused'">暂停</button></div></div>
        <div class="as-team-table-card"><table><thead><tr><th class="as-team-person-col">安装人员</th><th>服务区域</th><th>能力标签</th><th>本月安装</th><th>评分</th><th>状态</th></tr><tr class="as-team-table-filter-row"><th><label class="as-search"><Search /><input v-model="keyword" type="search" placeholder="搜索姓名或手机号" aria-label="搜索服务人员"></label></th><th><ElSelect v-model="region" class="as-table-select" popper-class="as-table-select-popper" placeholder="全部区域" aria-label="服务区域"><ElOption label="全部区域" value="all" /><ElOption v-for="item in regionOptions" :key="item" :label="item" :value="item" /></ElSelect></th><th><ElSelect v-model="skill" class="as-table-select" popper-class="as-table-select-popper" placeholder="全部能力" aria-label="技能标签" @change="handleSkillChange"><ElOption label="全部能力" value="all" /><ElOption v-for="item in skillOptions" :key="item" :label="item" :value="item" /><ElOption v-if="canManage" label="编辑能力..." value="__manage_team_abilities__" /></ElSelect></th><th></th><th></th><th><ElSelect v-model="certificationFilter" class="as-table-select" popper-class="as-table-select-popper" placeholder="全部状态" aria-label="认证状态"><ElOption label="全部状态" value="all" /><ElOption label="已认证" value="certified" /><ElOption label="待审核" value="pending" /><ElOption label="暂停" value="paused" /></ElSelect></th></tr></thead><tbody><tr v-if="loading"><td colspan="6" class="as-team-table-empty"><LoaderCircle class="as-spin" /> 正在加载服务团队...</td></tr><tr v-else-if="!filteredProviders.length"><td colspan="6" class="as-team-table-empty">没有找到匹配的安装人员</td></tr><tr v-for="provider in pagination.rows" v-else :key="provider.id" tabindex="0" :class="{ selected: String(provider.id) === String(selectedId) }" @click="selectProvider(provider)" @keydown.enter="selectProvider(provider)"><td><div class="as-team-person"><span class="as-team-avatar">{{ initials(provider.name) }}</span><span><strong>{{ provider.name }}</strong><small>{{ display(provider, 'roleLabel', 'role_display', 'roleDisplay', 'role') }} · {{ display(provider, 'phone') }}</small></span></div></td><td>{{ (provider.regions || [provider.city]).filter(Boolean).join(' / ') || '-' }}</td><td><div class="as-tag-list"><span v-for="tag in (provider.skills || provider.abilities || [])" :key="tag">{{ tag }}</span></div></td><td>{{ provider.monthOrders ?? provider.month_orders ?? 0 }} 单</td><td><span class="as-team-score"><Star />{{ formatScore(provider.score ?? provider.rating) }}</span></td><td><span class="as-status" :class="providerStatusClass(provider)">{{ providerStatus(provider) }}</span></td></tr></tbody></table></div>
      <ListPagination v-model:page-size="pagination.pageSize" :page="pagination.page" :total="pagination.total" :total-pages="pagination.totalPages" :loading="loading" label="服务团队分页" @change="pagination.page = $event" />
      </section>
      <ProjectDetailDrawer :open="drawerOpen" title="服务人员详情" @close="closeProviderDetail">

      <aside v-if="selectedProvider" class="as-panel as-team-detail">
        <div class="as-team-detail-head"><span class="as-team-detail-avatar">{{ initials(selectedProvider.name) }}</span><div><h2>{{ selectedProvider.name }}</h2><p>{{ display(selectedProvider, 'roleLabel', 'role_display', 'roleDisplay', 'role') }} · {{ display(selectedProvider, 'phone') }}</p></div></div>
        <div class="as-team-detail-actions"><button type="button" class="as-button as-button--secondary" @click="openContact"><Phone />联系人员</button><button type="button" class="as-button as-button--primary" @click="auditProvider"><ClipboardCheck />查看档案</button></div>
        <dl class="as-team-info-grid"><div><dt>认证状态</dt><dd>{{ providerStatus(selectedProvider) }}</dd></div><div><dt>最近活跃</dt><dd>{{ display(selectedProvider, 'lastActiveAt', 'last_active_at') }}</dd></div><div><dt>累计订单</dt><dd>{{ display(selectedProvider, 'totalOrders', 'total_orders') }} 单</dd></div><div><dt>服务评分</dt><dd>{{ formatScore(selectedProvider.score ?? selectedProvider.rating) }}</dd></div></dl>
        <section class="as-team-detail-section as-team-score-section"><div class="as-team-section-head"><h3>评分依据</h3><span>{{ selectedScoreSummary.count ? `${selectedScoreSummary.count} 条节点评分` : '暂无节点评分' }}</span></div><div class="as-team-score-summary"><strong>{{ formatScore(selectedScoreSummary.average) }}</strong><div><span>满分 5 分</span><small>{{ selectedScoreSummary.source === 'rating' ? '评分来自服务节点完成后的管理端确认' : selectedScoreSummary.source === 'manual' ? '当前使用人员档案中的基础评分' : '完成服务节点后由管理端评分' }}</small></div></div><div v-if="selectedScoreSummary.items.length" class="as-team-score-list"><article v-for="item in selectedScoreSummary.items.slice(0, 5)" :key="item.id"><span class="as-team-score"><Star />{{ formatScore(item.rating) }}</span><div><strong>{{ item.projectName || '服务项目' }}<template v-if="item.nodeName"> · {{ item.nodeName }}</template></strong><small>节点完成评分 · {{ item.ratedAt || '-' }}</small></div></article></div></section>
        <section class="as-team-detail-section"><h3>能力标签</h3><div class="as-tag-list"><span v-for="item in (selectedProvider.skills || selectedProvider.abilities || [])" :key="item" class="is-skill">{{ item }}</span><span v-if="!(selectedProvider.skills || selectedProvider.abilities || []).length">暂无能力标签</span></div></section>
        <section v-if="canManage" class="as-team-detail-section"><h3>状态操作</h3><div class="as-team-certification-actions"><button v-if="(selectedProvider.certificationStatus || selectedProvider.certification_status) === 'pending'" type="button" class="as-button as-button--primary" :disabled="saving" @click="updateCertification('certified')"><ShieldCheck />审核通过</button><button v-else-if="(selectedProvider.certificationStatus || selectedProvider.certification_status) === 'paused'" type="button" class="as-button as-button--primary" :disabled="saving" @click="updateCertification('certified')"><RotateCcw />恢复服务</button><button v-else type="button" class="as-button as-button--danger" :disabled="saving" @click="updateCertification('paused')">暂停服务</button></div></section>
         <section class="as-team-detail-section"><h3>最近安装记录</h3><div v-if="!selectedServiceRecords.length" class="as-empty as-empty--compact">暂无服务记录</div><button v-for="(item, index) in selectedServiceRecords" v-else :key="item.id || index" type="button" class="as-team-record"><strong>{{ recordTitle(item) }}</strong><span>{{ recordMeta(item) }}</span></button></section>
        <section v-if="canManage" class="as-team-detail-section"><h3>服务奖励</h3><div v-if="!selectedRewards.length" class="as-empty as-empty--compact">暂无服务奖励</div><button v-for="reward in selectedRewards" v-else :key="reward.id" type="button" class="as-team-record"><strong>{{ display(reward, 'title', 'prize', 'name') }}</strong><span>{{ display(reward, 'statusLabel', 'status_display', 'status') }} · {{ display(reward, 'description', 'remark') }}</span></button></section>
      </aside>
      <div v-else class="as-panel as-team-detail as-empty as-empty--large"><Users /> 选择一名服务人员查看详情</div>
      </ProjectDetailDrawer>
      </div>
    </section>

    <ModalShell :open="archiveOpen" title="实名档案" :description="selectedProvider ? `${selectedProvider.name} · ${display(selectedProvider, 'roleLabel', 'role_display', 'roleDisplay', 'role')}` : '请选择服务人员查看档案。'" wide @close="archiveOpen = false">
      <template v-if="selectedProvider">
        <div class="as-team-archive-head"><span class="as-team-detail-avatar">{{ initials(selectedProvider.name) }}</span><div><h3>{{ selectedProvider.name }}</h3><p>{{ providerStatus(selectedProvider) }} · {{ display(selectedProvider, 'phone') }}</p></div></div>
        <dl class="as-team-archive-grid"><div><dt>服务身份</dt><dd>{{ display(selectedProvider, 'roleLabel', 'role_display', 'roleDisplay', 'role') }}</dd></div><div><dt>认证状态</dt><dd>{{ providerStatus(selectedProvider) }}</dd></div><div><dt>所在城市</dt><dd>{{ display(selectedProvider, 'city') }}</dd></div><div><dt>联系电话</dt><dd>{{ display(selectedProvider, 'phone') }}</dd></div><div><dt>服务评分</dt><dd>{{ formatScore(selectedProvider.score ?? selectedProvider.rating) }}</dd></div><div><dt>本月订单</dt><dd>{{ selectedProvider.monthOrders ?? selectedProvider.month_orders ?? 0 }} 单</dd></div><div><dt>累计订单</dt><dd>{{ selectedProvider.totalOrders ?? selectedProvider.total_orders ?? 0 }} 单</dd></div><div><dt>最近活跃</dt><dd>{{ display(selectedProvider, 'lastActiveAt', 'last_active_at') }}</dd></div></dl>
        <section class="as-team-archive-section"><h3>服务区域</h3><div class="as-tag-list"><span v-for="item in (selectedProvider.regions || [selectedProvider.city]).filter(Boolean)" :key="item">{{ item }}</span><span v-if="!(selectedProvider.regions || [selectedProvider.city]).filter(Boolean).length">未设置地区</span></div></section>
        <section class="as-team-archive-section"><h3>能力标签</h3><div class="as-tag-list"><span v-for="item in (selectedProvider.skills || selectedProvider.abilities || [])" :key="item" class="is-skill">{{ item }}</span><span v-if="!(selectedProvider.skills || selectedProvider.abilities || []).length">暂无能力标签</span></div></section>
        <section class="as-team-archive-section"><h3>人员简介</h3><p class="as-team-archive-bio">{{ display(selectedProvider, 'bio') }}</p></section>
        <section class="as-team-archive-section as-team-archive-attachments"><h3>资质与档案附件</h3><AttachmentPanel target-type="provider_application" :target-id="selectedProvider.id" :categories="PROVIDER_ARCHIVE_CATEGORIES" :editable="false" compact @error="error = $event" /></section>
      </template>
      <template #footer><button type="button" class="as-button as-button--secondary" @click="archiveOpen = false">关闭</button></template>
    </ModalShell>

    <ModalShell :open="contactOpen" title="联系人员" :description="selectedProvider ? `${selectedProvider.name} · ${display(selectedProvider, 'roleLabel', 'role_display', 'roleDisplay', 'role')} · ${display(selectedProvider, 'city')}` : '请选择安装人员后联系。'" wide @close="contactOpen = false"><template v-if="selectedProvider"><div class="as-info-grid"><div><dt>联系电话</dt><dd>{{ display(selectedProvider, 'phone') }}</dd></div><div><dt>认证状态</dt><dd>{{ providerStatus(selectedProvider) }}</dd></div><div><dt>服务评分</dt><dd>{{ formatScore(selectedProvider.score ?? selectedProvider.rating) }}</dd></div><div><dt>累计订单</dt><dd>{{ display(selectedProvider, 'totalOrders', 'total_orders') }} 单</dd></div></div><div class="as-team-modal-section"><h3>服务区域</h3><div class="as-tag-list"><span v-for="item in (selectedProvider.regions || [selectedProvider.city]).filter(Boolean)" :key="item">{{ item }}</span></div></div></template><template #footer><button type="button" class="as-button as-button--secondary" @click="contactOpen = false">关闭</button></template></ModalShell>

    <ModalShell :open="capabilityOpen" title="编辑能力标签" :description="editedCapabilityNode ? `${editedCapabilityNode.serviceTypeLabel} · ${editedCapabilityNode.nodeName}` : '按业务节点维护能力选项'" @close="capabilityOpen = false"><div class="as-capability-editor"><label class="as-field"><span>一级业务节点</span><select v-model="capabilityNodeValue" @change="syncCapabilityDraft"><optgroup v-for="group in capabilityGroups" :key="group.serviceType" :label="group.serviceTypeLabel"><option v-for="node in group.nodes" :key="`${group.serviceType}:${node.nodeKey}`" :value="`${group.serviceType}:${node.nodeKey}`">{{ node.nodeName }}</option></optgroup></select></label><div class="as-capability-list"><div v-for="(_name, index) in capabilityDraft" :key="index" class="as-capability-row"><input v-model="capabilityDraft[index]" maxlength="128" :aria-label="`能力标签 ${index + 1}`"><button type="button" class="as-icon-button" title="删除能力标签" aria-label="删除能力标签" :disabled="capabilityDraft.length <= 1" @click="removeCapabilityTag(index)"><X /></button></div></div><button type="button" class="as-button as-button--secondary" :disabled="capabilityDraft.length >= 50" @click="addCapabilityTag"><Plus />添加能力</button></div><template #footer><button type="button" class="as-button as-button--secondary" @click="capabilityOpen = false">取消</button><button type="button" class="as-button as-button--primary" :disabled="capabilitySaving" @click="saveCapabilityTags"><LoaderCircle v-if="capabilitySaving" class="as-spin" /><Check v-else />保存能力</button></template></ModalShell>
  </div>
</template>

<style scoped>
.as-team-page { max-width: 1680px; }
.as-team-view-tabs { margin-bottom: 14px; }
.as-team-tab-panel { min-width: 0; }
.as-team-coverage-view :deep(.as-team-coverage-map) { margin-bottom: 0; }
.as-team-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.as-team-metrics article { display: grid; min-height: 94px; align-content: center; gap: 5px; border: 1px solid var(--as-border); border-radius: 8px; background: #fff; padding: 14px; }
.as-team-metrics span, .as-team-metrics small { color: var(--as-muted); font-size: 11px; }
.as-team-metrics strong { color: #182230; font-size: 27px; line-height: 29px; }
.as-team-metrics small { color: var(--as-positive-text, var(--as-success)); font-size: 10px; font-weight: 700; }
.as-team-layout { display: block; }
.as-team-main-column { min-width: 0; overflow: hidden; }
.as-team-toolbar { display: none; }
.as-team-status-tabs { display: inline-grid; grid-template-columns: repeat(4, minmax(45px, 1fr)); overflow: hidden; border: 1px solid var(--as-border); border-radius: 7px; background: #fff; }
.as-team-status-tabs button { min-width: 0; min-height: 34px; border: 0; border-right: 1px solid var(--as-border); background: #fff; color: #526273; font-size: 9px; font-weight: 750; }
.as-team-status-tabs button:last-child { border-right: 0; }
.as-team-status-tabs button.active { background: #eaf3ff; color: var(--as-primary); }
.as-team-table-card { overflow: auto; border: 0; border-radius: 0; background: #fff; }
.as-team-table-card table { width: 100%; min-width: 900px; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
.as-team-table-card th, .as-team-table-card td { border-right: 1px solid #e8eef5; border-bottom: 1px solid #edf0f2; padding: 12px 11px; color: #526273; font-size: 10px; text-align: left; vertical-align: middle; }
.as-team-table-card th:last-child, .as-team-table-card td:last-child { border-right: 0; }
.as-team-table-card th { position: sticky; top: 0; z-index: 2; height: 42px; background: #f1f6fb; color: #3f5874; font-size: 10px; font-weight: 850; }
.as-team-table-filter-row th { top: 42px; height: 44px; background: #fff; padding: 6px 8px; }
.as-team-table-filter-row .as-search input { height: 28px; padding-left: 29px; font-size: 11px; }
.as-team-table-card th.as-team-person-col { width: 25%; }
.as-team-table-card tbody tr { cursor: pointer; background: #fff; }
.as-team-table-card tbody tr:hover, .as-team-table-card tbody tr.selected { background: #eef6ff; }
.as-team-table-card tbody tr:last-child td { border-bottom: 0; }
.as-team-table-empty { height: 120px; color: var(--as-muted); text-align: center !important; }
.as-team-table-empty svg { width: 14px; height: 14px; vertical-align: middle; }
.as-team-person { display: flex; min-width: 0; align-items: center; gap: 8px; }
.as-team-person > span:last-child { min-width: 0; }
.as-team-person strong, .as-team-person small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.as-team-person strong { color: #243145; font-size: 11px; }
.as-team-person small { margin-top: 3px; color: var(--as-muted); font-size: 9px; }
.as-team-avatar, .as-team-detail-avatar { display: flex; width: 32px; height: 32px; flex: 0 0 auto; align-items: center; justify-content: center; border-radius: 7px; background: #1677ff; color: #fff; font-size: 12px; font-weight: 850; }
.as-team-score { display: inline-flex; align-items: center; gap: 3px; color: #b77905; font-weight: 800; }
.as-team-score svg { width: 12px; height: 12px; fill: currentColor; }
.as-team-detail { display: grid; min-width: 0; min-height: 100%; grid-template-columns: repeat(2, minmax(0, 1fr)); align-content: start; gap: 12px; overflow: auto; border: 0; border-radius: 0; background: #f4f7fb; padding: 14px 16px 18px; box-shadow: none; }
.as-team-detail-head { display: flex; min-height: 104px; grid-column: 1 / -1; align-items: center; gap: 12px; border: 1px solid #dbe5ef; border-radius: 8px; background: #fff; padding: 16px 18px; }
.as-team-detail-head > div { min-width: 0; }
.as-team-detail-head h2 { overflow: hidden; margin: 0; color: #182230; font-size: 19px; line-height: 25px; text-overflow: ellipsis; white-space: nowrap; }
.as-team-detail-head p { overflow: hidden; margin: 4px 0 0; color: var(--as-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.as-team-detail-avatar { width: 42px; height: 42px; font-size: 16px; }
.as-team-detail-actions { display: flex; min-height: 58px; grid-column: 1 / -1; align-items: center; gap: 8px; border: 1px solid #dbe5ef; border-radius: 8px; background: #fff; padding: 10px 14px; }
.as-team-detail-actions .as-button { min-height: 32px; font-size: 10px; }
.as-team-info-grid { display: grid; grid-column: 1 / -1; grid-template-columns: repeat(4, minmax(0, 1fr)); overflow: hidden; margin: 0; border: 1px solid #dbe5ef; border-radius: 8px; background: #fff; }
.as-team-info-grid > div { min-width: 0; min-height: 58px; border-right: 1px solid #edf0f2; border-bottom: 1px solid #edf0f2; padding: 9px 11px; }
.as-team-info-grid > div:nth-child(2n) { border-right: 1px solid #edf0f2; }
.as-team-info-grid > div:nth-child(4n) { border-right: 0; }
.as-team-info-grid dt { color: var(--as-muted); font-size: 9px; }
.as-team-info-grid dd { overflow: hidden; margin: 4px 0 0; color: #344054; font-size: 10px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.as-team-detail-section { min-width: 0; border: 1px solid #dbe5ef; border-radius: 8px; background: #fff; padding: 14px 16px; }
.as-team-detail-section h3, .as-team-modal-section h3 { margin: 0 0 10px; color: #172033; font-size: 13px; }
.as-team-score-section { grid-column: 1 / -1; }
.as-team-section-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.as-team-section-head h3 { margin-bottom: 0; }
.as-team-section-head > span { color: var(--as-muted); font-size: 9px; }
.as-team-score-summary { display: flex; align-items: center; gap: 10px; margin-top: 12px; border: 1px solid #f2e0ad; border-radius: 7px; background: #fffaf0; padding: 10px 12px; }
.as-team-score-summary > strong { color: #9b6500; font-size: 23px; line-height: 25px; }
.as-team-score-summary > div { display: grid; gap: 2px; }
.as-team-score-summary span { color: #7c5b1e; font-size: 10px; font-weight: 750; }
.as-team-score-summary small { color: #a3834c; font-size: 9px; }
.as-team-score-list { display: grid; gap: 0; margin-top: 8px; }
.as-team-score-list article { display: flex; min-width: 0; align-items: center; gap: 9px; border-bottom: 1px solid #edf0f2; padding: 8px 0; }
.as-team-score-list article:last-child { border-bottom: 0; }
.as-team-score-list article > div { min-width: 0; }
.as-team-score-list article strong, .as-team-score-list article small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.as-team-score-list article strong { color: #344054; font-size: 10px; }
.as-team-score-list article small { margin-top: 3px; color: var(--as-muted); font-size: 9px; }
.as-team-certification-actions { display: flex; justify-content: flex-start; }
.as-team-certification-actions .as-button { min-height: 32px; font-size: 10px; }
.as-team-record { display: grid; width: 100%; gap: 3px; border: 0; border-bottom: 1px solid #edf0f2; background: #fff; padding: 7px 0; text-align: left; }
.as-team-record:last-child { border-bottom: 0; }
.as-team-record:hover { background: #f8fbff; }
.as-team-record strong { overflow: hidden; color: #344054; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.as-team-record span { overflow: hidden; color: var(--as-muted); font-size: 9px; line-height: 14px; text-overflow: ellipsis; white-space: nowrap; }
.as-team-modal-section { border-top: 1px solid #edf0f2; padding-top: 12px; }
.as-team-archive-head { display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #e4ebf3; padding-bottom: 14px; }
.as-team-archive-head > div { min-width: 0; }
.as-team-archive-head h3 { margin: 0; color: #172033; font-size: 17px; }
.as-team-archive-head p { margin: 4px 0 0; color: var(--as-muted); font-size: 10px; }
.as-team-archive-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); overflow: hidden; margin: 14px 0 0; border: 1px solid #dbe5ef; border-radius: 7px; }
.as-team-archive-grid > div { min-width: 0; min-height: 58px; border-right: 1px solid #edf0f2; border-bottom: 1px solid #edf0f2; padding: 9px 11px; }
.as-team-archive-grid > div:nth-child(4n) { border-right: 0; }
.as-team-archive-grid dt { color: var(--as-muted); font-size: 9px; }
.as-team-archive-grid dd { overflow: hidden; margin: 4px 0 0; color: #344054; font-size: 10px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.as-team-archive-section { margin-top: 14px; border-top: 1px solid #edf0f2; padding-top: 13px; }
.as-team-archive-section h3 { margin: 0 0 10px; color: #172033; font-size: 12px; }
.as-team-archive-bio { margin: 0; color: #526273; font-size: 10px; line-height: 1.7; white-space: pre-wrap; }
.as-team-archive-attachments :deep(.as-attachment-group__head label) { display: none; }
@media (max-width: 720px) { .as-team-archive-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .as-team-archive-grid > div:nth-child(2n) { border-right: 0; } }
@media (max-width: 820px) { .as-team-detail { grid-template-columns: minmax(0, 1fr); } .as-team-detail-head, .as-team-detail-actions, .as-team-info-grid { grid-column: 1; } .as-team-info-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .as-team-info-grid > div:nth-child(2n) { border-right: 0; } }
@media (max-width: 1180px) { .as-team-layout { grid-template-columns: minmax(0, 1fr); } .as-team-detail { min-height: 400px; } }
@media (max-width: 940px) { .as-team-toolbar { grid-template-columns: repeat(2, minmax(0, 1fr)); } .as-team-toolbar .as-search { grid-column: 1 / -1; } .as-team-status-tabs { grid-column: 1 / -1; } }
@media (max-width: 620px) { .as-team-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .as-team-toolbar { grid-template-columns: minmax(0, 1fr); } .as-team-toolbar .as-search, .as-team-toolbar .as-select, .as-team-status-tabs { grid-column: auto; } }
</style>
