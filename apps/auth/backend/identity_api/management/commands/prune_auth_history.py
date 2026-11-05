from __future__ import annotations

import os
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from identity_api.models import AuthSession, OrganizationSyncRun


class Command(BaseCommand):
    help = "Delete expired Auth sessions and old completed organization sync runs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=int(os.getenv("AUTH_HISTORY_RETENTION_DAYS", "180") or "180"),
            help="Keep completed organization sync runs created within this many days.",
        )

    def handle(self, *args, **options):
        days = int(options["days"])
        if days < 1:
            raise CommandError("--days must be a positive integer")

        cutoff = timezone.now() - timedelta(days=days)
        session_deleted, _details = AuthSession.objects.filter(expires_at__lte=timezone.now()).delete()
        sync_run_deleted, _details = OrganizationSyncRun.objects.exclude(
            status=OrganizationSyncRun.STATUS_RUNNING,
        ).filter(started_at__lt=cutoff).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {session_deleted} expired session and {sync_run_deleted} old sync run row(s)."
            )
        )
