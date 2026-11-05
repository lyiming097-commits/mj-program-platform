<script setup>
import { computed, onMounted, ref } from "vue";
import {
  ArrowLeft,
  CircleAlert,
  ClipboardCheck,
  LogIn,
  Play,
  ShieldCheck,
  Upload,
} from "@lucide/vue";
import { apiGet } from "@/api";

const loading = ref(true);
const error = ref("");
const resource = ref(null);

const title = computed(() => resource.value?.title || "迈杰智能讲台公开安装示范");
const summary = computed(() => resource.value?.summary || "标准产品安装示范，定制项目以现场资料为准。");
const tags = computed(() => Array.isArray(resource.value?.tags) ? resource.value.tags : []);

onMounted(async () => {
  document.title = "示范资料 · 迈杰服务";
  try {
    const payload = await apiGet("/api/after-sales/public/demo");
    resource.value = payload?.item || null;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "公开资料暂时无法加载";
  } finally {
    loading.value = false;
  }
});

function openDemo() {
  const url = String(resource.value?.externalUrl || "").trim();
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}

function goBack() {
  window.location.assign("/auth/");
}
</script>

<template>
  <main class="public-demo">
    <header class="public-demo__bar">
      <button type="button" class="public-demo__icon-button" title="返回" aria-label="返回" @click="goBack"><ArrowLeft /></button>
      <div><strong>迈杰服务</strong><span>公开示范资料</span></div>
      <a class="public-demo__login" href="/auth/"><LogIn />登录</a>
    </header>

    <div class="public-demo__content">
      <section class="public-demo__viewer" aria-labelledby="public-demo-title">
        <button type="button" class="public-demo__play" :disabled="!resource?.externalUrl" :title="resource?.externalUrl ? '播放示范资料' : '尚未配置视频地址'" @click="openDemo"><Play /></button>
        <div class="public-demo__viewer-copy">
          <span>{{ resource?.resourceTypeLabel || "安装视频" }}</span>
          <h1 id="public-demo-title">{{ title }}</h1>
          <p>{{ summary }}</p>
          <div v-if="tags.length" class="public-demo__tags"><span v-for="tag in tags" :key="tag">{{ tag }}</span></div>
        </div>
        <div class="public-demo__viewer-status">{{ resource?.externalUrl ? "点击播放" : "示范封面" }}</div>
      </section>

      <div v-if="loading" class="public-demo__notice">正在加载公开资料...</div>
      <div v-else-if="error" class="public-demo__notice is-error"><CircleAlert />{{ error }}</div>

      <section class="public-demo__gate">
        <ShieldCheck />
        <div><h2>公开内容</h2><p>{{ resource?.content || "正式项目资料只对后台分配到该项目、该节点的服务人员开放。" }}</p></div>
      </section>

      <section class="public-demo__scope" aria-label="现场服务流程示范">
        <article><ClipboardCheck /><div><strong>任务说明</strong><span>查看公开的标准任务内容和资料清单</span></div></article>
        <article><Upload /><div><strong>现场记录</strong><span>登录后按任务提交过程照片和完成资料</span></div></article>
      </section>

      <a class="public-demo__primary" href="/auth/"><LogIn />登录查看我的任务</a>
    </div>
  </main>
</template>

<style scoped>
.public-demo { min-height: 100vh; background: #f4f6f8; color: #18212f; }
.public-demo__bar { position: sticky; top: 0; z-index: 5; min-height: 64px; padding: 0 20px; display: grid; grid-template-columns: 40px 1fr auto; align-items: center; gap: 12px; border-bottom: 1px solid #dbe1e8; background: rgba(255, 255, 255, .96); }
.public-demo__bar > div { min-width: 0; display: flex; flex-direction: column; }
.public-demo__bar strong { font-size: 15px; }
.public-demo__bar span { color: #697586; font-size: 12px; }
.public-demo__icon-button { width: 36px; height: 36px; display: grid; place-items: center; border: 0; background: transparent; color: #273548; cursor: pointer; }
.public-demo__icon-button svg, .public-demo__login svg, .public-demo__primary svg { width: 18px; height: 18px; }
.public-demo__login { display: inline-flex; align-items: center; gap: 6px; color: #0b6bcb; font-size: 14px; font-weight: 700; text-decoration: none; }
.public-demo__content { width: min(920px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 48px; }
.public-demo__viewer { min-height: 390px; position: relative; overflow: hidden; display: grid; place-items: center; padding: 44px; border-radius: 8px; background: #17212f; color: #fff; }
.public-demo__viewer-copy { position: relative; max-width: 560px; text-align: center; }
.public-demo__viewer-copy > span { color: #8fd1ff; font-size: 13px; font-weight: 700; }
.public-demo__viewer h1 { margin: 10px 0 12px; font-size: 38px; line-height: 1.15; letter-spacing: 0; }
.public-demo__viewer p { margin: 0; color: #d2dae5; line-height: 1.7; }
.public-demo__play { position: relative; width: 64px; height: 64px; margin-bottom: 22px; display: grid; place-items: center; border: 1px solid rgba(255,255,255,.55); border-radius: 50%; background: #fff; color: #1267a8; cursor: pointer; }
.public-demo__play:disabled { cursor: default; opacity: .78; }
.public-demo__play svg { width: 28px; height: 28px; margin-left: 3px; }
.public-demo__viewer-status { position: absolute; right: 18px; bottom: 16px; padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,.48); color: #e8edf4; font-size: 12px; }
.public-demo__tags { margin-top: 18px; display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; }
.public-demo__tags span { padding: 5px 8px; border: 1px solid rgba(255,255,255,.28); border-radius: 4px; color: #e5edf6; font-size: 12px; }
.public-demo__notice { margin-top: 14px; padding: 12px 14px; border: 1px solid #ccd7e3; border-radius: 6px; background: #fff; color: #5f6c7b; font-size: 13px; }
.public-demo__notice.is-error { display: flex; align-items: center; gap: 8px; border-color: #f0b6ba; color: #a32631; }
.public-demo__notice svg { width: 17px; height: 17px; }
.public-demo__gate { margin-top: 20px; padding: 20px; display: flex; gap: 14px; align-items: flex-start; border-left: 4px solid #12845d; background: #fff; }
.public-demo__gate > svg { flex: 0 0 auto; width: 24px; height: 24px; color: #12845d; }
.public-demo__gate h2 { margin: 0 0 5px; font-size: 16px; }
.public-demo__gate p { margin: 0; color: #5f6c7b; line-height: 1.65; }
.public-demo__scope { margin-top: 20px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.public-demo__scope article { min-width: 0; padding: 18px; display: flex; gap: 12px; border: 1px solid #dbe1e8; border-radius: 8px; background: #fff; }
.public-demo__scope svg { flex: 0 0 auto; width: 22px; height: 22px; color: #1267a8; }
.public-demo__scope div { min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.public-demo__scope strong { font-size: 14px; }
.public-demo__scope span { color: #697586; font-size: 13px; line-height: 1.55; }
.public-demo__primary { width: fit-content; min-height: 42px; margin: 24px auto 0; padding: 0 18px; display: flex; align-items: center; justify-content: center; gap: 8px; border-radius: 6px; background: #1267a8; color: #fff; font-size: 14px; font-weight: 700; text-decoration: none; }
@media (max-width: 680px) {
  .public-demo__bar { padding: 0 12px; }
  .public-demo__content { width: min(100% - 24px, 920px); padding-top: 12px; }
  .public-demo__viewer { min-height: 340px; padding: 30px 20px; }
  .public-demo__viewer h1 { font-size: 28px; }
  .public-demo__scope { grid-template-columns: 1fr; }
  .public-demo__primary { width: 100%; }
}
</style>
