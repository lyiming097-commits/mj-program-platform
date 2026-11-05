import { readonly, shallowRef } from "vue";
import { deactivateProvider } from "@/api/mobile";
import { clearSession, deleteWeChatAccount } from "@/composables/useSession";


function confirmDeletion(): Promise<boolean> {
  return new Promise((resolve) => {
    uni.showModal({
      title: "注销服务账号",
      content: "注销后将立即停止服务资格并清理个人档案，当前账号无法恢复。依法需要留存的历史项目、任务和审计记录仍会保留。",
      confirmText: "确认注销",
      confirmColor: "#b42318",
      success: (result) => resolve(result.confirm),
      fail: () => resolve(false),
    });
  });
}


export function useAccountDeletion() {
  const deleting = shallowRef(false);
  const deletionError = shallowRef("");

  async function requestAccountDeletion(): Promise<void> {
    if (deleting.value || !(await confirmDeletion())) return;
    deleting.value = true;
    deletionError.value = "";
    try {
      await deactivateProvider();
      await deleteWeChatAccount();
      clearSession();
      uni.showModal({
        title: "账号已注销",
        content: "微信登录身份和服务人员个人档案已清理。",
        showCancel: false,
        success: () => uni.reLaunch({ url: "/pages/login/index" }),
      });
    } catch (reason) {
      deletionError.value = reason instanceof Error ? reason.message : "账号注销失败，请稍后重试";
    } finally {
      deleting.value = false;
    }
  }

  return {
    deleting: readonly(deleting),
    deletionError: readonly(deletionError),
    requestAccountDeletion,
  };
}
