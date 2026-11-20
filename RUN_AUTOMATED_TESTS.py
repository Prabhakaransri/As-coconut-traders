import os,subprocess,tempfile,pathlib,textwrap
src=(pathlib.Path(__file__).resolve().parent / 'AS_Coconut_Traders_Billing.py').read_text()
test=r'''
import traceback
results=[]
def check(name, fn):
 try:fn();results.append((name,'PASS',''))
 except Exception as e:results.append((name,'FAIL',repr(e)));traceback.print_exc()
messagebox.askyesno=lambda *a,**k: True
messagebox.askyesnocancel=lambda *a,**k: False
messagebox.showinfo=lambda *a,**k: None
messagebox.showwarning=lambda *a,**k: None
errors=[]
messagebox.showerror=lambda *a,**k: errors.append(str(a))
def equal(a,b):assert a==b,(a,b)
def pid(n):return con.execute('SELECT id FROM products WHERE name=?',(n,)).fetchone()[0]
def stock(n):return con.execute('SELECT stock FROM products WHERE id=?',(pid(n),)).fetchone()[0]
def setentry(w,v):w.delete(0,'end');w.insert(0,str(v))
def test_catalog():
 equal(len(PRODUCT_CATALOG),14);equal(con.execute('SELECT COUNT(*) FROM products').fetchone()[0],15)
 equal(con.execute('SELECT unit FROM products WHERE name="Packing Bag"').fetchone()[0],'Nos')
def test_purchase():
 supplier.delete(0,'end');supplier.insert(0,'Demo Supplier')
 v74_cart.extend([(pid('Black Coconut'),'Black Coconut',2500,55),(pid('Small Size Coconut'),'Small Size Coconut',250,55)])
 setentry(purchase_paid,25000)
 v74_save_group()
 equal(stock('Black Coconut'),2500);equal(stock('Small Size Coconut'),250)
 equal(con.execute('SELECT COUNT(*) FROM purchase_groups').fetchone()[0],1)
 equal(con.execute('SELECT SUM(amount),SUM(paid) FROM purchases').fetchone(),(151250,25000))
def test_supplier_payment():
 con.execute("INSERT INTO supplier_payments(supplier,created,amount,method) VALUES('Demo Supplier',datetime('now'),126250,'Cash')");con.commit()
 a=supplier_purchase_allocations();equal(round(sum(v[1] for v in a.values()),2),0)
 refresh_supplier_accounts()
def test_bag():
 bid=pid('Packing Bag');con.execute("INSERT INTO purchases(created,supplier,product_id,qty,unit_cost,amount,paid) VALUES(datetime('now'),'Bag Supplier',?,100,10,1000,250)",(bid,))
 con.execute('UPDATE products SET stock=stock+100 WHERE id=?',(bid,));con.commit();refresh_all()
 purchase_id=con.execute('SELECT MAX(id) FROM purchases').fetchone()[0]
 bag_purchase_tree.selection_set(str(purchase_id));delete_selected_bag_purchase()
 equal(stock('Packing Bag'),0)
 restore_last_bag_entry();equal(stock('Packing Bag'),100)
 equal(con.execute('SELECT COUNT(*) FROM purchases WHERE id=?',(purchase_id,)).fetchone()[0],1)
def test_customer():
 con.execute("INSERT INTO customers(name,phone,address) VALUES('Sample Customer','0000000000','TEST ONLY')");con.commit();refresh_all()
 equal(con.execute('SELECT COUNT(*) FROM customers').fetchone()[0],1)
def test_bill():
 cid=con.execute('SELECT id FROM customers').fetchone()[0]
 bill_customer.set(f'{cid} | Sample Customer')
 cart.extend([dict(pid=pid('Black Coconut'),name='Black Coconut',qty=250,rate=65,tax=0,total=16250),dict(pid=pid('Small Size Coconut'),name='Small Size Coconut',qty=140,rate=55,tax=0,total=7700),dict(pid=pid('Packing Bag'),name='Packing Bag',qty=10,rate=30,tax=0,total=300)])
 setentry(bill_paid,5000)
 import builtins
 globals()['open_pdf']=lambda *a,**k: None
 globals()['share_invoice_whatsapp']=lambda *a,**k: None
 iid=create_invoice()
 assert iid is not None,errors
 equal(con.execute('SELECT total,paid FROM invoices WHERE id=?',(iid,)).fetchone(),(24250,5000))
 equal(stock('Black Coconut'),2250);equal(stock('Small Size Coconut'),110);equal(stock('Packing Bag'),90)
 globals()['test_iid']=iid

def test_pdf():
 p=save_invoice_pdf(test_iid,force=True);assert p.exists() and p.stat().st_size>1000,p
 from PIL import Image
 im=premium_bill_image(test_iid);assert isinstance(im,Image.Image) and im.width>0
 import subprocess
 output=subprocess.check_output(['pdftotext',str(p),'-'],text=True)
 for unit in ('Kg','Nos'):assert unit in output,output[:1000]
def test_ledger():
 cid=con.execute('SELECT id FROM customers').fetchone()[0]
 due,adv=customer_account_position(cid);equal(due,19250);equal(adv,0)
 con.execute("INSERT INTO customer_payments(customer_id,created,amount,method) VALUES(?,datetime('now'),19250,'UPI')",(cid,));con.commit()
 due,adv=customer_account_position(cid);equal(due,0);equal(adv,0)
 con.execute("INSERT INTO customer_payments(customer_id,created,amount,method) VALUES(?,datetime('now'),500,'UPI')",(cid,));con.commit()
 due,adv=customer_account_position(cid);equal(due,0);equal(adv,500)
def test_insufficient_stock():
 global cart
 cart.clear();cart.append(dict(pid=pid('Black Coconut'),name='Black Coconut',qty=999999,rate=50,tax=0,total=49999950))
 cid=con.execute('SELECT id FROM customers').fetchone()[0];bill_customer.set(f'{cid} | Sample Customer');setentry(bill_paid,0)
 before=con.execute('SELECT COUNT(*) FROM invoices').fetchone()[0];before_stock=stock('Black Coconut')
 result=create_invoice();assert result is None
 equal(con.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],before);equal(stock('Black Coconut'),before_stock)
 cart.clear()
def test_historical_merge():
 before_stock=stock('Black Coconut')
 for q in (2,3):
  con.execute("INSERT INTO purchases(created,supplier,product_id,qty,unit_cost,amount,paid) VALUES(datetime('now'),'Merge Supplier',?,?,50,?,0)",(pid('Black Coconut'),q,q*50))
 con.commit();refresh_all()
 ids=[str(r[0]) for r in con.execute("SELECT id FROM purchases WHERE supplier='Merge Supplier'")]
 purchase_manage_tree.selection_set(ids)
 v74_merge_selected()
 gids=con.execute("SELECT DISTINCT group_id FROM purchases WHERE supplier='Merge Supplier'").fetchall()
 equal(len(gids),1);assert gids[0][0] is not None
 equal(stock('Black Coconut'),before_stock)
 equal(con.execute("SELECT SUM(amount) FROM purchases WHERE supplier='Merge Supplier'").fetchone()[0],250)
def test_cross_supplier_merge_rejected():
 refresh_all();ids=[str(con.execute("SELECT id FROM purchases WHERE supplier=? LIMIT 1",(name,)).fetchone()[0]) for name in ('Demo Supplier','Bag Supplier')]
 before=con.execute('SELECT COUNT(*) FROM purchase_groups').fetchone()[0]
 purchase_manage_tree.selection_set(ids);v74_merge_selected()
 equal(con.execute('SELECT COUNT(*) FROM purchase_groups').fetchone()[0],before)
 assert any('SAME supplier' in str(x) for x in errors)
def test_sqlite_integrity():
 equal(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
 equal(con.execute('PRAGMA foreign_key_check').fetchall(), [])
def test_invoice_item_totals():
 for iid,total in con.execute('SELECT id,total FROM invoices').fetchall():
  item_sum=con.execute('SELECT COALESCE(SUM(line_total),0) FROM invoice_items WHERE invoice_id=?',(iid,)).fetchone()[0]
  assert abs(item_sum-total)<0.01,(iid,item_sum,total)
def test_supplier_purchase_group_consistency():
 rows=con.execute('SELECT p.id,p.supplier,g.supplier FROM purchases p JOIN purchase_groups g ON p.group_id=g.id').fetchall()
 for purchase_id,ps,gs in rows:equal(ps,gs)
for n,f in [('catalog',test_catalog),('multi_product_purchase',test_purchase),('supplier_settlement',test_supplier_payment),('bag_delete_restore',test_bag),('sample_customer',test_customer),('multi_item_invoice',test_bill),('pdf_and_image',test_pdf),('customer_pending_advance',test_ledger),('insufficient_stock_rollback',test_insufficient_stock),('historical_purchase_merge',test_historical_merge),('cross_supplier_merge_guard',test_cross_supplier_merge_rejected),('sqlite_integrity',test_sqlite_integrity),('invoice_item_totals',test_invoice_item_totals),('supplier_group_consistency',test_supplier_purchase_group_consistency)]:check(n,f)
for n,s,err in results:print('TEST',n,s,err,flush=True)
print('ERROR_DIALOGS',errors,flush=True)
print('TOTAL',len(results),'FAILED',sum(s!='PASS' for _,s,_ in results),flush=True)
assert all(status=='PASS' for _,status,_ in results), 'Automated workflow tests failed'
root.destroy()
con.close()
'''
assert src.endswith('root.mainloop()\ncon.close()\n')
out=src[:-len('root.mainloop()\ncon.close()\n')]+test
with tempfile.TemporaryDirectory(prefix='asct_tests_') as d:
 p=pathlib.Path(d) / 'test_runner_generated.py';p.write_text(out)
 env=os.environ.copy();env['LOCALAPPDATA']=d;env['DISPLAY']=':99'
 xv=subprocess.Popen(['Xvfb',':99','-screen','0','1280x900x24'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) if os.name!='nt' else None
 try:
  import time;time.sleep(.7)
  r=subprocess.run(['python',str(p)],env=env,capture_output=True,text=True,timeout=100)
  print('EXIT',r.returncode);print('STDOUT',r.stdout[-9000:]);print('STDERR',r.stderr[-9000:])
 finally:
  if xv:xv.terminate()
