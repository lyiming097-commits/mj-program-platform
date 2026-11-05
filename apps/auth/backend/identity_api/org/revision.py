from django.db import transaction

from ..models import OrganizationState


ORGANIZATION_STATE_ID = 1


def get_organization_revision() -> int:
    revision = (
        OrganizationState.objects.filter(state_id=ORGANIZATION_STATE_ID)
        .values_list("revision", flat=True)
        .first()
    )
    return max(int(revision or 0), 0)


def lock_organization_state() -> OrganizationState:
    state, _created = OrganizationState.objects.select_for_update().get_or_create(
        state_id=ORGANIZATION_STATE_ID,
        defaults={"revision": 0},
    )
    return state


def advance_organization_revision(*, state: OrganizationState | None = None, synced_at=None) -> int:
    if state is None and not transaction.get_connection().in_atomic_block:
        with transaction.atomic():
            return advance_organization_revision(synced_at=synced_at)
    state = state or lock_organization_state()
    state.revision = max(int(state.revision or 0), 0) + 1
    update_fields = ["revision", "updated_at"]
    if synced_at is not None:
        state.synced_at = synced_at
        update_fields.append("synced_at")
    state.save(update_fields=update_fields)
    return state.revision
