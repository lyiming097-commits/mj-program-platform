from typing import Literal

from pydantic import BaseModel, Field, field_validator


def default_page_settings() -> dict:
    return {
        "titleMode": "default", "customTitle": "", "allowCopy": False, "copyDataSource": "initiator",
        "previewBeforeSubmit": True, "oneClickGroup": True, "consultants": [],
        "showAdminWhenNoConsultant": False, "redirectMode": "default", "redirectUrl": "",
        "afterApproval": "next_dialog", "refreshMemberFields": True,
    }


def default_page_permissions() -> dict:
    return {
        "accessMode": "all", "members": [], "canSubmit": True,
        "canViewOwnRecords": True, "canViewAllRecords": False, "canExportRecords": False,
    }


class FormPayload(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    fields: list[dict]
    pageSettings: dict = Field(default_factory=default_page_settings)
    permissions: dict = Field(default_factory=default_page_permissions)
    updatedAt: str | None = None


class WorkflowPayload(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    category: str = Field(default="常用流程", max_length=40)
    nodes: list[dict]
    applicantFieldPermissions: list[dict] = Field(default_factory=list)
    publishedAt: str | None = None
    publishedVersion: int = 0
    publishedSnapshot: dict | None = None
    updatedAt: str | None = None


class WorkflowRunPayload(BaseModel):
    values: dict = Field(default_factory=dict)


class WorkflowRecallPayload(BaseModel):
    comment: str = Field(default="", max_length=2000)


class TaskActionPayload(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    comment: str = Field(default="", max_length=2000)
    values: dict = Field(default_factory=dict)
    targetUsername: str | None = Field(default=None, max_length=80)
    rejectBehavior: Literal["return", "end"] | None = None


class RecordPayload(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    applicant: str = Field(default="钟小康", max_length=100)
    values: dict[str, str] = Field(default_factory=dict)


class ApprovalCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    category: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=2000)
    assignees: list[str] = Field(min_length=1, max_length=50)

    @field_validator("name", "category")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("不能为空")
        return value.strip()
