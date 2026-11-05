import { shallowRef } from "vue";
import { fetchProviderTags } from "@/api/mobile";

export function useProviderTags() {
  const tags = shallowRef<string[]>([]);
  const loading = shallowRef(false);

  async function load(): Promise<void> {
    if (loading.value) return;
    loading.value = true;
    try {
      const response = await fetchProviderTags();
      tags.value = Array.isArray(response.items)
        ? [...new Set(response.items.map((item) => String(item || "").trim()).filter(Boolean))]
        : [];
    } catch {
      // Registration can continue with free-form skills when the catalog is unavailable.
      tags.value = [];
    } finally {
      loading.value = false;
    }
  }

  return { tags, loading, load };
}
