<script setup>
import { ArrowUpRight } from "@lucide/vue";
import { ref } from "vue";
import { APPLICATION_TEMPLATE_WORKSPACE_PATH } from "@/config";
import { openApplicationTemplateTab } from "@/application-template-navigation";
const error = ref("");
function openTemplate(event) {
  const opening = openApplicationTemplateTab(event);
  if (opening) {
    error.value = "";
    opening.catch(reason => { error.value = reason.message; });
  }
}
</script>

<template>
  <section id="auth-template-entry-panel" role="tabpanel" aria-labelledby="auth-template-entry-tab"
    class="rounded-lg border border-slate-200 bg-white p-4">
    <a :href="APPLICATION_TEMPLATE_WORKSPACE_PATH" target="_blank" rel="noopener noreferrer" @click="openTemplate"
      class="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">
      打开应用模板 <ArrowUpRight class="h-4 w-4" aria-hidden="true" />
    </a>
    <p v-if="error" role="alert" class="mt-2 text-sm text-red-700">{{ error }}</p>
  </section>
</template>
