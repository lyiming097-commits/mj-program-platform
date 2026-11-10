<script setup lang="ts">
import { computed, ref } from 'vue'
import { PlatformTopBar, PlatformSidebar } from '@platform-ui'
import { ArrowLeft, FilePenLine, Home, X } from '@lucide/vue'
import Designer from './Designer.vue'
import { loadLoginSession } from './session'
import type { ApprovalPortalView, AuthUser } from './types'
import { portalCategories, type PortalCategory } from './portal-applications'
import './platform-shell.css'
const user = ref<AuthUser | null>(null)
const designer = ref<any>(null)
const platformSession = ref<any>(null)
const active = ref('工作台')
const portalView = ref<ApprovalPortalView>('home')
const approvalCenterOpen = ref(false)
const approvalEditor = ref<{ form: boolean; workflow: boolean } | null>(null)
const showPrimaryNavigation = computed(() => Boolean(user.value) && active.value === '工作台' && portalView.value === 'home')
const showApprovalNavigation = computed(() => Boolean(user.value) && active.value === '工作台' && portalView.value !== 'home')
const selectedCategory = ref<PortalCategory>('产品管理')
const items = portalCategories.map(category => ({ id: category, label: category }))
function portalViewChanged(view: typeof portalView.value) {
  portalView.value = view
  if (view !== 'home') approvalCenterOpen.value = true
}
async function showHome(closeCenter = false) {
  if (await designer.value?.resetHome() && closeCenter) approvalCenterOpen.value = false
}
function selectCategory(item: PortalCategory | { id: PortalCategory }) {
  designer.value?.selectAppCategory(typeof item === 'string' ? item : item.id)
}
const managementItems = computed(() => user.value?.role === 'admin' ? [
  { id: '表单设计', label: '表单设计' },
  { id: '流程设计', label: '流程设计' },
  ...((user.value as AuthUser & { canManagePermissions?: boolean }).canManagePermissions ? [
    { id: '数据管理', label: '数据管理' },
  ] : []),
] : [])
const visibleManagementItems = computed(() => approvalEditor.value
  ? managementItems.value.filter(item => item.id === '表单设计' ? approvalEditor.value?.form : item.id === '流程设计' && approvalEditor.value?.workflow)
  : managementItems.value)
function navigate(item: string | { id: string }) {
  const page = typeof item === 'string' ? item : item.id
  if (page === '工作台') { void showHome(); return }
  if (page === active.value || !visibleManagementItems.value.some(item => item.id === page)) return
  if (!designer.value?.navigatePlatformPage(page)) return
  active.value = page
}
function userChanged(value: AuthUser) { user.value = value; platformSession.value = loadLoginSession() }
async function signOut() {
  await designer.value?.signOut()
}
</script>
<template>
  <PlatformTopBar :session="platformSession" :user="user" app-name="迈杰教育科技" @logout="signOut" />
  <nav v-if="user" class="portal-top-tabs" :class="{ 'approval-center-open': approvalCenterOpen || approvalEditor }" aria-label="平台页面">
    <button type="button" :aria-current="active === '工作台' && portalView === 'home' ? 'page' : undefined" @click="showHome()"><Home :size="15" />首页</button>
    <button v-if="approvalCenterOpen" type="button" :aria-current="showApprovalNavigation ? 'page' : undefined" @click="designer?.openApprovalCenter()">审批中心</button>
    <button v-if="approvalCenterOpen" type="button" aria-label="关闭审批中心" @click="showHome(true)"><X :size="15" /></button>
    <button v-if="approvalEditor" type="button" :aria-current="active !== '工作台' ? 'page' : undefined" @click="designer?.resumeApprovalEditor()"><FilePenLine :size="15" />流程表单</button>
    <button v-if="approvalEditor" type="button" aria-label="关闭流程表单" @click="designer?.returnToWorkspace()"><X :size="15" /></button>
  </nav>
  <PlatformSidebar v-if="showPrimaryNavigation" fixed class="portal-sidebar" module-title="首页" :module-icon="Home" :items="items" :active-item-id="selectedCategory" @item-click="selectCategory" />
  <nav v-if="showPrimaryNavigation && !approvalCenterOpen && !approvalEditor" class="platform-mobile-nav" aria-label="应用导航">
    <button v-for="category in portalCategories" :key="category" :class="{ active: category === selectedCategory }" @click="selectCategory(category)">{{ category }}</button>
  </nav>
  <div class="platform-content" :class="{ authenticated: user, 'management-open': active !== '工作台', 'approval-editor-visible': approvalEditor && active !== '工作台', 'approval-navigation-open': showApprovalNavigation, 'without-primary-nav': user && !showPrimaryNavigation && !showApprovalNavigation }">
    <nav v-if="user && active !== '工作台'" class="management-navigation" aria-label="应用管理导航">
      <button v-if="!approvalEditor && portalView === 'workspace'" class="management-back" @click="designer?.returnToWorkspace()"><ArrowLeft :size="15" />返回审批中心</button>
      <button v-else-if="!approvalEditor" class="management-back" @click="navigate('工作台')"><ArrowLeft :size="15" />返回审批首页</button>
      <button v-for="item in visibleManagementItems" :key="item.id" :class="{ active: active === item.id || (active === '页面设置' && item.id === '表单设计') }" @click="navigate(item)">{{ item.label }}</button>
    </nav>
    <Designer ref="designer" :management-items="visibleManagementItems" @user-change="userChanged" @page-change="value => active = value" @portal-view-change="portalViewChanged" @portal-category-change="value => selectedCategory = value" @management-page="navigate" @editor-change="value => approvalEditor = value" />
  </div>
</template>
