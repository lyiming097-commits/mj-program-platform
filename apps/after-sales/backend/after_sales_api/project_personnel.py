"""DingTalk personnel snapshots and exact membership for legacy/new drafts."""
from django.db.models import JSONField, Lookup, Q


@JSONField.register_lookup
class JsonArrayHasString(Lookup):
    lookup_name = "has_string"
    prepare_rhs = False

    def as_postgresql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"({lhs} ? {rhs})", [*lhs_params, *rhs_params]

    def as_sqlite(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return (
            f"EXISTS (SELECT 1 FROM json_each({lhs}) personnel_member "
            f"WHERE personnel_member.type = 'text' AND personnel_member.value = {rhs})",
            [*lhs_params, *rhs_params],
        )


def personnel_members(value):
    if not isinstance(value, dict):
        return []
    rows = value.get("members") if "members" in value else [value]
    if not isinstance(rows, list):
        return []
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("userId"), str):
            continue
        user_id = row["userId"].strip()
        if user_id and user_id not in seen:
            seen.add(user_id)
            result.append({"userId": user_id, "name": str(row.get("name") or user_id).strip(),
                           **({"note": row["note"]} if "note" in row else {})})
    return result


def validate_personnel_selection(value):
    from .services import DomainValidationError

    def invalid():
        raise DomainValidationError("请选择有效的项目人员", code="INVALID_PROJECT_PERSONNEL")

    if not isinstance(value, dict):
        invalid()
    if "members" not in value:
        user_id, name = value.get("userId", ""), value.get("name", "")
        if (not isinstance(user_id, str) or not isinstance(name, str)
                or len(user_id) > 128 or len(name) > 128):
            invalid()
        # A legacy single-person request replaces the full selection, including
        # stale arrays supplied by older clients. Names remain display snapshots.
        return {**{key: row for key, row in value.items() if key not in {"userIds", "members"}},
                "userId": user_id.strip(), "name": (name.strip() or user_id.strip()) if user_id.strip() else ""}
    rows = value["members"]
    if not isinstance(rows, list):
        invalid()
    for row in rows:
        if not isinstance(row, dict):
            invalid()
        user_id, name = row.get("userId"), row.get("name")
        if (not isinstance(user_id, str) or not isinstance(name, str)
                or not user_id.strip() or not name.strip() or len(user_id) > 128 or len(name) > 128):
            invalid()
        if "note" in row and not isinstance(row["note"], str):
            invalid()
    members = personnel_members(value)
    return {**value, "members": members, "userIds": [row["userId"] for row in members],
            "userId": members[0]["userId"] if members else "",
            "name": "、".join(row["name"] for row in members)}


def management_member_q(user_id):
    if not user_id:
        return Q(pk__in=[])
    return (Q(business_data__managementAssignment__userId=user_id)
            | Q(business_data__managementAssignment__userIds__has_string=user_id))
