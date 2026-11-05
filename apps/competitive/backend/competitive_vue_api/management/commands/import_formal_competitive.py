import os
from pathlib import Path

import psycopg
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from psycopg.rows import dict_row

from competitive_vue_api.models import (
    CollectionDraft,
    CollectionDraftAttachment,
    Competitor,
    CompetitorParameter,
    CompetitorVersion,
    PendingFileDeletion,
    PermissionRule,
    PermissionState,
    SettingItem,
    Submission,
    SubmissionAttachment,
)
from competitive_vue_api.releases import ensure_current_release


TABLES = (
    (Competitor, "competitors"),
    (Submission, "submissions"),
    (CompetitorParameter, "competitor_parameters"),
    (CompetitorVersion, "competitor_versions"),
    (SubmissionAttachment, "submission_attachments"),
    (PendingFileDeletion, "pending_file_deletions"),
    (CollectionDraft, "collection_drafts"),
    (CollectionDraftAttachment, "collection_draft_attachments"),
    (SettingItem, "setting_items"),
    (PermissionRule, "permission_rules"),
    (PermissionState, "permission_states"),
)
LEGACY_EXCLUDED_COLUMNS = {
    "submissions": {"competitor_release_id"},
}


class Command(BaseCommand):
    help = "Import the formal FastAPI competitive database into an empty Django database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-dsn",
            default=os.getenv("FORMAL_COMPETITIVE_SOURCE_DSN", ""),
            help="Read-only PostgreSQL DSN for the formal competitive source database.",
        )
        parser.add_argument(
            "--upload-dir",
            default=os.getenv("UPLOAD_DIR", "/app/uploads"),
            help="Directory containing the copied formal upload files.",
        )
        parser.add_argument("--source-host", default="")
        parser.add_argument("--source-port", default="5432")
        parser.add_argument("--source-db", default="competitive_db")
        parser.add_argument("--source-user", default="competitive_user")
        parser.add_argument("--source-password-file", default="")
        parser.add_argument(
            "--repair-timestamps",
            action="store_true",
            help="Restore source created_at/updated_at on an already imported target.",
        )

    def handle(self, *args, **options):
        source_dsn = str(options["source_dsn"] or "").strip()
        source_connect = source_dsn
        if not source_connect:
            password_file = Path(str(options["source_password_file"] or ""))
            if not options["source_host"] or not password_file.is_file():
                raise CommandError(
                    "Provide --source-dsn or --source-host with --source-password-file"
                )
            source_connect = {
                "host": options["source_host"],
                "port": options["source_port"],
                "dbname": options["source_db"],
                "user": options["source_user"],
                "password": password_file.read_text(encoding="utf-8").strip(),
            }
        upload_dir = Path(options["upload_dir"]).resolve()

        repair_timestamps = bool(options["repair_timestamps"])
        nonempty = [table for model, table in TABLES if model.objects.exists()]
        if nonempty and not repair_timestamps:
            raise CommandError(
                "Target business tables must be empty; found data in: "
                + ", ".join(nonempty)
            )

        source_rows = {}
        try:
            connect_args = (
                {"conninfo": source_connect}
                if isinstance(source_connect, str)
                else source_connect
            )
            with psycopg.connect(**connect_args, row_factory=dict_row) as source:
                source.execute("SET TRANSACTION READ ONLY")
                for model, table in TABLES:
                    excluded = LEGACY_EXCLUDED_COLUMNS.get(table, set())
                    columns = [
                        field.column
                        for field in model._meta.concrete_fields
                        if field.column not in excluded
                    ]
                    query = psycopg.sql.SQL("SELECT {} FROM {} ORDER BY 1").format(
                        psycopg.sql.SQL(", ").join(map(psycopg.sql.Identifier, columns)),
                        psycopg.sql.Identifier(table),
                    )
                    source_rows[table] = list(source.execute(query).fetchall())
        except psycopg.Error as exc:
            raise CommandError(f"Unable to read formal competitive database: {exc}") from exc

        attachment_errors = self._validate_attachments(
            source_rows["submission_attachments"], upload_dir
        )
        if attachment_errors:
            raise CommandError("Attachment validation failed: " + "; ".join(attachment_errors))

        if repair_timestamps:
            self._repair_timestamps(source_rows)
            self.stdout.write(self.style.SUCCESS("Formal timestamps restored."))
            return

        try:
            with transaction.atomic():
                for model, table in TABLES:
                    objects = [model(**self._model_values(model, row)) for row in source_rows[table]]
                    model.objects.bulk_create(objects, batch_size=500)
                    for obj, row in zip(objects, source_rows[table], strict=True):
                        obj.created_at = row["created_at"]
                        obj.updated_at = row["updated_at"]
                    if objects:
                        model.objects.bulk_update(
                            objects, ["created_at", "updated_at"], batch_size=500
                        )
                    actual = model.objects.count()
                    expected = len(objects)
                    if actual != expected:
                        raise CommandError(
                            f"Count mismatch for {table}: expected {expected}, found {actual}"
                        )
                for competitor in Competitor.objects.prefetch_related("parameters"):
                    release = ensure_current_release(
                        competitor,
                        changed_by="系统迁移",
                        note="由导入的正式竞品资料生成初始版本。",
                    )
                    Submission.objects.filter(competitor=competitor).update(
                        competitor_release=release
                    )
        except Exception as exc:
            if isinstance(exc, CommandError):
                raise
            raise CommandError(f"Import rolled back: {exc}") from exc

        for _, table in TABLES:
            self.stdout.write(f"{table}: {len(source_rows[table])}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Formal competitive import complete; "
                f"validated {len(source_rows['submission_attachments'])} attachments."
            )
        )

    @staticmethod
    def _model_values(model, row):
        values = {}
        for field in model._meta.concrete_fields:
            if field.column not in row:
                continue
            value = row[field.column]
            if field.is_relation:
                values[field.attname] = value
            else:
                values[field.name] = value
        return values

    @staticmethod
    def _repair_timestamps(source_rows):
        with transaction.atomic():
            for model, table in TABLES:
                rows = source_rows[table]
                source_ids = {row[model._meta.pk.column] for row in rows}
                target = {obj.pk: obj for obj in model.objects.all()}
                if source_ids != set(target):
                    raise CommandError(
                        f"Primary key mismatch for {table}; timestamp repair aborted"
                    )
                objects = []
                for row in rows:
                    obj = target[row[model._meta.pk.column]]
                    obj.created_at = row["created_at"]
                    obj.updated_at = row["updated_at"]
                    objects.append(obj)
                if objects:
                    model.objects.bulk_update(
                        objects, ["created_at", "updated_at"], batch_size=500
                    )

    @staticmethod
    def _validate_attachments(rows, upload_dir):
        errors = []
        for row in rows:
            storage_key = str(row.get("storage_key") or "").strip()
            if not storage_key:
                errors.append(f"{row['id']} has no storage key")
                continue
            path = upload_dir / storage_key
            if not path.is_file():
                errors.append(f"missing {storage_key}")
            elif path.stat().st_size != int(row["byte_size"]):
                errors.append(
                    f"size mismatch {storage_key}: "
                    f"expected {row['byte_size']}, found {path.stat().st_size}"
                )
        return errors
