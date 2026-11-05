from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from .permission_views import (
    current_permissions,
    permission_directory,
    permissions_collection,
)
from .competitor_views import (
    competitor_board_summary,
    competitor_detail,
    competitor_detail_legacy,
    competitor_submissions,
    competitors_collection,
)
from .action_views import (
    create_competitor,
    extend_expiry,
    merge_submission,
    resubmit_submission,
    return_submission,
    soft_delete_competitor,
    update_competitor,
)
from .dashboard_views import bootstrap, expiry_summary, map_config, sidebar_metrics
from .draft_views import delete_draft, latest_draft, save_draft
from .product_views import product_detail, product_image, product_options, products_collection
from .settings_views import setting_item_detail, setting_items, settings_collection
from .submission_views import (
    add_attachment,
    attachment_content,
    attachment_detail,
    create_submission,
    my_submissions,
    submission_detail,
    submissions_root,
)
from .views import health, health_live, health_ready, session


@csrf_exempt
def competitor_root(request, competitor_id):
    if request.method == "DELETE":
        return soft_delete_competitor(request, competitor_id)
    if request.method == "PATCH":
        return update_competitor(request, competitor_id)
    return competitor_detail_legacy(request, competitor_id)


urlpatterns = [
    path("health/", health, name="app-health"),
    path("health/live", health_live, name="app-health-live"),
    path("health/ready", health_ready, name="app-health-ready"),
    path("session/", session, name="session"),
    path("permissions/current", current_permissions, name="permissions-current"),
    path("permissions", permissions_collection, name="permissions"),
    path("permissions/directory", permission_directory, name="permissions-directory"),
    path("settings", settings_collection, name="settings"),
    path("settings/items", setting_items, name="setting-items"),
    path("settings/items/<uuid:item_id>", setting_item_detail, name="setting-item"),
    path("products", products_collection, name="products"),
    path("products/options", product_options, name="product-options"),
    path("products/<str:product_id>", product_detail, name="product-detail"),
    path("products/<str:product_id>/image", product_image, name="product-image"),
    path("location/map-config", map_config, name="map-config"),
    path("bootstrap", bootstrap, name="bootstrap"),
    path("expiry-summary", expiry_summary, name="expiry-summary"),
    path("sidebar-metrics", sidebar_metrics, name="sidebar-metrics"),
    path("competitors", competitors_collection, name="competitors"),
    path("competitors/board-summary", competitor_board_summary, name="competitor-board-summary"),
    path(
        "competitors/<uuid:competitor_id>/submissions",
        competitor_submissions,
        name="competitor-submissions",
    ),
    path(
        "competitors/<uuid:competitor_id>/detail",
        competitor_detail,
        name="competitor-detail",
    ),
    path(
        "competitors/<uuid:competitor_id>",
        competitor_root,
        name="competitor",
    ),
    path("drafts/latest", latest_draft, name="latest-draft"),
    path("drafts", save_draft, name="drafts"),
    path("drafts/<uuid:draft_id>", delete_draft, name="draft"),
    path("submissions", submissions_root, name="submissions"),
    path("submissions/mine", my_submissions, name="my-submissions"),
    path("submissions/<uuid:submission_id>", submission_detail, name="submission"),
    path(
        "submissions/<uuid:submission_id>/attachments",
        add_attachment,
        name="submission-attachments",
    ),
    path(
        "submissions/<uuid:submission_id>/attachments/<uuid:attachment_id>",
        attachment_detail,
        name="submission-attachment",
    ),
    path(
        "submissions/<uuid:submission_id>/attachments/<uuid:attachment_id>/content",
        attachment_content,
        name="submission-attachment-content",
    ),
    path(
        "submissions/<uuid:submission_id>/extend-expiry",
        extend_expiry,
        name="extend-expiry",
    ),
    path(
        "submissions/<uuid:submission_id>/return",
        return_submission,
        name="return-submission",
    ),
    path(
        "submissions/<uuid:submission_id>/resubmit",
        resubmit_submission,
        name="resubmit-submission",
    ),
    path(
        "submissions/<uuid:submission_id>/create-competitor",
        create_competitor,
        name="create-competitor",
    ),
    path(
        "submissions/<uuid:submission_id>/merge",
        merge_submission,
        name="merge-submission",
    ),
]
