import json

from django.core.management.base import BaseCommand

from identity_api.dingtalk.client import DingTalkAPIError
from identity_api.org.sync import sync_organization_contacts


class Command(BaseCommand):
    help = "Sync DingTalk organization departments and employees into local database."

    def handle(self, *args, **options):
        try:
            result = sync_organization_contacts()
        except DingTalkAPIError as exc:
            detail = getattr(exc, "detail", None)
            self.stderr.write(self.style.ERROR(f"DingTalk contacts sync failed: {exc}"))
            if detail is not None:
                self.stderr.write(json.dumps(detail, ensure_ascii=False, default=str))
            raise
        self.stdout.write(self.style.SUCCESS(f"Synced DingTalk contacts: {result}"))
