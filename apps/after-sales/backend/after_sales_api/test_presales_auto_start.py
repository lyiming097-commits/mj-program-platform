from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import RequestFactory, TestCase
from django.utils import timezone

from . import services
from .models import ProjectNode
from .tests import CleanDomainMixin, RequestMixin


class PresalesStartBackfillTests(RequestMixin, CleanDomainMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        self.migration = import_module("after_sales_api.migrations.0023_presales_auto_start")

    def make_project(self, code, **fields):
        return services.create_project(self.request("post", "/"), {
            "code": code, "name": code, "customer": "测试学校", "service_type": "presales",
            "status": "in_progress", **fields,
        })

    def backfill(self):
        self.migration.backfill_presales_starts(apps, SimpleNamespace(connection=connection))

    def test_backfill_uses_unlock_history_and_preserves_explicit_times_for_both_sources(self):
        for source in ("", "crm-history"):
            project = self.make_project(source or "local-history", source_crm_id=source)
            approved_at = timezone.now()
            first = project.nodes.get(node_key="early-approval")
            first.status = "completed"
            first.business_data = {"outcome": "approved"}
            first.completed_at = approved_at
            first.save()
            ProjectNode.objects.filter(project=project, node_key="early-plan").update(status="active", actual_start_at=None)
            manual_start = project.nodes.get(node_key="budget-match").created_at
            ProjectNode.objects.filter(project=project, node_key="budget-match").update(status="active", actual_start_at=manual_start)
            # A row incorrectly marked active must not bypass prerequisites.
            ProjectNode.objects.filter(project=project, node_key="early-plan-result").update(status="active", actual_start_at=None)
            self.backfill()
            self.assertEqual(project.nodes.get(node_key="early-plan").actual_start_at, approved_at)
            self.assertEqual(project.nodes.get(node_key="budget-match").actual_start_at, manual_start)
            self.assertIsNone(project.nodes.get(node_key="project-filing").actual_start_at)
            self.assertIsNone(project.nodes.get(node_key="early-plan-result").actual_start_at)
            self.assertEqual(project.nodes.get(node_key="early-approval").actual_start_at, first.actual_start_at)
            self.backfill()
            self.assertEqual(project.nodes.get(node_key="early-plan").actual_start_at, approved_at)

    def test_first_node_uses_creation_time_and_other_projects_are_not_changed(self):
        active = self.make_project("active")
        excluded = [self.make_project("completed", status="completed"),
                    self.make_project("cancelled", status="cancelled"),
                    self.make_project("blocked", status="blocked"),
                    self.make_project("deleted", deleted_at=timezone.now()),
                    self.make_project("midsales", service_type="midsales")]
        for project in [active, *excluded]:
            project.nodes.update(actual_start_at=None)
        self.backfill()
        first = active.nodes.get(node_key="early-approval")
        self.assertEqual(first.actual_start_at, first.created_at)
        self.assertFalse(active.nodes.exclude(pk=first.pk).exclude(actual_start_at=None).exists())
        for project in excluded:
            self.assertFalse(project.nodes.exclude(actual_start_at=None).exists())
