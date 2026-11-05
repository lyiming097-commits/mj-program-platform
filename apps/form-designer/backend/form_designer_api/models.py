from django.db import models

class Form(models.Model):
    id = models.CharField(max_length=80, primary_key=True)
    schema_json = models.TextField()
    updated_at = models.CharField(max_length=40)
    class Meta:
        db_table = 'forms'

class Workflow(models.Model):
    id = models.CharField(max_length=80, primary_key=True)
    schema_json = models.TextField()
    updated_at = models.CharField(max_length=40)
    class Meta:
        db_table = 'workflows'

class Submission(models.Model):
    id = models.CharField(max_length=32, primary_key=True)
    form_id = models.CharField(max_length=80, db_index=True)
    title = models.CharField(max_length=200)
    applicant = models.CharField(max_length=100)
    values_json = models.TextField()
    created_at = models.CharField(max_length=40)
    updated_at = models.CharField(max_length=40)
    deleted_at = models.CharField(max_length=40, null=True)
    class Meta:
        db_table = 'submissions'

class WorkflowRun(models.Model):
    id = models.CharField(max_length=32, primary_key=True)
    workflow_id = models.CharField(max_length=80, db_index=True)
    workflow_version = models.IntegerField()
    form_id = models.CharField(max_length=80, db_index=True)
    submission_id = models.CharField(max_length=32)
    applicant = models.CharField(max_length=100)
    status = models.CharField(max_length=40, db_index=True)
    result_json = models.TextField()
    created_at = models.CharField(max_length=40)
    class Meta:
        db_table = 'workflow_runs'

class RecordSeeded(models.Model):
    form_id = models.CharField(max_length=80, primary_key=True)
    class Meta:
        db_table = 'record_seeded'

class PermissionState(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    revision = models.PositiveIntegerField(default=1)

class PermissionRule(models.Model):
    permission = models.CharField(max_length=20)
    scope_type = models.CharField(max_length=20)
    target_id = models.CharField(max_length=80)
    target_name = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)

class AuditEvent(models.Model):
    actor_user_id = models.CharField(max_length=80)
    effective_user_id = models.CharField(max_length=80)
    action = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)


class CategorySupervisorState(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    revision = models.PositiveIntegerField(default=1)
    assignments = models.JSONField(default=dict)
