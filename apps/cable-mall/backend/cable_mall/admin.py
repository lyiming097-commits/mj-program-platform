from django.contrib import admin

from .models import (
    CableMallExternalAccount,
    CableMallPermissionRule,
    CablePackage,
    CablePackageItem,
    CableProduct,
    CartItem,
    CustomCableRequest,
    Order,
    OrderItem,
    OrderPackage,
    ProductCartItem,
    Project,
    ShippingAddress,
    SigningInfo,
)


class CablePackageItemInline(admin.TabularInline):
    model = CablePackageItem
    extra = 0


@admin.register(CableProduct)
class CableProductAdmin(admin.ModelAdmin):
    list_display = ("product_archive_id", "abbr", "label", "product_model", "category_a", "category_b", "unit_price", "phase", "is_active")
    list_filter = ("is_active", "category_a", "category_b", "phase")
    search_fields = ("label", "abbr", "product_model", "kingdee_code")


@admin.register(CablePackage)
class CablePackageAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "classroom_name", "classroom_scope", "owner_name", "is_archived", "updated_at")
    list_filter = ("is_archived", "project", "classroom_scope")
    search_fields = ("name", "owner_name", "classroom_name", "project__name")
    inlines = [CablePackageItemInline]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "customer_name", "shipping_contact", "shipping_phone", "is_archived", "updated_at")
    list_filter = ("is_archived",)
    search_fields = ("name", "customer_name", "opportunity_info", "shipping_address", "shipping_contact", "shipping_phone", "note")


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ("package", "quantity", "updated_at")


@admin.register(ProductCartItem)
class ProductCartItemAdmin(admin.ModelAdmin):
    list_display = ("product", "quantity", "owner_name", "owner_user_id", "external_account", "updated_at")
    search_fields = ("product__abbr", "product__label", "owner_name", "owner_user_id", "external_account__username", "external_account__display_name")
    list_filter = ("external_account",)


class OrderPackageInline(admin.TabularInline):
    model = OrderPackage
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_no", "source", "customer_name", "project_name", "signing_company_name", "owner_name", "external_account_username", "total_packages", "total_cables", "total_amount", "status", "created_at")
    list_filter = ("status", "source")
    search_fields = ("order_no", "customer_name", "project_name", "signing_company_name", "signing_tax_number", "owner_name", "external_account_username", "external_account_name")
    inlines = [OrderPackageInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("product_abbr", "product_model", "quantity_per_package", "total_quantity", "line_total")
    search_fields = ("product_abbr", "product_model", "product_label")


@admin.register(OrderPackage)
class OrderPackageAdmin(admin.ModelAdmin):
    list_display = ("order", "package_name", "package_quantity")


@admin.register(ShippingAddress)
class ShippingAddressAdmin(admin.ModelAdmin):
    list_display = ("receiver_name", "receiver_phone", "detail_address", "created_by", "owner_user_id", "external_account", "updated_at")
    search_fields = ("receiver_name", "receiver_phone", "detail_address", "created_by", "owner_user_id", "external_account__username")


@admin.register(SigningInfo)
class SigningInfoAdmin(admin.ModelAdmin):
    list_display = ("company_name", "opening_bank", "tax_number", "bank_account", "created_by", "owner_user_id", "external_account", "updated_at")
    search_fields = ("company_name", "opening_bank", "tax_number", "bank_account", "created_by", "owner_user_id", "external_account__username")


@admin.register(CableMallExternalAccount)
class CableMallExternalAccountAdmin(admin.ModelAdmin):
    list_display = ("username", "display_name", "credit_code", "status", "owner_name", "owner_user_id", "last_login_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("username", "display_name", "credit_code", "owner_name", "owner_user_id")


@admin.register(CustomCableRequest)
class CustomCableRequestAdmin(admin.ModelAdmin):
    list_display = ("head_a_type", "head_a_gender", "head_b_type", "head_b_gender", "length_m", "quantity", "status", "bound_product", "handle_result", "created_at")
    list_filter = ("status", "head_a_type", "head_b_type")
    search_fields = ("head_a_type", "head_b_type", "contact_name", "contact_phone", "note", "handle_result", "bound_product__abbr", "bound_product__product_model")


@admin.register(CableMallPermissionRule)
class CableMallPermissionRuleAdmin(admin.ModelAdmin):
    list_display = ("permission", "scope_type", "target_name", "target_id", "sort_order", "created_by", "updated_at")
    list_filter = ("permission", "scope_type")
    search_fields = ("target_name", "target_id", "created_by")
