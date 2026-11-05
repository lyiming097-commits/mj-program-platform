import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .database import connect_database


class UserRepository:
    @staticmethod
    def list_active_public(order_by_role=False):
        from .organization import routing_users
        rows = [(u['username'], u['displayName'], u['role'], u['department'], u['managerUsername'], u['departmentIds'], u['managerUserIds']) for u in routing_users()]
        return sorted(rows, key=lambda row: (row[2], row[1]) if order_by_role else row[1])

    list_active_for_routing = list_active_public

    @staticmethod
    def get_active_user(username):
        from .organization import routing_users
        return next(((u['username'], u['displayName']) for u in routing_users() if u['username'] == username), None)


class DatabaseRepository:
    @staticmethod
    def health_check() -> None:
        with connect_database() as connection:
            connection.execute("SELECT 1").fetchone()


class FormRepository:
    @staticmethod
    def list_schemas() -> list[tuple]:
        with connect_database() as connection:
            return connection.execute("SELECT schema_json FROM forms ORDER BY updated_at DESC").fetchall()

    @staticmethod
    def get_schema(form_id: str) -> tuple | None:
        with connect_database() as connection:
            return connection.execute("SELECT schema_json FROM forms WHERE id = ?", (form_id,)).fetchone()

    @staticmethod
    def save_schema(form_id: str, schema: dict) -> None:
        with connect_database() as connection:
            connection.execute(
                "INSERT INTO forms (id, schema_json, updated_at) VALUES (?, ?, ?) "
                "ON DUPLICATE KEY UPDATE schema_json = VALUES(schema_json), updated_at = VALUES(updated_at)",
                (form_id, json.dumps(schema, ensure_ascii=False), schema["updatedAt"]),
            )


class WorkflowRepository:
    @staticmethod
    def lock_definition(workflow_id: str) -> None:
        # Called inside the HTTP transaction. An advisory lock also covers the
        # initial sample definition before it has a row, and concurrent creates.
        from django.db import connection
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                               ['form-designer:workflow:' + workflow_id])

    @staticmethod
    def list_schemas() -> list[tuple]:
        with connect_database() as connection:
            return connection.execute("SELECT schema_json FROM workflows ORDER BY updated_at DESC").fetchall()

    @staticmethod
    def get_schema(workflow_id: str) -> tuple | None:
        with connect_database() as connection:
            return connection.execute("SELECT schema_json FROM workflows WHERE id = ?", (workflow_id,)).fetchone()

    @staticmethod
    def create_schema(schema: dict) -> None:
        with connect_database() as connection:
            connection.execute(
                "INSERT INTO workflows (id, schema_json, updated_at) VALUES (?, ?, ?)",
                (schema["id"], json.dumps(schema, ensure_ascii=False), schema["updatedAt"]),
            )

    @staticmethod
    def save_schema(workflow_id: str, schema: dict) -> None:
        with connect_database() as connection:
            connection.execute(
                "INSERT INTO workflows (id, schema_json, updated_at) VALUES (?, ?, ?) "
                "ON DUPLICATE KEY UPDATE schema_json = VALUES(schema_json), updated_at = VALUES(updated_at)",
                (workflow_id, json.dumps(schema, ensure_ascii=False), schema["updatedAt"]),
            )


class SubmissionRepository:
    @staticmethod
    def seed_sample_records(form_id: str, now: str) -> None:
        if form_id != "sample":
            return
        samples = [
            ("啊额连键我我去", "钟小康", {"item-name": "委屈俄", "quantity": "1", "address": "产品组", "scene": "设备维修", "remark": "非常紧急"}),
            ("1321321", "钟小康", {"item-name": "此说法", "quantity": "10", "address": "产品组", "scene": "固定资产采购", "remark": "非常紧急"}),
            ("1321321", "钟小康", {"item-name": "213213", "quantity": "4"}),
            ("申请键盘", "钟小康", {"item-name": "机械键盘", "quantity": "1", "unit-price": "399"}),
        ]
        with connect_database() as connection:
            marker = connection.execute("INSERT IGNORE INTO record_seeded (form_id) VALUES (?)", (form_id,))
            if marker.rowcount == 0:
                return
            for title, applicant, values in samples:
                record_id = uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO submissions (id, form_id, title, applicant, values_json, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                    (record_id, form_id, title, applicant, json.dumps(values, ensure_ascii=False), now, now),
                )

    @staticmethod
    def list_records(form_id: str, recycle: bool) -> list[tuple]:
        deleted_filter = "deleted_at IS NOT NULL" if recycle else "deleted_at IS NULL"
        with connect_database() as connection:
            return connection.execute(
                f"SELECT id, form_id, title, applicant, values_json, created_at, updated_at, deleted_at "
                f"FROM submissions WHERE form_id = ? AND {deleted_filter} ORDER BY created_at DESC",
                (form_id,),
            ).fetchall()

    @staticmethod
    def create_record(record_id: str, form_id: str, title: str, applicant: str, values_json: str, now: str) -> None:
        with connect_database() as connection:
            connection.execute(
                "INSERT INTO submissions (id, form_id, title, applicant, values_json, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (record_id, form_id, title, applicant, values_json, now, now),
            )

    @staticmethod
    def update_record(record_id: str, form_id: str, title: str, applicant: str, values_json: str, now: str) -> tuple | None:
        with connect_database() as connection:
            cursor = connection.execute(
                "UPDATE submissions SET title = ?, applicant = ?, values_json = ?, updated_at = ? WHERE id = ? AND form_id = ? AND deleted_at IS NULL",
                (title, applicant, values_json, now, record_id, form_id),
            )
            if not cursor.rowcount:
                return None
            return connection.execute(
                "SELECT id, form_id, title, applicant, values_json, created_at, updated_at, deleted_at FROM submissions WHERE id = ?",
                (record_id,),
            ).fetchone()

    @staticmethod
    def delete_record(record_id: str, form_id: str, permanent: bool, now: str) -> bool:
        with connect_database() as connection:
            if permanent:
                cursor = connection.execute(
                    "DELETE FROM submissions WHERE id = ? AND form_id = ? AND deleted_at IS NOT NULL",
                    (record_id, form_id),
                )
            else:
                cursor = connection.execute(
                    "UPDATE submissions SET deleted_at = ?, updated_at = ? WHERE id = ? AND form_id = ? AND deleted_at IS NULL",
                    (now, now, record_id, form_id),
                )
            return cursor.rowcount > 0

    @staticmethod
    def restore_record(record_id: str, form_id: str, now: str) -> tuple | None:
        with connect_database() as connection:
            cursor = connection.execute(
                "UPDATE submissions SET deleted_at = NULL, updated_at = ? WHERE id = ? AND form_id = ? AND deleted_at IS NOT NULL",
                (now, record_id, form_id),
            )
            if not cursor.rowcount:
                return None
            return connection.execute(
                "SELECT id, form_id, title, applicant, values_json, created_at, updated_at, deleted_at FROM submissions WHERE id = ?",
                (record_id,),
            ).fetchone()


class WorkflowRunRepository:
    @staticmethod
    def list_for_workflow(workflow_id: str) -> list[tuple]:
        with connect_database() as connection:
            return connection.execute(
                "SELECT result_json FROM workflow_runs WHERE workflow_id = ? ORDER BY created_at DESC", (workflow_id,)
            ).fetchall()

    @staticmethod
    def list_for_applicant(user_id: str) -> list[tuple]:
        with connect_database() as connection:
            return connection.execute(
                "SELECT applicant, result_json FROM workflow_runs WHERE result_json::jsonb ->> 'applicantUsername' = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()

    @staticmethod
    def list_pending() -> list[tuple]:
        with connect_database() as connection:
            return connection.execute(
                "SELECT result_json FROM workflow_runs WHERE status = 'pending' ORDER BY created_at DESC"
            ).fetchall()

    @staticmethod
    def list_all() -> list[tuple]:
        with connect_database() as connection:
            return connection.execute("SELECT result_json FROM workflow_runs ORDER BY created_at DESC").fetchall()

    @staticmethod
    @contextmanager
    def task_action_transaction() -> Iterator["WorkflowTaskUnitOfWork"]:
        with connect_database() as connection:
            yield WorkflowTaskUnitOfWork(connection)

    @staticmethod
    def create_run(run: dict, now: str) -> None:
        with connect_database() as connection:
            connection.execute(
                "INSERT INTO submissions (id, form_id, title, applicant, values_json, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (run["submissionId"], run["formId"], run["title"], run["applicant"], json.dumps(run["values"], ensure_ascii=False), now, now),
            )
            connection.execute(
                "INSERT INTO workflow_runs (id, workflow_id, workflow_version, form_id, submission_id, applicant, status, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run["id"], run["workflowId"], run["workflowVersion"], run["formId"], run["submissionId"], run["applicant"], run["status"], json.dumps(run, ensure_ascii=False), now),
            )


class WorkflowTaskUnitOfWork:
    def __init__(self, connection):
        self.connection = connection

    def get_run_for_update(self, run_id: str) -> tuple | None:
        return self.connection.execute(
            "SELECT workflow_id, workflow_version, form_id, submission_id, status, result_json FROM workflow_runs WHERE id = ? FOR UPDATE",
            (run_id,),
        ).fetchone()

    def get_submission_values(self, submission_id: str, form_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT values_json FROM submissions WHERE id = ? AND form_id = ? AND deleted_at IS NULL",
            (submission_id, form_id),
        ).fetchone()
        return row[0] if row else None

    def get_form_schema(self, form_id: str) -> str | None:
        row = self.connection.execute("SELECT schema_json FROM forms WHERE id = ?", (form_id,)).fetchone()
        return row[0] if row else None

    def get_active_user(self, username: str):
        return UserRepository.get_active_user(username)

    def save_run(self, run: dict) -> None:
        self.connection.execute(
            "UPDATE workflow_runs SET status = ?, result_json = ? WHERE id = ?",
            (run["status"], json.dumps(run, ensure_ascii=False), run["id"]),
        )

    def save_task_action(self, run_id: str, submission_id: str, form_id: str, run: dict, values: dict, now: str) -> None:
        self.connection.execute(
            "UPDATE submissions SET values_json = ?, updated_at = ? WHERE id = ? AND form_id = ?",
            (json.dumps(values, ensure_ascii=False), now, submission_id, form_id),
        )
        self.connection.execute(
            "UPDATE workflow_runs SET status = ?, result_json = ? WHERE id = ?",
            (run["status"], json.dumps(run, ensure_ascii=False), run_id),
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
