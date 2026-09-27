import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-db-test-'))
from app import server


class ConnectionTests(unittest.TestCase):
    def test_workspace_and_catalog_connections_close_after_commit_or_rollback(self):
        for connect in (server.db,server.catalog_db):
            with connect() as c:
                c.execute('CREATE TABLE IF NOT EXISTS connection_cleanup_test(value TEXT)')
                c.execute('DELETE FROM connection_cleanup_test')
                c.execute("INSERT INTO connection_cleanup_test VALUES ('committed')")
            with self.assertRaises(sqlite3.ProgrammingError):c.execute('SELECT 1')
            with self.assertRaises(ValueError):
                with connect() as failed:
                    failed.execute("INSERT INTO connection_cleanup_test VALUES ('rolled back')")
                    raise ValueError('rollback')
            with self.assertRaises(sqlite3.ProgrammingError):failed.execute('SELECT 1')
            with connect() as check:
                self.assertEqual([r[0] for r in check.execute('SELECT value FROM connection_cleanup_test')],['committed'])
                check.execute('DROP TABLE connection_cleanup_test')
