from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from identity_api.models import InternalServiceCredential


class Command(BaseCommand):
    help = "Synchronize internal service credentials from the generated app registry"

    def add_arguments(self, parser):
        parser.add_argument("--registry", required=True)

    def handle(self, *args, **options):
        registry_path = Path(str(options["registry"])).resolve()
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CommandError(f"App registry not found: {registry_path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Cannot read app registry: {exc}") from exc

        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
            raise CommandError("Unsupported app registry schema")
        revision = str(payload.get("revision") or "").strip()
        if len(revision) != 64:
            raise CommandError("App registry revision is invalid")
        raw_services = payload.get("authServices")
        if not isinstance(raw_services, list):
            raise CommandError("App registry authServices must be a list")

        services: list[dict[str, object]] = []
        seen_names: set[str] = set()
        for index, raw_service in enumerate(raw_services):
            if not isinstance(raw_service, dict):
                raise CommandError(f"authServices[{index}] must be an object")
            app_id = str(raw_service.get("appId") or "").strip()
            service_name = str(raw_service.get("serviceName") or "").strip()
            secret_file = Path(str(raw_service.get("secretFile") or "").strip())
            if not app_id or not service_name or not secret_file.is_absolute():
                raise CommandError(f"authServices[{index}] is incomplete")
            if service_name in seen_names:
                raise CommandError(f"Duplicate internal service: {service_name}")
            seen_names.add(service_name)
            try:
                secret = secret_file.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise CommandError(f"Cannot read secret for {service_name}: {exc}") from exc
            if len(secret) < 32 or len(secret) > 4096:
                raise CommandError(f"Secret length is invalid for {service_name}")
            services.append(
                {
                    "app_id": app_id,
                    "service_name": service_name,
                    "secret": secret,
                    "enabled": bool(raw_service.get("enabled", True)),
                }
            )

        created = 0
        rotated = 0
        unchanged = 0
        with transaction.atomic():
            existing_by_name = {
                item.service_name: item
                for item in InternalServiceCredential.objects.select_for_update().all()
            }
            for service in services:
                service_name = str(service["service_name"])
                credential = existing_by_name.get(service_name)
                if credential is None:
                    credential = InternalServiceCredential(service_name=service_name)
                    credential.set_secret(str(service["secret"]))
                    created += 1
                elif not credential.matches_secret(str(service["secret"])):
                    credential.set_secret(str(service["secret"]))
                    rotated += 1
                else:
                    unchanged += 1
                credential.app_id = str(service["app_id"])
                credential.enabled = bool(service["enabled"])
                credential.registry_revision = revision
                credential.save()

            disabled = InternalServiceCredential.objects.exclude(service_name__in=seen_names).update(
                enabled=False,
                registry_revision=revision,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Internal services synchronized: {created} created, {rotated} rotated, "
                f"{unchanged} unchanged, {disabled} disabled"
            )
        )
