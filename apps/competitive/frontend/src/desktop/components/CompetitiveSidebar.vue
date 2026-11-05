<script setup>
import { Archive } from "lucide-vue-next";

defineProps({
  access: { type: Object, required: true },
  activeItemId: { type: String, default: "" },
  items: { type: Array, default: () => [] },
  metrics: { type: Object, default: null },
  ready: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  error: { type: String, default: "" },
});

const emit = defineEmits(["item-click", "retry"]);
</script>

<template>
  <aside class="competitive-sidebar">
    <div class="sidebar-head">
      <span class="module-icon"><Archive :size="20" /></span>
      <strong>竞品情报中心</strong>
    </div>

    <nav v-if="ready" class="sidebar-nav" aria-label="主导航">
      <button
        v-for="item in items"
        :key="item.id"
        type="button"
        class="sidebar-item"
        :class="{ active: activeItemId === item.id }"
        @click="emit('item-click', item)"
      >
        <component :is="item.icon" :size="16" />
        <span>{{ item.label }}</span>
      </button>
    </nav>
    <div v-else class="sidebar-nav sidebar-status" :role="error ? 'alert' : 'status'">
      <span>{{ error ? '权限加载失败' : '正在校验访问权限...' }}</span>
      <button v-if="error" type="button" :disabled="loading" @click="emit('retry')">重试</button>
    </div>

    <section v-if="ready && access.canAccess" class="sidebar-metrics" aria-label="本月数据">
      <p>本月数据</p>
      <div v-if="metrics" class="metric-grid">
        <div>
          <strong>{{ metrics?.monthlySubmissions ?? '-' }}</strong>
          <span>提交</span>
        </div>
        <div>
          <strong>{{ metrics?.pendingSubmissions ?? '-' }}</strong>
          <span>待审核</span>
        </div>
        <div v-if="access.canManage">
          <strong>{{ metrics?.expiredSubmissions ?? '-' }}</strong>
          <span>已过期</span>
        </div>
        <div v-if="access.canManage">
          <strong>{{ metrics?.totalCompetitors ?? '-' }}</strong>
          <span>竞品总数</span>
        </div>
        <div v-else-if="!access.canReview">
          <strong>{{ metrics?.needsInfoSubmissions ?? '-' }}</strong>
          <span>待补充</span>
        </div>
      </div>
      <div v-else class="sidebar-metrics-status" :role="error ? 'alert' : 'status'">
        <span>{{ loading ? '正在加载数据...' : '本月数据加载失败' }}</span>
        <button v-if="!loading" type="button" @click="emit('retry')">重试</button>
      </div>
    </section>

  </aside>
</template>

<style scoped>
.competitive-sidebar { display: flex; width: 216px; min-width: 216px; min-height: 0; flex-direction: column; border-right: 1px solid #e2e8f0; background: #fff; }
.sidebar-head { display: flex; min-height: 64px; flex-shrink: 0; align-items: center; gap: 12px; border-bottom: 1px solid #f1f5f9; padding: 14px 16px; }
.module-icon { display: grid; width: 36px; height: 36px; flex: 0 0 auto; place-items: center; border-radius: 8px; background: #2563eb; color: #fff; }
.sidebar-head strong { overflow: hidden; color: #0f172a; font-size: 14px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-nav { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 8px; overflow-y: auto; padding: 12px; }
.sidebar-item { display: flex; width: 100%; height: 40px; align-items: center; gap: 12px; border: 0; border-radius: 8px; background: transparent; padding: 0 12px; color: #475569; text-align: left; transition: background .14s ease, color .14s ease; }
.sidebar-item:hover { background: #f8fafc; color: #0f172a; }
.sidebar-item.active { background: #eff6ff; color: #1d4ed8; }
.sidebar-item span { min-width: 0; flex: 1; overflow: hidden; font-size: 14px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-status, .sidebar-metrics-status { color: #64748b; font-size: 12px; }
.sidebar-status button, .sidebar-metrics-status button { align-self: flex-start; min-height: 34px; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; padding: 0 12px; color: #2563eb; font-size: 12px; }
.sidebar-status button:hover, .sidebar-metrics-status button:hover { background: #eff6ff; }
.sidebar-metrics { flex: 0 0 auto; margin: 0 12px 12px; border-top: 1px solid #f1f5f9; padding-top: 12px; }
.sidebar-metrics > p { margin: 0 0 8px; color: #64748b; font-size: 11px; font-weight: 600; }
.sidebar-metrics-status { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; }
.metric-grid strong, .metric-grid span { display: block; }
.metric-grid strong { color: #1e293b; font-size: 14px; font-weight: 600; line-height: 18px; }
.metric-grid span { margin-top: 1px; color: #94a3b8; font-size: 10px; line-height: 14px; }
</style>
