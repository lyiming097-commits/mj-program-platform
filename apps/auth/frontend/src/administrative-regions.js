import { areaList } from "@vant/area-data";

export function buildAdministrativeRegionTree(source = areaList) {
  const provinces = Object.entries(source?.province_list || {}).map(([code, name]) => ({
    code,
    name,
    cities: [],
  }));
  const provinceByPrefix = new Map(provinces.map((province) => [province.code.slice(0, 2), province]));
  const cityByPrefix = new Map();

  Object.entries(source?.city_list || {}).forEach(([code, name]) => {
    const province = provinceByPrefix.get(code.slice(0, 2));
    if (!province) return;
    const city = { code, name, districts: [] };
    province.cities.push(city);
    cityByPrefix.set(code.slice(0, 4), city);
  });

  Object.entries(source?.county_list || {}).forEach(([code, name]) => {
    const city = cityByPrefix.get(code.slice(0, 4));
    if (!city) return;
    city.districts.push({ code, name });
  });

  return provinces;
}

export const administrativeRegions = buildAdministrativeRegionTree();

export const administrativeRegionStats = administrativeRegions.reduce((stats, province) => {
  stats.provinces += 1;
  stats.cities += province.cities.length;
  stats.districts += province.cities.reduce((count, city) => count + city.districts.length, 0);
  return stats;
}, { provinces: 0, cities: 0, districts: 0 });

const searchableRegions = administrativeRegions.flatMap((province) => [
  {
    level: "province",
    levelLabel: "省级",
    code: province.code,
    name: province.name,
    path: province.name,
    provinceCode: province.code,
    cityCode: province.cities[0]?.code || "",
  },
  ...province.cities.flatMap((city) => [
    {
      level: "city",
      levelLabel: "市级",
      code: city.code,
      name: city.name,
      path: `${province.name} / ${city.name}`,
      provinceCode: province.code,
      cityCode: city.code,
    },
    ...city.districts.map((district) => ({
      level: "district",
      levelLabel: "区县",
      code: district.code,
      name: district.name,
      path: `${province.name} / ${city.name} / ${district.name}`,
      provinceCode: province.code,
      cityCode: city.code,
    })),
  ]),
]);

export function searchAdministrativeRegions(keyword) {
  const normalized = String(keyword || "").trim().toLocaleLowerCase();
  if (!normalized) return [];
  return searchableRegions.filter((item) => (
    item.name.toLocaleLowerCase().includes(normalized)
    || item.code.includes(normalized)
  ));
}
