from django.contrib import admin

from .models import (
    AuthSession,
    Department,
    DepartmentEmployee,
    DepartmentManager,
    Employee,
    InternalServiceCredential,
    OrganizationSyncRun,
    WeChatMiniIdentity,
    WeChatMiniRegistrationChallenge,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("dept_id", "name", "manager_user_id", "parent_dept_id", "updated_at")
    search_fields = ("dept_id", "name", "manager_user_id")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("user_id", "name", "identity_source", "status", "account_status", "handover_user_id", "updated_at")
    list_filter = ("identity_source", "status", "account_status")
    search_fields = ("user_id", "name", "handover_user_id")


@admin.register(WeChatMiniIdentity)
class WeChatMiniIdentityAdmin(admin.ModelAdmin):
    list_display = ("employee", "app_id", "last_login_at", "privacy_version", "created_at")
    search_fields = ("employee__user_id", "employee__name", "openid", "unionid")
    readonly_fields = ("openid", "unionid", "created_at", "updated_at")


@admin.register(WeChatMiniRegistrationChallenge)
class WeChatMiniRegistrationChallengeAdmin(admin.ModelAdmin):
    list_display = ("app_id", "expires_at", "used_at", "created_at")
    readonly_fields = ("token_digest", "openid", "unionid", "created_at")


@admin.register(DepartmentEmployee)
class DepartmentEmployeeAdmin(admin.ModelAdmin):
    list_display = ("department", "employee", "updated_at")
    search_fields = ("department__name", "employee__name", "employee__user_id")


@admin.register(DepartmentManager)
class DepartmentManagerAdmin(admin.ModelAdmin):
    list_display = ("department", "employee", "is_primary", "sort_order", "updated_at")
    search_fields = ("department__name", "employee__name", "employee__user_id")


@admin.register(AuthSession)
class AuthSessionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "session_id", "user_id", "actor_user_id", "status", "expires_at")
    list_filter = ("status", "created_at", "expires_at")
    search_fields = ("session_id", "user_id", "actor_user_id", "revoke_reason")
    readonly_fields = [field.name for field in AuthSession._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(InternalServiceCredential)
class InternalServiceCredentialAdmin(admin.ModelAdmin):
    list_display = ("service_name", "app_id", "enabled", "registry_revision", "updated_at")
    list_filter = ("enabled", "app_id", "updated_at")
    search_fields = ("service_name", "app_id")
    exclude = ("secret_salt", "secret_digest")
    readonly_fields = [
        "service_name",
        "app_id",
        "enabled",
        "registry_revision",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(OrganizationSyncRun)
class OrganizationSyncRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "run_id", "status", "started_by", "finished_at")
    list_filter = ("status", "started_at", "finished_at")
    search_fields = ("run_id", "started_by", "error")
    readonly_fields = [field.name for field in OrganizationSyncRun._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
