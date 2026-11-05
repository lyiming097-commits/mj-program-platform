import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from identity_api.models import PlatformCompanyEntity, PlatformCompanyEntityHistory


FIELDS = {
    "company_name": 255, "category": 64, "tax_number": 64, "bank_name": 255,
    "bank_account": 64, "address": 512, "phone": 64, "created_by": 64, "updated_by": 64,
}


class Command(BaseCommand):
    help = "Preview/import an audited legacy export, preserving IDs; never overwrite existing platform data."

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-fingerprint")

    def handle(self, *args, **options):
        try:
            payload = json.loads(Path(options["source"]).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise CommandError("Invalid company export") from exc
        if not isinstance(payload, dict) or payload.get("format") != "platform-company-entities/v1" or payload.get("source") != "crm-legacy":
            raise CommandError("Unsupported company export format")
        records = payload.get("records")
        if not isinstance(records, list) or payload.get("count") != len(records):
            raise CommandError("Invalid record count")
        fingerprint = hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if fingerprint != payload.get("fingerprint"):
            raise CommandError("Export fingerprint mismatch")
        if options["apply"] and options["expected_fingerprint"] != fingerprint:
            raise CommandError("Apply requires the fingerprint verified during preview")
        seen_ids, seen_tax_numbers = set(), set()
        for row in records:
            if not isinstance(row, dict) or type(row.get("id")) is not int or not 1 <= row["id"] <= 9223372036854775807:
                raise CommandError("Invalid company ID")
            if row["id"] in seen_ids:
                raise CommandError("Duplicate company ID in export")
            seen_ids.add(row["id"])
            for field, max_length in FIELDS.items():
                if not isinstance(row.get(field), str) or len(row[field]) > max_length:
                    raise CommandError(f"Invalid {field} for company ID {row['id']}")
            if not row["company_name"].strip() or not row["tax_number"].strip():
                raise CommandError("Company name and tax number are required")
            if row["tax_number"] in seen_tax_numbers:
                raise CommandError("Duplicate tax number in export")
            seen_tax_numbers.add(row["tax_number"])
            for field in ("created_at", "updated_at"):
                value = row.get(field)
                timestamp = parse_datetime(value) if isinstance(value, str) else None
                if timestamp is None or timezone.is_naive(timestamp):
                    raise CommandError(f"Invalid {field} for company ID {row['id']}")
        try:
            with transaction.atomic():
                existing = list(PlatformCompanyEntity.objects.select_for_update())
                by_id = {item.id: item for item in existing}
                by_tax = {item.tax_number: item for item in existing}
                pending = []
                for row in records:
                    item = by_id.get(row["id"])
                    if item is not None:
                        if item.deleted_at or any(getattr(item, field) != row[field] for field in FIELDS) or any(
                            getattr(item, field) != parse_datetime(row[field]) for field in ("created_at", "updated_at")
                        ):
                            raise CommandError(f"Platform record conflicts with company ID {row['id']}; no records changed")
                        continue
                    if row["tax_number"] in by_tax:
                        raise CommandError(f"Tax number belongs to another platform ID for company {row['id']}; no records changed")
                    pending.append(row)
                if options["apply"]:
                    for row in pending:
                        item = PlatformCompanyEntity.objects.create(id=row["id"], **{field: row[field] for field in FIELDS})
                        PlatformCompanyEntity.objects.filter(pk=item.pk).update(
                            created_at=parse_datetime(row["created_at"]), updated_at=parse_datetime(row["updated_at"]))
                        PlatformCompanyEntityHistory.objects.create(
                            entity_id=item.id, action="import", actor_user_id="platform-data-import",
                            effective_user_id="platform-data-import", after={**row, "importFingerprint": fingerprint})
                    with connection.cursor() as cursor:
                        for statement in connection.ops.sequence_reset_sql(no_style(), [PlatformCompanyEntity]):
                            cursor.execute(statement)
        except IntegrityError as exc:
            raise CommandError("Concurrent company change; import rolled back, run preview again") from exc
        mode = "Imported" if options["apply"] else "Preview"
        self.stdout.write(f"{mode}: total={len(records)}, new={len(pending)}, unchanged={len(records) - len(pending)}, fingerprint={fingerprint}")
