<script setup lang="ts">
import { computed, watch } from "vue";
import { useAccordionState } from "@/composables/useAccordionState";

interface Props {
  title?: string;
  meta?: string;
  initiallyExpanded?: boolean;
}

const props = withDefaults(defineProps<Props>(), { title: "", meta: "", initiallyExpanded: false });
const { activeId, sectionId } = useAccordionState();
const expanded = computed(() => activeId.value === sectionId);

watch(
  () => props.initiallyExpanded,
  (value) => { if (value) activeId.value = sectionId; },
  { immediate: true },
);

function toggle(): void {
  activeId.value = expanded.value ? 0 : sectionId;
}
</script>

<template>
  <view class="section" :class="{ 'is-expanded': expanded }">
    <view
      class="section-head"
      role="button"
      :aria-label="`${expanded ? '收起' : '展开'}${props.title}`"
      :aria-expanded="expanded"
      hover-class="section-head--pressed"
      @tap.stop="toggle"
    >
      <view class="section-title"><text class="section-heading">{{ props.title }}</text><text v-if="props.meta" class="section-meta">{{ props.meta }}</text></view>
      <view class="section-chevron" :class="{ expanded }" />
    </view>
    <view v-if="expanded" class="section-body"><slot /></view>
  </view>
</template>

<style scoped>
.section { overflow: hidden; border-top: 1rpx solid #dce3e9; border-bottom: 1rpx solid #dce3e9; background: #fff; }
.section-head { display: flex; width: 100%; min-height: 88rpx; align-items: center; justify-content: space-between; background: #fff; padding: 0 28rpx; }
.section.is-expanded .section-head { border-bottom-color: #e4e7ec; }
.section-head--pressed { background: #f8fbff; }
.section-title { display: flex; min-width: 0; align-items: center; gap: 16rpx; }
.section-heading { min-width: 0; overflow: hidden; color: #263244; font-size: 28rpx; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.section-meta { overflow: hidden; max-width: 320rpx; color: #7a8794; font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
.section-chevron { width: 15rpx; height: 15rpx; flex: 0 0 auto; border-right: 3rpx solid #7b8798; border-bottom: 3rpx solid #7b8798; margin: 0 6rpx 6rpx 16rpx; transform: rotate(45deg); transition: transform .18s ease; }
.section-chevron.expanded { margin-top: 8rpx; margin-bottom: 0; transform: rotate(225deg); }
.section-body { border-top: 1rpx solid #e4e7ec; padding: 28rpx; }
</style>
