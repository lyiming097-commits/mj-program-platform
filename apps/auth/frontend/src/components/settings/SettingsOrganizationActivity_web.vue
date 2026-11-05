<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { Clock3, RefreshCw, X } from "@lucide/vue";
import { PlatformDetailDrawer } from "@platform-ui";
import { apiGet } from "@/api";
import { formatOrganizationSyncTime } from "@/organization-sync-time";
const props = defineProps({
  lastSyncLabel: String,
  syncRun: Object,
  syncStatus: String,
  busy: Boolean,
  canSync: Boolean,
  canManageAccounts: Boolean,
});
const emit = defineEmits(["sync", "refresh", "drawer-change"]);
const drawer = ref("");
const records = ref([]),
  total = ref(0),
  offset = ref(0),
  loading = ref(false),
  error = ref("");
let requestId = 0;
const title = computed(() =>
  drawer.value === "sync" ? "通讯录同步详情" : "账号操作记录",
);
const stateLabel = computed(() =>
  props.syncStatus === "error"
    ? "状态获取失败"
    : { running: "同步中", succeeded: "正常", failed: "同步失败" }[
        props.syncRun?.status
      ] || "暂无同步任务",
);
const changes = computed(() => [
  ["新增部门", props.syncRun?.summary?.departmentAddedCount],
  ["移除部门", props.syncRun?.summary?.departmentRemovedCount],
  ["新增/返职人员", props.syncRun?.summary?.employeeAddedCount],
  ["本次未同步到的人员", props.syncRun?.summary?.employeeMissingCount],
]);
async function loadRecords() {
  const seq = ++requestId;
  loading.value = true;
  error.value = "";
  try {
    const data = await apiGet("/api/org/account-operations", {
      offset: offset.value,
    });
    if (seq === requestId) {
      records.value = data.items || [];
      total.value = data.total || 0;
    }
  } catch (reason) {
    if (seq === requestId) error.value = reason.message || "操作记录加载失败";
  } finally {
    if (seq === requestId) loading.value = false;
  }
}
function openRecords() {
  offset.value = 0;
  drawer.value = "records";
  void loadRecords();
}
function page(delta) {
  offset.value += delta * 20;
  void loadRecords();
}
watch(drawer, (value) => {
  emit("drawer-change", Boolean(value));
  if (!value) ++requestId;
});
onBeforeUnmount(() => {
  ++requestId;
  emit("drawer-change", false);
});
</script>
<template>
  <div class="space-y-3">
    <template v-if="canSync">
      <section class="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500" aria-label="通讯录同步状态">
        <div class="flex flex-wrap items-center gap-2">
          <Clock3 class="h-4 w-4 shrink-0" aria-hidden="true" />
          <span aria-live="polite">{{ lastSyncLabel }}</span>
          <span :class="syncRun?.status === 'failed' || syncStatus === 'error' ? 'text-red-700' : 'text-slate-600'">{{ stateLabel }}</span>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <button type="button" class="org-text-button" @click="drawer = 'sync'; emit('refresh')">
            查看变更数量
          </button>
          <button v-if="syncStatus === 'error'" type="button" class="org-text-button" @click="emit('refresh')">
            重试读取状态
          </button>
        </div>
        <p v-if="syncRun?.status === 'failed'" class="break-words text-red-700" role="alert">
          {{ syncRun.error || "同步失败，请重试" }}
        </p>
      </section>
      <button
        type="button"
        class="desktop-action-option desktop-action-option-sync"
        :aria-label="syncRun?.status === 'failed' ? '重试同步' : '同步通讯录'"
        :disabled="busy || syncRun?.status === 'running'"
        @click="emit('sync')"
      >
        <span class="desktop-action-option-main">
          <span class="desktop-action-option-icon"><RefreshCw class="h-4 w-4" :class="{ 'animate-spin': syncRun?.status === 'running' }" aria-hidden="true" /></span>
          <span class="desktop-action-option-copy">
            <span class="desktop-action-option-title">{{ syncRun?.status === "failed" ? "重试同步" : "同步通讯录" }}</span>
            <span class="desktop-action-option-meta">拉取最新组织通讯录</span>
          </span>
        </span>
        <span class="desktop-action-option-state">{{ syncRun?.status === "running" ? "同步中" : "执行" }}</span>
      </button>
    </template>
    <button
      v-if="canManageAccounts"
      type="button"
      class="desktop-action-option"
      aria-label="账号操作记录"
      @click="openRecords"
    >
      <span class="desktop-action-option-main">
        <span class="desktop-action-option-icon"><Clock3 class="h-4 w-4" aria-hidden="true" /></span>
        <span class="desktop-action-option-copy">
          <span class="desktop-action-option-title">账号操作记录</span>
          <span class="desktop-action-option-meta">查看账号启用、禁用历史</span>
        </span>
      </span>
      <span class="desktop-action-option-state">查看</span>
    </button>
  </div>
  <PlatformDetailDrawer
    :open="Boolean(drawer)"
    labelled-by="org-activity-title"
    @close="drawer = ''"
  >
    <div class="auth-org-surface flex h-full min-h-0 flex-col">
      <header
        class="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white p-4"
      >
        <div class="flex items-center gap-3">
          <span
            class="flex h-10 w-10 items-center justify-center rounded-full bg-blue-50 text-blue-600"
            ><Clock3 class="h-5 w-5" aria-hidden="true"
          /></span>
          <h2 id="org-activity-title" class="text-base font-semibold">
            {{ title }}
          </h2>
        </div>
        <button
          type="button"
          class="org-button"
          aria-label="关闭记录详情"
          @click="drawer = ''"
        >
          <X class="h-4 w-4" aria-hidden="true" />
        </button>
      </header>
      <div class="min-h-0 flex-1 space-y-3 overflow-y-auto bg-slate-100 p-4">
        <section
          v-if="drawer === 'sync'"
          class="rounded-lg border border-slate-200 bg-white p-4"
        >
          <h3 class="border-l-4 border-blue-600 pl-2 text-sm font-semibold">
            最近一次同步
          </h3>
          <p class="mt-3 text-sm">{{ lastSyncLabel }} · {{ stateLabel }}</p>
          <p
            v-if="syncRun?.error"
            class="mt-2 break-words text-sm text-red-700"
            role="alert"
          >
            {{ syncRun.error }}
          </p>
          <dl
            v-if="syncRun?.status === 'succeeded'"
            class="mt-4 grid grid-cols-2 gap-4"
          >
            <div v-for="[label, value] in changes" :key="label">
              <dt class="text-xs text-slate-500">{{ label }}</dt>
              <dd class="mt-1 text-base font-semibold tabular-nums">
                {{ value ?? "未记录" }}
              </dd>
            </div>
          </dl>
          <p
            v-if="syncRun?.summary?.userDetailFallbackCount"
            class="mt-3 text-sm text-amber-700"
          >
            {{
              syncRun.summary.userDetailFallbackCount
            }}
            人详情读取失败，已保留原资料。
          </p>
          <p class="mt-4 text-xs leading-5 text-slate-500">
            同步失败时保留上次成功数据。新增部门默认不启用，可在“启用范围”中检查。
          </p>
          <button
            type="button"
            class="org-button mt-3"
            @click="emit('refresh')"
          >
            刷新状态
          </button>
        </section>
        <template v-else>
          <p v-if="loading" role="status" class="text-sm text-slate-500">
            正在加载操作记录
          </p>
          <div v-else-if="error" role="alert">
            <p class="text-sm text-red-700">{{ error }}</p>
            <button type="button" class="org-button mt-2" @click="loadRecords">
              重新加载
            </button>
          </div>
          <p v-else-if="!records.length" class="text-sm text-slate-500">
            暂无账号操作记录。此功能上线后的账号启停会在这里记录。
          </p>
          <section
            v-for="record in loading || error ? [] : records"
            :key="record.id"
            class="rounded-lg border border-slate-200 bg-white p-4"
          >
            <h3 class="border-l-4 border-blue-600 pl-2 text-sm font-semibold">
              {{ record.accountStatus }} {{ record.count }} 人 ·
              {{ record.scope === "all" ? "全部在职账号" : "单个账号" }}
            </h3>
            <p class="mt-2 text-xs text-slate-500">
              {{ record.actorName }} ·
              {{ formatOrganizationSyncTime(record.createdAt) }}
            </p>
            <p
              v-if="record.actorUserId !== record.effectiveUserId"
              class="mt-1 text-xs text-slate-500"
            >
              通过 {{ record.effectiveName }} 的代理身份操作
            </p>
            <details class="mt-3 text-sm">
              <summary tabindex="0" class="cursor-pointer text-blue-600">
                受影响人员（{{ record.count }}）
              </summary>
              <ul class="mt-2 divide-y divide-slate-100">
                <li
                  v-for="item in record.changes"
                  :key="item.userId"
                  class="flex flex-wrap justify-between gap-2 py-2"
                >
                  <span
                    >{{ item.name }}
                    <small class="text-slate-500">{{
                      item.userId
                    }}</small></span
                  ><span>{{ item.before }} → {{ item.after }}</span>
                </li>
              </ul>
            </details>
          </section>
        </template>
      </div>
      <footer
        v-if="drawer === 'records'"
        class="flex shrink-0 items-center justify-center gap-3 border-t border-slate-200 bg-white p-3 text-sm"
      >
        <button
          type="button"
          class="org-button"
          :disabled="loading || offset === 0"
          @click="page(-1)"
        >
          上一页</button
        ><span>共 {{ total }} 条 · 第 {{ Math.floor(offset / 20) + 1 }} 页</span
        ><button
          type="button"
          class="org-button"
          :disabled="loading || offset + 20 >= total"
          @click="page(1)"
        >
          下一页
        </button>
      </footer>
    </div>
  </PlatformDetailDrawer>
</template>
