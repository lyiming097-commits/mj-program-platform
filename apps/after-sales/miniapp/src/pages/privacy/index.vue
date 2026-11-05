<script setup lang="ts">
import { onLoad } from "@dcloudio/uni-app";
import { computed, shallowRef } from "vue";


const documentType = shallowRef<"agreement" | "privacy">("privacy");
const title = computed(() => documentType.value === "agreement" ? "用户协议" : "隐私保护指引");

onLoad((options) => {
  documentType.value = options?.document === "agreement" ? "agreement" : "privacy";
  uni.setNavigationBarTitle({ title: title.value });
});
</script>

<template>
  <view class="document-page">
    <text class="document-title">{{ title }}</text>
    <text class="document-meta">运营方：杭州迈杰教育科技有限公司</text>
    <text class="document-meta">生效日期：2026 年 9 月 15 日</text>

    <template v-if="documentType === 'privacy'">
      <view class="document-section"><text class="section-title">一、我们收集的信息</text><text class="section-copy">为完成服务人员注册、审核和现场任务协作，我们会处理微信登录标识、姓名、联系电话、所在城市、服务地区、服务技能、人员简介，以及您在项目中提交的任务进度、反馈、图片和文件。我们不保存微信 session_key。</text></view>
      <view class="document-section"><text class="section-title">二、使用目的</text><text class="section-copy">上述信息仅用于确认账号身份、审核服务资格、指派售中和售后任务、完成现场协作、处理服务评价与奖励，以及保障系统和业务安全。售前人员来自钉钉组织，不使用小程序注册人员目录。</text></view>
      <view class="document-section"><text class="section-title">三、共享与存储</text><text class="section-copy">服务档案会展示给本系统管理端的授权人员，用于审核和任务指派。信息存储于运营方控制的服务器，不会用于与本服务无关的营销。除法律要求、履行服务合同或获得您的另行同意外，我们不会向无关第三方提供个人信息。</text></view>
      <view class="document-section"><text class="section-title">四、保存期限</text><text class="section-copy">账号存续期间保存注册资料。注销后会清理微信身份关联及服务档案中的联系电话、地区、技能和简介；为履行合同、结算、争议处理和审计义务所需的历史项目、任务与操作记录，会在法定或业务必要期限内继续保留。</text></view>
      <view class="document-section"><text class="section-title">五、您的权利</text><text class="section-copy">您可以在“我的”中查看和更正服务档案，或注销服务账号。注销会停止服务资格且无法恢复。对历史记录留存或个人信息处理有疑问时，请通过管理端服务团队联系运营方。</text></view>
      <view class="document-section"><text class="section-title">六、权限说明</text><text class="section-copy">选择图片、拍摄或文件能力仅在您主动上传现场资料时使用。发布前还需以微信公众平台最终展示的《小程序用户隐私保护指引》为准完成权限声明。</text></view>
    </template>

    <template v-else>
      <view class="document-section"><text class="section-title">一、服务范围</text><text class="section-copy">本小程序用于迈杰服务人员注册、资格审核以及售中、售后现场任务协作。管理人员使用管理端，服务人员使用本小程序；小程序账号不具备管理端权限。</text></view>
      <view class="document-section"><text class="section-title">二、注册与审核</text><text class="section-copy">您应提交真实、准确、完整的资料。提交后账号会进入待审核状态，只有审核通过后才可接受任务。资料更新后可能需要重新审核。</text></view>
      <view class="document-section"><text class="section-title">三、任务履行</text><text class="section-copy">您应按任务要求及时处理现场工作，如实填写进度、费用、证明材料和反馈，不得上传违法、侵权或与任务无关的内容。</text></view>
      <view class="document-section"><text class="section-title">四、账号安全</text><text class="section-copy">账号仅限本人使用。发现异常登录或身份信息被冒用时，应立即停止使用并联系运营方。运营方可暂停违规、异常或不再符合服务要求的账号。</text></view>
      <view class="document-section"><text class="section-title">五、注销与记录</text><text class="section-copy">您可在小程序内注销账号。注销后服务资格立即停止，微信登录身份和可删除的个人档案会被清理；依法或为履行既有服务所需的历史项目、任务、结算和审计记录不会同步删除。</text></view>
      <view class="document-section"><text class="section-title">六、协议更新</text><text class="section-copy">业务或法律要求变化时，运营方可能更新本协议。涉及您权益的重要变化会通过小程序提示，并在需要时重新取得同意。</text></view>
    </template>
  </view>
</template>

<style scoped>
.document-page { min-height: 100vh; background: #fff; padding: 42rpx 36rpx 72rpx; }
.document-title, .document-meta, .section-title, .section-copy { display: block; }
.document-title { color: #182230; font-size: 38rpx; font-weight: 700; line-height: 52rpx; }
.document-meta { margin-top: 8rpx; color: #7a8794; font-size: 21rpx; line-height: 32rpx; }
.document-section { border-top: 1rpx solid #e4e7ec; margin-top: 28rpx; padding-top: 26rpx; }
.section-title { color: #27364a; font-size: 27rpx; font-weight: 700; line-height: 40rpx; }
.section-copy { margin-top: 12rpx; color: #526174; font-size: 24rpx; line-height: 42rpx; }
</style>
