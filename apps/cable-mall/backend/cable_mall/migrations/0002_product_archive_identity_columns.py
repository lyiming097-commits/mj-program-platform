from django.db import migrations


RENAMES = (
    ("cable_mall_cableproduct", "source_product_id", "product_archive_id"),
    ("cable_mall_cableproduct", "kingdee", "kingdee_code"),
    ("cable_mall_cableproduct", "source_updated_at", "archive_updated_at"),
    ("cable_mall_cablepackageitem", "source_product_id", "product_archive_id"),
    ("cable_mall_orderitem", "source_product_id", "product_archive_id"),
)


def rename_legacy_columns(apps, schema_editor):
    """Bring databases created by the old syncdb-only app to the current state.

    The initial migration is intentionally marked fake by Django when all old
    tables already exist. This follow-up therefore performs only the column
    transition. On a new database the target columns already exist and every
    operation is a no-op.
    """
    connection = schema_editor.connection
    quote = connection.ops.quote_name
    introspection = connection.introspection

    for table_name, old_name, new_name in RENAMES:
        description = introspection.get_table_description(connection.cursor(), table_name)
        columns = {column.name for column in description}
        if old_name not in columns:
            continue
        if new_name in columns:
            raise RuntimeError(
                f"线缆商城表 {table_name} 同时存在旧列 {old_name} 和新列 {new_name}，"
                "已停止迁移，请先核对两列数据。"
            )
        schema_editor.execute(
            f"ALTER TABLE {quote(table_name)} "
            f"RENAME COLUMN {quote(old_name)} TO {quote(new_name)}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("cable_mall", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(rename_legacy_columns, migrations.RunPython.noop),
    ]
