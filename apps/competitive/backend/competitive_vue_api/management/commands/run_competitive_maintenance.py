import time

from django.core.management.base import BaseCommand, CommandError

from competitive_vue_api.maintenance import run_maintenance_cycle


class Command(BaseCommand):
    help = "Run competitive expiry, soft-delete and attachment maintenance."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=60)
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        interval = options["interval"]
        batch_size = options["batch_size"]
        if interval < 10:
            raise CommandError("interval must be at least 10 seconds")
        if not 1 <= batch_size <= 1000:
            raise CommandError("batch-size must be between 1 and 1000")

        while True:
            result = run_maintenance_cycle(batch_size=batch_size)
            self.stdout.write(
                "maintenance complete: "
                f"expired_submissions={result['expiry']['submissions']} "
                f"expired_competitors={result['expiry']['competitors']} "
                f"purged={result['purged']} files={result['files']}"
            )
            if options["once"]:
                return
            time.sleep(interval)
