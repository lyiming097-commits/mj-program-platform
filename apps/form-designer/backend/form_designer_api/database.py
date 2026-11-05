from django.db import connection, transaction

class DatabaseConnection:
    def __enter__(self):
        self.atomic = transaction.atomic()
        self.atomic.__enter__()
        self.cursors = []
        return self

    def __exit__(self, *args):
        for cursor in self.cursors:
            cursor.close()
        return self.atomic.__exit__(*args)

    def execute(self, query, params=()):
        # Existing business repositories use parameterized SQL; migrations own DDL.
        query = query.replace('?', '%s')
        if 'ON DUPLICATE KEY UPDATE' in query:
            query = query.split('ON DUPLICATE KEY UPDATE')[0] + 'ON CONFLICT (id) DO UPDATE SET schema_json=EXCLUDED.schema_json, updated_at=EXCLUDED.updated_at'
        if query.startswith('INSERT IGNORE INTO'):
            query = query.replace('INSERT IGNORE INTO', 'INSERT INTO', 1) + ' ON CONFLICT DO NOTHING'
        if connection.vendor == 'sqlite':
            query = query.replace(' FOR UPDATE', '')
        cursor = connection.cursor()
        self.cursors.append(cursor)
        cursor.execute(query, params)
        return cursor

def connect_database():
    return DatabaseConnection()
