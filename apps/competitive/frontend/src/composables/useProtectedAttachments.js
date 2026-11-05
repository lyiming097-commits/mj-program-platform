import { shallowRef } from "vue";
import { attachmentUrl, downloadProtectedMedia } from "@/features/competitiveApi";

export function useProtectedAttachments(notify) {
  const mediaPreview = shallowRef(null);
  const downloadingId = shallowRef("");

  function previewAttachment(submissionId, file) {
    mediaPreview.value = {
      id: file.id,
      name: file.name,
      type: file.type,
      previewUrl: attachmentUrl(submissionId, file.id),
    };
  }

  async function downloadAttachment(submissionId, file) {
    if (downloadingId.value) return;
    downloadingId.value = file.id;
    try {
      await downloadProtectedMedia(attachmentUrl(submissionId, file.id), file.name);
    } catch (reason) {
      notify(reason.message || "附件下载失败");
    } finally {
      downloadingId.value = "";
    }
  }

  return { mediaPreview, downloadingId, previewAttachment, downloadAttachment };
}
