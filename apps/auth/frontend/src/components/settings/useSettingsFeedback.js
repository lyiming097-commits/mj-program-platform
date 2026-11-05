import { inject, onBeforeUnmount, provide, ref } from "vue";

const settingsFeedbackKey = Symbol("settings-feedback");

// One host for the desktop workspace, including feedback from drawers and nested tabs.
export function provideSettingsFeedback() {
  const feedback = ref({ message: "", tone: "success", sequence: 0, duration: 3000 });
  let disposed = false;
  function showFeedback(message, tone = "success") {
    if (disposed) return;
    feedback.value = {
      message,
      tone,
      sequence: feedback.value.sequence + 1,
      duration: tone === "error" ? 5000 : 3000,
    };
  }
  function clearFeedback() {
    feedback.value = { ...feedback.value, message: "" };
  }
  provide(settingsFeedbackKey, showFeedback);
  onBeforeUnmount(() => { disposed = true; });
  return { feedback, showFeedback, clearFeedback };
}

// The shared permissions panel also runs on mobile, where this host is absent.
export function useSettingsFeedback() {
  return inject(settingsFeedbackKey, () => {});
}
