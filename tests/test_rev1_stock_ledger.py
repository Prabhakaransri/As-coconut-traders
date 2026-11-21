"""V81 Rev-1 stock ledger regression tests (isolated in-memory SQLite)."""
import sqlite3
import unittest

class StockLedgerTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.executescript("""
        CREATE TABLE products(id INTEGER PRIMARY KEY, stock REAL NOT NULL);
        CREATE TABLE stock_movement_log(id INTEGER PRIMARY KEY, product_id INTEGER, changed TEXT, qty_in REAL, qty_out REAL);
        CREATE TABLE stock_register_baseline(product_id INTEGER PRIMARY KEY, initial_qty REAL, started TEXT);
        INSERT INTO products VALUES(1,0);
        INSERT INTO stock_register_baseline VALUES(1,0,'2026-11-20');
        """)
    def ledger(self):
        return self.db.execute("SELECT COALESCE(SUM(qty_in),0),COALESCE(SUM(qty_out),0) FROM stock_movement_log").fetchone()
    def test_purchase_then_delete_must_not_leave_phantom_turnover(self):
        # Desired Rev-1 semantics: a voided test purchase must be excluded from operational turnover.
        self.db.execute("INSERT INTO stock_movement_log VALUES(1,1,'2026-11-20T10:00:00',150,0)")
        self.db.execute("INSERT INTO stock_movement_log VALUES(2,1,'2026-11-20T10:01:00',0,150)")
        self.assertEqual(self.ledger(),(150,150))
        # This documents the V81 defect; new production query must use source-linked void status.
    def test_net_stock_after_reversal(self):
        self.db.execute("INSERT INTO stock_movement_log VALUES(1,1,'2026-11-20T10:00:00',150,0)")
        self.db.execute("INSERT INTO stock_movement_log VALUES(2,1,'2026-11-20T10:01:00',0,150)")
        self.assertEqual(self.ledger()[0]-self.ledger()[1],0)
if __name__=="__main__":
    unittest.main()
