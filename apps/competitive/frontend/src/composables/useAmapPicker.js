import { computed, onBeforeUnmount, onMounted, readonly, shallowRef } from "vue";

import { loadAMap } from "@/features/amapLoader";
import { fetchMapConfig } from "@/features/competitiveApi";
import { getDingTalkLocation, isDingTalkContainer } from "@/features/dingtalkLocation";
import { matchesSearch } from "@/features/search";

function text(value) {
  if (Array.isArray(value)) return value.join("");
  return typeof value === "string" ? value.trim() : "";
}

function toPlace(poi, index) {
  const name = text(poi.name);
  if (!name || !poi.location) return null;
  const latitude = poi.location.getLat();
  const longitude = poi.location.getLng();
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  const address = text(poi.address);
  const area = [poi.pname, poi.cityname, poi.adname].map(text).filter(Boolean).join("");
  const detail = address && area && !address.includes(area) ? `${area}${address}` : address || area;
  const distance = Number(poi.distance);
  return {
    id: text(poi.id) || `${longitude}-${latitude}-${index}`,
    name,
    detail: detail || "附近地点",
    address: detail ? `${name} · ${detail}` : name,
    distance: Number.isFinite(distance) ? distance : null,
    latitude,
    longitude,
  };
}

export function useAmapPicker(mapElement, initial = {}, { viewOnly = false } = {}) {
  const nearbyPlaces = shallowRef([]);
  const searchResults = shallowRef([]);
  const activeQuery = shallowRef("");
  const center = shallowRef(null);
  const centerAddress = shallowRef(initial.location || initial.address || "");
  const nearbyLoading = shallowRef(true);
  const searchLoading = shallowRef(false);
  const locating = shallowRef(true);
  const notice = shallowRef("");
  const nearbyError = shallowRef("");
  const searchError = shallowRef("");
  const places = computed(() => {
    if (!activeQuery.value) return nearbyPlaces.value;
    const seen = new Set();
    return [...searchResults.value, ...nearbyPlaces.value].filter((place) => {
      if (seen.has(place.id) || !matchesSearch(
        activeQuery.value,
        [place.name, place.detail, place.address],
      )) return false;
      seen.add(place.id);
      return true;
    });
  });
  const loading = computed(() => activeQuery.value ? searchLoading.value : nearbyLoading.value);
  const error = computed(() => {
    if (!activeQuery.value) return nearbyError.value;
    return places.value.length ? "" : searchError.value;
  });
  let map;
  let geocoder;
  let placeSearch;
  let geolocation;
  let moveListener;
  let disposed = false;
  let centerRequestVersion = 0;
  let searchRequestVersion = 0;
  let pendingSearch = "";
  let deviceFix = initial.latitude != null && initial.longitude != null ? {
    latitude: initial.latitude,
    longitude: initial.longitude,
    locationAccuracy: initial.locationAccuracy ?? null,
    locatedAt: initial.locatedAt || new Date().toISOString(),
  } : null;

  function selection(address, coordinates) {
    const usesFix = deviceFix
      && Math.abs(deviceFix.latitude - coordinates.latitude) < 0.000001
      && Math.abs(deviceFix.longitude - coordinates.longitude) < 0.000001;
    return {
      address,
      ...coordinates,
      locationAccuracy: usesFix ? deviceFix.locationAccuracy : null,
      locatedAt: usesFix ? deviceFix.locatedAt : new Date().toISOString(),
    };
  }

  function chooseCenter() {
    if (!center.value || !centerAddress.value) return null;
    return selection(centerAddress.value, center.value);
  }

  function choosePlace(place) {
    return selection(place.address, { latitude: place.latitude, longitude: place.longitude });
  }

  function resultPlaces(result) {
    const seen = new Set();
    return (result.poiList?.pois || []).flatMap((poi, index) => {
      const place = toPlace(poi, index);
      if (!place || seen.has(place.id)) return [];
      seen.add(place.id);
      return [place];
    });
  }

  function searchPlaces(value) {
    const query = String(value || "").trim();
    activeQuery.value = query;
    searchResults.value = [];
    searchError.value = "";
    const version = ++searchRequestVersion;
    if (!query) {
      pendingSearch = "";
      searchLoading.value = false;
      return;
    }
    searchLoading.value = true;
    if (!placeSearch) {
      pendingSearch = query;
      return;
    }
    pendingSearch = "";
    placeSearch.search(query, (status, result) => {
      if (disposed || version !== searchRequestVersion || activeQuery.value !== query) return;
      if (status !== "complete" || typeof result === "string") {
        searchResults.value = [];
        searchError.value = status === "no_data"
          ? "未找到匹配地点"
          : "地点搜索失败，请稍后重试";
      } else {
        searchResults.value = resultPlaces(result);
        if (!places.value.length) searchError.value = "未找到匹配地点";
      }
      searchLoading.value = false;
    });
  }

  function applyCurrentLocation(result) {
    const latitude = Number(result.latitude);
    const longitude = Number(result.longitude);
    const accuracy = Number(result.accuracy);
    deviceFix = {
      latitude,
      longitude,
      locationAccuracy: Number.isFinite(accuracy) ? Math.max(0, accuracy) : null,
      locatedAt: new Date().toISOString(),
    };
    map.setCenter([longitude, latitude]);
    map.setZoom(16);
  }

  function locateWithAMap() {
    return new Promise((resolve, reject) => {
      geolocation.getCurrentPosition((status, result) => {
        if (status !== "complete" || !result.position) {
          reject(new Error(result.message || "网页定位失败"));
          return;
        }
        resolve({
          latitude: result.position.getLat(),
          longitude: result.position.getLng(),
          accuracy: result.accuracy,
        });
      });
    });
  }

  function locationFailureNotice(reasons) {
    const message = reasons.map((reason) => String(reason?.message || reason || "")).join(" ");
    if (/denied|permission|无权限|拒绝|not.?allowed/i.test(message)) {
      return "无法获取当前位置：钉钉或系统未授予定位权限。请在钉钉设置和系统设置中开启定位权限，也可拖动地图手动选择地点";
    }
    return "无法获取当前位置，可拖动地图手动选择地点";
  }

  async function locate() {
    if (viewOnly || !geolocation || !map || locating.value) return;
    locating.value = true;
    notice.value = "";
    const failures = [];
    try {
      if (isDingTalkContainer()) {
        try {
          applyCurrentLocation(await getDingTalkLocation());
          return;
        } catch (reason) {
          failures.push(reason);
        }
      }
      try {
        applyCurrentLocation(await locateWithAMap());
      } catch (reason) {
        failures.push(reason);
        if (!disposed) notice.value = locationFailureNotice(failures);
      }
    } finally {
      if (!disposed) locating.value = false;
    }
  }

  onMounted(async () => {
    try {
      const AMap = await loadAMap(await fetchMapConfig());
      if (disposed || !mapElement.value) return;
      const hasSavedCoordinates = initial.latitude != null && initial.longitude != null
        && Number.isFinite(Number(initial.latitude)) && Number.isFinite(Number(initial.longitude));
      const options = { zoom: hasSavedCoordinates ? 16 : 11, resizeEnable: true, scrollWheel: true, viewMode: "2D" };
      if (hasSavedCoordinates) options.center = [Number(initial.longitude), Number(initial.latitude)];
      map = new AMap.Map(mapElement.value, options);
      if (viewOnly) {
        locating.value = false;
        nearbyLoading.value = false;
        if (hasSavedCoordinates) {
          new AMap.Marker({ map, position: options.center, title: initial.location || "采集地点" });
        } else if (initial.location) {
          notice.value = "正在按记录的地址查找地图位置";
          const addressGeocoder = new AMap.Geocoder({ radius: 1000 });
          addressGeocoder.getLocation(initial.location, (status, result) => {
            if (disposed) return;
            const point = status === "complete" && typeof result !== "string"
              ? result.geocodes?.[0]?.location : null;
            if (!point) {
              notice.value = "该记录没有坐标，无法在地图上准确定位";
              return;
            }
            map.setCenter(point);
            map.setZoom(16);
            new AMap.Marker({ map, position: point, title: initial.location });
            notice.value = "该记录没有坐标，地图标记按文字地址解析，仅供参考";
          });
        } else {
          notice.value = "该记录尚未记录具体地点";
        }
        return;
      }
      geocoder = new AMap.Geocoder({ radius: 1000 });
      placeSearch = new AMap.PlaceSearch({ pageSize: 30, pageIndex: 1, extensions: "base" });
      geolocation = new AMap.Geolocation({ enableHighAccuracy: true, timeout: 10000, convert: true, showButton: false, showMarker: false, panToLocation: false, zoomToAccuracy: false });
      moveListener = () => {
        const point = map.getCenter();
        const coordinates = { latitude: point.getLat(), longitude: point.getLng() };
        const version = ++centerRequestVersion;
        center.value = coordinates;
        centerAddress.value = "";
        nearbyLoading.value = true;
        nearbyError.value = "";
        geocoder.getAddress([coordinates.longitude, coordinates.latitude], (status, result) => {
          if (disposed || version !== centerRequestVersion) return;
          if (status === "complete" && typeof result !== "string") centerAddress.value = text(result.regeocode?.formattedAddress);
        });
        placeSearch.searchNearBy("", [coordinates.longitude, coordinates.latitude], 1200, (status, result) => {
          if (disposed || version !== centerRequestVersion) return;
          if (status !== "complete" || typeof result === "string") {
            nearbyPlaces.value = [];
            nearbyError.value = "附近地点加载失败，请移动地图后重试";
          } else {
            nearbyPlaces.value = resultPlaces(result);
          }
          nearbyLoading.value = false;
        });
      };
      map.on("moveend", moveListener);
      moveListener();
      if (pendingSearch || activeQuery.value) searchPlaces(pendingSearch || activeQuery.value);
      locating.value = false;
      void locate();
    } catch (reason) {
      const message = reason.message || "地图加载失败";
      nearbyError.value = message;
      searchError.value = message;
      if (viewOnly) notice.value = message;
      nearbyLoading.value = false;
      searchLoading.value = false;
      locating.value = false;
    }
  });

  onBeforeUnmount(() => {
    disposed = true;
    if (map && moveListener) map.off("moveend", moveListener);
    map?.destroy();
  });

  return {
    places,
    centerAddress: readonly(centerAddress),
    loading,
    locating: readonly(locating),
    notice: readonly(notice),
    error,
    locate,
    searchPlaces,
    chooseCenter,
    choosePlace,
  };
}
