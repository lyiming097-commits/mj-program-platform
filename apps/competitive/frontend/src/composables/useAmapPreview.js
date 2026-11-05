import { onBeforeUnmount, onMounted, readonly, shallowRef, watch } from "vue";

import { loadAMap } from "@/features/amapLoader";
import { fetchMapConfig } from "@/features/competitiveApi";

export function useAmapPreview(mapElement, latitude, longitude) {
  const loading = shallowRef(true);
  const error = shallowRef("");
  let map;
  let marker;
  let disposed = false;

  function coordinates() {
    const lat = Number(latitude.value);
    const lng = Number(longitude.value);
    return Number.isFinite(lat) && Number.isFinite(lng) ? [lng, lat] : null;
  }

  function updatePosition() {
    const position = coordinates();
    if (!map || !marker || !position) return;
    marker.setPosition(position);
    map.setCenter(position);
  }

  onMounted(async () => {
    const position = coordinates();
    if (!position) {
      loading.value = false;
      return;
    }
    try {
      const AMap = await loadAMap(await fetchMapConfig());
      if (disposed || !mapElement.value) return;
      map = new AMap.Map(mapElement.value, {
        center: position,
        zoom: 16,
        viewMode: "2D",
        resizeEnable: true,
        dragEnable: false,
        zoomEnable: false,
        doubleClickZoom: false,
        keyboardEnable: false,
        scrollWheel: false,
        touchZoom: false,
      });
      const markerElement = document.createElement("span");
      markerElement.setAttribute("aria-hidden", "true");
      Object.assign(markerElement.style, {
        display: "block",
        width: "18px",
        height: "18px",
        border: "4px solid #ffffff",
        borderRadius: "50%",
        background: "#1677ff",
        boxShadow: "0 2px 8px rgba(15, 23, 42, 0.35)",
        boxSizing: "border-box",
      });
      marker = new AMap.Marker({ position, anchor: "center", content: markerElement });
      map.add(marker);
      loading.value = false;
    } catch (reason) {
      if (disposed) return;
      error.value = reason.message || "地图预览加载失败";
      loading.value = false;
    }
  });

  watch([latitude, longitude], updatePosition);

  onBeforeUnmount(() => {
    disposed = true;
    map?.destroy();
    map = null;
    marker = null;
  });

  return { loading: readonly(loading), error: readonly(error) };
}
