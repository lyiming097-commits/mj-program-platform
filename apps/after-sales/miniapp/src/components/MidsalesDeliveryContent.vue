<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";
import { fetchMidsalesProofs } from "@/api/mobile";
import type { MidsalesProof, MobileAttachment } from "@/api/types";
import MobileAttachmentPanel from "@/components/MobileAttachmentPanel.vue";

interface Props {
  projectId: number;
  nodeKey: string;
  editable: boolean;
  enabled?: boolean;
}

const props = withDefaults(defineProps<Props>(), { enabled: true });
const proofs = shallowRef<MidsalesProof[]>([]);
const loading = shallowRef(false);
const error = shallowRef("");

const proofOrder: Readonly<Record<MidsalesProof["proofType"], number>> = {
  process: 0,
  completion: 1,
  evaluation: 2,
};
const orderedProofs = computed(() => [...proofs.value].sort((left, right) => (
  proofOrder[left.proofType] - proofOrder[right.proofType]
)));

function statusClass(proof: MidsalesProof): string {
  if (proof.status === "approved") return "is-approved";
  if (proof.status === "rejected") return "is-rejected";
  return "";
}

function syncAttachments(proofId: number, attachments: readonly MobileAttachment[]): void {
  proofs.value = proofs.value.map((proof) => proof.id === proofId
    ? { ...proof, attachments: [...attachments] }
    : proof);
}

async function load(): Promise<void> {
  if (!props.enabled || !props.projectId || !props.nodeKey) {
    proofs.value = [];
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const response = await fetchMidsalesProofs(props.projectId, props.nodeKey);
    proofs.value = Array.isArray(response.items) ? response.items : [];
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "交付内容加载失败";
  } finally {
    loading.value = false;
  }
}

watch(() => [props.enabled, props.projectId, props.nodeKey], () => { void load(); }, { immediate: true });
</script>

<template>
  <view class="delivery-content">
    <view v-if="error" class="error-banner">{{ error }}</view>
    <view v-if="loading && !proofs.length" class="delivery-empty">正在加载交付内容...</view>
    <view v-else-if="orderedProofs.length" class="proof-list">
      <view v-for="proof in orderedProofs" :key="proof.id" class="proof-item">
        <view class="proof-head">
          <view class="proof-heading-copy"><text class="proof-heading-label">{{ proof.proofTypeLabel }}</text><text class="proof-heading-count">{{ proof.attachments?.length || 0 }} 个文件</text></view>
          <text class="proof-status" :class="statusClass(proof)">{{ proof.statusLabel }}</text>
        </view>
        <view class="proof-body">
          <MobileAttachmentPanel
            target-type="midsales_proof"
            :target-id="proof.id"
            :editable="editable && proof.canUpload"
            upload-label="上传材料"
            empty-label="暂无材料"
            success-message="交付材料已上传"
            @changed="syncAttachments(proof.id, $event)"
          />
        </view>
        <view v-if="proof.reviewOpinion" class="review-opinion"><text class="review-opinion-label">审核意见</text><text class="review-opinion-copy">{{ proof.reviewOpinion }}</text></view>
      </view>
    </view>
    <view v-else class="delivery-empty">暂无交付内容</view>
  </view>
</template>

<style scoped>
.delivery-content { min-width: 0; }
.proof-list { display: grid; gap: 20rpx; }
.proof-item { overflow: hidden; border: 1rpx solid #dbe5ef; border-radius: 12rpx; background: #fff; }
.proof-head { display: flex; min-height: 82rpx; align-items: center; justify-content: space-between; gap: 18rpx; border-bottom: 1rpx solid #e4ebf3; background: #f8fbff; padding: 14rpx 18rpx; }
.proof-heading-copy { min-width: 0; }
.proof-heading-label, .proof-heading-count { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.proof-heading-label { color: #27364a; font-size: 23rpx; font-weight: 700; }
.proof-heading-count { margin-top: 4rpx; color: #7b8798; font-size: 19rpx; }
.proof-status { display: inline-flex; min-height: 42rpx; flex: 0 0 auto; align-items: center; border: 1rpx solid #d3dde9; border-radius: 10rpx; background: #fff; padding: 2rpx 12rpx; color: #667085; font-size: 19rpx; font-weight: 700; }
.proof-status.is-approved { border-color: #b7decf; background: #eef9f4; color: #087550; }
.proof-status.is-rejected { border-color: #efc8cd; background: #fff3f4; color: #b42318; }
.proof-body { padding: 18rpx; }
.review-opinion { display: grid; gap: 6rpx; border-top: 1rpx solid #e4ebf3; background: #fff9eb; padding: 16rpx 18rpx; }
.review-opinion-label { color: #856b36; font-size: 19rpx; font-weight: 700; }
.review-opinion-copy { color: #6f5b32; font-size: 21rpx; line-height: 34rpx; }
.delivery-empty { display: grid; min-height: 140rpx; place-items: center; border: 1rpx dashed #cad5e2; border-radius: 12rpx; background: #fbfcfe; color: #8a98aa; font-size: 21rpx; }
</style>
