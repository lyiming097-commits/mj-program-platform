from decimal import Decimal

from .image_cache import product_thumb_url
from .models import CableMallExternalAccount


def money(value):
    if value is None:
        return "0.00"
    return f"{Decimal(value):.2f}"


def number(value):
    if value is None:
        return None
    return float(value)


def order_salesperson_display(order):
    if getattr(order, "salesperson_name", ""):
        return order.salesperson_name
    customer_account = None
    if getattr(order, "external_account_id", None):
        customer_account = CableMallExternalAccount.objects.filter(pk=order.external_account_id).first()
    if customer_account is None and getattr(order, "external_account_username", ""):
        customer_account = CableMallExternalAccount.objects.filter(username=order.external_account_username).first()
    if customer_account is not None:
        return customer_account.owner_name or customer_account.owner_user_id or "-"
    return getattr(order, "owner_name", "") or getattr(order, "owner_user_id", "") or "-"


def order_submitter_display(order):
    if getattr(order, "submitter_name", ""):
        return order.submitter_name
    if getattr(order, "source", "internal") == "external":
        return (
            getattr(order, "external_account_name", "")
            or getattr(order, "external_account_username", "")
            or getattr(order, "owner_name", "")
            or "-"
        )
    return getattr(order, "owner_name", "") or getattr(order, "owner_user_id", "") or "-"


def cable_item_sort_key(item):
    return (
        item.product_abbr or "",
        item.product_label or "",
        item.product_model or "",
        str(item.product_archive_id or item.id or ""),
    )


def cable_product_dict(product):
    local_thumb = product_thumb_url(product)
    public_images = [local_thumb] if local_thumb else []
    product_id = str(getattr(product, "id", "") or "").strip()
    preview_url = f"/api/products/{product_id}/image/?variant=preview" if product_id and product.product_images else ""
    external_preview_url = (
        f"/api/external-cable-mall/products/{product_id}/image/?variant=preview"
        if product_id and product.product_images
        else ""
    )
    return {
        "id": product.id,
        "product_archive_id": product.product_archive_id,
        "label": product.label,
        "product_brand": product.product_brand,
        "product_model": product.product_model,
        "abbr": product.abbr,
        "category_a": product.category_a,
        "category_b": product.category_b,
        "kingdee_code": product.kingdee_code,
        "product_images": public_images,
        "product_image": public_images[0] if public_images else "",
        "product_thumb": local_thumb,
        "product_image_preview": preview_url,
        "product_image_preview_external": external_preview_url,
        "plan_para": product.plan_para,
        "solution_params": product.plan_para,
        "spec_text": product.spec_text,
        "length_m": number(product.length_m),
        "quantity_unit": product.quantity_unit,
        "unit_price": money(product.unit_price),
        "salesperson_price": money(product.salesperson_price),
        "distributor_price": money(product.distributor_price),
        "budget_price": money(product.budget_price),
        "market_reference_price": money(product.market_reference_price),
        "comments": product.comments,
        "phase": product.phase,
        "archive_updated_at": product.archive_updated_at.isoformat() if product.archive_updated_at else None,
        "synced_at": product.synced_at.isoformat() if product.synced_at else None,
    }


def package_item_dict(item):
    return {
        "id": item.id,
        "product_id": item.product_id,
        "product_archive_id": item.product_archive_id,
        "product_label": item.product_label,
        "product_brand": item.product_brand,
        "product_model": item.product_model,
        "product_abbr": item.product_abbr,
        "category_a": item.category_a,
        "category_b": item.category_b,
        "spec_text": item.spec_text,
        "length_m": number(item.length_m),
        "source_unit": item.source_unit,
        "unit_price": money(item.unit_price),
        "quantity": item.quantity,
        "note": item.note,
    }


def package_dict(package, include_items=True):
    data = {
        "id": package.id,
        "project_id": package.project_id,
        "external_account_id": getattr(package, "external_account_id", None),
        "name": package.name,
        "created_by": package.created_by,
        "owner_name": package.owner_name,
        "classroom_name": package.classroom_name,
        "classroom_scope": package.classroom_scope,
        "note": package.note,
        "quantity": package.quantity,
        "is_default": package.is_default,
        "is_archived": package.is_archived,
        "created_at": package.created_at.isoformat(),
        "updated_at": package.updated_at.isoformat(),
    }
    if include_items:
        items = sorted(package.items.all(), key=cable_item_sort_key)
        data["items"] = [package_item_dict(item) for item in items]
        data["item_count"] = len(items)
        data["cable_count"] = sum(item.quantity for item in items)
    return data


def project_dict(project):
    packages = list(project.packages.filter(is_archived=False).prefetch_related("items"))
    return {
        "id": project.id,
        "external_account_id": getattr(project, "external_account_id", None),
        "name": project.name,
        "created_by": project.created_by,
        "customer_name": project.customer_name,
        "opportunity_info": project.opportunity_info,
        "shipping_address": project.shipping_address,
        "shipping_contact": project.shipping_contact,
        "shipping_phone": project.shipping_phone,
        "note": project.note,
        "is_archived": project.is_archived,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "package_count": len(packages),
        "cable_count": sum(sum(item.quantity for item in package.items.all()) for package in packages),
        "order_quantity": sum(package.quantity for package in packages),
    }


def cart_item_dict(item):
    return {
        "id": item.id,
        "quantity": item.quantity,
        "package": package_dict(item.package),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def product_cart_item_dict(item):
    return {
        "id": item.id,
        "owner_user_id": getattr(item, "owner_user_id", ""),
        "owner_name": getattr(item, "owner_name", ""),
        "external_account_id": getattr(item, "external_account_id", None),
        "quantity": item.quantity,
        "product": cable_product_dict(item.product),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def order_item_dict(item):
    return {
        "id": item.id,
        "product_archive_id": item.product_archive_id,
        "product_label": item.product_label,
        "product_brand": item.product_brand,
        "product_model": item.product_model,
        "product_abbr": item.product_abbr,
        "category_a": item.category_a,
        "category_b": item.category_b,
        "spec_text": item.spec_text,
        "length_m": number(item.length_m),
        "source_unit": item.source_unit,
        "unit_price": money(item.unit_price),
        "quantity_per_package": item.quantity_per_package,
        "total_quantity": item.total_quantity,
        "billing_quantity": money(item.billing_quantity),
        "line_total": money(item.line_total),
        "note": item.note,
    }


def order_package_dict(package):
    return {
        "id": package.id,
        "source_package_id": package.source_package_id,
        "source_project_id": getattr(package, "source_project_id", None),
        "project_name": getattr(package, "project_name", ""),
        "classroom_name": getattr(package, "classroom_name", ""),
        "classroom_scope": getattr(package, "classroom_scope", ""),
        "package_name": package.package_name,
        "package_note": package.package_note,
        "package_quantity": package.package_quantity,
        "items": [order_item_dict(item) for item in sorted(package.items.all(), key=cable_item_sort_key)],
    }


def order_dict(order, include_packages=True):
    can_export_pdf = order.status not in {"未锁定", "已删除", "已下单", ""}
    contract_file = getattr(order, "contract_file", None)
    shipment_file = getattr(order, "shipment_file", None)
    invoice_file = getattr(order, "invoice_file", None)
    payment_file = getattr(order, "payment_file", None)
    customer_external_account_id = getattr(order, "external_account_id", None)
    if not customer_external_account_id and getattr(order, "external_account_username", ""):
        customer_external_account_id = (
            CableMallExternalAccount.objects
            .filter(username=order.external_account_username)
            .values_list("id", flat=True)
            .first()
        )
    data = {
        "id": order.id,
        "order_no": order.order_no,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "project_name": order.project_name,
        "source_shipping_address_id": getattr(order, "source_shipping_address_id", None),
        "source_signing_info_id": getattr(order, "source_signing_info_id", None),
        "signing_info_id": getattr(order, "signing_info_id", None),
        "signing_company_name": getattr(order, "signing_company_name", ""),
        "signing_opening_bank": getattr(order, "signing_opening_bank", ""),
        "signing_tax_number": getattr(order, "signing_tax_number", ""),
        "signing_bank_account": getattr(order, "signing_bank_account", ""),
        "shipping_method": getattr(order, "shipping_method", ""),
        "arrival_date": order.arrival_date.isoformat() if getattr(order, "arrival_date", None) else "",
        "remark": order.remark,
        "total_packages": order.total_packages,
        "total_cables": order.total_cables,
        "total_amount": money(order.total_amount),
        "status": order.status,
        "status_label": order.status,
        "is_locked": can_export_pdf,
        "can_export_pdf": can_export_pdf,
        "locked_at": order.locked_at.isoformat() if getattr(order, "locked_at", None) else None,
        "contract_file_url": contract_file.url if contract_file else "",
        "contract_file_name": contract_file.name.rsplit("/", 1)[-1] if contract_file else "",
        "contract_uploaded_at": order.contract_uploaded_at.isoformat() if getattr(order, "contract_uploaded_at", None) else None,
        "contract_note": getattr(order, "contract_note", ""),
        "shipment_file_url": shipment_file.url if shipment_file else "",
        "shipment_file_name": shipment_file.name.rsplit("/", 1)[-1] if shipment_file else "",
        "shipped_at": order.shipped_at.isoformat() if getattr(order, "shipped_at", None) else None,
        "shipment_note": getattr(order, "shipment_note", ""),
        "invoice_file_url": invoice_file.url if invoice_file else "",
        "invoice_file_name": invoice_file.name.rsplit("/", 1)[-1] if invoice_file else "",
        "invoice_uploaded_at": order.invoice_uploaded_at.isoformat() if getattr(order, "invoice_uploaded_at", None) else None,
        "invoice_note": getattr(order, "invoice_note", ""),
        "payment_file_url": payment_file.url if payment_file else "",
        "payment_file_name": payment_file.name.rsplit("/", 1)[-1] if payment_file else "",
        "paid_at": order.paid_at.isoformat() if getattr(order, "paid_at", None) else None,
        "payment_note": getattr(order, "payment_note", ""),
        "received_at": order.received_at.isoformat() if getattr(order, "received_at", None) else None,
        "source": getattr(order, "source", "internal"),
        "source_label": "外部商城" if getattr(order, "source", "internal") == "external" else "内部下单",
        "owner_user_id": getattr(order, "owner_user_id", ""),
        "owner_name": getattr(order, "owner_name", ""),
        "salesperson_user_id": getattr(order, "salesperson_user_id", ""),
        "salesperson_name": order_salesperson_display(order),
        "submitter_user_id": getattr(order, "submitter_user_id", ""),
        "submitter_name": order_submitter_display(order),
        "external_account_id": getattr(order, "external_account_id", None),
        "external_account_username": getattr(order, "external_account_username", ""),
        "external_account_name": getattr(order, "external_account_name", ""),
        "external_account_credit_code": getattr(order, "external_account_credit_code", ""),
        "customer_external_account_id": customer_external_account_id,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "excel_url": (
            f"/api/external-cable-mall/orders/{order.id}/export.xlsx"
            if getattr(order, "source", "internal") == "external"
            else f"/api/orders/{order.id}/export.xlsx"
        ),
        "pdf_url": (
            (
                f"/api/external-cable-mall/orders/{order.id}/export.pdf"
                if getattr(order, "source", "internal") == "external"
                else f"/api/orders/{order.id}/export.pdf"
            )
            if can_export_pdf
            else ""
        ),
    }
    if include_packages:
        data["packages"] = [order_package_dict(package) for package in order.packages.all()]
    return data


def shipping_address_dict(item):
    return {
        "id": item.id,
        "detail_address": item.detail_address,
        "receiver_name": item.receiver_name,
        "receiver_phone": item.receiver_phone,
        "created_by": item.created_by,
        "owner_user_id": getattr(item, "owner_user_id", ""),
        "external_account_id": getattr(item, "external_account_id", None),
        "is_default": bool(getattr(item, "is_default", False)),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def signing_info_dict(item):
    return {
        "id": item.id,
        "company_name": item.company_name,
        "opening_bank": item.opening_bank,
        "tax_number": item.tax_number,
        "bank_account": item.bank_account,
        "created_by": item.created_by,
        "owner_user_id": getattr(item, "owner_user_id", ""),
        "external_account_id": getattr(item, "external_account_id", None),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def external_account_dict(item, include_counts=True):
    data = {
        "id": item.id,
        "username": item.username,
        "display_name": item.display_name,
        "credit_code": item.credit_code,
        "phone": item.phone,
        "status": item.status,
        "status_label": "启用" if item.status == "active" else "停用",
        "owner_user_id": item.owner_user_id,
        "owner_name": item.owner_name,
        "created_by": item.created_by,
        "last_login_at": item.last_login_at.isoformat() if item.last_login_at else "",
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
    if include_counts:
        data["order_count"] = getattr(item, "order_count", 0)
    return data


def custom_request_dict(item):
    bound_product = item.bound_product
    bound_product_label = ""
    if bound_product:
        bound_product_label = bound_product.abbr or bound_product.product_model or bound_product.label
        bound_product_data = cable_product_dict(bound_product)
    else:
        bound_product_data = None
    return {
        "id": item.id,
        "contact_name": item.contact_name,
        "contact_phone": item.contact_phone,
        "submitter": item.contact_name or item.contact_phone,
        "head_a_type": item.head_a_type,
        "head_a_gender": item.head_a_gender,
        "head_b_type": item.head_b_type,
        "head_b_gender": item.head_b_gender,
        "length_m": number(item.length_m),
        "quantity": item.quantity,
        "category_a": item.category_a,
        "category_b": item.category_b,
        "scenario": item.scenario,
        "note": item.note,
        "status": item.status,
        "handle_result": item.handle_result,
        "bound_product_id": item.bound_product_id,
        "bound_product_label": bound_product_label,
        "bound_product": bound_product_data,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
