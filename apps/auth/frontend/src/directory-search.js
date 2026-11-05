import { matchesDirectorySearchKeyword } from "@platform-ui";

export function employeeMatchesDirectoryKeyword(employee, rawKeyword) {
  const departments = employee?.departments || [];
  const handoverEmployee = employee?.handoverEmployee || null;
  return matchesDirectorySearchKeyword(rawKeyword, {
    names: [employee?.name, employee?.rawName],
    ids: employee?.userId,
    pinyin: employee?.pinyin,
    pinyinInitials: employee?.pinyinInitials,
  })
    || departments.some((department) => matchesDirectorySearchKeyword(rawKeyword, {
      names: department?.name,
      ids: department?.deptId,
      pinyin: department?.pinyin,
      pinyinInitials: department?.pinyinInitials,
    }))
    || matchesDirectorySearchKeyword(rawKeyword, {
      names: handoverEmployee?.name,
      ids: handoverEmployee?.userId,
      pinyin: handoverEmployee?.pinyin,
      pinyinInitials: handoverEmployee?.pinyinInitials,
    });
}
