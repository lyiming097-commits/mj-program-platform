<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { Gift, LoaderCircle, Pencil, Plus, RotateCcw, Save, Search, X } from "@lucide/vue";
import GlobalNotice from "@/components/GlobalNotice.vue";
import ModalShell from "@/components/ModalShell.vue";
import { serviceApi } from "@/serviceApi";

const props = defineProps({ active: { type: Boolean, default: false } });
const emit = defineEmits(["dirty-change"]);
const rows = ref([]);
const loading = ref(true);
const loadError = ref("");
const busy = ref(false);
const error = ref("");
const success = ref("");
const search = ref("");
const newName = ref("");
const editingId = ref(null);
const editingName = ref("");
const editingOriginal = ref("");
const editInput = ref(null);
const pendingToggle = ref(null);

const visibleRows = computed(() => rows.value.filter((item) => item.name.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())));
const enabledCount = computed(() => rows.value.filter((item) => item.enabled).length);
const dirty = computed(() => Boolean(newName.value.trim()) || (editingId.value !== null && editingName.value.trim() !== editingOriginal.value));
watch(dirty, (value) => emit("dirty-change", value), { immediate: true });
watch(() => props.active, (active) => { if (!active) discardDrafts(); });

function discardDrafts() {
  newName.value = "";
  editingId.value = null;
  editingName.value = "";
  editingOriginal.value = "";
  pendingToggle.value = null;
}
defineExpose({ discardDrafts });

function showSuccess(message) {
  success.value = message;
  window.setTimeout(() => { if (success.value === message) success.value = ""; }, 2600);
}

async function load() {
  loading.value = true;
  loadError.value = "";
  error.value = "";
  try {
    const response = await serviceApi.listRewardPrizes();
    rows.value = Array.isArray(response?.items) ? response.items : [];
  } catch (reason) {
    loadError.value = reason instanceof Error ? reason.message : "实物奖品加载失败";
  } finally {
    loading.value = false;
  }
}

async function addPrize() {
  const name = newName.value.trim();
  if (!name || busy.value || loading.value || loadError.value) return;
  busy.value = true;
  error.value = "";
  try {
    const response = await serviceApi.createRewardPrize({ name });
    rows.value = [...rows.value, response.item];
    newName.value = "";
    showSuccess("奖品已添加");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "添加奖品失败";
  } finally {
    busy.value = false;
  }
}

async function editPrize(item) {
  editingId.value = item.id;
  editingOriginal.value = item.name;
  editingName.value = item.name;
  await nextTick();
  editInput.value?.[0]?.focus();
}

function cancelEdit() {
  editingId.value = null;
  editingName.value = "";
  editingOriginal.value = "";
}

async function updatePrize(id, changes, message) {
  if (busy.value) return false;
  busy.value = true;
  error.value = "";
  try {
    const response = await serviceApi.updateRewardPrize(id, changes);
    rows.value = rows.value.map((row) => row.id === id ? response.item : row);
    showSuccess(message);
    return true;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "奖品更新失败";
    return false;
  } finally {
    busy.value = false;
  }
}

async function saveEdit() {
  const name = editingName.value.trim();
  if (!name || editingId.value === null) return;
  if (name === editingOriginal.value || await updatePrize(editingId.value, { name }, "奖品名称已更新")) cancelEdit();
}

async function confirmToggle() {
  const item = pendingToggle.value;
  if (!item) return;
  if (await updatePrize(item.id, { enabled: !item.enabled }, item.enabled ? "奖品已停用" : "奖品已启用")) {
    pendingToggle.value = null;
  }
}

function closeToggle() {
  if (!busy.value) pendingToggle.value = null;
}

onMounted(load);
</script>

<template>
  <section class="as-settings-panel as-prize-settings" aria-labelledby="prize-settings-title">
    <GlobalNotice v-model:error="error" v-model:success="success" />
    <div class="as-settings-panel-head"><div><h2 id="prize-settings-title">实物奖励</h2><p>停用的奖品不会出现在新增奖励中，已发放记录仍保留原名称。</p></div></div>
    <div class="as-prize-controls">
      <form class="as-prize-add" @submit.prevent="addPrize"><label for="new-prize-name">奖品名称</label><div><input id="new-prize-name" v-model="newName" maxlength="255" :disabled="busy || loading || Boolean(loadError)" placeholder="输入奖品名称"><button type="submit" class="as-button as-button--primary" :disabled="busy || loading || Boolean(loadError) || !newName.trim()"><Plus />添加奖品</button></div></form>
      <label class="as-prize-search"><Search /><input v-model="search" type="search" aria-label="搜索实物奖品" placeholder="搜索奖品"></label>
    </div>
    <div class="as-prize-list-head"><strong>奖品目录</strong><span>{{ enabledCount }} 个可用 · {{ rows.length }} 个合计</span></div>
    <div v-if="loading" class="as-prize-empty" role="status"><LoaderCircle class="as-spin" />正在加载奖品...</div>
    <div v-else-if="loadError" class="as-prize-empty" role="alert">{{ loadError }}<button type="button" class="as-button as-button--secondary" @click="load">重试</button></div>
    <div v-else-if="!rows.length" class="as-prize-empty"><Gift />暂无实物奖品</div>
    <div v-else-if="!visibleRows.length" class="as-prize-empty">没有匹配的奖品</div>
    <ul v-else class="as-prize-list">
      <li v-for="item in visibleRows" :key="item.id" class="as-prize-row">
        <template v-if="editingId === item.id">
          <input ref="editInput" v-model="editingName" maxlength="255" :aria-label="`修改${item.name}名称`" :disabled="busy" @keydown.enter.prevent="saveEdit" @keydown.esc="cancelEdit">
          <span class="as-prize-status" :class="{ 'is-off': !item.enabled }">{{ item.enabled ? '可用' : '已停用' }}</span>
          <div class="as-prize-actions"><button type="button" class="as-button as-button--primary" :disabled="busy || !editingName.trim()" @click="saveEdit"><Save />保存</button><button type="button" class="as-button as-button--secondary" :disabled="busy" @click="cancelEdit"><X />取消</button></div>
        </template>
        <template v-else>
          <strong :class="{ 'is-off': !item.enabled }">{{ item.name }}</strong>
          <span class="as-prize-status" :class="{ 'is-off': !item.enabled }">{{ item.enabled ? '可用' : '已停用' }}</span>
          <div class="as-prize-actions"><button type="button" class="as-button as-button--secondary" :disabled="busy || editingId !== null" @click="editPrize(item)"><Pencil />修改</button><button type="button" class="as-button as-button--secondary" :disabled="busy || editingId !== null" @click="pendingToggle = item"><RotateCcw v-if="!item.enabled" /><X v-else />{{ item.enabled ? '停用' : '启用' }}</button></div>
        </template>
      </li>
    </ul>
    <ModalShell :open="Boolean(pendingToggle)" :title="pendingToggle?.enabled ? '停用奖品' : '启用奖品'" :description="pendingToggle?.name || ''" @close="closeToggle">
      <p>{{ pendingToggle?.enabled ? '停用后，新增奖励将无法再选择此奖品；历史奖励不受影响。' : '启用后，此奖品会重新出现在新增奖励的选项中。' }}</p>
      <template #footer><button type="button" class="as-button as-button--secondary" :disabled="busy" @click="closeToggle">取消</button><button type="button" class="as-button" :class="pendingToggle?.enabled ? 'as-button--danger' : 'as-button--primary'" :disabled="busy" @click="confirmToggle">{{ busy ? '处理中...' : pendingToggle?.enabled ? '确认停用' : '确认启用' }}</button></template>
    </ModalShell>
  </section>
</template>

<style scoped>
.as-prize-settings { display: grid; min-width: 0; gap: 14px; border: 1px solid var(--as-border); border-radius: 8px; background: #fff; padding: 16px; }
.as-settings-panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; border-bottom: 1px solid #edf0f2; padding-bottom: 13px; }
.as-settings-panel-head h2 { margin: 0; color: #182230; font-size: 16px; }
.as-settings-panel-head p { margin: 4px 0 0; color: var(--as-muted); font-size: 12px; line-height: 18px; }
.as-prize-controls { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; }
.as-prize-add { display: grid; width: min(100%, 520px); gap: 6px; }
.as-prize-add label { color: #475569; font-size: 12px; font-weight: 600; }
.as-prize-add > div { display: flex; gap: 8px; }
.as-prize-add input, .as-prize-row input, .as-prize-search input { min-width: 0; height: 36px; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; padding: 0 10px; color: #0f172a; font-size: 13px; }
.as-prize-add input { flex: 1; }
.as-prize-add button { flex: 0 0 auto; }
.as-prize-search { display: flex; width: min(100%, 270px); height: 36px; align-items: center; gap: 5px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 0 10px; }
.as-prize-search svg { width: 16px; height: 16px; color: #64748b; }
.as-prize-search input { width: 100%; height: 32px; border: 0; padding: 0; outline: 0; }
.as-prize-list-head { display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #e2e8f0; padding: 8px 0 10px; color: #334155; font-size: 13px; }
.as-prize-list-head span { color: #64748b; font-size: 12px; }
.as-prize-list { margin: 0; padding: 0; list-style: none; }
.as-prize-row { display: grid; min-height: 54px; grid-template-columns: minmax(0, 1fr) 70px auto; align-items: center; gap: 12px; border-bottom: 1px solid #e2e8f0; padding: 8px 0; }
.as-prize-row > strong { min-width: 0; overflow-wrap: anywhere; color: #0f172a; font-size: 13px; font-weight: 600; }
.as-prize-row > strong.is-off { color: #64748b; }
.as-prize-status { color: #047857; font-size: 12px; }
.as-prize-status.is-off { color: #64748b; }
.as-prize-actions { display: flex; justify-content: flex-end; gap: 6px; }
.as-prize-actions .as-button { min-height: 32px; padding: 0 9px; font-size: 12px; }
.as-prize-actions svg, .as-prize-add svg { width: 14px; height: 14px; }
.as-prize-empty { display: flex; min-height: 130px; align-items: center; justify-content: center; gap: 8px; color: #64748b; font-size: 13px; }
.as-prize-empty svg { width: 18px; height: 18px; }
@media (max-width: 700px) { .as-prize-controls { flex-wrap: wrap; gap: 12px; } .as-prize-search { width: 100%; } .as-prize-row { grid-template-columns: minmax(0, 1fr) 60px; } .as-prize-actions { grid-column: 1 / -1; justify-content: flex-start; } }
</style>
