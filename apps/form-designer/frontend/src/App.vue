<script setup lang="ts">
import { computed, ref } from 'vue'
import { PlatformTopBar, PlatformSidebar } from '@platform-ui'
import { ArrowLeft, ClipboardList, Home } from '@lucide/vue'
import Designer from './Designer.vue'
import { loadLoginSession } from './session'
import type { AuthUser } from './types'
import './platform-shell.css'
const user = ref<AuthUser | null>(null)
const designer = ref<any>(null)
const platformSession = ref<any>(null)
const active = ref('工作台')
const portalView = ref<'home' | 'workspace' | 'records'>('home')
const showPrimaryNavigation = computed(() => Boolean(user.value) && active.value === '工作台' && portalView.value === 'home')
const items = [{ id: '工作台', label: '审批首页', icon: Home }]
const managementItems = computed(() => user.value?.role === 'admin' ? [
  { id: '表单设计', label: '表单设计' },
  { id: '流程设计', label: '流程设计' },
  ...((user.value as AuthUser & { canManagePermissions?: boolean }).canManagePermissions ? [
    { id: '数据管理', label: '数据管理' },
  ] : []),
] : [])
function navigate(item: string | { id: string }) {
  const page = typeof item === 'string' ? item : item.id
  if (page === active.value) { if (page === '工作台') designer.value?.resetHome(); return }
  if (page !== '工作台' && !managementItems.value.some(item => item.id === page)) return
  if (!designer.value?.navigatePlatformPage(page)) return
  if (page === '工作台') designer.value?.resetHome()
  active.value = page
}
function userChanged(value: AuthUser) { user.value = value; platformSession.value = loadLoginSession() }
async function signOut() {
  await designer.value?.signOut()
}
</script>
<template>
  <PlatformTopBar :session="platformSession" :user="user" app-name="审批中心" @logout="signOut" />
  <PlatformSidebar v-if="showPrimaryNavigation" fixed module-title="审批中心" module-subtitle="流程审批" :module-icon="ClipboardList" :items="items" active-item-id="工作台" @item-click="navigate" />
  <nav v-if="showPrimaryNavigation" class="platform-mobile-nav" aria-label="应用导航"><button class="active" @click="navigate('工作台')"><Home :size="15" />审批首页</button></nav>
  <div class="platform-content" :class="{ authenticated: user, 'management-open': active !== '工作台', 'without-primary-nav': user && !showPrimaryNavigation }">
    <nav v-if="user && active !== '工作台'" class="management-navigation" aria-label="应用管理导航">
      <button v-if="portalView === 'workspace'" class="management-back" @click="designer?.returnToWorkspace()"><ArrowLeft :size="15" />返回更多</button>
      <button v-else class="management-back" @click="navigate('工作台')"><ArrowLeft :size="15" />返回审批首页</button>
      <button v-for="item in managementItems" :key="item.id" :class="{ active: active === item.id || (active === '页面设置' && item.id === '表单设计') }" @click="navigate(item)">{{ item.label }}</button>
    </nav>
    <Designer ref="designer" :management-items="managementItems" @user-change="userChanged" @page-change="value => active = value" @portal-view-change="value => portalView = value" @management-page="navigate" />
  </div>
</template>
