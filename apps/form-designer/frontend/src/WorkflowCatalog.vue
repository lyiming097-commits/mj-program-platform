<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { Boxes, BriefcaseBusiness, Building2, ChevronLeft, ChevronRight, FileText, Headset, Package, ShoppingCart, Users, Wallet } from '@lucide/vue'
import type { FormSchema, WorkflowSchema } from './types'
import { categoryLabel, publishedWorkflowCategories, recycledCategories, workflowCategory } from './workflow-categories'

type PublishedForm = { workflow: WorkflowSchema; form: FormSchema }
const props = defineProps<{ items: PublishedForm[]; loading: boolean }>()
const emit = defineEmits<{ start: [item: PublishedForm]; more: [] }>()
const allCategory = '全部流程'
const selectedCategory = ref(allCategory)
const categoryStrip = ref<HTMLDivElement | null>(null)
const canScrollLeft = ref(false)
const canScrollRight = ref(false)
const catalogId = useId()
let resizeObserver: ResizeObserver | undefined

const categories = computed(() => [
  allCategory, ...publishedWorkflowCategories(props.items.map(({ workflow }) => workflow)),
])
const filteredItems = computed(() => props.items.filter(({ workflow }) =>
  !recycledCategories.value.has(workflowCategory(workflow)) &&
  (selectedCategory.value === allCategory || workflowCategory(workflow) === selectedCategory.value),
))
const selectedTabId = computed(() => catalogId + '-category-' + categories.value.indexOf(selectedCategory.value))

function updateScroll() {
  const strip = categoryStrip.value
  if (!strip) return
  canScrollLeft.value = strip.scrollLeft > 1
  canScrollRight.value = strip.scrollLeft + strip.clientWidth < strip.scrollWidth - 1
}

function scrollCategories(direction: number) {
  const strip = categoryStrip.value
  strip?.scrollBy({ left: direction * Math.max(180, strip.clientWidth * 0.7), behavior: 'smooth' })
}

function handleCategoryKey(event: KeyboardEvent, index: number) {
  let next = index
  if (event.key === 'ArrowRight') next = (index + 1) % categories.value.length
  else if (event.key === 'ArrowLeft') next = (index - 1 + categories.value.length) % categories.value.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = categories.value.length - 1
  else return
  event.preventDefault()
  selectedCategory.value = categories.value[next]!
  void nextTick(() => {
    const tab = categoryStrip.value?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]
    tab?.focus()
    tab?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
  })
}

const categoryIcons: Record<string, typeof FileText> = {
  销售流程: ShoppingCart, 商务流程: BriefcaseBusiness, 售前流程: Headset, 采购流程: Package,
  行政流程: Building2, 人事流程: Users, 财务流程: Wallet, 产品流程: Boxes,
}

function flowIcon(item: PublishedForm) {
  const name = item.form.name
  if (/出差|外出/.test(name)) return BriefcaseBusiness
  if (/费用|报销|付款|保证金|价格|报价/.test(name)) return Wallet
  if (/采购|订单/.test(name)) return ShoppingCart
  if (/产品|样品|物料/.test(name)) return Package
  if (/人员|入职|离职|转正/.test(name)) return Users
  if (/售后|返修|服务/.test(name)) return Headset
  return categoryIcons[workflowCategory(item.workflow)] ?? FileText
}

watch(categories, async (next) => {
  if (!next.includes(selectedCategory.value)) selectedCategory.value = allCategory
  await nextTick()
  updateScroll()
})

onMounted(() => {
  updateScroll()
  resizeObserver = new ResizeObserver(updateScroll)
  if (categoryStrip.value) resizeObserver.observe(categoryStrip.value)
})
onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<template>
  <section class="process-catalog" aria-label="发起审批">
    <header class="process-catalog-heading">
      <div><h2>发起审批</h2><p>选择已发布表单填写申请</p></div>
      <div class="process-catalog-actions"><span aria-live="polite">{{ loading ? '正在加载…' : filteredItems.length + ' 个可发起流程' }}</span><button type="button" class="process-catalog-more" @click="emit('more')">更多<ChevronRight :size="14" /></button></div>
    </header>

    <nav class="process-category-bar" aria-label="流程分类导航">
      <div ref="categoryStrip" class="process-category-tabs" role="tablist" aria-label="流程分类" @scroll="updateScroll">
        <button
          v-for="(category, index) in categories"
          :id="catalogId + '-category-' + index"
          :key="category"
          type="button"
          role="tab"
          :aria-selected="selectedCategory === category"
          :aria-controls="catalogId + '-flows'"
          :tabindex="selectedCategory === category ? 0 : -1"
          :class="{ active: selectedCategory === category }"
          @click="selectedCategory = category"
          @keydown="handleCategoryKey($event, index)"
        >{{ categoryLabel(category) }}</button>
      </div>
      <div class="process-category-controls">
        <button type="button" aria-label="向左滚动流程分类" :disabled="!canScrollLeft" @click="scrollCategories(-1)"><ChevronLeft :size="18" /></button>
        <button type="button" aria-label="向右滚动流程分类" :disabled="!canScrollRight" @click="scrollCategories(1)"><ChevronRight :size="18" /></button>
      </div>
    </nav>

    <div :id="catalogId + '-flows'" role="tabpanel" :aria-labelledby="selectedTabId" :aria-busy="loading">
      <div v-if="filteredItems.length" class="process-catalog-grid">
        <button
          v-for="item in filteredItems"
          :key="item.workflow.id"
          type="button"
          class="process-catalog-item"
          :title="item.form.name + ' · ' + item.workflow.name"
          :aria-label="'发起' + item.form.name + '，' + item.workflow.name"
          @click="emit('start', item)"
        >
          <component :is="flowIcon(item)" :size="18" aria-hidden="true" />
          <span>{{ item.form.name }}</span>
        </button>
      </div>
      <div v-else class="process-catalog-empty" role="status">
        <FileText :size="24" aria-hidden="true" />
        <p>{{ loading ? '正在加载流程…' : '当前分类暂无可发起流程' }}</p>
        <span v-if="!loading">已发布且你有权发起的流程会显示在对应分类中</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.process-catalog {
  container-type: inline-size;
  margin-top: 20px;
  padding: 20px 23px 22px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}
.process-catalog-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.process-catalog-heading h2 { margin: 0; color: #1e293b; font-size: 16px; font-weight: 600; }
.process-catalog-heading p { margin: 5px 0 0; color: #94a3b8; font-size: 12px; }
.process-catalog-actions{display:flex;align-items:center;gap:14px;flex:none}.process-catalog-actions>span{color:#94a3b8;font-size:12px}.process-catalog-more{display:flex;align-items:center;gap:3px;padding:6px 0 6px 6px;border:0;background:transparent;color:#5c81af;font-size:13px;cursor:pointer}.process-catalog-more:hover{color:#2563eb}@media(max-width:600px){.process-catalog-actions>span{display:none}}
.process-category-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.process-category-tabs {
  display: flex;
  flex: 1;
  min-width: 0;
  gap: 20px;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scrollbar-width: none;
}
.process-category-tabs::-webkit-scrollbar { display: none; }
.process-category-tabs > button {
  position: relative;
  flex: none;
  height: 43px;
  padding: 0 0 5px;
  border: 0;
  background: transparent;
  color: #64748b;
  font-size: 14px;
  line-height: 20px;
  white-space: nowrap;
  cursor: pointer;
}
.process-category-tabs > button:hover { color: #1677ff; }
.process-category-tabs > button.active { color: #0f172a; font-weight: 600; }
.process-category-tabs > button.active::after {
  position: absolute;
  bottom: 0;
  left: 50%;
  width: 20px;
  height: 3px;
  border-radius: 3px;
  background: #1688ff;
  transform: translateX(-50%);
  content: '';
}
.process-category-controls { display: flex; flex: none; gap: 2px; }
.process-category-controls > button {
  display: grid;
  width: 28px;
  height: 32px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
}
.process-category-controls > button:hover:not(:disabled) { background: #eff6ff; color: #1677ff; }
.process-category-controls > button:disabled { color: #dbe3ec; cursor: default; }
.process-catalog-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.process-catalog-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  height: 42px;
  padding: 0 11px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color .15s, background .15s;
}
.process-catalog-item > svg { flex: none; color: #1688ff; }
.process-catalog-item > span { overflow: hidden; color: #1e293b; font-size: 14px; line-height: 20px; text-overflow: ellipsis; white-space: nowrap; }
.process-catalog-item:hover { border-color: #91caff; background: #f5faff; }
.process-catalog-item:focus-visible,
.process-category-tabs > button:focus-visible,
.process-category-controls > button:focus-visible { outline: 2px solid #1677ff; outline-offset: -2px; }
.process-catalog-empty { display: flex; min-height: 152px; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: #94a3b8; text-align: center; }
.process-catalog-empty > svg { color: #a6bfda; }
.process-catalog-empty > p { margin: 0; color: #64748b; font-size: 14px; }
.process-catalog-empty > span { font-size: 12px; line-height: 20px; }
@container (max-width: 640px) {
  .process-catalog-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@container (max-width: 340px) {
  .process-catalog-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 700px) {
  .process-catalog { padding: 14px; }
  .process-category-bar { gap: 8px; }
  .process-category-tabs { gap: 16px; }
}
@media (prefers-reduced-motion: reduce) {
  .process-catalog-item { transition: none; }
}
</style>
