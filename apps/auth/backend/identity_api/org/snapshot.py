from __future__ import annotations

from django.db import connection, transaction

from ..internal import INTERNAL_ORG_PATH_PREFIX, PUBLIC_ORG_PATH_PREFIX
from .revision import get_organization_revision, lock_organization_state


class OrganizationSnapshotMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = str(getattr(request, "path", "") or "")
        if not (path.startswith(INTERNAL_ORG_PATH_PREFIX) or path.startswith(PUBLIC_ORG_PATH_PREFIX)):
            return self.get_response(request)

        is_public_write = path.startswith(PUBLIC_ORG_PATH_PREFIX) and request.method in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }
        already_in_transaction = connection.in_atomic_block
        with transaction.atomic():
            if (
                connection.vendor == "postgresql"
                and not already_in_transaction
                and not is_public_write
            ):
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")

            if is_public_write:
                state = lock_organization_state()
                request.organization_state = state
                request.organization_revision = max(int(state.revision or 0), 0)
            else:
                request.organization_revision = get_organization_revision()
            return self.get_response(request)
