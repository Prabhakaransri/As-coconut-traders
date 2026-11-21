"""V81 Rev-1 stock movement regression checks (isolated SQLite test database)."""
import sqlite3
import unittest

QUERY = """SELECT COALESCE(SUM(qty_in),0),COALESCE(SUM(qty_out),0)
 FROM stock_movement_log WHERE product_id=?
 AND id NOT IN (SELECT movement_id FROM rev1_voided_stock_movements)
 AND substr(changed,1,10)=?"""

class StockLedgerTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.executescript("""
        CREATE TABLE stock_movement_log(
          id INTEGER PRIMARY KEY,product_id INTEGER,changed TEXT,
          qty_in REAL,qty_out REAL);
        CREATE TABLE rev1_voided_stock_movements(
          movement_id INTEGER PRIMARY KEY,archive_id INTEGER NOT NULL);
        """)
    def move(self,mid,inc,out):
        self.db.execute("INSERT INTO stock_movement_log VALUES(?,1,'2026-11-21T10:00:00',?,?)",(mid,inc,out))
    def report(self):
        return self.db.execute(QUERY,(1,'2026-11-21')).fetchone()
    def test_deleted_purchase_and_reversal_do_not_count(self):
        self.move(1,150,0)
        self.move(2,0,150)
        self.db.executemany("INSERT INTO rev1_voided_stock_movements VALUES(?,?)",[(1,7),(2,7)])
        self.assertEqual(self.report(),(0,0))
    def test_independent_purchase_same_quantity_is_preserved(self):
        self.move(1,150,0)
        self.move(2,150,0)
        self.move(3,0,150)
        self.db.executemany("INSERT INTO rev1_voided_stock_movements VALUES(?,?)",[(1,7),(3,7)])
        self.assertEqual(self.report(),(150,0))
    def test_audit_movements_remain_available(self):
        self.move(1,150,0)
        self.move(2,0,150)
        self.db.executemany("INSERT INTO rev1_voided_stock_movements VALUES(?,?)",[(1,7),(2,7)])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM stock_movement_log").fetchone()[0],2)
if __name__=="__main__":
    unittest.main()
