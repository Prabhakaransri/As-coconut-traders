import sqlite3, tkinter as tk, csv, shutil, os, sys, webbrowser, html, base64, re, json, tempfile, hashlib, secrets, urllib.request
from urllib.parse import quote
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime, timedelta
from pathlib import Path
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image as RLImage, KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.units import mm

# V45 build: logos/banner live next to the script, or in PyInstaller's bundle folder when packaged as an EXE.
BASE_DIR=Path(getattr(sys,'_MEIPASS',None) or Path(__file__).resolve().parent)

APP='AS Coconut Traders | Premium Billing V81 Final Candidate'
DATA=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'AS_Coconut_Traders_V72_Fresh_Start'
DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'billing.db'
con=sqlite3.connect(DB)
con.execute('PRAGMA foreign_keys=ON')
con.executescript('''
CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY,name TEXT NOT NULL,phone TEXT,address TEXT,gstin TEXT);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,unit TEXT NOT NULL DEFAULT 'Nos',stock REAL NOT NULL DEFAULT 0,cost REAL NOT NULL DEFAULT 0,rate REAL NOT NULL DEFAULT 0,hsn TEXT DEFAULT '',tax REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY,number TEXT UNIQUE NOT NULL,customer_id INTEGER,created TEXT NOT NULL,subtotal REAL NOT NULL,tax_total REAL NOT NULL,total REAL NOT NULL,paid REAL NOT NULL DEFAULT 0,notes TEXT,FOREIGN KEY(customer_id) REFERENCES customers(id));
CREATE TABLE IF NOT EXISTS invoice_items(id INTEGER PRIMARY KEY,invoice_id INTEGER NOT NULL,product_id INTEGER,description TEXT NOT NULL,qty REAL NOT NULL,rate REAL NOT NULL,tax_rate REAL NOT NULL,line_total REAL NOT NULL,FOREIGN KEY(invoice_id) REFERENCES invoices(id));
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,invoice_id INTEGER NOT NULL,created TEXT NOT NULL,amount REAL NOT NULL,method TEXT,FOREIGN KEY(invoice_id) REFERENCES invoices(id));
CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY,created TEXT NOT NULL,supplier TEXT,product_id INTEGER NOT NULL,qty REAL NOT NULL,unit_cost REAL NOT NULL,amount REAL NOT NULL,FOREIGN KEY(product_id) REFERENCES products(id));
CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY,created TEXT NOT NULL,description TEXT NOT NULL,amount REAL NOT NULL);
''')
con.execute("""CREATE TABLE IF NOT EXISTS business_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
)""")
con.execute("CREATE TABLE IF NOT EXISTS daily_rates(id INTEGER PRIMARY KEY,product_id INTEGER NOT NULL,changed TEXT NOT NULL,rate REAL NOT NULL,FOREIGN KEY(product_id) REFERENCES products(id))")
con.execute("""CREATE TABLE IF NOT EXISTS customer_payments (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    created TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    method TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(customer_id) REFERENCES customers(id)
)""")
con.execute("""CREATE TABLE IF NOT EXISTS deleted_invoices (
    invoice_id INTEGER PRIMARY KEY,
    invoice_number TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    pdf_original TEXT NOT NULL DEFAULT '',
    pdf_trashed TEXT NOT NULL DEFAULT ''
)""")
con.execute("""CREATE TABLE IF NOT EXISTS stock_adjustments (
    id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, created TEXT NOT NULL,
    old_stock REAL NOT NULL, new_stock REAL NOT NULL, difference REAL NOT NULL,
    reason TEXT NOT NULL, FOREIGN KEY(product_id) REFERENCES products(id)
)""")
# V35 reversible archive for packing bag purchase/payment history.
con.execute("""CREATE TABLE IF NOT EXISTS bag_history_archive (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, source_id INTEGER NOT NULL,
 deleted_at TEXT NOT NULL, payload TEXT NOT NULL, restored INTEGER NOT NULL DEFAULT 0
)""")
con.commit()
# V37: Preserve any pre-existing archived invoice when SQLite IDs were reused.
# Keep conflicting records in a separate audit table; never silently discard them.
con.execute("""CREATE TABLE IF NOT EXISTS archived_invoice_conflicts (
 id INTEGER PRIMARY KEY, original_invoice_id INTEGER NOT NULL,
 invoice_number TEXT NOT NULL, customer_name TEXT NOT NULL,
 deleted_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 payload TEXT NOT NULL, pdf_original TEXT NOT NULL, pdf_trashed TEXT NOT NULL,
 moved_at TEXT NOT NULL
)""")
con.commit()
# V14: retain existing records; add an active flag without changing invoice history.
_product_columns = {r[1] for r in con.execute('PRAGMA table_info(products)')}
if 'active' not in _product_columns:
    con.execute('ALTER TABLE products ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
# V33 CLEAN START: exactly 14 selectable coconut products, in fixed serial order.
# The original 11 categories include Mature Coconut; it is replaced by four
# distinct variants, making 14 sellable coconut products (11 - 1 + 4).
MATURE_TYPES = [
    ('Black Coconut','Kg'), ('Small Size Coconut','Kg'),
    ('Big Size Coconut','Kg'), ('Pollachi Coconut','Kg')
]
PRODUCT_CATALOG = [
    ('Fresh Coconut','Nos'),
    *MATURE_TYPES,
    ('Tender Coconut','Nos'), ('Coconut Oil','Litre'),
    ('Coconut Water','Litre'), ('Coconut Copra','Kg'),
    ('Desiccated Coconut','Kg'), ('Coconut Husk (Coir Fibre)','Kg'),
    ('Coir Pith (Coco Peat)','Kg'), ('Coconut Shell','Kg'),
    ('Coconut Charcoal','Kg')
]
for _name, _unit in PRODUCT_CATALOG:
    con.execute('INSERT OR IGNORE INTO products(name,unit,stock,cost,rate,hsn,tax,active) VALUES(?,?,0,0,0,"",0,1)', (_name,_unit))
# Packing bags have separate inventory and supplier accounts; excluded from 14 products.
con.execute("INSERT OR IGNORE INTO products(name,unit,stock,cost,rate,hsn,tax,active) VALUES('Packing Bag','Nos',0,0,0,'',0,1)")
# V15 supplier purchase ledger: existing purchases remain intact.
con.execute("""CREATE TABLE IF NOT EXISTS supplier_payments (
 id INTEGER PRIMARY KEY, supplier TEXT NOT NULL, created TEXT NOT NULL,
 amount REAL NOT NULL CHECK(amount>0), method TEXT NOT NULL DEFAULT 'Cash', reference TEXT NOT NULL DEFAULT ''
)""")
_purchase_columns={r[1] for r in con.execute('PRAGMA table_info(purchases)')}
if 'paid' not in _purchase_columns:
    con.execute('ALTER TABLE purchases ADD COLUMN paid REAL NOT NULL DEFAULT 0')
con.execute('''CREATE TABLE IF NOT EXISTS supplier_change_audit (
 id INTEGER PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL,
 source_id INTEGER NOT NULL, action TEXT NOT NULL, before_json TEXT NOT NULL,
 after_json TEXT NOT NULL DEFAULT '', backup_path TEXT NOT NULL DEFAULT ''
)''')
con.commit()
con.commit()
con.execute('''CREATE TABLE IF NOT EXISTS purchase_groups (
 id INTEGER PRIMARY KEY, supplier TEXT NOT NULL, created TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT ''
)''')
if 'group_id' not in {r[1] for r in con.execute('PRAGMA table_info(purchases)')}:
    con.execute('ALTER TABLE purchases ADD COLUMN group_id INTEGER REFERENCES purchase_groups(id)')
con.execute('CREATE INDEX IF NOT EXISTS idx_purchases_group ON purchases(group_id)')
con.commit()
con.execute("""CREATE TABLE IF NOT EXISTS invoice_sequence (
    id INTEGER PRIMARY KEY CHECK(id=1), last_number INTEGER NOT NULL
)""")
con.execute('INSERT OR IGNORE INTO invoice_sequence(id,last_number) VALUES(1,0)')
con.commit()
# V43: audit every actual stock balance change, including purchases, sales,
# corrections, invoice deletion/restoration and bag purchase deletion/restoration.
# Baseline is captured once when upgrading, so existing stock is carried forward.
con.execute("""CREATE TABLE IF NOT EXISTS stock_movement_log (
 id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL,
 changed TEXT NOT NULL, old_stock REAL NOT NULL, new_stock REAL NOT NULL,
 qty_in REAL NOT NULL, qty_out REAL NOT NULL,
 FOREIGN KEY(product_id) REFERENCES products(id))""")
con.execute("""CREATE TABLE IF NOT EXISTS stock_register_baseline (
 product_id INTEGER PRIMARY KEY, initial_qty REAL NOT NULL,
 started TEXT NOT NULL, FOREIGN KEY(product_id) REFERENCES products(id))""")
con.execute("""INSERT OR IGNORE INTO stock_register_baseline(product_id,initial_qty,started)
 SELECT id,stock,datetime('now','localtime') FROM products""")
con.execute("""CREATE TRIGGER IF NOT EXISTS v43_log_stock_changes
 AFTER UPDATE OF stock ON products
 WHEN ABS(NEW.stock-OLD.stock)>0.0000001
 BEGIN
 INSERT INTO stock_movement_log(product_id,changed,old_stock,new_stock,qty_in,qty_out)
 VALUES(NEW.id,strftime('%Y-%m-%dT%H:%M:%S','now','localtime'),OLD.stock,NEW.stock,
 CASE WHEN NEW.stock>OLD.stock THEN NEW.stock-OLD.stock ELSE 0 END,
 CASE WHEN NEW.stock<OLD.stock THEN OLD.stock-NEW.stock ELSE 0 END);
 END""")
con.commit()
# V44: Preserve the customer account position at bill creation for historical PDFs.
_invoice_cols={r[1] for r in con.execute('PRAGMA table_info(invoices)')}
for _column in ('opening_due','opening_advance'):
    if _column not in _invoice_cols:
        con.execute(f'ALTER TABLE invoices ADD COLUMN {_column} REAL NOT NULL DEFAULT 0')
con.commit()

con.execute("""CREATE TABLE IF NOT EXISTS customer_opening_balances(
 customer_id INTEGER PRIMARY KEY, amount REAL NOT NULL, updated TEXT NOT NULL)""")
con.execute("""CREATE TABLE IF NOT EXISTS customer_opening_audit(
 id INTEGER PRIMARY KEY,customer_id INTEGER,old_amount REAL,new_amount REAL,
 changed TEXT,backup_path TEXT)""")
con.commit()
def opening_amount(cid):
    if not cid:return 0.
    r=con.execute('SELECT amount FROM customer_opening_balances WHERE customer_id=?',(cid,)).fetchone()
    return float(r[0]) if r else 0.
def customer_account_position(customer_id):
    if not customer_id:return (0.0,0.0)
    due=con.execute('SELECT COALESCE(SUM(total-paid),0) FROM invoices WHERE customer_id=?',(customer_id,)).fetchone()[0]
    deposits=con.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE customer_id=?',(customer_id,)).fetchone()[0]
    net=round(float(due)-float(deposits)+opening_amount(customer_id),2)
    return (max(0,net),max(0,-net))

DEFAULT_SETTINGS={'shop_name':'AS COCONUT TRADERS','phone':'9361866945 / 7418989798','address':'A-49, New Kamaraj Vegetable Market, Kallurani, Tamil Nadu 627808','email':'info@ascoconuttraders.in','website':'ascoconuttraders.in','gstin':'','logo_path':str(BASE_DIR/'AS_Coconut_Traders_Logo.png')}
def setting(key):
    r=con.execute('SELECT value FROM business_settings WHERE key=?',(key,)).fetchone()
    return r[0] if r else DEFAULT_SETTINGS.get(key,'')

# Populate missing/blank shop identity fields without overwriting user-customized settings.
for _key in ('address', 'email'):
    _existing = con.execute('SELECT value FROM business_settings WHERE key=?', (_key,)).fetchone()
    if _existing is None or not _existing[0].strip():
        con.execute('INSERT OR REPLACE INTO business_settings(key,value) VALUES(?,?)', (_key, DEFAULT_SETTINGS[_key]))
con.commit()

# Initialize once from all known historical invoice numbers, including recycle bin.
_old_numbers = [r[0] for r in con.execute('SELECT number FROM invoices')]
_old_numbers += [r[0] for r in con.execute('SELECT invoice_number FROM deleted_invoices')]
_max_sequence = max([int(n.rsplit('/',1)[-1]) for n in _old_numbers if n.rsplit('/',1)[-1].isdigit()] or [0])
con.execute('UPDATE invoice_sequence SET last_number=MAX(last_number,?) WHERE id=1',(_max_sequence,))
con.commit()

def money(v):return f'₹{float(v):,.2f}'
def num(s,nonnegative=True):
    v=float(s)
    if not (v==v and abs(v)!=float('inf')) or (nonnegative and v<0):raise ValueError('Enter a valid non-negative number')
    return v

def rows(q,args=()):return con.execute(q,args).fetchall()
def combo_id(s):return int(s.split(' | ',1)[0]) if ' | ' in s else None

def refresh_combo(cb,query,blank=False):
    current=cb.get(); opts=[f'{a} | {b}' for a,b in rows(query)]; cb['values']=([''] if blank else [])+opts
    if current in cb['values']:cb.set(current)
    elif opts and not blank:cb.set(opts[0])
    else:cb.set('')

def entry(parent,label,row,col=0,width=22):
    ttk.Label(parent,text=label).grid(row=row,column=col*2,sticky='w',padx=5,pady=5)
    e=ttk.Entry(parent,width=width);e.grid(row=row,column=col*2+1,sticky='ew',padx=5,pady=5);return e

def table(parent,cols,widths=None):
    frame=ttk.Frame(parent);frame.pack(fill='both',expand=True,padx=8,pady=8)
    tree=ttk.Treeview(frame,columns=cols,show='headings',height=13)
    for i,c in enumerate(cols):tree.heading(c,text=c);tree.column(c,width=(widths[i] if widths else 120),anchor='w')
    sb=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=sb.set)
    tree.pack(side='left',fill='both',expand=True);sb.pack(side='right',fill='y');return tree

def fill(tree,data):
    tree.delete(*tree.get_children())
    for r in data:tree.insert('', 'end',values=r)

root=tk.Tk();root.title('AS COCONUT TRADERS  |  Premium Billing V81');root.geometry('1440x900');root.minsize(1020,650)
GREEN='#07563F';DARK='#052E25';GOLD='#D6AE52';BG='#F5F8F6';INK='#172E25'
root.configure(bg=BG)
style=ttk.Style();style.theme_use('clam')
style.configure('.',font=('Segoe UI',10),background=BG,foreground=INK)
style.configure('TFrame',background=BG)
style.configure('TLabel',background=BG,foreground=INK)
style.configure('TLabelframe',background=BG,bordercolor='#D9E5DC',padding=10)
style.configure('TLabelframe.Label',background=BG,foreground=GREEN,font=('Segoe UI',11,'bold'))
style.configure('TNotebook',background=BG,borderwidth=0)
style.configure('TNotebook.Tab',padding=(18,12),font=('Segoe UI',10,'bold'),background='#E3EBE5',foreground=DARK)
style.map('TNotebook.Tab',background=[('selected','#FFFFFF')],foreground=[('selected',GREEN)])
style.configure('Treeview',rowheight=34,font=('Segoe UI',10),background='#FFFFFF',fieldbackground='#FFFFFF',foreground=INK,borderwidth=0)
style.configure('Treeview.Heading',font=('Segoe UI',10,'bold'),background='#DDEBE2',foreground=DARK,padding=8)
style.map('Treeview',background=[('selected','#CDE7D7')],foreground=[('selected',DARK)])
style.configure('TButton',font=('Segoe UI',10,'bold'),padding=(12,8),background=GREEN,foreground='white',borderwidth=0)
style.configure('Accent.TButton',font=('Segoe UI',10,'bold'),padding=(12,9),background=GOLD,foreground=DARK,borderwidth=0)
style.map('Accent.TButton',background=[('active','#F0CE7C')])
style.map('TButton',background=[('active','#177450')],foreground=[('active','white')])
style.configure('TEntry',padding=6)
style.configure('TCombobox',padding=5)
header=tk.Frame(root,bg=DARK,height=118)
header.pack(fill='x');header.pack_propagate(False)
# V69: Scale the complete original banner to the available header width.
# The 1920x150 source must never be drawn unscaled (it clips on laptop screens).
_banner_path=BASE_DIR/'Coconut_Banner.png'
_banner_canvas=tk.Canvas(header,bg=DARK,height=118,highlightthickness=0)
_banner_canvas.pack(fill='both',expand=True)
_banner_source=None
_banner_render=None
_banner_last_size=None
try:
    from PIL import Image as PILImage, ImageTk
    if _banner_path.is_file():
        _banner_source=PILImage.open(_banner_path).convert('RGB')
except (ImportError, OSError):
    _banner_source=None

def draw_brand_banner(event=None):
    global _banner_render, _banner_last_size
    width=max(1,_banner_canvas.winfo_width())
    height=max(1,_banner_canvas.winfo_height())
    if (width,height)==_banner_last_size:
        return
    _banner_last_size=(width,height)
    _banner_canvas.delete('all')
    _banner_canvas.create_rectangle(0,0,width,height,fill=DARK,outline='')
    if _banner_source is not None:
        # Fit entire banner inside the header, keeping logo and contact line visible.
        source_w,source_h=_banner_source.size
        scale=min(width/source_w,height/source_h)
        target=(max(1,int(source_w*scale)),max(1,int(source_h*scale)))
        resized=_banner_source.resize(target,PILImage.Resampling.LANCZOS)
        _banner_render=ImageTk.PhotoImage(resized,master=root)
        _banner_canvas.create_image((width-target[0])//2,(height-target[1])//2,
                                    image=_banner_render,anchor='nw')
    else:
        _banner_canvas.create_text(20,18,text='AS COCONUT TRADERS',anchor='nw',
                                   fill='white',font=('Segoe UI',24,'bold'))
        _banner_canvas.create_text(20,77,
            text='9361866945  •  7418989798  |  ascoconuttraders.in',
            anchor='nw',fill=GOLD,font=('Segoe UI',11,'bold'))
_banner_canvas.bind('<Configure>',draw_brand_banner)
style.layout('NoTabs.TNotebook.Tab', [])
nav=tk.Frame(root,bg=BG)
nav.pack(fill='x',padx=10,pady=(5,0))
nb=ttk.Notebook(root,style='NoTabs.TNotebook');nb.pack(fill='both',expand=True,padx=10,pady=(3,6))
tabs={}
tab_pages={}
tab_canvases={}
def add_scrollable_page(name):
    page=ttk.Frame(nb)
    nb.add(page,text=name)
    canvas=tk.Canvas(page,bg=BG,highlightthickness=0,borderwidth=0)
    scroll=ttk.Scrollbar(page,orient='vertical',command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y')
    canvas.pack(side='left',fill='both',expand=True)
    content=ttk.Frame(canvas)
    window=canvas.create_window((0,0),window=content,anchor='nw')
    def update_region(event=None):
        canvas.configure(scrollregion=canvas.bbox('all'))
    def resize_content(event):
        canvas.itemconfigure(window,width=event.width)
    content.bind('<Configure>',update_region)
    canvas.bind('<Configure>',resize_content)
    tabs[name]=content
    tab_pages[name]=page
    tab_canvases[name]=canvas
    return content

for name in ('Dashboard','Daily & Customer Sales','Customer Ledger','New Bill','Customers','Products & Stock','Daily Stock Register','Purchases','Packing Bags','Payments & History','Reports & Backup','Recycle Bin','Shop Settings'):
    add_scrollable_page(name)

def scroll_current_page(event):
    if isinstance(getattr(event,'widget',None),(ttk.Treeview,ttk.Combobox,ttk.Scrollbar,tk.Listbox)):return
    # Mouse wheel must not navigate pages or scroll a hidden tab.
    widget=getattr(event,'widget',None)
    if widget is not None:
        try:
            if isinstance(widget,tk.Text):return
        except Exception:pass
    current=nb.select()
    for name,page in tab_pages.items():
        if str(page)==current:
            canvas=tab_canvases[name]
            if canvas.bbox('all') and canvas.bbox('all')[3]>canvas.winfo_height():
                canvas.yview_scroll(-1 if event.delta>0 else 1,'units')
            return 'break'
root.bind_all('<MouseWheel>',scroll_current_page,add='+')
root.bind_all('<Button-4>',lambda e: scroll_current_page(type('ScrollEvent',(),{'delta':120,'widget':e.widget})()),add='+')
root.bind_all('<Button-5>',lambda e: scroll_current_page(type('ScrollEvent',(),{'delta':-120,'widget':e.widget})()),add='+')
nav_buttons={}
for index,name in enumerate(tabs):
    r=index//5
    c=index%5
    nav.grid_columnconfigure(c,weight=1)
    b=tk.Button(nav,text=name,command=lambda n=name:nb.select(tab_pages[n]),
              font=('Segoe UI',9,'bold'),bg='#E8EFEA',fg=DARK,
              activebackground='#CDE7D7',relief='groove',bd=1,
              padx=5,pady=6,wraplength=175)
    b.grid(row=r,column=c,sticky='nsew',padx=2,pady=2)
    nav_buttons[name]=b


# Read-only live dashboard; never modifies the existing billing database.
dashboard=tabs['Dashboard']
ttk.Label(dashboard,text='Business Overview',font=('Segoe UI',20,'bold'),foreground=GREEN).pack(anchor='w',padx=18,pady=(18,3))
ttk.Label(dashboard,text='Sales, outstanding customer balances and available stock at a glance').pack(anchor='w',padx=18,pady=(0,15))
cards=tk.Frame(dashboard,bg=BG);cards.pack(fill='x',padx=16,pady=8)
metric_labels={}
for idx,(key,title) in enumerate([('sales','TOTAL SALES'),('received','PAYMENTS RECEIVED'),('due','OUTSTANDING BALANCE'),('extra','EXTRA AMOUNT PAID')]):
    card=tk.Frame(cards,bg='white',highlightbackground='#DFE9E2',highlightthickness=1,padx=16,pady=17)
    card.grid(row=0,column=idx,sticky='nsew',padx=5)
    cards.grid_columnconfigure(idx,weight=1)
    tk.Label(card,text=title,bg='white',fg='#62766B',font=('Segoe UI',9,'bold')).pack(anchor='w')
    v=tk.Label(card,text='—',bg='white',fg=GREEN,font=('Segoe UI',21,'bold'))
    v.pack(anchor='w',pady=(9,0));metric_labels[key]=v
stock_frame=ttk.LabelFrame(dashboard,text='Product-wise Available Stock (15 Items Including Packing Bag)',padding=8)
stock_frame.pack(fill='x',padx=20,pady=5)
stock_labels={}
for ix,(pname,unit) in enumerate(list(PRODUCT_CATALOG)+[('Packing Bag','Nos')]):
    cell=ttk.Frame(stock_frame,padding=5);cell.grid(row=ix//4,column=ix%4,sticky='ew',padx=4,pady=3)
    stock_frame.columnconfigure(ix%4,weight=1)
    ttk.Label(cell,text=pname,font=('Segoe UI',9,'bold')).pack(anchor='w')
    value=ttk.Label(cell,text='0 '+unit,font=('Segoe UI',13,'bold'),foreground=GREEN)
    value.pack(anchor='w');stock_labels[pname]=value
# V41: Customer advances must never be combined into a spendable balance.
# Display the available credit for each customer independently.
advance_frame=ttk.LabelFrame(dashboard,text='Customer-wise Available Advance (separate for every customer)',padding=8)
advance_frame.pack(fill='x',padx=20,pady=8)
advance_tree=ttk.Treeview(advance_frame,columns=('Customer','Phone','Available Advance'),show='headings',height=5)
for col,width in [('Customer',290),('Phone',190),('Available Advance',220)]:
    advance_tree.heading(col,text=col)
    advance_tree.column(col,width=width,anchor='e' if col=='Available Advance' else 'w')
advance_tree.pack(side='left',fill='x',expand=True)
advance_scroll=ttk.Scrollbar(advance_frame,orient='vertical',command=advance_tree.yview)
advance_scroll.pack(side='right',fill='y')
advance_tree.configure(yscrollcommand=advance_scroll.set)
pending_frame=ttk.LabelFrame(dashboard,text='Customer-wise Pending Amount',padding=8)
pending_frame.pack(fill='x',padx=20,pady=5)
pending_tree=ttk.Treeview(pending_frame,columns=('Customer','Phone','Pending Amount'),show='headings',height=4)
for _c,_w in [('Customer',270),('Phone',160),('Pending Amount',180)]:
    pending_tree.heading(_c,text=_c);pending_tree.column(_c,width=_w,anchor='e' if _c=='Pending Amount' else 'w')
pending_tree.pack(fill='x',expand=True)
recent_frame=ttk.LabelFrame(dashboard,text='Recent Invoices' ,padding=12);recent_frame.pack(fill='both',expand=True,padx=20,pady=16)
recent_tree=ttk.Treeview(recent_frame,columns=('Invoice','Date','Customer','Total','Paid','Balance'),show='headings',height=9)
for c in ('Invoice','Date','Customer','Total','Paid','Balance'):
    recent_tree.heading(c,text=c);recent_tree.column(c,width=155,anchor='w')
recent_tree.pack(fill='both',expand=True)
ttk.Button(recent_frame,text='Move Selected Invoice to Recycle Bin',command=lambda:delete_dashboard_invoice()).pack(anchor='e',pady=5)
def refresh_dashboard():
    sales,received=con.execute('SELECT COALESCE(SUM(total),0),COALESCE(SUM(paid),0) FROM invoices').fetchone()
    extra=con.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments').fetchone()[0]
    received+=extra
    # Calculate outstanding and credit PER CUSTOMER before aggregating summaries.
    # An advance from Customer A cannot cancel Customer B's unpaid invoices.
    customer_balances=rows('''SELECT c.name,COALESCE(c.phone,''),
        COALESCE((SELECT SUM(i.total-i.paid) FROM invoices i WHERE i.customer_id=c.id),0)
        - COALESCE((SELECT SUM(cp.amount) FROM customer_payments cp WHERE cp.customer_id=c.id),0)
        + COALESCE((SELECT amount FROM customer_opening_balances WHERE customer_id=c.id),0) AS balance
        FROM customers c ORDER BY c.name COLLATE NOCASE''')
    due_total=sum(max(0,float(balance)) for _,_,balance in customer_balances)
    advance_total=sum(max(0,-float(balance)) for _,_,balance in customer_balances)
    # Walk-in invoices cannot be assigned another customer's advance.
    walkin_due=con.execute('SELECT COALESCE(SUM(total-paid),0) FROM invoices WHERE customer_id IS NULL').fetchone()[0]
    due_total+=max(0,float(walkin_due))
    for k,val in [('sales',money(sales)),('received',money(received)),('due',money(due_total)),('extra',money(advance_total))]:metric_labels[k].configure(text=val)
    pending_tree.delete(*pending_tree.get_children())
    advance_tree.delete(*advance_tree.get_children())
    for name,phone,balance in customer_balances:
        credit=round(max(0,-float(balance)),2)
        if balance>0.001:pending_tree.insert('','end',values=(name,phone,money(balance)))
        if credit>0.001:
            advance_tree.insert('','end',values=(name,phone,money(credit)))
    for name,unit,quantity in rows('SELECT name,unit,stock FROM products'):
        if name in stock_labels:stock_labels[name].configure(text=f'{quantity:,.2f} {unit}')
    recent_tree.delete(*recent_tree.get_children())
    for number,created,name,total,paid in rows('SELECT i.number,i.created,COALESCE(c.name,"Walk-in Customer"),i.total,i.paid FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id ORDER BY i.id DESC LIMIT 20'):
        recent_tree.insert('', 'end',values=(number,created[:10],name,money(total),money(paid),money(total-paid)))
# Detailed daily and customer sales report. Dates use the saved invoice timestamp.
report_tab=tabs['Daily & Customer Sales']
filters=ttk.LabelFrame(report_tab,text='Filter invoices by date and customer',padding=8)
filters.pack(fill='x',padx=8,pady=8)
ttk.Label(filters,text='From (YYYY-MM-DD)').grid(row=0,column=0,padx=4)
from_date=ttk.Entry(filters,width=14);from_date.grid(row=0,column=1,padx=4)
ttk.Label(filters,text='To (YYYY-MM-DD)').grid(row=0,column=2,padx=4)
to_date=ttk.Entry(filters,width=14);to_date.grid(row=0,column=3,padx=4)
ttk.Label(filters,text='Customer').grid(row=0,column=4,padx=4)
sales_customer=ttk.Combobox(filters,state='readonly',width=27);sales_customer.grid(row=0,column=5,padx=4)
report_totals=ttk.Label(report_tab,text='');report_totals.pack(anchor='w',padx=16,pady=5)
report_book=ttk.Notebook(report_tab);report_book.pack(fill='both',expand=True,padx=8,pady=5)
daily_page=ttk.Frame(report_book);detail_page=ttk.Frame(report_book);report_book.add(daily_page,text='Day-wise Totals');report_book.add(detail_page,text='Customer / Invoice-wise Details')
daily_tree=table(daily_page,('Date','Bills','Sales','Received','Balance'))
detail_tree=table(detail_page,('Invoice ID','Date & Time','Invoice No','Customer','Phone','Total','Paid','Due'))
def refresh_sales_report():
    customer=sales_customer.get();cid=combo_id(customer)
    where=[];params=[]
    for val,op in [(from_date.get().strip(),'>='),(to_date.get().strip(),'<')]:
        if val:
            try: datetime.strptime(val,'%Y-%m-%d')
            except ValueError:messagebox.showerror('Invalid date','Use YYYY-MM-DD');return
            where.append('substr(i.created,1,10) '+op+' ?')
            if op=='<':
                from datetime import timedelta
                val=(datetime.strptime(val,'%Y-%m-%d')+timedelta(days=1)).strftime('%Y-%m-%d')
            params.append(val)
    if from_date.get().strip() and to_date.get().strip() and from_date.get().strip()>to_date.get().strip():
        messagebox.showerror('Invalid range','From date must not be after To date');return
    if cid is not None:where.append('i.customer_id=?');params.append(cid)
    elif customer=='Walk-in':where.append('i.customer_id IS NULL')
    clause=(' WHERE '+' AND '.join(where)) if where else ''
    base=' FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id'+clause
    detail=rows('SELECT i.id,i.created,i.number,COALESCE(c.name,"Walk-in Customer"),COALESCE(c.phone,""),i.total,i.paid,i.total-i.paid'+base+' ORDER BY i.created DESC,i.id DESC',tuple(params))
    fill(detail_tree,[(a,b.replace('T',' '),n,c,ph,money(t),money(p),money(d)) for a,b,n,c,ph,t,p,d in detail])
    daily=rows('SELECT substr(i.created,1,10),COUNT(*),SUM(i.total),SUM(i.paid),SUM(i.total-i.paid)'+base+' GROUP BY substr(i.created,1,10) ORDER BY substr(i.created,1,10) DESC',tuple(params))
    fill(daily_tree,[(d,n,money(t),money(p),money(b)) for d,n,t,p,b in daily])
    report_totals.config(text=f'{len(detail)} bills   |   Sales: {money(sum(x[5] for x in detail))}   |   Received: {money(sum(x[6] for x in detail))}   |   Balance: {money(sum(x[7] for x in detail))}')
def refresh_sales_customers():
    old=sales_customer.get();opts=['All Customers','Walk-in']+[f'{a} | {b}' for a,b in rows('SELECT id,name FROM customers ORDER BY name')]
    sales_customer['values']=opts;sales_customer.set(old if old in opts else opts[0])
def report_invoice_id():
    sel=detail_tree.selection()
    if not sel:messagebox.showinfo('Select invoice','Select an invoice from Customer / Invoice-wise Details');return None
    return int(detail_tree.item(sel[0])['values'][0])
def report_open_pdf():
    iid=report_invoice_id()
    if iid:
        try:open_pdf(existing_or_rebuilt_pdf(iid))
        except Exception as e:messagebox.showerror('PDF error',str(e))
def report_share():
    iid=report_invoice_id()
    if iid:share_invoice_whatsapp(iid)
ttk.Button(filters,text='Apply Filter',command=refresh_sales_report).grid(row=0,column=6,padx=8)
ttk.Button(filters,text='Clear',command=lambda:(from_date.delete(0,'end'),to_date.delete(0,'end'),sales_customer.set('All Customers'),refresh_sales_report())).grid(row=0,column=7)
actions=ttk.Frame(report_tab);actions.pack(fill='x',padx=8,pady=4)
ttk.Button(actions,text='Open Selected PDF',command=report_open_pdf).pack(side='left',padx=5)
ttk.Button(actions,text='Share Colour Image via WhatsApp',command=report_share).pack(side='left',padx=5)
nb.bind('<<NotebookTabChanged>>',lambda event: (refresh_dashboard() if nb.tab(nb.select(),'text')=='Dashboard' else (refresh_sales_customers(),refresh_sales_report()) if nb.tab(nb.select(),'text')=='Daily & Customer Sales' else None))

# Customer account ledger: payments are customer-level, never tied to a particular invoice.
# This allows weekly/monthly settlement and preserves individual invoice history.
ledger_tab=tabs['Customer Ledger']
ledger_top=ttk.LabelFrame(ledger_tab,text='Regular customer account / weekly and monthly statement',padding=10)
ledger_top.pack(fill='x',padx=10,pady=8)
ttk.Label(ledger_top,text='Customer').grid(row=0,column=0,padx=4,pady=4)
ledger_customer=ttk.Combobox(ledger_top,state='readonly',width=32)
ledger_customer.grid(row=0,column=1,padx=4)
ttk.Label(ledger_top,text='Period').grid(row=0,column=2,padx=4)
ledger_period=ttk.Combobox(ledger_top,state='readonly',values=['This Week','This Month','All Time','Custom Dates'],width=16)
ledger_period.set('This Month');ledger_period.grid(row=0,column=3,padx=4)
ttk.Label(ledger_top,text='From YYYY-MM-DD').grid(row=1,column=0,padx=4)
ledger_from=ttk.Entry(ledger_top,width=16);ledger_from.grid(row=1,column=1,sticky='w',padx=4)
ttk.Label(ledger_top,text='To YYYY-MM-DD').grid(row=1,column=2,padx=4)
ledger_to=ttk.Entry(ledger_top,width=16);ledger_to.grid(row=1,column=3,sticky='w',padx=4)
ledger_summary=ttk.Label(ledger_tab,text='Select customer to view account',font=('Segoe UI',11,'bold'))
ledger_summary.pack(anchor='w',padx=15,pady=8)
ledger_tree=table(ledger_tab,('Date & Time','Type','Reference','Debit (Sales)','Credit (Payment)','Running Balance'))

def refresh_ledger_customers():
    opts=[f'{i} | {name}' for i,name in rows('SELECT id,name FROM customers ORDER BY name')]
    old=ledger_customer.get();ledger_customer['values']=opts
    if opts:ledger_customer.set(old if old in opts else opts[0])

def ledger_dates():
    from datetime import timedelta
    now=datetime.now().date();mode=ledger_period.get()
    if mode=='This Week':start=now-timedelta(days=now.weekday());end=now
    elif mode=='This Month':start=now.replace(day=1);end=now
    elif mode=='All Time':return '0001-01-01','9999-12-31'
    else:
        start=datetime.strptime(ledger_from.get().strip(),'%Y-%m-%d').date()
        end=datetime.strptime(ledger_to.get().strip(),'%Y-%m-%d').date()
        if start>end:raise ValueError('From date cannot be after To date')
    return start.isoformat(),end.isoformat()

def refresh_ledger():
    try:
        cid=combo_id(ledger_customer.get())
        if cid is None:return
        start,end=ledger_dates()
        # All invoice payments (at billing or later) are represented as separate credits.
        # The invoices.paid field is only a cached total; do not sum it as another credit.
        events=[]
        opening=opening_amount(cid)
        if opening:
            events.append(('0001-01-01T00:00:00','Manual Opening Balance','Manual opening net (old pending - old payment - advance)',max(0,opening),max(0,-opening),'O'))
        for created,number,total,iid in rows('SELECT created,number,total,id FROM invoices WHERE customer_id=?',(cid,)):
            events.append((created,'Invoice',number,float(total),0.,'I'+str(iid)))
        for created,amount,method,iid,pid in rows('SELECT p.created,p.amount,COALESCE(p.method,""),i.id,p.id FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE i.customer_id=?',(cid,)):
            events.append((created,'Payment',method+' / Invoice '+str(iid),0.,float(amount),'P'+str(pid)))
        for created,amount,method,ref,pid in rows('SELECT created,amount,method,COALESCE(reference,""),id FROM customer_payments WHERE customer_id=?',(cid,)):
            events.append((created,'Account Payment',method+(' / '+ref if ref else ''),0.,float(amount),'C'+str(pid)))
        events.sort(key=lambda x:(x[0],x[5]))
        opening=sum(e[3]-e[4] for e in events if e[0][:10]<start)
        current=opening;shown=[];sales=received=0.
        for dt,kind,ref,debit,credit,_ in events:
            if not start<=dt[:10]<=end:continue
            current+=debit-credit;sales+=debit;received+=credit
            shown.append((dt.replace('T',' '),kind,ref,money(debit) if debit else '',money(credit) if credit else '',money(current)))
        fill(ledger_tree,shown)
        ledger_summary.config(text=f'Opening: {money(opening)}   |   Purchases: {money(sales)}   |   Payments: {money(received)}   |   Closing Balance: {money(current)}')
    except (ValueError,TypeError) as ex:messagebox.showerror('Ledger date error',str(ex))

ttk.Button(ledger_top,text='View Statement',command=refresh_ledger).grid(row=0,column=4,padx=8)
ledger_pay=ttk.LabelFrame(ledger_tab,text='Receive payment against customer account',padding=10)
ledger_pay.pack(fill='x',padx=10,pady=8)
ttk.Label(ledger_pay,text='Amount ₹').grid(row=0,column=0,padx=5)
ledger_amount=ttk.Entry(ledger_pay,width=16);ledger_amount.grid(row=0,column=1,padx=5)
ttk.Label(ledger_pay,text='Mode').grid(row=0,column=2,padx=5)
ledger_method=ttk.Combobox(ledger_pay,state='readonly',values=['Cash','UPI','Bank Transfer','Card'],width=16)
ledger_method.set('UPI');ledger_method.grid(row=0,column=3,padx=5)
ttk.Label(ledger_pay,text='Reference (optional)').grid(row=0,column=4,padx=5)
ledger_reference=ttk.Entry(ledger_pay,width=20);ledger_reference.grid(row=0,column=5,padx=5)
def save_account_payment():
    try:
        cid=combo_id(ledger_customer.get());amount=num(ledger_amount.get())
        if cid is None or amount<=0:raise ValueError('Choose customer and enter a positive payment')
        due=customer_balance(cid)
        # Advance receipts are allowed: a negative customer balance represents available credit.
        if not messagebox.askyesno('Confirm payment',f'Record {money(amount)} from {ledger_customer.get()}?\nCurrent due: {money(due)}\nBalance after: {money(due-amount)}'):return
        with con:con.execute('INSERT INTO customer_payments(customer_id,created,amount,method,reference) VALUES(?,?,?,?,?)',(cid,datetime.now().isoformat(timespec='seconds'),amount,ledger_method.get(),ledger_reference.get().strip()))
        ledger_amount.delete(0,'end');ledger_reference.delete(0,'end')
        refresh_ledger();refresh_account_payment_history();refresh_dashboard();messagebox.showinfo('Saved','Payment recorded in customer account')
    except ValueError as ex:messagebox.showerror('Payment error',str(ex))
ttk.Button(ledger_pay,text='Save Customer Payment',command=save_account_payment).grid(row=0,column=6,padx=10)

# V40: Account payments are separate; invoice-linked advances are reversed
# with the invoice and restored with it. Standalone customer advances remain.
account_history_frame=ttk.LabelFrame(ledger_tab,text='Customer Account Payment History — select a payment to delete',padding=8)
account_history_frame.pack(fill='x',padx=10,pady=5)
account_history_tree=ttk.Treeview(account_history_frame,columns=('ID','Date','Amount','Method','Reference'),show='headings',height=5)
for col,width in [('ID',60),('Date',170),('Amount',130),('Method',120),('Reference',360)]:
    account_history_tree.heading(col,text=col)
    account_history_tree.column(col,width=width,anchor='w')
account_history_tree.pack(fill='x',expand=True)
def refresh_account_payment_history():
    account_history_tree.delete(*account_history_tree.get_children())
    cid=combo_id(ledger_customer.get())
    if cid is None:return
    for pid,created,amount,method,ref in rows('SELECT id,created,amount,method,reference FROM customer_payments WHERE customer_id=? ORDER BY id DESC',(cid,)):
        account_history_tree.insert('', 'end', iid=str(pid),values=(pid,created[:19].replace('T',' '),money(amount),method,ref))
def delete_selected_account_payment():
    selected=account_history_tree.selection()
    if not selected:return messagebox.showinfo('Select payment','Select a payment from Customer Account Payment History.')
    pid=int(selected[0])
    rec=con.execute('SELECT customer_id,amount,created,reference FROM customer_payments WHERE id=?',(pid,)).fetchone()
    if not rec:return messagebox.showerror('Not found','Payment already deleted.')
    cid,amount,created,ref=rec
    if cid!=combo_id(ledger_customer.get()):return messagebox.showerror('Customer changed','Refresh the history and select the payment again.')
    if not messagebox.askyesno('Confirm payment deletion',f'Delete this customer account payment?\n\nAmount: {money(amount)}\nDate: {created}\nReference: {ref}\n\nThis changes the customer balance and dashboard. It does NOT delete an invoice.\n\nBack up your database before deleting financial records.'):
        return
    with con:
        con.execute('DELETE FROM customer_payments WHERE id=? AND customer_id=?',(pid,cid))
    refresh_account_payment_history();refresh_ledger();refresh_dashboard()
    messagebox.showinfo('Payment deleted','Selected account payment removed. Customer balance and dashboard refreshed.')
ttk.Button(account_history_frame,text='DELETE SELECTED ACCOUNT PAYMENT',command=delete_selected_account_payment).pack(anchor='e',pady=5)
# V40: One-time cleanup of legacy orphan advances left by earlier bill deletions.
# This never selects normal standalone deposits or advances belonging to live invoices.
def reconcile_orphan_invoice_advances():
    candidates=rows("""SELECT cp.id,c.name,cp.amount,cp.reference,cp.created
       FROM customer_payments cp JOIN customers c ON c.id=cp.customer_id
       WHERE cp.reference LIKE 'Advance received with ASCT/%'
       AND NOT EXISTS (SELECT 1 FROM invoices i
                       WHERE i.number=substr(cp.reference,length('Advance received with ')+1)
                         AND i.customer_id=cp.customer_id)
       ORDER BY cp.id""")
    if not candidates:
        return messagebox.showinfo('Advance reconciliation','No orphan invoice-linked advances found. Standalone advances are unchanged.')
    total=sum(float(r[2]) for r in candidates)
    preview='\n'.join(f'ID {pid} | {name} | {money(amt)} | {ref}' for pid,name,amt,ref,created in candidates[:15])
    if len(candidates)>15:preview+=f'\n... and {len(candidates)-15} more'
    if not messagebox.askyesno('Review orphan advances',
        f'{len(candidates)} invoice-linked advance(s) have no matching active invoice.\n'
        f'Total: {money(total)}\n\n{preview}\n\n'
        'These could belong to deleted bills. Remove ONLY these orphan credits?\n'
        'A database backup will be created first. Standalone customer advances will NOT be deleted.'):
        return
    try:
        backup=DATA/('billing_before_advance_reconcile_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.db')
        # SQLite online backup is consistent even when the application has an open connection.
        dest=sqlite3.connect(backup)
        try:con.backup(dest)
        finally:dest.close()
        with con:
            con.executemany('DELETE FROM customer_payments WHERE id=?',[(r[0],) for r in candidates])
        refresh_all()
        messagebox.showinfo('Advance reconciliation complete',
            f'Removed {len(candidates)} orphan advance credit(s), total {money(total)}.\n\nBackup: {backup}')
    except Exception as ex:
        messagebox.showerror('Advance reconciliation failed',str(ex))

ttk.Button(account_history_frame,text='FIX OLD DELETED-BILL ADVANCES (REVIEW + BACKUP)',
           command=reconcile_orphan_invoice_advances).pack(anchor='e',pady=5)

ledger_customer.bind('<<ComboboxSelected>>',lambda event:refresh_account_payment_history(),add='+')

def export_ledger_csv():
    if not ledger_customer.get():return
    path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV files','*.csv')],initialfile='Customer_Statement.csv')
    if not path:return
    with open(path,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['Customer',ledger_customer.get()]);w.writerow(['Summary',ledger_summary.cget('text')]);w.writerow(['Date & Time','Type','Reference','Debit (Sales)','Credit (Payment)','Running Balance'])
        for item in ledger_tree.get_children():w.writerow(ledger_tree.item(item)['values'])
    messagebox.showinfo('Exported','Customer statement saved')
ttk.Button(ledger_pay,text='Export Statement CSV',command=export_ledger_csv).grid(row=0,column=7,padx=5)

def save_statement_pdf():
    try:
        cid=combo_id(ledger_customer.get())
        if cid is None:raise ValueError('Select a customer first')
        refresh_ledger()
        start,end=ledger_dates()
        name,phone=con.execute('SELECT name,COALESCE(phone,"") FROM customers WHERE id=?',(cid,)).fetchone()
        folder=DATA/'Customer_Statements'/f'{safe_folder(name)}_{cid}'
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'Statement_{start}_{end}.pdf'
        doc=SimpleDocTemplate(str(path),pagesize=(210*mm,297*mm),leftMargin=13*mm,rightMargin=13*mm,topMargin=15*mm,bottomMargin=15*mm)
        styles=getSampleStyleSheet()
        body=styles['Normal']; small=ParagraphStyle('statementSmall',parent=body,fontSize=8,leading=11)
        story=[Paragraph(html.escape(setting('shop_name')),styles['Heading1']),
               Paragraph('CUSTOMER ACCOUNT STATEMENT',styles['Heading2']),
               Paragraph(f'<b>Customer:</b> {html.escape(name)} &nbsp; <b>Phone:</b> {html.escape(phone)}',body),
               Paragraph(f'<b>Period:</b> {start} to {end}',body),
               Spacer(1,5*mm)]
        data=[['Date','Type / Reference','Debit (INR)','Credit (INR)','Balance (INR)']]
        for item in ledger_tree.get_children():
            dt,kind,ref,debit,credit,balance=ledger_tree.item(item)['values']
            data.append([str(dt)[:10],Paragraph(html.escape(str(kind)+' / '+str(ref)),small),str(debit).replace('₹',''),str(credit).replace('₹',''),str(balance).replace('₹','')])
        if len(data)==1:data.append(['','No transactions','','',''])
        tab=Table(data,colWidths=[24*mm,70*mm,28*mm,28*mm,34*mm],repeatRows=1)
        tab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#DCEDE2')),('GRID',(0,0),(-1,-1),0.3,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP'),('FONTSIZE',(0,0),(-1,-1),8),('ALIGN',(2,1),(-1,-1),'RIGHT'),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        story.extend([tab,Spacer(1,5*mm),Paragraph(html.escape(ledger_summary.cget('text')),small),Spacer(1,8*mm),Paragraph('Generated: '+datetime.now().strftime('%d-%m-%Y %I:%M %p'),small)])
        doc.build(story)
        if messagebox.askyesno('Statement saved',f'PDF saved:\n{path}\n\nOpen now?'):open_pdf(path)
    except Exception as ex:messagebox.showerror('Statement PDF error',str(ex))

def share_statement_whatsapp():
    cid=combo_id(ledger_customer.get())
    if cid is None:return messagebox.showinfo('Select customer','Select a customer first')
    name,phone=con.execute('SELECT name,COALESCE(phone,"") FROM customers WHERE id=?',(cid,)).fetchone()
    digits=re.sub(r'\D','',phone)
    if len(digits)==10:digits='91'+digits
    if not 11<=len(digits)<=15:return messagebox.showwarning('Mobile number','Enter a valid customer mobile number in Customers')
    refresh_ledger()
    start,end=ledger_dates()
    msg=f'AS COCONUT TRADERS\nCustomer: {name}\nAccount period: {start} to {end}\n{ledger_summary.cget("text")}\nThank you.'
    webbrowser.open(f'https://wa.me/{digits}?text={quote(msg)}')
    messagebox.showinfo('WhatsApp','WhatsApp Web opens with the statement summary. Review and click Send yourself. To send a PDF, first export it and attach the file manually.')

ttk.Button(ledger_pay,text='Statement PDF',command=save_statement_pdf).grid(row=1,column=0,columnspan=2,padx=5,pady=7,sticky='w')
ttk.Button(ledger_pay,text='WhatsApp Statement',command=share_statement_whatsapp).grid(row=1,column=2,columnspan=3,padx=5,pady=7,sticky='w')


# Customers
f=tabs['Customers'];form=ttk.LabelFrame(f,text='Customer Details — Add / Edit',padding=3);form.pack(fill='x',padx=8,pady=(3,2))
c_name=entry(form,'Customer name',0);c_phone=entry(form,'Phone',0,1);c_addr=entry(form,'Address',1);c_gstin=entry(form,'GSTIN (optional)',1,1)
# The customer table is the primary view: reserve visible space for saved customers.
customer_list_frame=ttk.LabelFrame(f,text='Saved Customers — select a row to edit or delete',padding=3)
customer_list_frame.pack(fill='both',expand=True,padx=8,pady=(2,6))
customer_tree=ttk.Treeview(customer_list_frame,columns=('ID','Name','Phone','Address','GSTIN'),show='headings',height=8)
for label,w in [('ID',65),('Name',260),('Phone',180),('Address',400),('GSTIN',180)]:
    customer_tree.heading(label,text=label)
    customer_tree.column(label,width=w,anchor='w',stretch=True)
customer_scroll=ttk.Scrollbar(customer_list_frame,orient='vertical',command=customer_tree.yview)
customer_tree.configure(yscrollcommand=customer_scroll.set)
customer_scroll.pack(side='right',fill='y')
customer_tree.pack(side='left',fill='both',expand=True)
def refresh_customers():fill(customer_tree,rows('SELECT id,name,phone,address,gstin FROM customers ORDER BY id DESC'))
def add_customer():
    if not c_name.get().strip():return messagebox.showerror('Missing','Customer name required')
    with con:con.execute('INSERT INTO customers(name,phone,address,gstin) VALUES(?,?,?,?)',(c_name.get().strip(),c_phone.get().strip(),c_addr.get().strip(),c_gstin.get().strip()))
    for e in (c_name,c_phone,c_addr,c_gstin):e.delete(0,'end')
    refresh_all()
ttk.Button(form,text='Save Customer',command=add_customer).grid(row=2,column=0,columnspan=4,pady=2)

# Customer management: editing preserves historical invoice references.
def selected_customer_id():
    selected=customer_tree.selection()
    return int(customer_tree.item(selected[0],'values')[0]) if selected else None

def load_customer_for_edit(_=None):
    cid=selected_customer_id()
    if cid is None:return
    r=con.execute('SELECT name,phone,address,gstin FROM customers WHERE id=?',(cid,)).fetchone()
    if r:
        for widget,value in zip((c_name,c_phone,c_addr,c_gstin),r):
            widget.delete(0,'end');widget.insert(0,value or '')

def update_customer():
    cid=selected_customer_id()
    if cid is None:return messagebox.showwarning('Select customer','Select a customer in the table first.')
    name=c_name.get().strip()
    if not name:return messagebox.showerror('Missing name','Customer name is required.')
    if not messagebox.askyesno('Update customer',f'Update customer #{cid} to {name}? Existing invoices will remain linked to this customer.'):return
    try:
        with con:con.execute('UPDATE customers SET name=?,phone=?,address=?,gstin=? WHERE id=?',(name,c_phone.get().strip(),c_addr.get().strip(),c_gstin.get().strip(),cid))
        refresh_all();messagebox.showinfo('Updated','Customer details updated.')
    except Exception as ex:messagebox.showerror('Update error',str(ex))

def delete_customer():
    cid=selected_customer_id()
    if cid is None:return messagebox.showwarning('Select customer','Select a customer first.')
    r=con.execute('SELECT name FROM customers WHERE id=?',(cid,)).fetchone()
    if not r:return
    linked=con.execute('SELECT COUNT(*) FROM invoices WHERE customer_id=?',(cid,)).fetchone()[0]
    payments=con.execute('SELECT COUNT(*) FROM customer_payments WHERE customer_id=?',(cid,)).fetchone()[0]
    # Do not destroy customers linked to recycled bills: their archived payloads may need restoration.
    archived=con.execute('SELECT COUNT(*) FROM deleted_invoices WHERE customer_name=?',(r[0],)).fetchone()[0]
    if linked or payments or archived:
        return messagebox.showwarning('Customer has history',f'Cannot delete {r[0]}. This customer has invoices, payments, or recycled bills.\n\nUse Edit Customer to correct the name instead. Historical accounting data is protected.')
    if not messagebox.askyesno('Delete customer',f'Delete {r[0]} permanently?'):return
    with con:con.execute('DELETE FROM customers WHERE id=?',(cid,))
    for widget in (c_name,c_phone,c_addr,c_gstin):widget.delete(0,'end')
    refresh_all()

customer_tree.bind('<<TreeviewSelect>>',load_customer_for_edit)
customer_actions=ttk.Frame(form)
customer_actions.grid(row=3,column=0,columnspan=4,sticky='w',pady=1)
ttk.Button(customer_actions,text='Update Selected Customer',command=update_customer).pack(side='left',padx=5)
ttk.Button(customer_actions,text='Delete Unused Customer',command=delete_customer).pack(side='left',padx=5)


# V57: simple opening account, signed amount is pending (+) or advance (-).
opening_frame=ttk.LabelFrame(f,text='Customer Opening Balance - Simple Entry',padding=7)
opening_frame.pack(fill='x',padx=8,pady=5)
ttk.Label(opening_frame,text='Enter remaining MANUAL pending OR unused advance after old payments. Do not enter old payments again.').pack(anchor='w')
opening_table=ttk.Treeview(opening_frame,columns=('ID','Customer','Phone','Opening Pending','Opening Advance','Net Preview'),show='headings',height=8)
for col,width in [('ID',55),('Customer',190),('Phone',125),('Opening Pending',145),('Opening Advance',145),('Net Preview',185)]:
    opening_table.heading(col,text=col);opening_table.column(col,width=width)
opening_table.pack(fill='x')
opening_values={}
active_opening_editor=[None]
def opening_preview(cid):
    pending,advance=opening_values[cid]
    net=round(customer_balance(cid)-opening_amount(cid)+pending-advance,2)
    return ('Pending '+money(net)) if net>0 else ('Advance '+money(-net)) if net<0 else 'Settled '+money(0)
def refresh_opening_table():
    opening_values.clear();opening_table.delete(*opening_table.get_children())
    for cid,cname,phone in con.execute('SELECT id,name,COALESCE(phone,"") FROM customers ORDER BY name COLLATE NOCASE'):
        old=round(opening_amount(cid),2)
        opening_values[cid]=[max(0,old),max(0,-old)]
        opening_table.insert('','end',iid=str(cid),values=(cid,cname,phone,f'{max(0,old):.2f}',f'{max(0,-old):.2f}',opening_preview(cid)))
def edit_opening(event):
    iid=opening_table.identify_row(event.y);col=opening_table.identify_column(event.x)
    if not iid or col not in ('#4','#5'):return
    bbox=opening_table.bbox(iid,col)
    if not bbox:return
    if active_opening_editor[0] is not None:
        try:active_opening_editor[0].destroy()
        except tk.TclError:pass
    cid=int(iid);idx=0 if col=='#4' else 1
    widget=tk.Entry(opening_table);active_opening_editor[0]=widget
    widget.insert(0,f'{opening_values[cid][idx]:.2f}')
    widget.place(x=bbox[0],y=bbox[1],width=bbox[2],height=bbox[3])
    widget.focus_set();widget.select_range(0,'end')
    closed=[False]
    def finish(commit):
        if closed[0]:return 'break'
        if commit:
            try:
                value=round(num(widget.get()),2)
                if value<0:raise ValueError('Negative amount')
            except Exception:
                messagebox.showerror('Invalid amount','Enter a valid non-negative amount.');widget.focus_set();return 'break'
            opening_values[cid][idx]=value
            if value>0:opening_values[cid][1-idx]=0.
            vals=list(opening_table.item(iid,'values'))
            vals[3]=f'{opening_values[cid][0]:.2f}';vals[4]=f'{opening_values[cid][1]:.2f}'
            vals[5]=opening_preview(cid);opening_table.item(iid,values=vals)
        closed[0]=True
        if active_opening_editor[0] is widget:active_opening_editor[0]=None
        widget.destroy();return 'break'
    widget.bind('<Return>',lambda e:finish(True))
    widget.bind('<KP_Enter>',lambda e:finish(True))
    widget.bind('<Escape>',lambda e:finish(False))
    widget.bind('<FocusOut>',lambda e:finish(True))
opening_table.bind('<Double-1>',edit_opening)
def save_opening_balances():
    if active_opening_editor[0] is not None:
        active_opening_editor[0].event_generate('<Return>')
        if active_opening_editor[0] is not None:return
    changes=[]
    for cid,(pending,advance) in opening_values.items():
        if pending>0 and advance>0:return messagebox.showerror('Invalid','Pending and advance cannot both be positive.')
        old=round(opening_amount(cid),2);new=round(pending-advance,2)
        if abs(new-old)>0.005:changes.append((cid,old,new,pending,advance))
    if not changes:return messagebox.showinfo('No changes','No opening balances changed.')
    if not messagebox.askyesno('Confirm opening balance',f'Update {len(changes)} customer opening balances?\nExisting bills and payments remain unchanged.\nFull backup will be created first.',icon='warning'):return
    try:
        backup_dir=DATA/'Backups';backup_dir.mkdir(parents=True,exist_ok=True)
        backup_path=backup_dir/('Before_Opening_Balances_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
        with sqlite3.connect(str(backup_path)) as backup_db:con.backup(backup_db)
        if not backup_path.is_file() or backup_path.stat().st_size==0:raise RuntimeError('Backup failed')
        now=datetime.now().isoformat(timespec='seconds')
        columns={row[1] for row in con.execute('PRAGMA table_info(customer_opening_balances)')}
        with con:
            for cid,old,new,pending,advance in changes:
                if {'old_pending','old_payment','old_advance'}<=columns:
                    con.execute('INSERT INTO customer_opening_balances(customer_id,amount,updated,old_pending,old_payment,old_advance) VALUES(?,?,?,?,?,?) ON CONFLICT(customer_id) DO UPDATE SET amount=excluded.amount,updated=excluded.updated,old_pending=excluded.old_pending,old_payment=excluded.old_payment,old_advance=excluded.old_advance',(cid,new,now,pending,0,advance))
                else:
                    con.execute('INSERT INTO customer_opening_balances(customer_id,amount,updated) VALUES(?,?,?) ON CONFLICT(customer_id) DO UPDATE SET amount=excluded.amount,updated=excluded.updated',(cid,new,now))
                con.execute('INSERT INTO customer_opening_audit(customer_id,old_amount,new_amount,changed,backup_path) VALUES(?,?,?,?,?)',(cid,old,new,now,str(backup_path)))
        refresh_all()
        messagebox.showinfo('Saved',f'{len(changes)} customer opening balances updated.\nBackup: {backup_path}')
    except Exception as exc:messagebox.showerror('Save failed',str(exc))
ttk.Button(opening_frame,text='Refresh',command=refresh_opening_table).pack(side='left',padx=5,pady=5)
ttk.Button(opening_frame,text='SAVE ALL OPENING BALANCES',command=save_opening_balances).pack(side='left',padx=5,pady=5)
ttk.Label(opening_frame,text='Double-click, type, Enter, then Save All').pack(side='left',padx=5)

# Products
f=tabs['Products & Stock'];form=ttk.LabelFrame(f,text='Add Product',padding=8);form.pack(fill='x',padx=8,pady=8)
ttk.Label(form,text='Product name').grid(row=0,column=0,padx=5,pady=4,sticky='w')
p_name=ttk.Combobox(form,state='readonly',values=[n for n,u in PRODUCT_CATALOG],width=29)
p_name.grid(row=0,column=1,padx=5,pady=4)
p_unit=entry(form,'Unit (Nos / Kg)',0,1);p_unit.insert(0,'Nos')
def catalog_unit(_=None):
    chosen=p_name.get()
    for name,unit in PRODUCT_CATALOG:
        if chosen==name:p_unit.delete(0,'end');p_unit.insert(0,unit);break
def select_catalog_product(_=None):
    catalog_unit()
    selected=p_name.get().strip()
    for item in product_tree.get_children():
        values=product_tree.item(item,'values')
        if values and values[1]==selected:
            product_tree.selection_set(item)
            product_tree.focus(item)
            product_tree.see(item)
            load_product_for_edit()
            return
    product_tree.selection_remove(product_tree.selection())
    refresh_product_action_state()
p_name.bind('<<ComboboxSelected>>',select_catalog_product)
p_stock=entry(form,'Opening stock',1);p_cost=entry(form,'Purchase cost / unit',1,1)
p_rate=entry(form,'Selling rate / unit',2);p_hsn=entry(form,'HSN (optional)',2,1);p_tax=entry(form,'GST % (verify)',3);p_tax.insert(0,'0')
# V64: Cost and selling price are independent fields. Make focus explicit and
# never auto-copy the purchase cost into the selling rate.
p_cost.configure(takefocus=True)
p_rate.configure(takefocus=True)
p_cost.bind('<Return>', lambda event: (p_rate.focus_set(), 'break')[1])
p_rate.bind('<Return>', lambda event: (p_hsn.focus_set(), 'break')[1])

# Daily price updates: changing a master rate never changes old invoice rates.
daily_box=ttk.LabelFrame(tabs['Products & Stock'],text='Update Today\'s Product Selling Rate / Unit',padding=8)
daily_box.pack(fill='x',padx=8,pady=6)
daily_product=ttk.Combobox(daily_box,state='readonly',width=33)
daily_product.grid(row=0,column=0,padx=5)
ttk.Label(daily_box,text='New rate ₹ / unit').grid(row=0,column=1,padx=5)
daily_price=ttk.Entry(daily_box,width=14);daily_price.grid(row=0,column=2,padx=5)
def update_daily_rate():
    try:
        pid=combo_id(daily_product.get());rate=num(daily_price.get())
        if not pid or rate<=0:raise ValueError('Select product and enter positive rate')
        with con:
            con.execute('UPDATE products SET rate=? WHERE id=?',(rate,pid))
            con.execute('INSERT INTO daily_rates(product_id,changed,rate) VALUES(?,?,?)',(pid,datetime.now().isoformat(timespec='seconds'),rate))
        refresh_all();messagebox.showinfo('Rate updated','New rate saved. Previous invoices remain unchanged.')
    except ValueError as ex:messagebox.showerror('Rate error',str(ex))
ttk.Button(daily_box,text='Save Today\'s Rate',command=update_daily_rate).grid(row=0,column=3,padx=8)


ttk.Label(f,text='PRODUCT LIST — Select a row to Edit, Adjust Stock, Delete or Deactivate',font=('Segoe UI',11,'bold')).pack(fill='x',padx=14,pady=(8,0))
product_tree=table(f,('S.No','Product','Unit','Stock','Cost','Selling rate','HSN','GST %','Status'))
product_display_id_map={}
def refresh_products():
    # Show parent and four variants in business order; database IDs are unchanged.
    # The serial number is visual only: actual database IDs are preserved for invoices.
    catalog_names=[name for name,unit in PRODUCT_CATALOG]
    db_rows=rows("SELECT id,name,unit,ROUND(stock,2),ROUND(cost,2),ROUND(rate,2),hsn,tax,CASE WHEN active=1 THEN 'Active' ELSE 'Inactive' END FROM products")
    by_name={str(r[1]).casefold():r for r in db_rows}
    display=[]
    product_display_id_map.clear()
    for serial,name in enumerate(catalog_names,1):
        record=by_name.get(name.casefold())
        if record is not None:
            product_display_id_map[serial]=int(record[0])
            display.append((serial,*record[1:]))
    fill(product_tree,display)
    if 'product_save_button' in globals():refresh_product_action_state()
def add_product():
    # Existing catalog entries are edited, never inserted twice.
    if selected_stock_product_id() is not None:
        return update_product()
    try:
        name=p_name.get().strip()
        if not name:raise ValueError('Product name required')
        existing=con.execute('SELECT id FROM products WHERE name=? COLLATE NOCASE',(name,)).fetchone()
        if existing:
            return messagebox.showinfo('Product already exists',
                f'{name} is already in the product list.\n\nSelect the product row and click Update Selected Product, or Adjust Stock to Entered Qty.\nDo not use Save Product for an existing product.')
        with con:con.execute('INSERT INTO products(name,unit,stock,cost,rate,hsn,tax) VALUES(?,?,?,?,?,?,?)',(name,p_unit.get().strip() or 'Nos',num(p_stock.get() or '0'),num(p_cost.get() or '0'),num(p_rate.get() or '0'),p_hsn.get().strip(),num(p_tax.get() or '0')))
        p_name.set('')
        for e in (p_stock,p_cost,p_rate,p_hsn):e.delete(0,'end')
        refresh_all()
    except (ValueError,sqlite3.IntegrityError) as ex:messagebox.showerror('Product error',str(ex))
product_save_button=ttk.Button(form,text='Save New Product',command=add_product)
product_save_button.grid(row=4,column=0,columnspan=4,pady=7)
def refresh_product_action_state():
    selected_id=selected_stock_product_id()
    if selected_id is not None:
        product_save_button.configure(text='Update Selected Product',command=update_product)
    else:
        product_save_button.configure(text='Save New Product',command=add_product)

# Product master editing and auditable stock corrections.
def selected_stock_product_id():
    selected=product_tree.selection()
    if not selected:return None
    try:return product_display_id_map.get(int(product_tree.item(selected[0],'values')[0]))
    except (ValueError,IndexError):return None

def load_product_for_edit(_=None):
    pid=selected_stock_product_id()
    refresh_product_action_state()
    if pid is None:return
    r=con.execute('SELECT name,unit,stock,cost,rate,hsn,tax FROM products WHERE id=?',(pid,)).fetchone()
    if r:
        for widget,value in zip((p_name,p_unit,p_stock,p_cost,p_rate,p_hsn,p_tax),r):
            if widget is p_name:widget.set(str(value if value is not None else ''))
            else:widget.delete(0,'end');widget.insert(0,str(value if value is not None else ''))

def update_product():
    pid=selected_stock_product_id()
    if pid is None:return messagebox.showwarning('Select product','Select a product first.')
    try:
        name=p_name.get().strip()
        if not name:raise ValueError('Product name is required')
        current=con.execute('SELECT name,stock FROM products WHERE id=?',(pid,)).fetchone()
        if not current:return messagebox.showerror('Product not found','Refresh the product list.')
        if name.casefold()!=str(current[0]).casefold():
            raise ValueError('Selected product and product name do not match. Select the correct product row first.')
        cost=num(p_cost.get() or '0');rate=num(p_rate.get() or '0');tax=num(p_tax.get() or '0')
        if cost<0 or rate<0:raise ValueError('Purchase cost and selling rate cannot be negative')
        # A price edit is deliberate: changing purchase cost never recalculates selling rate.
        previous=con.execute('SELECT cost,rate FROM products WHERE id=?',(pid,)).fetchone()
        if previous and abs(rate-float(previous[1] or 0))>0.00001:
            if not messagebox.askyesno('Confirm selling price change',
                f'{name}\nSelling rate: {money(previous[1])} -> {money(rate)}\n'
                f'Purchase cost: {money(previous[0])} -> {money(cost)}\n\nSave these independent prices?'):
                return
        new_stock=round(num(p_stock.get() or '0'),4)
        old_stock=float(current[1] or 0)
        difference=round(new_stock-old_stock,4)
        if tax>100:raise ValueError('GST % cannot exceed 100')
        if abs(difference)>0.000001:
            if not messagebox.askyesno('Confirm product stock update',
                f'{name}\nCurrent stock: {old_stock:g}\nEntered stock: {new_stock:g}\n'
                f'Change: {difference:+g}\n\n'
                'The entered quantity will REPLACE current stock, not add to it.\n'
                'A stock adjustment will be recorded. Continue?',icon='warning'):return
        now=datetime.now().isoformat(timespec='seconds')
        with con:
            con.execute('UPDATE products SET name=?,unit=?,stock=?,cost=?,rate=?,hsn=?,tax=? WHERE id=?',
                (name,p_unit.get().strip() or 'Nos',new_stock,cost,rate,p_hsn.get().strip(),tax,pid))
            if abs(difference)>0.000001:
                con.execute('INSERT INTO stock_adjustments(product_id,created,old_stock,new_stock,difference,reason) '
                    'VALUES(?,?,?,?,?,?)',(pid,now,old_stock,new_stock,difference,
                    'Product form stock update (absolute quantity)'))
        refresh_all()
        messagebox.showinfo('Updated',
            f'{name} saved.\nStock: {new_stock:g}\nCost: {money(cost)}\nSelling rate: {money(rate)}\n'
            'Any stock quantity change is recorded in Stock Adjustment History.')
    except (ValueError,sqlite3.Error) as ex:
        messagebox.showerror('Product update error',str(ex))

def adjust_stock():
    pid=selected_stock_product_id()
    if pid is None:return messagebox.showwarning('Select product','Select a product first.')
    try:
        new=num(p_stock.get());reason=stock_reason.get().strip()
        if not reason:raise ValueError('Enter a reason for stock correction')
        row=con.execute('SELECT name,stock FROM products WHERE id=?',(pid,)).fetchone()
        if not row:return
        old=float(row[1]);diff=round(new-old,4)
        if abs(diff)<0.000001:return messagebox.showinfo('No change','New stock is same as existing stock.')
        if not messagebox.askyesno('Confirm stock adjustment',f'{row[0]}\nOld stock: {old:g}\nNew stock: {new:g}\nDifference: {diff:+g}\nReason: {reason}\n\nSave this stock correction?'):return
        with con:
            con.execute('UPDATE products SET stock=? WHERE id=?',(new,pid))
            con.execute('INSERT INTO stock_adjustments(product_id,created,old_stock,new_stock,difference,reason) VALUES(?,?,?,?,?,?)',(pid,datetime.now().isoformat(timespec='seconds'),old,new,diff,reason))
        refresh_all();messagebox.showinfo('Saved','Stock corrected and recorded in adjustment history.')
    except ValueError as ex:messagebox.showerror('Stock error',str(ex))

def toggle_product_active():
    pid=selected_stock_product_id()
    if pid is None:return messagebox.showwarning('Select product','Select a product in the list first.')
    name,active=con.execute('SELECT name,active FROM products WHERE id=?',(pid,)).fetchone()
    new=0 if active else 1
    verb='Deactivate' if active else 'Activate'
    if not messagebox.askyesno(verb+' product',f'{verb} {name}?\nHistorical invoices will remain unchanged.'):return
    with con:con.execute('UPDATE products SET active=? WHERE id=?',(new,pid))
    refresh_all()
    messagebox.showinfo('Saved',f'{name} is now '+('Active' if new else 'Inactive'))

def delete_product():
    pid=selected_stock_product_id()
    if pid is None:return messagebox.showwarning('Select product','Select a product first.')
    r=con.execute('SELECT name,stock FROM products WHERE id=?',(pid,)).fetchone()
    if not r:return
    for table,col in [('invoice_items','product_id'),('purchases','product_id'),('daily_rates','product_id'),('stock_adjustments','product_id')]:
        if con.execute(f'SELECT 1 FROM {table} WHERE {col}=? LIMIT 1',(pid,)).fetchone():
            return messagebox.showwarning('Product has history','Cannot delete a product with sales, purchases, rate history or stock adjustments. Edit it instead.')
    if abs(float(r[1]))>0.000001:return messagebox.showwarning('Stock remaining','Stock must be zero before deleting an unused product.')
    if not messagebox.askyesno('Delete product',f'Permanently delete unused product {r[0]}?'):return
    with con:con.execute('DELETE FROM products WHERE id=?',(pid,))
    refresh_all()

product_tree.bind('<<TreeviewSelect>>',load_product_for_edit)
product_actions=ttk.Frame(form)
product_actions.grid(row=5,column=0,columnspan=8,sticky='w',pady=5)
ttk.Button(product_actions,text='Update Selected Product',command=update_product).pack(side='left',padx=5)
ttk.Button(product_actions,text='Delete Unused Product',command=delete_product).pack(side='left',padx=5)
ttk.Button(product_actions,text='Activate / Deactivate',command=toggle_product_active).pack(side='left',padx=5)
ttk.Label(product_actions,text='Stock adjustment reason:').pack(side='left',padx=(15,3))
stock_reason=ttk.Entry(product_actions,width=27);stock_reason.pack(side='left',padx=3)
ttk.Button(product_actions,text='Adjust Stock to Entered Qty',command=adjust_stock).pack(side='left',padx=5)
stock_history_frame=ttk.LabelFrame(f,text='Stock Adjustment History (Latest 100)',padding=6)
stock_history_frame.pack(side='bottom',fill='x',padx=8,pady=5)
stock_history_tree=ttk.Treeview(stock_history_frame,columns=('Date','Product','Old','New','Change','Reason'),show='headings',height=3)
for col,width in [('Date',160),('Product',170),('Old',80),('New',80),('Change',90),('Reason',300)]:
    stock_history_tree.heading(col,text=col);stock_history_tree.column(col,width=width)
stock_history_tree.pack(fill='x')
def refresh_stock_history():
    fill(stock_history_tree,rows('SELECT a.created,p.name,ROUND(a.old_stock,2),ROUND(a.new_stock,2),ROUND(a.difference,2),a.reason FROM stock_adjustments a JOIN products p ON p.id=a.product_id ORDER BY a.id DESC LIMIT 100'))

def clear_stock_adjustment_history():
    count=con.execute('SELECT COUNT(*) FROM stock_adjustments').fetchone()[0]
    if count==0:
        messagebox.showinfo('Stock history','There is no stock adjustment history to clear.')
        return
    confirmed=messagebox.askyesno('Clear stock adjustment history',
        f'Permanently delete all {count} stock adjustment history records?\n\n'
        'This action cannot be undone. Current product stock, sales, purchases, '
        'and customer balances will NOT change.\n\n'
        'Please back up your database before continuing.')
    if not confirmed:return
    try:
        with con:con.execute('DELETE FROM stock_adjustments')
        refresh_stock_history()
        messagebox.showinfo('History cleared',f'{count} stock adjustment records deleted. Current stock is unchanged.')
    except sqlite3.Error as exc:
        messagebox.showerror('Clear history failed',str(exc))

stock_history_controls=ttk.Frame(stock_history_frame)
stock_history_controls.pack(fill='x',pady=(6,0))
ttk.Button(stock_history_controls,text='CLEAR STOCK ADJUSTMENT HISTORY',command=clear_stock_adjustment_history).pack(side='right')


# V54: Audited bulk reset; old invoices, purchases, payments and balances are untouched.
con.execute("""CREATE TABLE IF NOT EXISTS bulk_product_resets (
 id INTEGER PRIMARY KEY, created TEXT NOT NULL, backup_path TEXT NOT NULL,
 product_count INTEGER NOT NULL, reason TEXT NOT NULL)""")
con.execute("""CREATE TABLE IF NOT EXISTS bulk_product_reset_items (
 id INTEGER PRIMARY KEY, reset_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
 product_name TEXT NOT NULL, old_stock REAL NOT NULL, old_cost REAL NOT NULL,
 old_rate REAL NOT NULL, new_stock REAL NOT NULL, new_cost REAL NOT NULL,
 new_rate REAL NOT NULL, FOREIGN KEY(reset_id) REFERENCES bulk_product_resets(id))""")
con.commit()

def reset_all_stock_and_price():
    product_rows=con.execute(
        'SELECT id,name,stock,cost,rate FROM products ORDER BY id').fetchall()
    if not product_rows:
        return messagebox.showinfo('Reset stock and price','No products found.')
    changed=[r for r in product_rows if any(abs(float(v or 0))>0.0000001 for v in r[2:])]
    if not changed:
        return messagebox.showinfo('Nothing to reset',
            'All product stock quantities, costs and selling rates are already zero.')
    if not messagebox.askyesno('RESET ALL STOCK & PRICE',
        f'This will set Stock, Purchase Cost and Selling Rate to ZERO for '
        f'{len(product_rows)} products ({len(changed)} with nonzero values).\\n\\n'
        'Historical invoices, purchases, customer balances and payments remain unchanged.\\n'
        'A stock adjustment and reset audit record will be saved.\\n\\n'
        'Continue to final confirmation?',icon='warning'):
        return
    typed=simpledialog.askstring('Final reset confirmation',
        'Type RESET ALL to confirm clearing ALL current stock and prices.\\n'
        'This action is not a normal Undo operation.',parent=root)
    if typed!='RESET ALL':
        return messagebox.showinfo('Cancelled','Reset cancelled. No values were changed.')
    backup_dir=DATA/'Backups'
    backup_path=None
    try:
        backup_dir.mkdir(parents=True,exist_ok=True)
        backup_path=backup_dir/('Before_All_Stock_Price_Reset_'+
            datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
        # SQLite online backup includes the complete current database.
        with sqlite3.connect(str(backup_path)) as backup_con:
            con.backup(backup_con)
        if not backup_path.is_file() or backup_path.stat().st_size==0:
            raise RuntimeError('Database backup was not created.')
        now=datetime.now().isoformat(timespec='seconds')
        with con:
            cursor=con.execute(
                'INSERT INTO bulk_product_resets(created,backup_path,product_count,reason) '
                'VALUES(?,?,?,?)',
                (now,str(backup_path),len(product_rows),'Manual RESET ALL STOCK & PRICE'))
            reset_id=cursor.lastrowid
            for pid,name,stock,cost,rate in product_rows:
                old_stock=float(stock or 0);old_cost=float(cost or 0);old_rate=float(rate or 0)
                con.execute(
                    'INSERT INTO bulk_product_reset_items('
                    'reset_id,product_id,product_name,old_stock,old_cost,old_rate,'
                    'new_stock,new_cost,new_rate) VALUES(?,?,?,?,?,?,?,?,?)',
                    (reset_id,pid,name,old_stock,old_cost,old_rate,0,0,0))
                if abs(old_stock)>0.0000001:
                    con.execute(
                        'INSERT INTO stock_adjustments('
                        'product_id,created,old_stock,new_stock,difference,reason) '
                        'VALUES(?,?,?,?,?,?)',
                        (pid,now,old_stock,0,-old_stock,
                         f'Bulk reset #{reset_id}: RESET ALL STOCK & PRICE'))
                con.execute('UPDATE products SET stock=0,cost=0,rate=0 WHERE id=?',(pid,))
        refresh_all()
        refresh_daily_stock_register()
        messagebox.showinfo('Reset completed',
            f'Stock, purchase cost and selling rate reset to 0 for '
            f'{len(product_rows)} products.\\n\\n'
            f'Existing invoices, purchases and customer payments were not deleted.\\n'
            f'Backup: {backup_path}\\n'
            f'Audit reset ID: {reset_id}')
    except Exception as exc:
        messagebox.showerror('Reset failed',
            f'Bulk reset did not complete: {exc}\\n\\n'
            f'Backup: {backup_path if backup_path else "Not created"}')

reset_all_frame=ttk.Frame(f)
reset_all_frame.pack(side='bottom',fill='x',padx=12,pady=(3,8))
ttk.Button(reset_all_frame,text='RESET ALL STOCK & PRICE',
    command=reset_all_stock_and_price).pack(side='left',padx=5)
ttk.Label(reset_all_frame,
    text='Sets all current stock, cost and selling rate to 0. Requires backup and typed confirmation.',
    foreground='#8B4513').pack(side='left',padx=10)

# Purchases
f=tabs['Purchases'];form=ttk.LabelFrame(f,text='Record Supplier Purchase / Stock Inward',padding=10);form.pack(fill='x',padx=8,pady=8)
supplier=entry(form,'Supplier name',0);purchase_product=ttk.Combobox(form,state='readonly',width=32);ttk.Label(form,text='Product').grid(row=0,column=2);purchase_product.grid(row=0,column=3,padx=5)
purchase_qty=entry(form,'Quantity',1);purchase_cost=entry(form,'Unit cost',1,1)
purchase_paid=entry(form,'Paid now (₹)',2)
purchase_method=ttk.Combobox(form,state='readonly',values=['Cash','UPI','Bank Transfer','Card','Credit'],width=18)
purchase_method.set('Cash');ttk.Label(form,text='Payment method').grid(row=2,column=2);purchase_method.grid(row=2,column=3,padx=5)
# V74: Grouped purchases have one supplier and one purchase header, with separate stock lines.
v74_frame=ttk.LabelFrame(f,text='Multi-Product Purchase / Grouped History',padding=8)
v74_frame.pack(fill='x',padx=8,pady=6)
v74_group_tree=ttk.Treeview(v74_frame,columns=('Purchase #','Date','Supplier','Items','Total','Initial Paid'),show='headings',height=4,selectmode='browse')
for _col,_width in [('Purchase #',90),('Date',155),('Supplier',170),('Items',75),('Total',145),('Initial Paid',145)]:
    v74_group_tree.heading(_col,text=_col);v74_group_tree.column(_col,width=_width)
v74_group_tree.pack(fill='x')

purchase_tree=table(f,('Date','Supplier','Product','Quantity','Unit cost','Amount','Paid','Balance'))
# Staging items is in memory; no stock or financial change until Save All.
v74_cart=[]
v74_cart_frame=ttk.Frame(v74_frame);v74_cart_frame.pack(fill='x',pady=5)
v74_cart_tree=ttk.Treeview(v74_cart_frame,columns=('Product','Qty','Unit cost','Total'),show='headings',height=3,selectmode='extended')
for _col,_w in [('Product',230),('Qty',100),('Unit cost',110),('Total',130)]:
    v74_cart_tree.heading(_col,text=_col);v74_cart_tree.column(_col,width=_w)
v74_cart_tree.pack(side='left',fill='x',expand=True)

def v74_refresh_cart():
    v74_cart_tree.delete(*v74_cart_tree.get_children())
    for index,(pid,name,qty,cost) in enumerate(v74_cart):
        v74_cart_tree.insert('', 'end',iid=str(index),values=(name,qty,cost,money(round(qty*cost,2))))

def v74_add_line():
    try:
        pid=combo_id(purchase_product.get());qty=num(purchase_qty.get());cost=num(purchase_cost.get())
        if not pid or qty<=0 or cost<0:raise ValueError('Select product, positive quantity and valid cost')
        name=con.execute('SELECT name FROM products WHERE id=?',(pid,)).fetchone()[0]
        v74_cart.append((pid,name,qty,cost));v74_refresh_cart()
        purchase_qty.delete(0,'end');purchase_cost.delete(0,'end')
    except (ValueError,TypeError,sqlite3.Error) as exc:messagebox.showerror('Add product',str(exc),parent=root)

def v74_remove_line():
    for idx in sorted((int(x) for x in v74_cart_tree.selection()),reverse=True):v74_cart.pop(idx)
    v74_refresh_cart()

def v74_save_group():
    try:
        name=supplier.get().strip()
        if not name or not v74_cart:raise ValueError('Enter supplier and add at least one product')
        paid=num(purchase_paid.get() or '0')
        total=round(sum(round(q*c,2) for _,_,q,c in v74_cart),2)
        if paid<0 or paid>total:raise ValueError('Initial payment must be between zero and purchase total')
        if not messagebox.askyesno('Confirm Purchase',f'Supplier: {name}\nProducts: {len(v74_cart)}\nTotal: {money(total)}\nPaid: {money(paid)}\nSave as ONE grouped purchase?',parent=root):return
        backup=v66_backup()
        timestamp=datetime.now().isoformat(timespec='seconds')
        with con:
            cur=con.execute('INSERT INTO purchase_groups(supplier,created,note) VALUES(?,?,?)',(name,timestamp,'V74 multi-product purchase'))
            group_id=cur.lastrowid
            # Initial payment is stored once on the first line; never repeat per item.
            for index,(pid,product_name,qty,cost) in enumerate(v74_cart):
                con.execute('INSERT INTO purchases(created,supplier,product_id,qty,unit_cost,amount,paid,group_id) VALUES(?,?,?,?,?,?,?,?)',
                    (timestamp,name,pid,qty,cost,round(qty*cost,2),paid if index==0 else 0,group_id))
                con.execute('UPDATE products SET stock=stock+?,cost=? WHERE id=?',(qty,cost,pid))
            v66_audit('purchase_group',group_id,'create',None,{'supplier':name,'items':v74_cart,'paid':paid},backup)
        v74_cart.clear();v74_refresh_cart();purchase_paid.delete(0,'end');refresh_all()
        messagebox.showinfo('Saved',f'Purchase #{group_id} saved with {len(con.execute("SELECT id FROM purchases WHERE group_id=?",(group_id,)).fetchall())} items. Backup saved.',parent=root)
    except (ValueError,TypeError,sqlite3.Error) as exc:messagebox.showerror('Save purchase',str(exc),parent=root)

def v74_refresh_groups():
    v74_group_tree.delete(*v74_group_tree.get_children())
    for gid,created,name,count,total,paid in con.execute('''SELECT g.id,g.created,g.supplier,COUNT(p.id),COALESCE(SUM(p.amount),0),COALESCE(SUM(p.paid),0)
        FROM purchase_groups g JOIN purchases p ON p.group_id=g.id
        GROUP BY g.id ORDER BY g.id DESC LIMIT 300'''):
        v74_group_tree.insert('', 'end',iid=str(gid),values=(gid,created,name,count,money(total),money(paid)))

def v74_view_group(event=None):
    selection=v74_group_tree.selection()
    if not selection:return
    gid=int(selection[0]);details=con.execute('''SELECT pr.name,p.qty,p.unit_cost,p.amount FROM purchases p JOIN products pr ON pr.id=p.product_id
        WHERE p.group_id=? ORDER BY p.id''',(gid,)).fetchall()
    lines=[f'{name}: {qty:g} x Rs {cost:g} = {money(amount)}' for name,qty,cost,amount in details]
    messagebox.showinfo('Purchase #'+str(gid),'\n'.join(lines),parent=root)

v74_actions=ttk.Frame(v74_frame);v74_actions.pack(fill='x',pady=5)
ttk.Button(v74_actions,text='ADD PRODUCT TO PURCHASE',command=v74_add_line).pack(side='left',padx=4)
ttk.Button(v74_actions,text='REMOVE SELECTED ITEM',command=v74_remove_line).pack(side='left',padx=4)
ttk.Button(v74_actions,text='SAVE ALL AS ONE PURCHASE',command=v74_save_group).pack(side='left',padx=4)
v74_group_tree.bind('<Double-1>',v74_view_group)

def supplier_purchase_allocations():
    """Read-only FIFO allocation of later supplier payments across purchase balances.

    Never rewrites initial purchase payments or supplier payment history. A payment
    beyond all open purchases is a supplier advance, available against future buys.
    """
    purchases=con.execute('SELECT id,supplier,amount,paid FROM purchases ORDER BY created,id').fetchall()
    later=dict(con.execute('SELECT supplier,COALESCE(SUM(amount),0) FROM supplier_payments GROUP BY supplier').fetchall())
    allocated={}
    for purchase_id,name,total,initial in purchases:
        due=max(0.0,round(float(total)-float(initial),2))
        remaining=max(0.0,float(later.get(name,0)))
        used=min(due,remaining)
        later[name]=round(remaining-used,2)
        allocated[purchase_id]=(round(float(initial)+used,2),round(due-used,2))
    return allocated

def refresh_purchases():
    v74_refresh_groups()
    allocations=supplier_purchase_allocations()
    purchase_tree.delete(*purchase_tree.get_children())
    records=con.execute('SELECT p.id,p.created,p.supplier,pr.name,p.qty,p.unit_cost,p.amount,p.paid FROM purchases p JOIN products pr ON pr.id=p.product_id ORDER BY p.id DESC LIMIT 500').fetchall()
    for purchase_id,created,name,product,qty,cost,total,initial in records:
        paid,balance=allocations.get(purchase_id,(float(initial),round(float(total)-float(initial),2)))
        purchase_tree.insert('', 'end',iid=str(purchase_id),values=(created,name,product,qty,cost,money(total),money(paid),money(balance)))
def add_purchase():
    try:
        pid=combo_id(purchase_product.get());qty=num(purchase_qty.get());cost=num(purchase_cost.get());paid=num(purchase_paid.get() or '0')
        if not pid or qty<=0:raise ValueError('Choose product and positive quantity')
        if paid>round(qty*cost,2):raise ValueError('Paid amount cannot exceed purchase total')
        if not supplier.get().strip():raise ValueError('Supplier name is required')
        with con:
            con.execute('INSERT INTO purchases(created,supplier,product_id,qty,unit_cost,amount,paid) VALUES(?,?,?,?,?,?,?)',(datetime.now().isoformat(timespec='seconds'),supplier.get().strip(),pid,qty,cost,round(qty*cost,2),paid))
            con.execute('UPDATE products SET stock=stock+?,cost=? WHERE id=?',(qty,cost,pid))
        refresh_all();messagebox.showinfo('Saved','Purchase saved; stock increased')
    except ValueError as ex:messagebox.showerror('Error',str(ex))
ttk.Button(form,text='Save Purchase / Add Stock',command=add_purchase).grid(row=3,column=0,columnspan=4,pady=8)

# Supplier-wise accounts and payments (separate from customer receivables).
supplier_frame=ttk.LabelFrame(f,text='Supplier Accounts / Outstanding Payments',padding=8)
supplier_frame.pack(side='bottom',fill='x',padx=8,pady=5)
supplier_tree=ttk.Treeview(supplier_frame,columns=('Supplier','Purchase Total','Payments','Outstanding'),show='headings',height=4)
for c in ('Supplier','Purchase Total','Payments','Outstanding'):
    supplier_tree.heading(c,text=c);supplier_tree.column(c,width=190)
supplier_tree.pack(fill='x')
supplier_controls=ttk.Frame(supplier_frame);supplier_controls.pack(fill='x',pady=5)
ttk.Label(supplier_controls,text='Supplier').pack(side='left')
supplier_choice=ttk.Combobox(supplier_controls,state='readonly',width=28);supplier_choice.pack(side='left',padx=5)
ttk.Label(supplier_controls,text='Payment ₹').pack(side='left')
supplier_payment_amount=ttk.Entry(supplier_controls,width=12);supplier_payment_amount.pack(side='left',padx=5)
ttk.Label(supplier_controls,text='Mode').pack(side='left')
supplier_payment_method=ttk.Combobox(supplier_controls,state='readonly',values=['Cash','UPI','Bank Transfer','Card'],width=15)
supplier_payment_method.set('Cash');supplier_payment_method.pack(side='left',padx=5)
supplier_filter_row=ttk.Frame(supplier_frame)
supplier_filter_row.pack(fill='x',before=supplier_tree,pady=(0,5))
ttk.Label(supplier_filter_row,text='Find supplier').pack(side='left',padx=(0,8))
supplier_search_var=tk.StringVar()
supplier_search_box=ttk.Entry(supplier_filter_row,textvariable=supplier_search_var,width=26)
supplier_search_box.pack(side='left',padx=3)
supplier_show_all=tk.BooleanVar(value=False)
ttk.Checkbutton(supplier_filter_row,text='Show settled accounts',variable=supplier_show_all,command=lambda:refresh_supplier_accounts()).pack(side='left',padx=10)
ttk.Label(supplier_filter_row,text='Double-click a purchase row to edit',foreground=GREEN).pack(side='right')
def refresh_supplier_accounts():
    suppliers=rows('SELECT supplier FROM purchases UNION SELECT supplier FROM supplier_payments ORDER BY supplier COLLATE NOCASE')
    supplier_choice['values']=[r[0] for r in suppliers if r[0] and r[0].strip()]
    supplier_tree.delete(*supplier_tree.get_children())
    query=supplier_search_var.get().strip().casefold()
    for (name,) in suppliers:
        if not name or not name.strip() or query not in name.casefold():continue
        total=float(con.execute('SELECT COALESCE(SUM(amount),0) FROM purchases WHERE supplier=?',(name,)).fetchone()[0])
        paid=float(con.execute('SELECT COALESCE(SUM(paid),0) FROM purchases WHERE supplier=?',(name,)).fetchone()[0])
        paid+=float(con.execute('SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier=?',(name,)).fetchone()[0])
        balance=round(total-paid,2)
        if not supplier_show_all.get() and abs(balance)<0.005:continue
        supplier_tree.insert('', 'end',values=(name,money(total),money(paid),money(balance)))
supplier_search_var.trace_add('write',lambda *_:refresh_supplier_accounts())
def select_supplier(_=None):
    selection=supplier_tree.selection()
    if selection:supplier_choice.set(supplier_tree.item(selection[0],'values')[0])
supplier_tree.bind('<<TreeviewSelect>>',select_supplier)
def save_supplier_payment():
    try:
        name=supplier_choice.get().strip();amount=num(supplier_payment_amount.get())
        if not name or amount<=0:raise ValueError('Select supplier and enter positive payment')
        total=con.execute('SELECT COALESCE(SUM(amount-paid),0) FROM purchases WHERE supplier=?',(name,)).fetchone()[0]
        prior=con.execute('SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier=?',(name,)).fetchone()[0]
        if amount>round(total-prior,2)+0.001:
            extra=round(amount-max(total-prior,0),2)
            if not messagebox.askyesno('Supplier advance',f'Payment exceeds pending.\nExtra Rs {extra:,.2f} will be saved as SUPPLIER ADVANCE.\nContinue?',parent=root):return
        with con:con.execute('INSERT INTO supplier_payments(supplier,created,amount,method) VALUES(?,?,?,?)',(name,datetime.now().isoformat(timespec='seconds'),amount,supplier_payment_method.get()))
        supplier_payment_amount.delete(0,'end');refresh_all();messagebox.showinfo('Saved','Supplier payment recorded; all linked balances refreshed')
    except (ValueError,sqlite3.Error) as ex:messagebox.showerror('Supplier payment',str(ex))
ttk.Button(supplier_controls,text='Record Supplier Payment',command=save_supplier_payment).pack(side='left',padx=8)


# V66 Supplier ledger: edits are transactional, backed up and audited.
# A separate management table preserves stable database IDs; display tables do not.
management=ttk.LabelFrame(f,text='V66 | EDIT / DELETE PURCHASES & SUPPLIER PAYMENTS',padding=7)
management.pack(side='bottom',fill='x',padx=8,pady=5)
management_tabs=ttk.Notebook(management)
management_tabs.pack(fill='x')
purchase_manage_tab=ttk.Frame(management_tabs)
payment_manage_tab=ttk.Frame(management_tabs)
management_tabs.add(purchase_manage_tab,text='Purchase History / Edit')
management_tabs.add(payment_manage_tab,text='Supplier Payment History / Edit')
purchase_manage_tree=ttk.Treeview(purchase_manage_tab,columns=('ID','Date','Supplier','Product','Qty','Cost','Total','Paid'),show='headings',height=5,selectmode='extended')
for col,w in [('ID',50),('Date',145),('Supplier',150),('Product',175),('Qty',80),('Cost',80),('Total',100),('Paid',100)]:
    purchase_manage_tree.heading(col,text=col);purchase_manage_tree.column(col,width=w)
purchase_manage_tree.pack(fill='x')
payment_manage_tree=ttk.Treeview(payment_manage_tab,columns=('ID','Date','Supplier','Amount','Method','Reference'),show='headings',height=5,selectmode='browse')
for col,w in [('ID',50),('Date',145),('Supplier',180),('Amount',110),('Method',100),('Reference',170)]:
    payment_manage_tree.heading(col,text=col);payment_manage_tree.column(col,width=w)
payment_manage_tree.pack(fill='x')

def v74_merge_selected():
    try:
        ids=sorted({int(x) for x in purchase_manage_tree.selection()})
        if len(ids)<2:raise ValueError('Ctrl+Click or Shift+Click at least two purchase rows')
        records=con.execute('SELECT id,created,supplier,group_id,amount,paid FROM purchases WHERE id IN ('+','.join('?'*len(ids))+')',ids).fetchall()
        if len(records)!=len(ids):raise ValueError('One or more purchase rows no longer exist')
        suppliers={r[2].strip().casefold() for r in records}
        if len(suppliers)!=1:raise ValueError('Only purchases from the SAME supplier can be merged')
        # Reject partial selection of an existing group; it would split a purchase unexpectedly.
        for gid in {r[3] for r in records if r[3] is not None}:
            all_ids={r[0] for r in con.execute('SELECT id FROM purchases WHERE group_id=?',(gid,))}
            if not all_ids.issubset(set(ids)):raise ValueError('Select ALL items belonging to grouped purchase #'+str(gid))
        name=records[0][2];total=sum(float(r[4]) for r in records);paid=sum(float(r[5]) for r in records)
        if not messagebox.askyesno('Merge Purchases',f'Merge {len(ids)} selected product rows for {name}?\nTotal: {money(total)}\nInitial paid: {money(paid)}\n\nStock and payments will NOT be added again.\nA backup and audit record will be created.',parent=root):return
        backup=v66_backup()
        with con:
            created=min(r[1] for r in records)
            gid=con.execute('INSERT INTO purchase_groups(supplier,created,note) VALUES(?,?,?)',(name,created,'V74 merged historical purchases')).lastrowid
            con.execute('UPDATE purchases SET group_id=? WHERE id IN ('+','.join('?'*len(ids))+')',(gid,*ids))
            v66_audit('purchase_group',gid,'merge',{'purchase_ids':ids}, {'supplier':name,'total':total,'initial_paid':paid},backup)
        refresh_all();v66_refresh_management()
        messagebox.showinfo('Merged',f'Purchase #{gid} created. No stock or payment amounts changed.',parent=root)
    except (ValueError,sqlite3.Error) as exc:messagebox.showerror('Merge Purchases',str(exc),parent=root)

ttk.Button(purchase_manage_tab,text='MERGE SELECTED PURCHASES (SAME SUPPLIER)',command=v74_merge_selected).pack(anchor='w',pady=6)

def v66_refresh_management():
    purchase_manage_tree.delete(*purchase_manage_tree.get_children())
    allocations=supplier_purchase_allocations()
    for record in con.execute('SELECT p.id,p.created,p.supplier,pr.name,p.qty,p.unit_cost,p.amount,p.paid FROM purchases p JOIN products pr ON pr.id=p.product_id ORDER BY p.id DESC LIMIT 300'):
        effective_paid=allocations.get(record[0],(float(record[7]),0))[0]
        purchase_manage_tree.insert('', 'end',iid=str(record[0]),values=(*record[:7],effective_paid))
    payment_manage_tree.delete(*payment_manage_tree.get_children())
    for record in con.execute('SELECT id,created,supplier,amount,method,reference FROM supplier_payments ORDER BY id DESC LIMIT 300'):
        payment_manage_tree.insert('', 'end',iid=str(record[0]),values=record)

def v66_backup():
    folder=DATA/'supplier_edit_backups';folder.mkdir(parents=True,exist_ok=True)
    path=folder/('supplier_before_edit_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
    target=sqlite3.connect(str(path))
    try:con.backup(target)
    finally:target.close()
    return str(path)

def v66_selected(tree):
    selected=tree.selection()
    if not selected:raise ValueError('Select a record from the history table first')
    return int(selected[0])

def v66_prompt_number(title,label,initial):
    val=simpledialog.askstring(title,label,initialvalue=str(initial),parent=root)
    if val is None:return None
    result=float(val)
    if not (0<=result<1e12):raise ValueError('Enter a valid finite non-negative amount')
    return round(result,4)

def v66_audit(kind,record_id,action,before,after,backup_path):
    con.execute('INSERT INTO supplier_change_audit(created,kind,source_id,action,before_json,after_json,backup_path) VALUES(?,?,?,?,?,?,?)',
        (datetime.now().isoformat(timespec='seconds'),kind,record_id,action,json.dumps(before),json.dumps(after),backup_path))

def v66_supplier_due(name,excluding_purchase=None,excluding_payment=None):
    q='SELECT COALESCE(SUM(amount-paid),0) FROM purchases WHERE supplier=?'
    args=[name]
    if excluding_purchase is not None:q+=' AND id<>?';args.append(excluding_purchase)
    due=float(con.execute(q,args).fetchone()[0])
    q='SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier=?';args=[name]
    if excluding_payment is not None:q+=' AND id<>?';args.append(excluding_payment)
    return round(due-float(con.execute(q,args).fetchone()[0]),2)

def v66_purchase_action(action):
    try:
        pid=v66_selected(purchase_manage_tree)
        before=con.execute('SELECT id,created,supplier,product_id,qty,unit_cost,amount,paid,group_id FROM purchases WHERE id=?',(pid,)).fetchone()
        if not before:raise ValueError('Purchase not found')
        product_id=before[3];old_qty=float(before[4]);old_paid=float(before[7]);name=before[2]
        if action=='edit':
            new_qty=v66_prompt_number('Edit purchase','Purchase quantity',old_qty)
            if new_qty is None:return
            if new_qty<=0:raise ValueError('Quantity must be greater than zero')
            new_cost=v66_prompt_number('Edit purchase','Unit purchase cost',before[5])
            if new_cost is None:return
            new_paid=v66_prompt_number('Edit purchase','Initially paid amount',old_paid)
            if new_paid is None:return
            new_name=simpledialog.askstring('Edit purchase','Supplier name',initialvalue=name,parent=root)
            if new_name is None:return
            new_name=new_name.strip()
            if not new_name:raise ValueError('Supplier name required')
            new_total=round(new_qty*new_cost,2)
            if new_paid>new_total+.001:raise ValueError('Paid amount exceeds purchase total')
            after=(pid,before[1],new_name,product_id,new_qty,new_cost,new_total,new_paid)
            if new_name==name:
                # Exclude the edited purchase, then validate the entire supplier account.
                if v66_supplier_due(name,excluding_purchase=pid)+new_total-new_paid < -.001:
                    raise ValueError('Edit would overpay supplier. Correct later supplier payments first.')
            else:
                if v66_supplier_due(name,excluding_purchase=pid)<-.001:
                    raise ValueError('Original supplier has payments against this purchase. Reconcile payments first.')
                if v66_supplier_due(new_name)+new_total-new_paid<-.001:
                    raise ValueError('New supplier would have negative outstanding')
        else:
            after=None
            if v66_supplier_due(name,excluding_purchase=pid)<-.001:
                raise ValueError('Cannot delete: supplier payments exceed remaining purchases. Edit/delete payments first.')
        stock=float(con.execute('SELECT stock FROM products WHERE id=?',(product_id,)).fetchone()[0])
        delta=(float(after[4])-old_qty) if after else -old_qty
        if stock+delta<-.00001:
            raise ValueError('Not enough current stock to reverse this purchase. Review sales/stock first.')
        if not messagebox.askyesno('Confirm '+action,'This changes purchase totals and stock. A database backup and audit record will be saved. Continue?',parent=root):return
        backup_path=v66_backup()
        with con:
            if after:
                con.execute('UPDATE purchases SET supplier=?,qty=?,unit_cost=?,amount=?,paid=? WHERE id=?',(after[2],after[4],after[5],after[6],after[7],pid))
            else:con.execute('DELETE FROM purchases WHERE id=?',(pid,))
            con.execute('UPDATE products SET stock=stock+? WHERE id=?',(delta,product_id))
            if abs(delta)>0.000001:
                con.execute('INSERT INTO stock_adjustments(product_id,created,old_stock,new_stock,difference,reason) VALUES(?,?,?,?,?,?)',
                    (product_id,datetime.now().isoformat(timespec='seconds'),stock,stock+delta,delta,'V66 supplier purchase '+action+' #'+str(pid)))
            v66_audit('purchase',pid,action,before,after,backup_path)
        refresh_all();v66_refresh_management()
        messagebox.showinfo('Saved','Purchase '+action+' completed. Backup and audit saved.',parent=root)
    except (ValueError,sqlite3.Error) as ex:messagebox.showerror('Purchase '+action,str(ex),parent=root)

# V67: Double-click a purchase in the main purchase list or management history.
def v67_edit_purchase(purchase_id):
    try:
        before=con.execute('SELECT id,created,supplier,product_id,qty,unit_cost,amount,paid FROM purchases WHERE id=?',(purchase_id,)).fetchone()
        if not before:raise ValueError('Purchase record no longer exists')
        dlg=tk.Toplevel(root);dlg.title('Edit Purchase #'+str(purchase_id));dlg.transient(root);dlg.grab_set();dlg.resizable(False,False)
        frame=ttk.Frame(dlg,padding=18);frame.pack(fill='both',expand=True)
        fields={}
        for r,(key,label,value) in enumerate([('created','Purchase date/time',before[1]),('supplier','Supplier name',before[2]),('qty','Quantity',before[4]),('cost','Unit cost',before[5]),('paid','Initially paid',before[7])]):
            ttk.Label(frame,text=label).grid(row=r,column=0,sticky='w',padx=6,pady=7)
            e=ttk.Entry(frame,width=35);e.insert(0,str(value));e.grid(row=r,column=1,sticky='ew',padx=6,pady=7);fields[key]=e
        ttk.Label(frame,text='Product').grid(row=5,column=0,sticky='w',padx=6,pady=7)
        products=con.execute('SELECT id,name FROM products ORDER BY name').fetchall()
        product_cb=ttk.Combobox(frame,state='readonly',width=33,values=[str(i)+' | '+name for i,name in products]);product_cb.grid(row=5,column=1,padx=6,pady=7)
        for i,name in products:
            if i==before[3]:product_cb.set(str(i)+' | '+name);break
        ttk.Label(frame,text='Later supplier payments are preserved.\nStock changes are validated before saving.',foreground='#8B4513').grid(row=6,column=0,columnspan=2,pady=8)
        def save():
            try:
                new_date=fields['created'].get().strip();datetime.fromisoformat(new_date.replace(' ','T'))
                new_name=fields['supplier'].get().strip()
                if not new_name:raise ValueError('Supplier name is required')
                new_product=combo_id(product_cb.get())
                if not new_product:raise ValueError('Select a product')
                new_qty=float(fields['qty'].get());new_cost=float(fields['cost'].get());new_paid=float(fields['paid'].get())
                import math
                if not all(math.isfinite(v) for v in (new_qty,new_cost,new_paid)):raise ValueError('Invalid number')
                if new_qty<=0 or new_cost<0 or new_paid<0:raise ValueError('Quantity must be positive; cost and paid cannot be negative')
                total=round(new_qty*new_cost,2)
                if new_paid>total+.001:raise ValueError('Initial payment exceeds purchase total')
                old_name=before[2]
                if old_name==new_name:
                    if v66_supplier_due(old_name,excluding_purchase=purchase_id)+total-new_paid<-.001:
                        raise ValueError('Supplier payments would exceed remaining purchases')
                else:
                    if v66_supplier_due(old_name,excluding_purchase=purchase_id)<-.001:
                        raise ValueError('Old supplier has later payments; reconcile these first')
                    if v66_supplier_due(new_name)+total-new_paid<-.001:
                        raise ValueError('New supplier balance would become negative')
                old_product=before[3];old_qty=float(before[4])
                deltas=({old_product:new_qty-old_qty} if old_product==new_product else {old_product:-old_qty,new_product:new_qty})
                stocks={}
                for product_id,delta in deltas.items():
                    record=con.execute('SELECT stock FROM products WHERE id=?',(product_id,)).fetchone()
                    if not record:raise ValueError('Product no longer exists')
                    stocks[product_id]=float(record[0])
                    if stocks[product_id]+delta<-.00001:raise ValueError('Not enough stock to reverse the original purchase. Review sales first.')
                after=(purchase_id,new_date,new_name,new_product,new_qty,new_cost,total,new_paid)
                if not messagebox.askyesno('Confirm Purchase Update','Update purchase #'+str(purchase_id)+' and linked stock, supplier balance and reports?\nA database backup and audit record will be saved.',parent=dlg):return
                backup=v66_backup()
                with con:
                    con.execute('UPDATE purchases SET created=?,supplier=?,product_id=?,qty=?,unit_cost=?,amount=?,paid=? WHERE id=?',(*after[1:],purchase_id))
                    for product_id,delta in deltas.items():
                        if abs(delta)<.000001:continue
                        con.execute('UPDATE products SET stock=stock+? WHERE id=?',(delta,product_id))
                        con.execute('INSERT INTO stock_adjustments(product_id,created,old_stock,new_stock,difference,reason) VALUES(?,?,?,?,?,?)',(product_id,datetime.now().isoformat(timespec='seconds'),stocks[product_id],stocks[product_id]+delta,delta,'V67 edit purchase #'+str(purchase_id)))
                    v66_audit('purchase',purchase_id,'double_click_edit',before,after,backup)
                dlg.destroy();refresh_all();messagebox.showinfo('Updated','Purchase and linked records updated. Backup and audit saved.',parent=root)
            except (ValueError,OverflowError,sqlite3.Error) as ex:messagebox.showerror('Cannot Update Purchase',str(ex),parent=dlg)
        buttons=ttk.Frame(frame);buttons.grid(row=7,column=0,columnspan=2,pady=10)
        ttk.Button(buttons,text='SAVE & UPDATE ALL',command=save).pack(side='left',padx=8)
        ttk.Button(buttons,text='CANCEL',command=dlg.destroy).pack(side='left',padx=8)
        dlg.bind('<Escape>',lambda e:dlg.destroy())
    except (ValueError,sqlite3.Error) as ex:messagebox.showerror('Edit Purchase',str(ex),parent=root)

def v67_main_purchase_double_click(event):
    item=purchase_tree.identify_row(event.y)
    if not item:return
    values=purchase_tree.item(item,'values')
    # Stable purchase ID is stored as the tree item identifier.
    v67_edit_purchase(int(item))

def v67_management_purchase_double_click(event):
    item=purchase_manage_tree.identify_row(event.y)
    if item:v67_edit_purchase(int(item))

purchase_tree.bind('<Double-1>',v67_main_purchase_double_click)
purchase_manage_tree.bind('<Double-1>',v67_management_purchase_double_click)

def v66_payment_action(action):
    try:
        pid=v66_selected(payment_manage_tree)
        before=con.execute('SELECT id,supplier,created,amount,method,reference FROM supplier_payments WHERE id=?',(pid,)).fetchone()
        if not before:raise ValueError('Payment not found')
        if action=='edit':
            amount=v66_prompt_number('Edit supplier payment','Payment amount',before[3])
            if amount is None:return
            if amount<=0:raise ValueError('Payment must be positive')
            method=simpledialog.askstring('Edit supplier payment','Payment method (Cash / UPI / Bank Transfer / Card)',initialvalue=before[4],parent=root)
            if method is None:return
            reference=simpledialog.askstring('Edit supplier payment','Reference / Notes',initialvalue=before[5] or '',parent=root)
            if reference is None:return
            if amount>v66_supplier_due(before[1],excluding_payment=pid)+.001:
                extra=round(amount-max(v66_supplier_due(before[1],excluding_payment=pid),0),2)
                if not messagebox.askyesno('Supplier advance',f'This edit creates supplier advance Rs {extra:,.2f}. Continue?',parent=root):return
            after=(pid,before[1],before[2],amount,method.strip() or 'Cash',reference.strip())
        else:after=None
        if not messagebox.askyesno('Confirm '+action,'A backup and audit history will be saved. Continue?',parent=root):return
        backup_path=v66_backup()
        with con:
            if after:con.execute('UPDATE supplier_payments SET amount=?,method=?,reference=? WHERE id=?',(after[3],after[4],after[5],pid))
            else:con.execute('DELETE FROM supplier_payments WHERE id=?',(pid,))
            v66_audit('supplier_payment',pid,action,before,after,backup_path)
        refresh_all();v66_refresh_management()
        messagebox.showinfo('Saved','Supplier payment '+action+' completed.',parent=root)
    except (ValueError,sqlite3.Error) as ex:messagebox.showerror('Supplier payment '+action,str(ex),parent=root)

purchase_buttons=ttk.Frame(purchase_manage_tab);purchase_buttons.pack(fill='x',pady=4)
ttk.Button(purchase_buttons,text='EDIT / UPDATE SELECTED PURCHASE',command=lambda:v66_purchase_action('edit')).pack(side='left',padx=4)
ttk.Button(purchase_buttons,text='DELETE SELECTED PURCHASE',command=lambda:v66_purchase_action('delete')).pack(side='left',padx=4)
ttk.Button(purchase_buttons,text='RESET SELECTION',command=lambda:purchase_manage_tree.selection_remove(purchase_manage_tree.selection())).pack(side='left',padx=4)
payment_buttons=ttk.Frame(payment_manage_tab);payment_buttons.pack(fill='x',pady=4)
ttk.Button(payment_buttons,text='EDIT / UPDATE PAYMENT',command=lambda:v66_payment_action('edit')).pack(side='left',padx=4)
ttk.Button(payment_buttons,text='DELETE SELECTED PAYMENT',command=lambda:v66_payment_action('delete')).pack(side='left',padx=4)
ttk.Button(payment_buttons,text='RESET SELECTION',command=lambda:payment_manage_tree.selection_remove(payment_manage_tree.selection())).pack(side='left',padx=4)
ttk.Button(payment_buttons,text='REFRESH HISTORY',command=v66_refresh_management).pack(side='left',padx=4)
# A reset clears only the selected row/form, never financial history.
v66_refresh_management()


# V26 dedicated packing-bag stock, purchases, supplier settlement and sales.
bag_tab=tabs['Packing Bags']
ttk.Label(bag_tab,text='Packing Bags | Stock, Purchase & Accounts',font=('Segoe UI',17,'bold'),foreground=GREEN).pack(anchor='w',padx=12,pady=12)
bag_summary=ttk.Label(bag_tab,text='',font=('Segoe UI',11,'bold'))
bag_summary.pack(anchor='w',padx=12,pady=5)
bag_form=ttk.LabelFrame(bag_tab,text='Buy Packing Bags / Stock Inward',padding=10)
bag_form.pack(fill='x',padx=10,pady=7)
bag_supplier=entry(bag_form,'Supplier',0)
bag_purchase_qty=entry(bag_form,'Bags purchased (Nos)',0,1)
bag_purchase_cost=entry(bag_form,'Purchase cost (₹)',1)
bag_cost_mode=ttk.Combobox(bag_form,state='readonly',values=['Total purchase amount','Cost per bag'],width=24)
bag_cost_mode.set('Total purchase amount')
ttk.Label(bag_form,text='Cost entered as').grid(row=2,column=0,sticky='w',padx=5,pady=5)
bag_cost_mode.grid(row=2,column=1,sticky='ew',padx=5,pady=5)
bag_purchase_paid=entry(bag_form,'Paid now',1,1)
def save_bag_purchase():
    try:
        name=bag_supplier.get().strip()
        qty=num(bag_purchase_qty.get())
        cost=num(bag_purchase_cost.get())
        paid=num(bag_purchase_paid.get() or '0')
        if not name or qty<=0 or qty!=int(qty):raise ValueError('Enter supplier and positive whole-number bag quantity')
        amount=round(qty*cost,2) if bag_cost_mode.get()=='Cost per bag' else round(cost,2)
        unit_cost=round(amount/qty,6)
        if paid>amount:raise ValueError('Paid now cannot exceed purchase total')
        bag=con.execute("SELECT id FROM products WHERE name='Packing Bag'").fetchone()
        if not bag:
            # Self-heal older databases that were created before the bag item existed.
            with con:
                con.execute("INSERT OR IGNORE INTO products(name,unit,stock,cost,rate,hsn,tax,active) VALUES('Packing Bag','Nos',0,0,0,'',0,1)")
            bag=con.execute("SELECT id FROM products WHERE name='Packing Bag'").fetchone()
        with con:
            con.execute('INSERT INTO purchases(created,supplier,product_id,qty,unit_cost,amount,paid) VALUES(?,?,?,?,?,?,?)',
                (datetime.now().isoformat(timespec='seconds'),name,bag[0],qty,unit_cost,amount,paid))
            con.execute('UPDATE products SET stock=stock+?,cost=? WHERE id=?',(qty,unit_cost,bag[0]))
        for e in (bag_purchase_qty,bag_purchase_cost,bag_purchase_paid):e.delete(0,'end')
        refresh_all()
        messagebox.showinfo('Saved',f'{int(qty)} packing bags added to stock. Supplier balance updated.')
    except (ValueError,sqlite3.Error) as ex:messagebox.showerror('Bag purchase',str(ex))
ttk.Button(bag_form,text='SAVE BAG PURCHASE + UPDATE STOCK',command=save_bag_purchase).grid(row=3,column=0,columnspan=4,pady=8)

bag_pay=ttk.LabelFrame(bag_tab,text='Pay Bag Supplier',padding=10)
# Supplier payments are managed centrally in Purchases to avoid duplicate controls.
# bag_pay is retained for backward-compatible refresh code, but not displayed.
# bag_pay.pack(fill='x',padx=10,pady=7)
ttk.Label(bag_pay,text='Supplier').grid(row=0,column=0,padx=5)
bag_supplier_choice=ttk.Combobox(bag_pay,state='readonly',width=28);bag_supplier_choice.grid(row=0,column=1,padx=5)
bag_pay_amount=entry(bag_pay,'Payment ₹',0,1)
bag_pay_method=ttk.Combobox(bag_pay,state='readonly',values=['Cash','UPI','Bank Transfer','Card'],width=16)
bag_pay_method.set('Cash')
ttk.Label(bag_pay,text='Method').grid(row=1,column=0,padx=5)
bag_pay_method.grid(row=1,column=1,padx=5)
def save_bag_supplier_payment():
    try:
        name=bag_supplier_choice.get().strip()
        amount=num(bag_pay_amount.get())
        if not name or amount<=0:raise ValueError('Choose supplier and enter positive payment')
        # Shared supplier account: payments are supplier-wide, never counted twice.
        due=con.execute('SELECT COALESCE(SUM(amount-paid),0) FROM purchases WHERE supplier=?',(name,)).fetchone()[0]
        due-=con.execute('SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier=?',(name,)).fetchone()[0]
        # Supplier prepayments are valid and appear as negative outstanding (advance).
        with con:
            con.execute('INSERT INTO supplier_payments(supplier,created,amount,method) VALUES(?,?,?,?)',
                (name,datetime.now().isoformat(timespec='seconds'),amount,bag_pay_method.get()))
        bag_pay_amount.delete(0,'end')
        refresh_all()
        messagebox.showinfo('Payment saved','Supplier account outstanding has been reduced.')
    except (ValueError,sqlite3.Error) as ex:messagebox.showerror('Bag supplier payment',str(ex))
ttk.Button(bag_pay,text='RECORD SUPPLIER PAYMENT',command=save_bag_supplier_payment).grid(row=1,column=2,padx=8)

bag_sales_frame=ttk.LabelFrame(bag_tab,text='Packing Bag Sales (Saved Invoices)',padding=8)
bag_sales_frame.pack(fill='x',padx=10,pady=7)
bag_sales_tree=ttk.Treeview(bag_sales_frame,columns=('Date','Invoice','Customer','Bags','Sales Amount'),show='headings',height=7)
for col in ('Date','Invoice','Customer','Bags','Sales Amount'):
    bag_sales_tree.heading(col,text=col);bag_sales_tree.column(col,width=175)
bag_sales_tree.pack(fill='x')
bag_purchase_frame=ttk.LabelFrame(bag_tab,text='Bag Purchases / Supplier Outstanding',padding=8)
bag_purchase_frame.pack(fill='x',padx=10,pady=7)
bag_purchase_tree=ttk.Treeview(bag_purchase_frame,columns=('Date','Supplier','Bags','Cost / Bag','Total','Paid at Purchase'),show='headings',height=6)
for col in ('Date','Supplier','Bags','Cost / Bag','Total','Paid at Purchase'):
    bag_purchase_tree.heading(col,text=col);bag_purchase_tree.column(col,width=160)
bag_purchase_tree.pack(fill='x')
bag_supplier_tree=ttk.Treeview(bag_purchase_frame,columns=('Supplier','All Purchases','All Payments','Outstanding'),show='headings',height=5)
for col in ('Supplier','All Purchases','All Payments','Outstanding'):
    bag_supplier_tree.heading(col,text=col);bag_supplier_tree.column(col,width=180)
# Supplier ledger is shown centrally in Purchases; no duplicate table here.
# bag_supplier_tree.pack(fill='x',pady=5)
def refresh_bag_management():
    bag=con.execute("SELECT id,stock,cost FROM products WHERE name='Packing Bag'").fetchone()
    if not bag:return
    bid,stock,cost=bag
    sold=con.execute("SELECT COALESCE(SUM(qty),0),COALESCE(SUM(line_total),0) FROM invoice_items WHERE description='Packing Bag'").fetchone()
    bought=con.execute('SELECT COALESCE(SUM(qty),0),COALESCE(SUM(amount),0) FROM purchases WHERE product_id=?',(bid,)).fetchone()
    bag_summary.config(text=f'Purchased: {bought[0]:,.0f} Nos    |    Sold (all saved bills): {sold[0]:,.0f} Nos    |    Available: {stock:,.0f} Nos    |    Sales: {money(sold[1])}    |    Purchase cost: {money(bought[1])}')
    fill(bag_sales_tree,[(d[:16].replace('T',' '),inv,cust,qty,money(amt)) for d,inv,cust,qty,amt in rows("""
        SELECT i.created,i.number,COALESCE(c.name,'Walk-in'),SUM(ii.qty),SUM(ii.line_total)
        FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
        LEFT JOIN customers c ON c.id=i.customer_id
        WHERE ii.description='Packing Bag' GROUP BY i.id ORDER BY i.created DESC LIMIT 500""")])
    bag_purchase_tree.delete(*bag_purchase_tree.get_children())
    for pid,d,n,q,c,t,pay in rows("""SELECT id,created,supplier,qty,unit_cost,amount,paid
        FROM purchases WHERE product_id=? ORDER BY id DESC LIMIT 500""",(bid,)):
        bag_purchase_tree.insert('', 'end', iid=str(pid), values=(d[:16].replace('T',' '),n,q,money(c),money(t),money(pay)))
    bag_payment_history_tree.delete(*bag_payment_history_tree.get_children())
    for payid,supplier,created,amount,method in rows('SELECT id,supplier,created,amount,method FROM supplier_payments ORDER BY id DESC LIMIT 500'):
        bag_payment_history_tree.insert('', 'end', iid=str(payid), values=(created[:16].replace('T',' '),supplier,money(amount),method))
    names=[x[0] for x in rows('SELECT supplier FROM purchases WHERE product_id=? UNION SELECT supplier FROM supplier_payments ORDER BY supplier COLLATE NOCASE',(bid,))]
    bag_supplier_choice['values']=names
    bag_supplier_tree.delete(*bag_supplier_tree.get_children())
    for name in names:
        total=con.execute('SELECT COALESCE(SUM(amount),0) FROM purchases WHERE supplier=?',(name,)).fetchone()[0]
        paid=con.execute('SELECT COALESCE(SUM(paid),0) FROM purchases WHERE supplier=?',(name,)).fetchone()[0]
        paid+=con.execute('SELECT COALESCE(SUM(amount),0) FROM supplier_payments WHERE supplier=?',(name,)).fetchone()[0]
        bag_supplier_tree.insert('','end',values=(name,money(total),money(paid),money(total-paid)))
# Purchase history: archive + reversible restore, with stock correction.
# Sales history cannot be deleted here because it belongs to customer invoices.
bag_history_buttons=ttk.Frame(bag_tab)
bag_history_buttons.pack(fill='x',padx=12,pady=5)

def delete_selected_bag_purchase():
    import json
    selected=bag_purchase_tree.selection()
    if not selected:
        messagebox.showinfo('Select purchase','Select a row in Bag Purchases first.');return
    try:
        pid=int(selected[0])
        record=con.execute('SELECT id,created,supplier,product_id,qty,unit_cost,amount,paid,group_id FROM purchases WHERE id=?',(pid,)).fetchone()
        if not record:raise ValueError('Purchase not found. Refresh the list.')
        bid=record[3]; qty=record[4]
        stock=con.execute('SELECT stock FROM products WHERE id=?',(bid,)).fetchone()[0]
        if stock+0.00001<qty:raise ValueError('Cannot delete: some of these bags have already been sold. Restore enough stock or correct the sale first.')
        if not messagebox.askyesno('Delete bag purchase',f'Delete {qty:g} bags from {record[2]}?\nStock will decrease by {qty:g}.\nA restorable archive will be kept.'):
            return
        v66_backup()  # Consistent snapshot before any stock/purchase deletion.
        with con:
            con.execute('INSERT INTO bag_history_archive(kind,source_id,deleted_at,payload) VALUES(?,?,?,?)',('purchase',pid,datetime.now().isoformat(timespec='seconds'),json.dumps(record)))
            con.execute('DELETE FROM purchases WHERE id=?',(pid,))
            con.execute('UPDATE products SET stock=stock-? WHERE id=?',(qty,bid))
        refresh_all()
        messagebox.showinfo('Archived','Purchase deleted and archived. Use Restore Last Deleted Bag Entry to undo.')
    except (ValueError,sqlite3.Error) as ex:messagebox.showerror('Delete purchase',str(ex))

def restore_last_bag_entry():
    import json
    archive=con.execute('SELECT id,kind,source_id,payload FROM bag_history_archive WHERE restored=0 ORDER BY id DESC LIMIT 1').fetchone()
    if not archive:
        messagebox.showinfo('Restore','No deleted bag entry to restore.');return
    aid,kind,source_id,payload=archive
    data=json.loads(payload)
    if not messagebox.askyesno('Restore bag history',f'Restore last deleted {kind} entry (ID {source_id})?'):return
    try:
        if kind not in ('purchase','payment'):
            raise ValueError('Unsupported archived entry type; no data changed.')
        table='purchases' if kind=='purchase' else 'supplier_payments'
        id_collision=bool(con.execute(f'SELECT 1 FROM {table} WHERE id=?',(source_id,)).fetchone())
        # SQLite may reuse a deleted INTEGER PRIMARY KEY. Restore with a fresh ID
        # rather than overwriting another real transaction or losing the archive.
        if kind=='purchase' and not con.execute('SELECT 1 FROM products WHERE id=?',(data[3],)).fetchone():
            raise ValueError('Original product no longer exists. Restore stopped; archived record remains safe.')
        v66_backup()
        with con:
            if kind=='purchase':
                # Older archive entries have 8 fields; V76 archives also retain group_id.
                purchase_data = list(data[:8])
                original_group_id = data[8] if len(data)>8 else None
                if original_group_id is not None and not con.execute('SELECT 1 FROM purchase_groups WHERE id=?',(original_group_id,)).fetchone():
                    original_group_id = None
                if id_collision:
                    con.execute('INSERT INTO purchases(created,supplier,product_id,qty,unit_cost,amount,paid,group_id) VALUES(?,?,?,?,?,?,?,?)',(*purchase_data[1:],original_group_id))
                else:
                    con.execute('INSERT INTO purchases(id,created,supplier,product_id,qty,unit_cost,amount,paid,group_id) VALUES(?,?,?,?,?,?,?,?,?)',(*purchase_data,original_group_id))
                con.execute('UPDATE products SET stock=stock+? WHERE id=?',(data[4],data[3]))
            else:
                if id_collision:
                    con.execute('INSERT INTO supplier_payments(supplier,created,amount,method,reference) VALUES(?,?,?,?,?)',data[1:])
                else:
                    con.execute('INSERT INTO supplier_payments(id,supplier,created,amount,method,reference) VALUES(?,?,?,?,?,?)',data)
            con.execute('UPDATE bag_history_archive SET restored=1 WHERE id=?',(aid,))
        refresh_all()
        messagebox.showinfo('Restored','Archived entry restored. Stock and supplier balances refreshed.' + (' A new transaction ID was assigned because the original ID was already in use.' if id_collision else ''))
    except (ValueError,sqlite3.Error) as ex:messagebox.showerror('Restore safely stopped',str(ex))

def delete_selected_bag_supplier_payment():
    import json
    selected=bag_payment_history_tree.selection()
    if not selected:
        messagebox.showinfo('Select payment','Select a row in Supplier Payment History first.');return
    try:
        pid=int(selected[0])
        record=con.execute('SELECT id,supplier,created,amount,method,reference FROM supplier_payments WHERE id=?',(pid,)).fetchone()
        if not record:raise ValueError('Payment not found.')
        if not messagebox.askyesno('Delete supplier payment',f'Delete payment {money(record[3])} to {record[1]}?\nThis will update the supplier balance.'):
            return
        v66_backup()  # Preserve original supplier payment before deletion.
        with con:
            con.execute('INSERT INTO bag_history_archive(kind,source_id,deleted_at,payload) VALUES(?,?,?,?)',('payment',pid,datetime.now().isoformat(timespec='seconds'),json.dumps(record)))
            con.execute('DELETE FROM supplier_payments WHERE id=?',(pid,))
        refresh_all()
    except (ValueError,sqlite3.Error) as ex:messagebox.showerror('Delete payment',str(ex))

ttk.Button(bag_history_buttons,text='DELETE SELECTED BAG PURCHASE',command=delete_selected_bag_purchase).pack(side='left',padx=4)
# Supplier payment deletion is available in Purchases > Supplier Payment History.
ttk.Button(bag_history_buttons,text='RESTORE LAST DELETED BAG ENTRY',command=restore_last_bag_entry).pack(side='left',padx=4)

bag_payment_frame=ttk.LabelFrame(bag_tab,text='Supplier Payment History (Select to Delete)',padding=8)
# Hide duplicate supplier payment history; keep tree for refresh compatibility.
# bag_payment_frame.pack(fill='x',padx=10,pady=5)
bag_payment_history_tree=ttk.Treeview(bag_payment_frame,columns=('Date','Supplier','Amount','Method'),show='headings',height=5)
for col in ('Date','Supplier','Amount','Method'):
    bag_payment_history_tree.heading(col,text=col)
    bag_payment_history_tree.column(col,width=160)
bag_payment_history_tree.pack(fill='x')

def choose_bag_supplier(_=None):
    sel=bag_supplier_tree.selection()
    if sel:bag_supplier_choice.set(bag_supplier_tree.item(sel[0],'values')[0])
bag_supplier_tree.bind('<<TreeviewSelect>>',choose_bag_supplier)
ttk.Button(bag_tab,text='Refresh Bag Stock & Accounts',command=refresh_bag_management).pack(anchor='w',padx=12,pady=7)

# Customer x product sales matrix, based on saved invoice line items.
customer_product_box=ttk.LabelFrame(tabs['Daily & Customer Sales'],text='Customer-wise Product Sales (All 11 Products)',padding=8)
customer_product_box.pack(side='bottom',fill='x',padx=8,pady=6)
cp_filters=ttk.Frame(customer_product_box);cp_filters.pack(fill='x')
ttk.Label(cp_filters,text='Customer').pack(side='left')
cp_customer=ttk.Combobox(cp_filters,state='readonly',width=32);cp_customer.pack(side='left',padx=6)
ttk.Label(cp_filters,text='From YYYY-MM-DD').pack(side='left')
cp_from=ttk.Entry(cp_filters,width=12);cp_from.pack(side='left',padx=5)
ttk.Label(cp_filters,text='To YYYY-MM-DD').pack(side='left')
cp_to=ttk.Entry(cp_filters,width=12);cp_to.pack(side='left',padx=5)
cp_tree=ttk.Treeview(customer_product_box,columns=('Product','Unit','Quantity','Sales Amount'),show='headings',height=6)
for c in ('Product','Unit','Quantity','Sales Amount'):
    cp_tree.heading(c,text=c);cp_tree.column(c,width=170)
cp_tree.pack(fill='x',pady=4)
def refresh_customer_product_report():
    cp_tree.delete(*cp_tree.get_children())
    cid=combo_id(cp_customer.get())
    if not cid:return
    try:
        for value in (cp_from.get().strip(),cp_to.get().strip()):
            if value:datetime.strptime(value,'%Y-%m-%d')
    except ValueError:return messagebox.showerror('Date','Use YYYY-MM-DD')
    data=rows("""SELECT COALESCE(p.name,ii.description),COALESCE(p.unit,'-'),ROUND(SUM(ii.qty),2),ROUND(SUM(ii.line_total),2)
    FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
    LEFT JOIN products p ON p.id=ii.product_id
    WHERE i.customer_id=? AND (?='' OR substr(i.created,1,10)>=?) AND (?='' OR substr(i.created,1,10)<=?)
    GROUP BY COALESCE(p.name,ii.description),COALESCE(p.unit,'-') ORDER BY 1""",
    (cid,cp_from.get().strip(),cp_from.get().strip(),cp_to.get().strip(),cp_to.get().strip()))
    for name,unit,qty,amount in data:cp_tree.insert('', 'end',values=(name,unit,qty,money(amount)))
ttk.Button(cp_filters,text='View Customer Product Sales',command=refresh_customer_product_report).pack(side='left',padx=7)

# V43 daily opening / stock-in / stock-out / closing, per product.
stock_day_tab=tabs['Daily Stock Register']
ttk.Label(stock_day_tab,text='DAILY STOCK REGISTER | PRODUCT-WISE IN / OUT / BALANCE',
          font=('Segoe UI',16,'bold'),foreground=GREEN).pack(anchor='w',padx=12,pady=10)
ttk.Label(stock_day_tab,text='Today closing automatically becomes tomorrow opening. Purchases add; saved sales deduct.').pack(anchor='w',padx=12)
stock_day_controls=ttk.Frame(stock_day_tab);stock_day_controls.pack(fill='x',padx=12,pady=10)
ttk.Label(stock_day_controls,text='Date (YYYY-MM-DD)').pack(side='left',padx=4)
stock_day_date=ttk.Entry(stock_day_controls,width=14)
stock_day_date.insert(0,datetime.now().strftime('%Y-%m-%d'))
stock_day_date.pack(side='left',padx=5)
ttk.Label(stock_day_controls,text='Product').pack(side='left',padx=6)
stock_day_product=ttk.Combobox(stock_day_controls,state='readonly',width=29)
stock_day_product.pack(side='left',padx=4)
stock_day_product['values']=['All Products']+[name for name,unit in PRODUCT_CATALOG]+['Packing Bag']
stock_day_product.set('All Products')
stock_day_table=ttk.Treeview(stock_day_tab,columns=('Product','Unit','Opening','Stock IN','Stock OUT','Closing'),show='headings',height=17)
for _col,_width in [('Product',230),('Unit',90),('Opening',115),('Stock IN',115),('Stock OUT',115),('Closing',115)]:
    stock_day_table.heading(_col,text=_col);stock_day_table.column(_col,width=_width,anchor='w' if _col=='Product' else 'e')
stock_day_table.pack(fill='both',expand=True,padx=12,pady=8)
stock_day_note=ttk.Label(stock_day_tab,text='',foreground=GREEN)
stock_day_note.pack(anchor='w',padx=12,pady=4)

def stock_register_rows(day):
    # V58: A completed RESET ALL STOCK & PRICE starts a new stock ledger epoch.
    # Keep historical stock movements intact for auditing and historical date views.
    # Current and future register balances exclude all pre-reset movements.
    result=[]
    for pid,name,unit in con.execute('SELECT id,name,unit FROM products ORDER BY id').fetchall():
        if name not in dict(PRODUCT_CATALOG) and name!='Packing Bag':continue
        baseline=con.execute(
            'SELECT initial_qty,substr(started,1,10) FROM stock_register_baseline WHERE product_id=?',
            (pid,)).fetchone()
        if not baseline:continue
        initial,started=baseline
        if day<started:continue
        # The most recent reset on/before this day is the stock baseline boundary.
        reset=con.execute('''SELECT r.created FROM bulk_product_resets r
            JOIN bulk_product_reset_items i ON i.reset_id=r.id
            WHERE i.product_id=? AND substr(r.created,1,10)<=?
            ORDER BY r.created DESC,r.id DESC LIMIT 1''',(pid,day)).fetchone()
        if reset:
            cutoff=str(reset[0]).replace(' ','T')
            # A reset sets stock to 0, even if the old stock was already zero.
            # Use strictly later movements to avoid reapplying the reset itself.
            opening=con.execute('''SELECT COALESCE(SUM(qty_in-qty_out),0)
                FROM stock_movement_log WHERE product_id=?
                AND REPLACE(changed,' ','T')>?
                AND substr(changed,1,10)<?''',(pid,cutoff,day)).fetchone()[0]
            # On the reset date show zero opening and only post-reset movements.
            # For later days, opening is post-reset accumulated movements.
            inout=con.execute('''SELECT COALESCE(SUM(qty_in),0),COALESCE(SUM(qty_out),0)
                FROM stock_movement_log WHERE product_id=?
                AND REPLACE(changed,' ','T')>?
                AND substr(changed,1,10)=?''',(pid,cutoff,day)).fetchone()
        else:
            prior=con.execute('''SELECT COALESCE(SUM(qty_in-qty_out),0)
                FROM stock_movement_log WHERE product_id=? AND substr(changed,1,10)<?''',
                (pid,day)).fetchone()[0]
            opening=float(initial)+float(prior)
            inout=con.execute('''SELECT COALESCE(SUM(qty_in),0),COALESCE(SUM(qty_out),0)
                FROM stock_movement_log WHERE product_id=? AND substr(changed,1,10)=?''',
                (pid,day)).fetchone()
        stock_in,stock_out=map(float,inout)
        opening=float(opening)
        result.append((name,unit,round(opening,3),round(stock_in,3),
                       round(stock_out,3),round(opening+stock_in-stock_out,3)))
    order={name:i for i,(name,unit) in enumerate(PRODUCT_CATALOG)}
    result.sort(key=lambda r:order.get(r[0],999))
    return result

def refresh_daily_stock_register():
    day=stock_day_date.get().strip()
    try:datetime.strptime(day,'%Y-%m-%d')
    except ValueError:
        messagebox.showerror('Invalid date','Enter date in YYYY-MM-DD format.');return
    product=stock_day_product.get()
    data=stock_register_rows(day)
    if product!='All Products':data=[r for r in data if r[0]==product]
    fill(stock_day_table,[(n,u,f'{o:g}',f'{i:g}',f'{out:g}',f'{c:g}') for n,u,o,i,out,c in data])
    stock_day_note.config(text=f'{len(data)} product(s) | Date: {day} | Each product keeps its own unit (Kg / Nos / Litre).')

def export_daily_stock_csv():
    day=stock_day_date.get().strip()
    try:datetime.strptime(day,'%Y-%m-%d')
    except ValueError:return messagebox.showerror('Date','Enter YYYY-MM-DD date first')
    data=stock_register_rows(day)
    product=stock_day_product.get()
    if product!='All Products':data=[r for r in data if r[0]==product]
    path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile=f'ASCT_Daily_Stock_{day}.csv',filetypes=[('CSV','*.csv')])
    if not path:return
    with open(path,'w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow(['Date','Product','Unit','Opening','Stock IN','Stock OUT','Closing'])
        for row in data:writer.writerow([day,*row])
    messagebox.showinfo('Export','Daily stock CSV saved successfully.')

ttk.Button(stock_day_controls,text='VIEW DAILY STOCK',command=refresh_daily_stock_register).pack(side='left',padx=6)
ttk.Button(stock_day_controls,text='EXPORT CSV',command=export_daily_stock_csv).pack(side='left',padx=6)

# Billing
f=tabs['New Bill'];top=ttk.LabelFrame(f,text='New Sales Invoice',padding=10);top.pack(fill='x',padx=8,pady=8)
ttk.Label(top,text='Invoice Date / Time:').grid(row=3,column=0,padx=5,pady=5)
bill_datetime=tk.StringVar(value=datetime.now().strftime('%d-%m-%Y  %I:%M %p'))
ttk.Label(top,textvariable=bill_datetime,font=('Segoe UI',10,'bold'),foreground=GREEN).grid(row=3,column=1,sticky='w')
ttk.Label(top,text='(Auto-set when saved)').grid(row=3,column=2,columnspan=2,sticky='w')
ttk.Label(top,text='Customer').grid(row=0,column=0,padx=5);bill_customer=ttk.Combobox(top,state='readonly',width=35);bill_customer.grid(row=0,column=1,padx=5)
ttk.Label(top,text='Payment method').grid(row=0,column=2,padx=5);bill_method=ttk.Combobox(top,state='readonly',values=['Cash','UPI','Bank Transfer','Card','Credit'],width=18);bill_method.set('Cash');bill_method.grid(row=0,column=3)
ttk.Label(top,text='Product').grid(row=1,column=0,pady=8);bill_product=ttk.Combobox(top,state='readonly',width=35);bill_product.grid(row=1,column=1)
ttk.Label(top,text='Qty').grid(row=1,column=2);bill_qty=ttk.Entry(top,width=14);bill_qty.grid(row=1,column=3)
bill_rate_label=ttk.Label(top,text='Rate / unit (editable)');bill_rate_label.grid(row=1,column=4);bill_rate=ttk.Entry(top,width=14);bill_rate.grid(row=1,column=5)
# Separate optional packaging charge; independent of coconut kg price.
ttk.Label(top,text='Bags (count)').grid(row=2,column=0,pady=8)
bag_qty=ttk.Entry(top,width=12);bag_qty.insert(0,'0');bag_qty.grid(row=2,column=1,sticky='w',padx=5)
ttk.Label(top,text='Price / bag (₹)').grid(row=2,column=2)
bag_rate=ttk.Entry(top,width=14);bag_rate.insert(0,'0');bag_rate.grid(row=2,column=3)
cart=[]
def selected_product(_=None):
    pid=combo_id(bill_product.get())
    if pid:
        r=con.execute('SELECT rate,unit FROM products WHERE id=?',(pid,)).fetchone()
        bill_rate_label.configure(text=f'Rate / {r[1]} (editable)')
        bill_rate.delete(0,'end');bill_rate.insert(0,str(r[0]));bill_qty.delete(0,'end');bill_qty.insert(0,'1')
bill_product.bind('<<ComboboxSelected>>',selected_product)
# Pack the action bar FIRST against the bottom edge. The expanding invoice table
# must never push Save/PDF/Print controls outside the visible window.
bottom=ttk.Frame(f,padding=10)
bottom.pack(side='bottom',fill='x',padx=8,pady=(4,8))
cart_tree=table(f,('Product','Qty','Rate','GST %','Line total'))
cart_tree.configure(selectmode='extended')
total_lbl=ttk.Label(bottom,text='Total: ₹0.00',font=('Segoe UI',15,'bold'));total_lbl.pack(side='left',padx=10)
ttk.Label(bottom,text='Paid now ₹').pack(side='left');bill_paid=ttk.Entry(bottom,width=15);bill_paid.insert(0,'0');bill_paid.pack(side='left',padx=5)

def cart_total():return round(sum(x['total'] for x in cart),2)
account_preview=tk.StringVar(value='Customer account: select a customer to view previous pending / advance')
ttk.Label(f,textvariable=account_preview,foreground=GREEN,font=('Segoe UI',10,'bold')).pack(anchor='w',padx=14,pady=2)
def refresh_account_preview(*_):
    cid=combo_id(bill_customer.get())
    due,credit=customer_account_position(cid)
    new_total=cart_total()
    applied=min(credit,new_total)
    net_due=max(0,round(due+new_total-credit,2))
    account_preview.set(f'Previous Pending: {money(due)}  |  Available Advance: {money(credit)}  |  Advance adjusted: {money(applied)}  |  Total Payable (before new cash): {money(net_due)}')
bill_customer.bind('<<ComboboxSelected>>',refresh_account_preview)

def render_cart():
    fill(cart_tree,[(x['name'],x['qty'],money(x['rate']),x['tax'],money(x['total'])) for x in cart]);total_lbl.config(text='Total: '+money(cart_total()));refresh_account_preview()
def add_to_cart():
    try:
        pid=combo_id(bill_product.get());qty=num(bill_qty.get());rate=num(bill_rate.get())
        if not pid or qty<=0:raise ValueError('Choose product and positive quantity')
        p=con.execute('SELECT name,stock,tax FROM products WHERE id=?',(pid,)).fetchone()
        existing=sum(x['qty'] for x in cart if x['pid']==pid)
        if existing+qty>p[1]+1e-8:raise ValueError(f'Insufficient stock. Available: {p[1]}')
        tax=p[2];cart.append(dict(pid=pid,name=p[0],qty=qty,rate=rate,tax=tax,total=round(qty*rate*(1+tax/100),2)))
        render_cart()
    except ValueError as ex:messagebox.showerror('Billing error',str(ex))
def add_bags():
    try:
        qty=num(bag_qty.get() or '0');rate=num(bag_rate.get() or '0')
        if qty<=0 or qty!=int(qty):raise ValueError('Bag count must be a positive whole number')
        if rate<=0:raise ValueError('Enter price per bag')
        bag=con.execute("SELECT id,stock FROM products WHERE name='Packing Bag'").fetchone()
        if not bag:raise ValueError('Packing Bag stock item is missing')
        already=sum(x['qty'] for x in cart if x['pid']==bag[0])
        if qty+already>bag[1]+1e-8:
            raise ValueError(f'Insufficient packing bags. Available: {bag[1]:g} Nos. Record a bag purchase or stock adjustment first.')
        cart.append(dict(pid=bag[0],name='Packing Bag',qty=qty,rate=rate,tax=0,total=round(qty*rate,2)))
        render_cart()
    except ValueError as ex:messagebox.showerror('Bag charge',str(ex))
ttk.Button(top,text='Add Bag Charge',command=add_bags).grid(row=2,column=4,columnspan=2,padx=8)
def remove_cart():
    # The Treeview is a view: always remove from the in-memory cart as well.
    active=_active_cart_editor.get('finish') if '_active_cart_editor' in globals() else None
    if active and not active(save=False):return
    selected=cart_tree.selection()
    if not selected:
        return messagebox.showinfo('Remove items','Select one or more bill rows first. Ctrl+Click selects multiple rows.')
    indexes=sorted({cart_tree.index(item) for item in selected},reverse=True)
    if len(indexes)>1 and not messagebox.askyesno('Remove selected items',
        f'Remove {len(indexes)} selected items from this unsaved bill?'):
        return
    for index in indexes:
        if 0<=index<len(cart):cart.pop(index)
    render_cart()

def clear_cart():
    active=_active_cart_editor.get('finish') if '_active_cart_editor' in globals() else None
    if active:active(save=False)
    if not cart:return messagebox.showinfo('Clear bill','The bill has no items.')
    if not messagebox.askyesno('Clear all bill items',
        f'Remove all {len(cart)} items from the current unsaved bill?\n\n'
        'Existing saved invoices and stock will not be changed.',icon='warning'):
        return
    cart.clear()
    render_cart()

def delete_selected_cart_key(event):
    # Do not intercept Delete while editing an inline Qty/Rate entry.
    if _active_cart_editor.get('widget') is not None:return
    remove_cart()
    return 'break'

ttk.Button(top,text='Add Item',command=add_to_cart).grid(row=1,column=6,padx=12)
ttk.Button(bottom,text='REMOVE SELECTED ITEM(S)',command=remove_cart).pack(side='right',padx=5)
ttk.Button(bottom,text='CLEAR ALL ITEMS',command=clear_cart).pack(side='right',padx=5)
cart_tree.bind('<Delete>',delete_selected_cart_key)

last_saved_invoice_id = None

def print_last_saved_bill():
    if last_saved_invoice_id is None:
        messagebox.showinfo("Print bill", "Save a bill first, then click PRINT BILL.")
        return
    try:
        path = existing_or_rebuilt_pdf(last_saved_invoice_id)
        if messagebox.askyesno("Print bill", "Print the last saved bill using the Windows default printer?\n\nTo choose a different printer, open the PDF and print from its viewer."):
            print_pdf(path, last_saved_invoice_id)
    except Exception as ex:
        messagebox.showerror("Print error", str(ex))

def create_invoice():
    global last_saved_invoice_id
    try:
        if not cart:raise ValueError('Add at least one item')
        cid=combo_id(bill_customer.get());paid=num(bill_paid.get() or '0');total=cart_total()
        opening_due,opening_advance=customer_account_position(cid)
        if paid>total+0.001 and not cid:raise ValueError('Select a saved customer to record the extra amount as customer advance')
        invoice_paid=min(paid,total)
        advance=round(max(0,paid-total),2)
        if not cid and paid<total-0.001:raise ValueError('Credit sale requires a saved customer')
        if not setting('gstin').strip() and any(x['tax'] > 0 for x in cart):raise ValueError('GSTIN is blank. Set product GST rates to 0 for a non-GST sales bill; verify tax treatment before issuing bills.')
        subtotal=round(sum(x['qty']*x['rate'] for x in cart),2);tax_total=round(total-subtotal,2)
        with con:
            for x in cart:
                if x['pid'] is None:continue
                updated=con.execute('UPDATE products SET stock=stock-? WHERE id=? AND stock>=?',(x['qty'],x['pid'],x['qty'])).rowcount
                if not updated:raise ValueError('Stock changed. Recheck '+x['name'])
            seq=con.execute('SELECT last_number FROM invoice_sequence WHERE id=1').fetchone()[0]+1
            con.execute('UPDATE invoice_sequence SET last_number=? WHERE id=1',(seq,))
            invnum=f'ASCT/{datetime.now():%Y%m%d}/{seq:05d}'
            cur=con.execute('INSERT INTO invoices(number,customer_id,created,subtotal,tax_total,total,paid,notes,opening_due,opening_advance) VALUES(?,?,?,?,?,?,?,?,?,?)',(invnum,cid,datetime.now().isoformat(timespec='seconds'),subtotal,tax_total,total,invoice_paid,bill_method.get(),opening_due,opening_advance))
            iid=cur.lastrowid
            for x in cart:con.execute('INSERT INTO invoice_items(invoice_id,product_id,description,qty,rate,tax_rate,line_total) VALUES(?,?,?,?,?,?,?)',(iid,x['pid'],x['name'],x['qty'],x['rate'],x['tax'],x['total']))
            if invoice_paid>0:con.execute('INSERT INTO payments(invoice_id,created,amount,method) VALUES(?,?,?,?)',(iid,datetime.now().isoformat(timespec='seconds'),invoice_paid,bill_method.get()))
            if advance>0:con.execute('INSERT INTO customer_payments(customer_id,created,amount,method,reference) VALUES(?,?,?,?,?)',(cid,datetime.now().isoformat(timespec='seconds'),advance,bill_method.get(),'Advance received with '+invnum))
        last_saved_invoice_id = iid
        try:
            draft_path=DATA/'current_bill_draft.json'
            if draft_path.exists():draft_path.unlink()
        except OSError:pass
        cart.clear();render_cart();bill_paid.delete(0,'end');bill_paid.insert(0,'0');bill_datetime.set(datetime.now().strftime('%d-%m-%Y  %I:%M %p'));refresh_all()
        try:
            pdf=save_invoice_pdf(iid)
            try:
                open_pdf(pdf)
            except Exception as open_ex:
                messagebox.showwarning('Bill saved - PDF not opened',f'Invoice {invnum} was saved and PDF generated at:\n{pdf}\n\nCould not automatically open PDF: {open_ex}')
            if messagebox.askyesno('WhatsApp invoice','Prepare a colour bill image for WhatsApp?\n\nYou will attach and send the PNG yourself.'):
                share_invoice_whatsapp(iid)
        except Exception as ex:
            messagebox.showwarning('Bill saved; PDF issue',f'Invoice {invnum} was saved in database. PDF failed: {ex}')
        return iid
    except (ValueError,sqlite3.Error) as ex:messagebox.showerror('Invoice error',str(ex))
ttk.Button(bottom,text='PRINT BILL',command=print_last_saved_bill).pack(side='right',padx=5)
ttk.Button(bottom,text='SAVE BILL + OPEN PDF',command=create_invoice).pack(side='right',padx=5)
ttk.Label(bottom,text='Save = 80mm PDF • Print = thermal printer • WhatsApp = colour PNG',foreground=GREEN).pack(side='right',padx=6)

# History and payment
f=tabs['Payments & History'];bar=ttk.LabelFrame(f,text='Receive Customer Payment',padding=10);bar.pack(fill='x',padx=8,pady=8)
ttk.Label(bar,text='Invoice').grid(row=0,column=0,padx=4);payment_invoice=ttk.Combobox(bar,state='readonly',width=47);payment_invoice.grid(row=0,column=1,padx=4)
payment_amount=entry(bar,'Amount ₹',0,1);ttk.Label(bar,text='Method').grid(row=0,column=4);payment_method=ttk.Combobox(bar,state='readonly',values=['Cash','UPI','Bank Transfer','Card'],width=16);payment_method.set('UPI');payment_method.grid(row=0,column=5)
# Search and invoice recovery controls are positioned above the table so they remain visible.
history_actions=ttk.Frame(f);history_actions.pack(fill='x',padx=9,pady=5)
ttk.Label(history_actions,text='Find old bill (invoice / customer / date):').pack(side='left',padx=5)
history_search=tk.StringVar()
history_search_entry=ttk.Entry(history_actions,textvariable=history_search,width=29)
history_search_entry.pack(side='left',padx=5)
ttk.Label(f,text='Double-click any invoice to view full details. Original invoice number, date, items and rates are retained.',foreground=GREEN).pack(anchor='w',padx=13)
history_tree=table(f,('ID','Invoice','Date','Customer','Total','Received','Balance','Method'))
history_tree.configure(selectmode='extended')
ttk.Label(f,text='Multiple bills: Ctrl+Click to select individual rows; Shift+Click to select a range. Delete moves ALL selected bills to Recycle Bin.',foreground=GREEN).pack(anchor='w',padx=13)
def refresh_history():
    data=rows('SELECT i.id,i.number,i.created,COALESCE(c.name,"Walk-in Customer"),i.total,i.paid,ROUND(i.total-i.paid,2),i.notes FROM invoices i LEFT JOIN customers c ON i.customer_id=c.id ORDER BY i.id DESC LIMIT 1000')
    term=history_search.get().strip().casefold()
    display=[(a,b,d[:16].replace('T',' '),c,money(t),money(p),money(bal),n) for a,b,d,c,t,p,bal,n in data]
    if term:display=[r for r in display if any(term in str(v).casefold() for v in r[:4])]
    fill(history_tree,display)
    old=payment_invoice.get();options=[f'{a} | {b} | {c} | Due {bal:.2f}' for a,b,c,bal in rows('SELECT i.id,i.number,COALESCE(c.name,"Walk-in"),ROUND(i.total-i.paid,2) FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id WHERE i.total-i.paid>0.005 ORDER BY i.id DESC')]
    payment_invoice['values']=options;payment_invoice.set(old if old in options else '')
def receive_payment():
    try:
        iid=combo_id(payment_invoice.get());amount=num(payment_amount.get())
        if not iid or amount<=0:raise ValueError('Select invoice and positive amount')
        with con:
            updated=con.execute('UPDATE invoices SET paid=paid+? WHERE id=? AND total-paid>=?',(amount,iid,amount-0.001)).rowcount
            if not updated:raise ValueError('Amount exceeds pending balance')
            con.execute('INSERT INTO payments(invoice_id,created,amount,method) VALUES(?,?,?,?)',(iid,datetime.now().isoformat(timespec='seconds'),amount,payment_method.get()))
        payment_amount.delete(0,'end');refresh_all();messagebox.showinfo('Payment saved','Customer balance updated')
    except ValueError as ex:messagebox.showerror('Payment error',str(ex))
ttk.Button(bar,text='Receive Payment',command=receive_payment).grid(row=1,column=0,columnspan=6,pady=7)
history_search.trace_add('write',lambda *_:refresh_history())

def selected_history_id():
    sel=history_tree.selection()
    if not sel:
        messagebox.showinfo('Select old bill','Please select an invoice in Payments & History first.')
        return None
    return int(history_tree.item(sel[0])['values'][0])

def view_old_bill(event=None):
    iid=selected_history_id()
    if iid is None:return
    inv=con.execute('SELECT i.number,i.created,COALESCE(c.name,"Walk-in Customer"),COALESCE(c.phone,""),i.subtotal,i.tax_total,i.total,i.paid FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id WHERE i.id=?',(iid,)).fetchone()
    if not inv:return messagebox.showerror('Missing record','Invoice record not found in database.')
    number,created,customer,phone,subtotal,tax,total,paid=inv
    win=tk.Toplevel(root);win.title(f'Old Bill Viewer | {number}');win.geometry('850x630');win.minsize(650,440)
    header=ttk.Frame(win,padding=14);header.pack(fill='x')
    ttk.Label(header,text=f'INVOICE {number}',font=('Segoe UI',17,'bold'),foreground=GREEN).pack(anchor='w')
    ttk.Label(header,text=f'Date: {created.replace("T"," ")}     Customer: {customer}     Phone: {phone}').pack(anchor='w',pady=6)
    area=ttk.Frame(win,padding=10);area.pack(fill='both',expand=True)
    columns=('Description','Qty','Rate','GST %','Amount')
    tr=ttk.Treeview(area,columns=columns,show='headings',height=9)
    for col,w in zip(columns,(290,95,110,90,125)):
        tr.heading(col,text=col);tr.column(col,width=w,anchor='w' if col=='Description' else 'e')
    tr.pack(fill='both',expand=True)
    for desc,qty,rate,gst,amount,unit in rows('''
        SELECT ii.description,ii.qty,ii.rate,ii.tax_rate,ii.line_total,
               COALESCE(p.unit, CASE WHEN ii.description='Packing Bag' THEN 'Nos' ELSE '' END)
        FROM invoice_items ii LEFT JOIN products p ON p.id=ii.product_id
        WHERE ii.invoice_id=? ORDER BY ii.id''',(iid,)):
        display_qty=f'{qty:g} {unit}'.strip()
        tr.insert('','end',values=(desc,display_qty,f'{rate:,.2f}',f'{gst:g}',f'{amount:,.2f}'))
    ttk.Label(win,text=f'Subtotal: {money(subtotal)}     Tax: {money(tax)}     TOTAL: {money(total)}     Received: {money(paid)}     Due: {money(total-paid)}',font=('Segoe UI',11,'bold')).pack(pady=9)
    controls=ttk.Frame(win,padding=10);controls.pack(fill='x')
    ttk.Button(controls,text='OPEN / VIEW PDF',command=lambda:open_old_bill_pdf(iid)).pack(side='left',padx=5)
    ttk.Button(controls,text='REGENERATE MISSING PDF',command=lambda:regenerate_old_bill_pdf(iid)).pack(side='left',padx=5)
    ttk.Button(controls,text='PRINT AGAIN',command=lambda:print_old_bill_pdf(iid)).pack(side='left',padx=5)
    ttk.Button(controls,text='Close',command=win.destroy).pack(side='right',padx=5)

def existing_or_rebuilt_pdf(iid):
    path=pdf_location(iid)
    if not path.is_file() or path.stat().st_size==0:
        path=save_invoice_pdf(iid)
    return path

def open_old_bill_pdf(iid=None):
    if iid is None:iid=selected_history_id()
    if iid is None:return
    try:open_pdf(existing_or_rebuilt_pdf(iid))
    except Exception as ex:messagebox.showerror('Open invoice PDF error',str(ex))

def regenerate_old_bill_pdf(iid=None):
    if iid is None:iid=selected_history_id()
    if iid is None:return
    try:
        path=pdf_location(iid)
        if path.is_file() and not messagebox.askyesno('Replace existing PDF',f'{path.name} already exists. Recreate it from saved bill records?'):
            return
        path=save_invoice_pdf(iid, force=True)
        if messagebox.askyesno('PDF recreated',f'Invoice PDF saved at:\n{path}\n\nOpen PDF now?'):
            open_pdf(path)
    except Exception as ex:messagebox.showerror('Recreate invoice PDF error',str(ex))

def print_old_bill_pdf(iid=None):
    if iid is None:iid=selected_history_id()
    if iid is None:return
    try:
        path=existing_or_rebuilt_pdf(iid)
        if messagebox.askyesno('Print old bill',f'Print {path.name} using the Windows default printer?\n\nFor another printer, open PDF and choose Print.'):
            print_pdf(path, iid)
    except Exception as ex:messagebox.showerror('Print old bill error',str(ex))

history_tree.bind('<Double-1>',view_old_bill)
ttk.Button(history_actions,text='VIEW OLD BILL',command=view_old_bill).pack(side='left',padx=4)
ttk.Button(history_actions,text='RECREATE PDF',command=regenerate_old_bill_pdf).pack(side='left',padx=4)
ttk.Button(history_actions,text='PRINT AGAIN',command=print_old_bill_pdf).pack(side='left',padx=4)
ttk.Button(history_actions,text='DELETE BILL (30-DAY RECYCLE)',command=lambda:delete_history_invoice()).pack(side='left',padx=4)

def print_selected():
    sel=history_tree.selection()
    if sel:print_invoice(int(history_tree.item(sel[0])['values'][0]))
    else:messagebox.showinfo('Select invoice','Select an invoice from the history table')
ttk.Button(f,text='Open PDF (selected invoice)',command=lambda:open_selected_pdf()).pack(side='right',padx=8,pady=5)
ttk.Button(f,text='PRINT (default printer)',command=lambda:print_selected_pdf()).pack(side='right',padx=8,pady=5)

# Consistent customer account calculations: invoice receipts plus standalone account receipts.
def customer_balance(cid):
    sale,paid=con.execute('SELECT COALESCE(SUM(total),0),COALESCE(SUM(paid),0) FROM invoices WHERE customer_id=?',(cid,)).fetchone()
    account=con.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE customer_id=?',(cid,)).fetchone()[0]
    return round(sale-paid-account+opening_amount(cid),2)

def customer_account_totals():
    return rows('''SELECT c.name,COALESCE(c.phone,''),
       COALESCE((SELECT SUM(total) FROM invoices WHERE customer_id=c.id),0) AS sales,
       COALESCE((SELECT SUM(paid) FROM invoices WHERE customer_id=c.id),0)+
       COALESCE((SELECT SUM(amount) FROM customer_payments WHERE customer_id=c.id),0) AS received,
       COALESCE((SELECT SUM(total-paid) FROM invoices WHERE customer_id=c.id),0)-
       COALESCE((SELECT SUM(amount) FROM customer_payments WHERE customer_id=c.id),0)
       + COALESCE((SELECT amount FROM customer_opening_balances WHERE customer_id=c.id),0) AS balance
       FROM customers c ORDER BY balance DESC, c.name''')

# Private management profitability analysis: estimated COGS at current product cost.
# Historical unit costs were not stored on invoice items in earlier versions.
pl_tab=add_scrollable_page('Profit & Loss')
pl_page=tab_pages['Profit & Loss']
r,c=divmod(len(tabs)-1,5)
nav.grid_columnconfigure(c,weight=1)
pl_nav_button=tk.Button(nav,text='Profit & Loss (Internal)',command=lambda:nb.select(pl_page),
          font=('Segoe UI',9,'bold'),bg='#E8EFEA',fg=DARK,
          padx=5,pady=6,wraplength=175)
pl_nav_button.grid(row=r,column=c,sticky='nsew',padx=2,pady=2)
nav_buttons['Profit & Loss']=pl_nav_button

def highlight_active_tab(event=None):
    current=nb.select()
    for label,button in nav_buttons.items():
        active=current==str(tab_pages[label])
        button.configure(bg=GREEN if active else '#E8EFEA',
                         fg='#FFFFFF' if active else DARK,
                         activebackground=GREEN if active else '#CDE7D7',
                         activeforeground='#FFFFFF' if active else DARK,
                         relief='solid' if active else 'groove',
                         bd=2 if active else 1,
                         highlightbackground=GOLD if active else '#E8EFEA')
nb.bind('<<NotebookTabChanged>>',highlight_active_tab)
root.after_idle(highlight_active_tab)
ttk.Label(pl_tab,text='Profit & Loss — INTERNAL MANAGEMENT ONLY',
          font=('Segoe UI',17,'bold'),foreground=GREEN).pack(anchor='w',padx=15,pady=(12,6))
ttk.Label(pl_tab,text='Estimated profit uses current product cost; older invoice item costs were not saved. This is NOT audited historical profit.',
          wraplength=1000).pack(anchor='w',padx=15,pady=5)
pl_filters=ttk.Frame(pl_tab,padding=8);pl_filters.pack(fill='x')
ttk.Label(pl_filters,text='From YYYY-MM-DD').pack(side='left')
pl_from=ttk.Entry(pl_filters,width=13);pl_from.pack(side='left',padx=7)
ttk.Label(pl_filters,text='To YYYY-MM-DD').pack(side='left')
pl_to=ttk.Entry(pl_filters,width=13);pl_to.pack(side='left',padx=7)
pl_summary=ttk.Label(pl_tab,text='',font=('Segoe UI',12,'bold'),justify='left')
pl_summary.pack(anchor='w',padx=18,pady=12)
pl_tree=table(pl_tab,('Product','Sales','Estimated Cost','Estimated Gross Profit'))
def refresh_profit_loss():
    try:
        start=pl_from.get().strip();end=pl_to.get().strip()
        for v in (start,end):
            if v:datetime.strptime(v,'%Y-%m-%d')
        if start and end and start>end:raise ValueError('From date must not exceed To date')
    except ValueError as ex:
        return messagebox.showerror('Date error',str(ex))
    conditions=[];params=[]
    if start:conditions.append('substr(i.created,1,10)>=?');params.append(start)
    if end:conditions.append('substr(i.created,1,10)<=?');params.append(end)
    where=(' WHERE '+' AND '.join(conditions)) if conditions else ''
    data=rows("""SELECT ii.description, SUM(ii.line_total),
        SUM(ii.qty*COALESCE(p.cost,0))
        FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
        LEFT JOIN products p ON p.id=ii.product_id""" + where +
        ' GROUP BY ii.description ORDER BY SUM(ii.line_total) DESC',tuple(params))
    fill(pl_tree,[(n,money(s),money(c),money(s-c)) for n,s,c in data])
    revenue=sum(x[1] for x in data);cogs=sum(x[2] for x in data)
    ex_conditions=[];ex_params=[]
    if start:ex_conditions.append('substr(created,1,10)>=?');ex_params.append(start)
    if end:ex_conditions.append('substr(created,1,10)<=?');ex_params.append(end)
    ex_where=(' WHERE '+' AND '.join(ex_conditions)) if ex_conditions else ''
    expenses=con.execute('SELECT COALESCE(SUM(amount),0) FROM expenses'+ex_where,tuple(ex_params)).fetchone()[0]
    pl_summary.config(text=f'Sales Revenue: {money(revenue)}     Estimated Cost of Goods Sold: {money(cogs)}\n'
        f'Estimated Gross Profit: {money(revenue-cogs)}     Recorded Expenses: {money(expenses)}\n'
        f'Estimated Net Profit / Loss: {money(revenue-cogs-expenses)}')
ttk.Button(pl_filters,text='View Profit & Loss',command=refresh_profit_loss).pack(side='left',padx=10)

# Reports
f=tabs['Reports & Backup'];summary=ttk.Label(f,text='',font=('Segoe UI',13),justify='left');summary.pack(anchor='w',padx=20,pady=16)
reports_ledger_tree=table(f,('Customer','Phone','Total Sales','Total Paid','Balance'))
def refresh_reports():
    sales=con.execute('SELECT COALESCE(SUM(total),0),COALESCE(SUM(paid),0),COALESCE(SUM(total-paid),0) FROM invoices').fetchone()
    account_received=con.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments').fetchone()[0]
    expenses=con.execute('SELECT COALESCE(SUM(amount),0) FROM expenses').fetchone()[0]
    summary.config(text=f'Total Sales: {money(sales[0])}     Received: {money(sales[1]+account_received)}     Outstanding: {money(sales[2]-account_received)}\nRecorded Expenses: {money(expenses)}     (Profit requires full cost and expense tracking)')
    data=customer_account_totals()
    fill(reports_ledger_tree,[(n,p,money(s),money(paid),money(due)) for n,p,s,paid,due in data])
actions=ttk.Frame(f,padding=8);actions.pack(fill='x')
def export_csv():
    path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='ASCT_customer_ledger.csv')
    if not path:return
    with open(path,'w',newline='',encoding='utf-8-sig') as out:
        w=csv.writer(out);w.writerow(['Customer','Phone','Total Sales','Total Paid','Balance'])
        w.writerows(customer_account_totals())
    messagebox.showinfo('Export complete',path)
def backup():
    path=filedialog.asksaveasfilename(defaultextension='.db',initialfile='ASCT_backup_'+datetime.now().strftime('%Y%m%d_%H%M')+'.db',filetypes=[('Database','*.db')])
    if path:
        dest=sqlite3.connect(path)
        try:con.backup(dest)
        finally:dest.close()
        messagebox.showinfo('Backup saved',path)
def add_expense():
    win=tk.Toplevel(root);win.title('Add Expense');win.geometry('400x170');desc=entry(win,'Description',0);amt=entry(win,'Amount ₹',1)
    def save():
        try:
            if not desc.get().strip():raise ValueError('Description required')
            with con:con.execute('INSERT INTO expenses(created,description,amount) VALUES(?,?,?)',(datetime.now().isoformat(timespec='seconds'),desc.get().strip(),num(amt.get())))
            win.destroy();refresh_reports()
        except ValueError as ex:messagebox.showerror('Error',str(ex))
    ttk.Button(win,text='Save Expense',command=save).grid(row=2,column=1,pady=12)
for name,func in [('Export Customer Ledger CSV',export_csv),('Backup Database',backup),('Add Expense',add_expense)]:ttk.Button(actions,text=name,command=func).pack(side='left',padx=8)

# Editable shop identity; saved locally in the billing database.
f=tabs['Shop Settings']
ttk.Label(f,text='Shop details shown at the top of every printed bill',font=('Segoe UI',13,'bold')).pack(anchor='w',padx=15,pady=12)
settings_frame=ttk.Frame(f,padding=12);settings_frame.pack(fill='x')
settings_inputs={}
for idx,(key,label) in enumerate([('shop_name','Shop name'),('phone','Phone numbers'),('address','Full shop address / PIN'),('email','Business email'),('website','Website'),('gstin','Business GSTIN (optional)'),('logo_path','Logo PNG file')]):
    e=entry(settings_frame,label,idx,width=65);e.insert(0,setting(key));settings_inputs[key]=e

def choose_logo():
    path=filedialog.askopenfilename(title='Choose shop logo',filetypes=[('PNG image','*.png')])
    if path:settings_inputs['logo_path'].delete(0,'end');settings_inputs['logo_path'].insert(0,path)
def save_settings():
    with con:
        for k,e in settings_inputs.items():con.execute('INSERT OR REPLACE INTO business_settings(key,value) VALUES(?,?)',(k,e.get().strip()))
    messagebox.showinfo('Saved','Shop details saved. New invoice prints will use these details.')
ttk.Button(settings_frame,text='Browse Logo',command=choose_logo).grid(row=6,column=2,padx=8)
ttk.Button(f,text='Save Shop Settings',command=save_settings).pack(anchor='w',padx=15,pady=12)
ttk.Label(f,text='GSTIN can be left blank. PDF automatically saves under AppData\\Local\\AS_Coconut_Traders\\Customer_Bills\\CustomerName_ID.\nUse Payments & History to open or print invoices. Existing saved bills are not modified.',justify='left').pack(anchor='w',padx=15)

def safe_folder(name):
    # Customer name is display-only; prevent path traversal and invalid Windows characters.
    cleaned=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_',name).strip(' .')
    return (cleaned[:65] or 'Walk-in Customer')

def pdf_location(iid):
    inv=con.execute('SELECT i.number,COALESCE(c.name,"Walk-in Customer"),COALESCE(c.id,0) FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id WHERE i.id=?',(iid,)).fetchone()
    if not inv:raise ValueError('Invoice not found')
    number,name,cid=inv
    folder=DATA/'Customer_Bills'/f'{safe_folder(name)}_{cid}'
    folder.mkdir(parents=True,exist_ok=True)
    return folder/(number.replace('/','_')+'.pdf')

def draw_invoice_watermark(canvas, doc):
    """Diagonal full-page AS COCONUT TRADERS watermark on every PDF page."""
    canvas.saveState()
    page_w,page_h=doc.pagesize
    canvas.translate(page_w/2,page_h/2)
    canvas.rotate(43)
    # Keep the watermark pale even in PDF viewers/printers that ignore alpha.
    # Important: setFillColor must precede setFillAlpha, because some
    # ReportLab versions reset alpha when setting a new fill colour.
    canvas.setFillColor(colors.HexColor('#D8E8DF'))
    try:
        canvas.setFillAlpha(0.30)
    except (AttributeError, TypeError):
        # Already a very light green if transparency is unsupported.
        pass
    canvas.setFont('Helvetica-Bold',43)
    canvas.drawCentredString(0,0,'AS COCONUT TRADERS')
    canvas.restoreState()

def invoice_items_with_units(iid):
    """Resolve the product unit for each saved invoice line, including old bills.

    A missing/deleted product retains a readable fallback rather than breaking
    reprints. This function does not modify invoice or stock data.
    """
    result=[]
    for desc,qty,rate,tax,amount,unit in rows("""SELECT ii.description,ii.qty,ii.rate,ii.tax_rate,ii.line_total,p.unit
        FROM invoice_items ii LEFT JOIN products p ON p.id=ii.product_id
        WHERE ii.invoice_id=? ORDER BY ii.id""",(iid,)):
        if not unit:
            name=str(desc).strip().lower()
            unit='Nos' if 'bag' in name else 'Kg' if 'coconut' in name or 'copra' in name else 'Nos'
        result.append((desc,qty,rate,tax,amount,str(unit).strip()))
    return result

def receipt_data(iid):
    """Single accounting snapshot shared by the PDF receipt and WhatsApp image."""
    inv=con.execute('SELECT i.number,i.created,COALESCE(c.name,"Walk-in Customer"),COALESCE(c.phone,""),COALESCE(c.address,""),i.subtotal,i.tax_total,i.total,i.paid,i.opening_due,i.opening_advance FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id WHERE i.id=?',(iid,)).fetchone()
    if not inv: raise ValueError('Invoice not found')
    number,created,name,phone,address,sub,tax,total,paid,opening_due,opening_advance=inv
    items=invoice_items_with_units(iid)
    extra=con.execute("SELECT COALESCE(SUM(cp.amount),0) FROM customer_payments cp JOIN invoices i ON i.customer_id=cp.customer_id WHERE i.id=? AND cp.reference=?",(iid,'Advance received with '+number)).fetchone()[0] or 0
    first=con.execute('SELECT amount FROM payments WHERE invoice_id=? ORDER BY id LIMIT 1',(iid,)).fetchone()
    first_paid=float(first[0]) if first else 0.0
    net=round(float(opening_due)+float(total)-float(opening_advance)-float(paid)-float(extra),2)
    amounts=[("TODAY'S PURCHASE AMOUNT",float(total))]
    if opening_due>0.005:amounts.append(('PREVIOUS PENDING AMOUNT (+)',float(opening_due)))
    if opening_advance>0.005:amounts.append(('PREVIOUS ADVANCE AMOUNT (-)',-float(opening_advance)))
    if first_paid+float(extra)>0.005:amounts.append(('AMOUNT PAID NOW (-)',-(first_paid+float(extra))))
    if paid-first_paid>0.005:amounts.append(('LATER PAYMENT RECEIVED (-)',-(float(paid)-first_paid)))
    amounts.append(('TOTAL PENDING AMOUNT TO PAY' if net>=-0.005 else 'AVAILABLE ADVANCE BALANCE',abs(net)))
    return dict(number=number,created=created,name=name,phone=phone,address=address,items=items,amounts=amounts,subtotal=float(sub),tax=float(tax),total=float(total))

def receipt_lines(iid):
    """Semantic lines; the printer and PNG use identical values."""
    d=receipt_data(iid)
    lines=[('shop',setting('shop_name') or 'AS COCONUT TRADERS'),('center',setting('phone')),('center',setting('website')),('rule',''),('heading','SALES BILL'),('text','Bill: '+d['number']),('text','Date: '+d['created'][:16].replace('T',' ')),('text','Customer: '+d['name'])]
    if d['phone']:lines.append(('text','Phone: '+d['phone']))
    if d['address']:lines.append(('text','Address: '+d['address']))
    lines += [('rule',''),('columns','ITEM                 QTY      AMOUNT')]
    for desc,qty,rate,tax,amount,unit in d['items']:
        lines.append(('item',str(desc)))
        lines.append(('itemdetail',f'{qty:g} {unit} x {rate:,.2f}'+(f'  GST {tax:g}%' if tax else '')+'     '+f'{amount:,.2f}'))
    lines.append(('rule',''))
    for index,(label,value) in enumerate(d['amounts']):
        lines.append(('total' if index==len(d['amounts'])-1 else 'amount',(label,value)))
    lines += [('rule',''),('footer','THANK YOU FOR YOUR BUSINESS!'),('center','Please keep this receipt')]
    return lines

def receipt_logo():
    logo=Path(setting('logo_path')) if setting('logo_path') else BASE_DIR/'AS_Coconut_Traders_Logo.png'
    return logo if logo.is_file() else BASE_DIR/'AS_Coconut_Traders_Logo.png'

def receipt_pdf_render(iid, output, monochrome=False):
    """True vector text and rules; colour archive / monochrome thermal print."""
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    import textwrap
    d=receipt_data(iid)
    w=80*mm; margin=4.3*mm; usable=w-2*margin
    green=black if monochrome else HexColor('#06462E')
    gold=black if monochrome else HexColor('#C89C27')
    pale=white if monochrome else HexColor('#F0F6ED')
    font='Helvetica'; bold='Helvetica-Bold'
    for candidate in ('C:/Windows/Fonts/arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if Path(candidate).exists():
            try:
                pdfmetrics.registerFont(TTFont('ASBodyV50',candidate));font='ASBodyV50';break
            except Exception:pass
    for candidate in ('C:/Windows/Fonts/arialbd.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
        if Path(candidate).exists():
            try:
                pdfmetrics.registerFont(TTFont('ASBoldV50',candidate));bold='ASBoldV50';break
            except Exception:pass
    def wrapped(txt, maxwidth, fontname, fontsize):
        words=str(txt).split();lines=[];line=''
        for word in words:
            trial=(line+' '+word).strip()
            if pdfmetrics.stringWidth(trial,fontname,fontsize)<=maxwidth:line=trial
            else:
                if line:lines.append(line)
                line=word
                while pdfmetrics.stringWidth(line,fontname,fontsize)>maxwidth and len(line)>1:
                    part=line[:-1];lines.append(part);line=line[-1]
        if line:lines.append(line)
        return lines or ['']
    # Calculate required paper height before constructing the single-page PDF.
    addr=wrapped(setting('address') or '',usable,font,6.1) if setting('address') else []
    details=[('Bill No',d['number']),('Date',d['created'][:16].replace('T',' ')),('Customer',d['name'])]
    if d['phone']:details.append(('Mobile',d['phone']))
    if d['address']:details.append(('Address',d['address']))
    details_lines=[(k,wrapped(v,usable-27*mm,font,7)) for k,v in details]
    item_lines=[wrapped(it[0],usable-41*mm,font,6.7) for it in d['items']]
    summary_lines=[wrapped(label,usable-28*mm,bold if j==len(d['amounts'])-1 else font,6.4) for j,(label,_) in enumerate(d['amounts'])]
    h=(109*mm+len(addr)*8+sum(max(11,len(v)*9) for _,v in details_lines)
       +sum(max(34,len(wrapped(it[0],usable-18*mm,font,7))*10+20) for it in d['items'])
       +sum(max(15,len(v)*9+5) for v in summary_lines))
    h=max(h,120*mm)
    c=pdfcanvas.Canvas(str(output),pagesize=(w,h),pageCompression=1)
    c.setTitle('AS Coconut Traders - '+d['number'])
    y=h-5*mm
    def centered(txt,size=8,fontname=None,color=None):
        nonlocal y
        c.setFillColor(color or black);c.setFont(fontname or font,size)
        c.drawCentredString(w/2,y,str(txt));y-=size+5
    def rule():
        nonlocal y
        c.setStrokeColor(gold);c.setLineWidth(.7);c.line(margin,y,w-margin,y);y-=10
    logo=receipt_logo()
    if logo.is_file():
        try:
            with Image.open(logo) as im:
                iw,ih=im.size
            lw=min(31*mm,usable);lh=lw*ih/iw
            if lh>16*mm:lh=16*mm;lw=lh*iw/ih
            c.drawImage(ImageReader(str(logo)),(w-lw)/2,y-lh,width=lw,height=lh,mask='auto')
            y-=lh+9
        except Exception:pass
    centered('AS COCONUT TRADERS',10,bold,green)
    centered('COCONUT PURCHASE - SALES - WHOLESALE',5.5,font,green)
    centered(setting('phone') or '9361866945 / 7418989798',7,bold)
    centered(setting('website') or 'ascoconuttraders.in',6)
    for line in addr:centered(line,6.1)
    y-=3;rule()
    c.setFillColor(green);c.roundRect(margin+17*mm,y-2,usable-34*mm,16,3,stroke=0,fill=1)
    c.setFillColor(white);c.setFont(bold,10);c.drawCentredString(w/2,y+3,'SALES BILL');y-=15
    for label,lines in details_lines:
        c.setFont(bold,7);c.setFillColor(green);c.drawString(margin+2,y,label)
        c.setFont(font,7);c.setFillColor(black)
        for j,line in enumerate(lines):c.drawString(margin+29*mm,y-j*9,line)
        y-=max(11,len(lines)*9)
    y-=5
    c.setFillColor(green);c.roundRect(margin,y-5,usable,16,2,stroke=0,fill=1)
    c.setFillColor(white);c.setFont(bold,7)
    c.drawString(margin+3,y+1,'No');c.drawString(margin+15,y+1,'Particulars')
    y-=18
    for idx,item in enumerate(d['items'],1):
        desc,qty,rate,tax,amount,unit=item
        lines=wrapped(desc,usable-18*mm,font,7)
        c.setFillColor(black);c.setFont(font,7)
        c.drawString(margin+3,y,str(idx))
        for j,line in enumerate(lines):c.drawString(margin+13,y-j*10,line)
        y-=len(lines)*10+3
        # Numeric values are in an independent row, each within its own cell.
        cols=[(margin+2*mm,margin+24*mm,'Qty: '+f'{qty:g} {unit}'),
              (margin+25*mm,margin+46*mm,'Rate: '+f'{rate:,.2f}'),
              (margin+47*mm,w-margin-2,'Amt: '+f'{amount:,.2f}')]
        for left,right_edge,value in cols:
            sz=6.5
            while pdfmetrics.stringWidth(value,font,sz)>right_edge-left and sz>4.0:sz-=.25
            if pdfmetrics.stringWidth(value,font,sz)>right_edge-left:
                value=value.replace(': ',':')
            c.setFont(font,sz);c.drawRightString(right_edge,y,value)
        y-=17
        c.setStrokeColor(HexColor('#D6DDD6') if not monochrome else black);c.setLineWidth(.3)
        c.line(margin,y+6,w-margin,y+6)
    y-=6
    for idx,((label,value),lines) in enumerate(zip(d['amounts'],summary_lines)):
        last=idx==len(d['amounts'])-1
        rowheight=max(15,len(lines)*9+5)
        if last:
            c.setFillColor(green);c.roundRect(margin,y-rowheight+7,usable,rowheight+2,2,fill=1,stroke=0)
        elif idx%2==0:
            c.setFillColor(pale);c.roundRect(margin,y-rowheight+7,usable,rowheight+2,2,fill=1,stroke=0)
        c.setFillColor(white if last else black)
        c.setFont(bold if last else font,6.4)
        for j,line in enumerate(lines):c.drawString(margin+3,y-j*9,line)
        c.setFont(bold if last else font,7.0)
        c.drawRightString(w-margin-3,y,('Rs. ' if value>=0 else '- Rs. ')+f'{abs(value):,.2f}')
        y-=rowheight
    y-=8;rule()
    centered('CUSTOMER ACCOUNT SUMMARY',8,bold,green)
    last_label,last_amt=d['amounts'][-1]
    pending=last_amt if last_label!='AVAILABLE ADVANCE BALANCE' else 0
    advance=last_amt if last_label=='AVAILABLE ADVANCE BALANCE' else 0
    for label,amount in [('Pending Amount to Pay',pending),('Available Advance Amount',advance)]:
        c.setFillColor(green);c.setFont(bold,6.7);c.drawString(margin+2,y,label)
        c.setFillColor(black);c.setFont(font,6.7);c.drawRightString(w-margin-2,y,'Rs. '+f'{amount:,.2f}');y-=12
    y-=4;rule()
    centered('Thank you for your Business!',9,bold,green)
    centered('AS COCONUT TRADERS',7,bold,gold)
    c.save()

def save_invoice_pdf(iid, force=False):
    path=pdf_location(iid)
    if path.is_file() and path.stat().st_size>0 and not force:return path
    fd,tmp=tempfile.mkstemp(prefix='thermal_bill_',suffix='.pdf',dir=str(path.parent));os.close(fd)
    temp_path=Path(tmp)
    try:
        receipt_pdf_render(iid,temp_path)
        try:os.replace(str(temp_path),str(path));return path
        except PermissionError:
            alt=path.with_name(path.stem+'_updated_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.pdf')
            os.replace(str(temp_path),str(alt));return alt
    finally:
        if temp_path.exists():temp_path.unlink()

def premium_bill_image(iid):
    """Premium green/gold receipt. PDF uses the same layout in monochrome."""
    from PIL import Image, ImageDraw, ImageFont
    import textwrap
    d=receipt_data(iid)
    W=900; pad=46; green='#06462E'; gold='#C89C27'; pale='#F0F6ED';ink='#18231C'
    def ft(size,bold=False):
        choices=['C:/Windows/Fonts/arialbd.ttf' if bold else 'C:/Windows/Fonts/arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
        for name in choices:
            try:return ImageFont.truetype(name,size)
            except OSError:pass
        return ImageFont.load_default()
    fsm=ft(22);f=ft(25);fb=ft(26,True);fh=ft(40,True);ftitle=ft(47,True)
    items=d['items'];extra_lines=sum(max(1,(len(str(it[0]))+32)//33) for it in items)
    H=1700+extra_lines*65+len(d['amounts'])*62
    im=Image.new('RGB',(W,H),'white');dr=ImageDraw.Draw(im)
    y=28
    def center(t,y,font,color=ink):
        b=dr.textbbox((0,0),str(t),font=font);dr.text(((W-(b[2]-b[0]))/2,y),str(t),font=font,fill=color)
    def rule(y):dr.line((pad,y,W-pad,y),fill=gold,width=3)
    # subtle premium double border, no background art that would spoil thermal printing
    dr.rounded_rectangle((16,12,W-17,H-15),radius=16,outline=gold,width=4)
    logo=receipt_logo()
    if logo.is_file():
        try:
            l=Image.open(logo).convert('RGBA');l.thumbnail((370,165))
            im.paste(l,((W-l.width)//2,y),l);y+=l.height+12
        except Exception:pass
    center('AS COCONUT TRADERS',y,ftitle,green);y+=62
    center('COCONUT PURCHASE  •  SALES  •  WHOLESALE',y,fsm,green);y+=45
    center(setting('phone') or '9361866945 / 7418989798',y,fb);y+=39
    center(setting('website') or 'ascoconuttraders.in',y,fsm);y+=39
    addr=setting('address') or ''
    if addr:
        for part in textwrap.wrap(addr,width=57)[:3]:center(part,y,fsm);y+=32
    y+=10;rule(y);y+=20
    dr.rounded_rectangle((255,y,645,y+62),radius=13,fill=green,outline=gold,width=4)
    center('SALES BILL',y+7,fh,'white');y+=85
    def detail(label,value):
        nonlocal y
        dr.text((pad+12,y),label,font=fb,fill=green)
        val=str(value)
        for j,line in enumerate(textwrap.wrap(val,width=47) or ['']):
            dr.text((225,y+j*34),line,font=f,fill=ink)
        y+=max(43,34*len(textwrap.wrap(val,width=47)))
    detail('Bill No',d['number'])
    detail('Date',d['created'][:16].replace('T',' '))
    detail('Customer',d['name'])
    if d['phone']:detail('Mobile',d['phone'])
    if d['address']:detail('Address',d['address'])
    y+=8
    # Compact receipt: keep item name and numeric values on separate lines.
    # This prevents collision even for long names and seven-digit amounts.
    dr.rounded_rectangle((pad,y,W-pad,y+53),radius=9,fill=green)
    dr.text((pad+15,y+10),'S.No',font=fb,fill='white')
    dr.text((pad+110,y+10),'Particulars',font=fb,fill='white')
    y+=65
    def right(t,x,yy,font,color=ink):
        b=dr.textbbox((0,0),str(t),font=font)
        dr.text((x-(b[2]-b[0]),yy),str(t),font=font,fill=color)
    for ix,(desc,qty,rate,tax,amt,unit) in enumerate(items,1):
        # Product description occupies its own full-width row.
        name_font=f
        max_name_width=W-pad-18-(pad+110)
        words=str(desc).split()
        parts=[];line=''
        for word in words:
            trial=(line+' '+word).strip()
            if dr.textbbox((0,0),trial,font=name_font)[2]<=max_name_width:
                line=trial
            else:
                if line:parts.append(line)
                line=word
        if line:parts.append(line)
        if not parts:parts=['']
        dr.text((pad+18,y),str(ix),font=f,fill=ink)
        for j,line in enumerate(parts):
            dr.text((pad+110,y+j*34),line,font=name_font,fill=ink)
        y+=len(parts)*34+8
        # Dedicated quantity/rate/amount row with non-overlapping columns.
        col_edges=(pad+260,pad+470,W-pad-10)
        col_lefts=(pad+112,pad+272,pad+490)
        values=(f'Qty: {qty:g} {unit}',f'Rate: {rate:,.2f}',f'Amount: {amt:,.2f}')
        for value,left,edge in zip(values,col_lefts,col_edges):
            vf=fsm
            while dr.textbbox((0,0),value,font=vf)[2] > edge-left and vf.size>12:
                vf=ft(vf.size-1)
            # Long values wrap within their own allocated column.
            if dr.textbbox((0,0),value,font=vf)[2]>edge-left:
                value=value.replace(': ',':\n')
            for line_no,segment in enumerate(value.split('\n')):
                right(segment,edge,y+line_no*25,vf)
        y+=63
        dr.line((pad,y-8,W-pad,y-8),fill='#D4DED3',width=2)
    y+=19
    for ix,(label,amount) in enumerate(d['amounts']):
        final=ix==len(d['amounts'])-1
        if final:
            dr.rounded_rectangle((pad,y-9,W-pad,y+54),radius=11,fill=green,outline=gold,width=3)
        elif ix%2==0:dr.rounded_rectangle((pad,y-5,W-pad,y+43),radius=7,fill=pale)
        color='white' if final else ink
        label_text=label.title() if not final else label
        label_font=fb if final else f
        max_label_width=495 if final else 535
        while dr.textbbox((0,0),label_text,font=label_font)[2]>max_label_width and label_font.size>15:
            label_font=ft(label_font.size-1,final)
        dr.text((pad+13,y+3),label_text,font=label_font,fill=color)
        right('Rs. '+f'{amount:,.2f}',W-pad-12,y+3,fb if final else f,color)
        y+=62 if final else 52
    y+=24;rule(y);y+=23
    center('CUSTOMER ACCOUNT SUMMARY',y,fb,green);y+=47
    last_label,last_amt=d['amounts'][-1]
    # Keep summary amounts in a dedicated right-aligned column.
    # The general invoice metadata detail() starts values at x=225 and
    # must NOT be reused here: long labels/large amounts collide.
    def account_summary_row(label, amount):
        nonlocal y
        label_x = pad + 15
        amount_right = W - pad - 18
        amount_text = 'Rs. '+f'{amount:,.2f}'
        label_font = fb
        amount_font = fb
        # Reserve a visible gutter between independently sized columns.
        available_width = W - 2*pad - 44
        label_width = int(available_width * 0.58)
        amount_width = available_width - label_width
        while (dr.textbbox((0,0),label,font=label_font)[2] > label_width
               and label_font.size > 16):
            label_font = ft(label_font.size-1,True)
        while (dr.textbbox((0,0),amount_text,font=amount_font)[2] > amount_width
               and amount_font.size > 16):
            amount_font = ft(amount_font.size-1,True)
        dr.rounded_rectangle((pad,y-7,W-pad,y+48),radius=7,fill=pale)
        dr.text((label_x,y+6),label,font=label_font,fill=green)
        right(amount_text,amount_right,y+6,amount_font,ink)
        y+=68
    if last_label=='AVAILABLE ADVANCE BALANCE':
        account_summary_row('Available Advance',last_amt)
        account_summary_row('Pending To Pay',0)
    else:
        account_summary_row('Pending To Pay',last_amt)
        account_summary_row('Available Advance',0)
    y+=14;rule(y);y+=25
    center('Thank you for your Business!',y,fh,green);y+=65
    center('AS COCONUT TRADERS',y,fb,gold);y+=55
    # crop without leaving large empty receipt tail
    return im.crop((0,0,W,min(H,y+32)))

def whatsapp_bill_image(iid):
    """Temporary colour PNG; permanent invoice archive remains PDF only."""
    im=premium_bill_image(iid)
    out=Path(tempfile.gettempdir())/'AS_Coconut_Traders_WhatsApp'
    out.mkdir(parents=True,exist_ok=True)
    path=out/(receipt_data(iid)['number'].replace('/','_')+'.png')
    im.save(path,format='PNG',optimize=True)
    return path

def open_pdf(path):
    if os.name=='nt':os.startfile(str(path))
    else:webbrowser.open(path.as_uri())

def print_pdf(path, iid=None):
    """Native vector black-and-white 80mm print, without altering colour PDF."""
    if os.name!='nt':raise RuntimeError('Direct printing is supported on Windows only')
    if iid is None:raise ValueError('Invoice ID required for thermal print')
    out=Path(tempfile.gettempdir())/'AS_Coconut_Traders_Thermal_Print'
    out.mkdir(parents=True,exist_ok=True)
    target=out/(receipt_data(iid)['number'].replace('/','_')+'_BW_'+datetime.now().strftime('%Y%m%d%H%M%S%f')+'.pdf')
    receipt_pdf_render(iid,target,monochrome=True)
    os.startfile(str(target),'print')

def open_selected_pdf():
    sel=history_tree.selection()
    if not sel:return messagebox.showinfo('Select invoice','Select invoice from history')
    iid=int(history_tree.item(sel[0])['values'][0])
    try:open_pdf(existing_or_rebuilt_pdf(iid))
    except Exception as ex:messagebox.showerror('PDF error',str(ex))

def print_selected_pdf():
    sel=history_tree.selection()
    if not sel:return messagebox.showinfo('Select invoice','Select invoice from history')
    iid=int(history_tree.item(sel[0])['values'][0])
    try:
        path=existing_or_rebuilt_pdf(iid)
        if messagebox.askyesno('Print bill',f'Send {path.name} to your Windows default printer?\n\nTo select another printer, choose Open PDF instead and print from the viewer.'):
            print_pdf(path, iid)
    except Exception as ex:messagebox.showerror('Print error',str(ex))

def print_invoice(iid):
    inv=con.execute('SELECT i.number,i.created,COALESCE(c.name,"Walk-in Customer"),COALESCE(c.phone,""),COALESCE(c.address,""),COALESCE(c.gstin,""),i.subtotal,i.tax_total,i.total,i.paid FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id WHERE i.id=?',(iid,)).fetchone()
    if not inv:return
    number,date,name,phone,address,gstin,sub,tax,total,paid=inv
    items=invoice_items_with_units(iid)
    trs=''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in (n,f'{q:g} {unit}',f'{r:.2f}',f'{t:.2f}%',f'{a:.2f}'))+'</tr>' for n,q,r,t,a,unit in items)
    logo=Path(setting('logo_path'))
    logo_html=''
    if logo.is_file() and logo.suffix.lower()=='.png':
        logo_html='<img class="logo" alt="Shop logo" src="data:image/png;base64,'+base64.b64encode(logo.read_bytes()).decode('ascii')+'">'
    shop=html.escape(setting('shop_name'))
    shop_phone=html.escape(setting('phone'))
    shop_address=html.escape(setting('address')).replace('\n','<br>')
    shop_site=html.escape(setting('website'))
    shop_email=html.escape(setting('email'))
    shop_gstin=html.escape(setting('gstin'))
    gst_line=f'<div><b>GSTIN:</b> {shop_gstin}</div>' if shop_gstin else ''
    tax_note='Tax classification and invoice compliance must be verified before statutory use.'
    doc=f'''<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(number)}</title>
    <style>@page{{size:A4;margin:14mm}}body{{font-family:Arial,sans-serif;max-width:850px;margin:22px auto;color:#24312b;font-size:13px}}.head{{display:flex;align-items:center;gap:18px;border-bottom:3px solid #b89136;padding-bottom:15px}}.logo{{width:135px;max-height:105px;object-fit:contain}}h1{{color:#17613b;margin:0 0 6px;font-size:25px}}.info{{line-height:1.6}}h2{{text-align:center;font-size:17px;margin:20px 0}}table{{width:100%;border-collapse:collapse;margin-top:15px}}td,th{{border:1px solid #aaa;padding:9px;text-align:left}}th{{background:#e8f3ec}}.right{{text-align:right}}.footer{{border-top:1px solid #ddd;margin-top:32px;padding-top:12px}}button{{padding:10px 16px}}body::before{{content:"AS COCONUT TRADERS";position:fixed;top:46%;left:50%;transform:translate(-50%,-50%) rotate(-43deg);font-size:54px;font-weight:bold;color:rgba(11,101,69,.10);white-space:nowrap;pointer-events:none;z-index:-1}}@media print{{button{{display:none}}body{{margin:0}}}}</style></head><body>
    <div class="head">{logo_html}<div class="info"><h1>{shop}</h1><div>{shop_address}</div><div><b>Phone:</b> {shop_phone}</div><div><b>Email:</b> {shop_email}</div><div><b>Website:</b> {shop_site}</div>{gst_line}</div></div>
    <h2>SALES BILL</h2><p><b>Invoice:</b> {html.escape(number)}<br><b>Date:</b> {html.escape(date[:19].replace('T',' '))}<br><b>Customer:</b> {html.escape(name)}<br><b>Phone:</b> {html.escape(phone)}<br><b>Address:</b> {html.escape(address)}<br><b>Customer GSTIN:</b> {html.escape(gstin)}</p>
    <table><tr><th>Item</th><th>Qty</th><th>Rate (INR)</th><th>Tax</th><th>Total (INR)</th></tr>{trs}</table>
    <p class="right">Subtotal: INR {sub:,.2f}<br>Tax: INR {tax:,.2f}<br><b>Grand Total: INR {total:,.2f}</b><br>Received: INR {paid:,.2f}<br><b>Invoice Balance: INR {total-paid:,.2f}</b></p>
    <div class="footer">Thank you for your business.<br><small>{tax_note}</small></div><button onclick="window.print()">Print / Save as PDF</button></body></html>'''

    folder=DATA/'invoices';folder.mkdir(exist_ok=True)
    path=folder/(number.replace('/','_')+'.html');path.write_text(doc,encoding='utf-8');webbrowser.open(path.as_uri())

def share_invoice_whatsapp(iid):
    """Create a colour PNG and open the customer's WhatsApp chat for manual attachment."""
    inv=con.execute('SELECT i.number,COALESCE(c.phone,""),COALESCE(c.name,"Walk-in Customer") FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id WHERE i.id=?',(iid,)).fetchone()
    if not inv:return messagebox.showerror('Invoice not found','Select a saved invoice.')
    number,phone,name=inv
    try:path=whatsapp_bill_image(iid).resolve()
    except Exception as ex:return messagebox.showerror('WhatsApp image error',str(ex))
    try:
        if os.name=='nt':
            import subprocess
            subprocess.Popen(['explorer.exe','/select,'+str(path)])
        else:webbrowser.open(path.parent.as_uri())
    except Exception as ex:messagebox.showwarning('Image folder',str(ex))
    digits=re.sub(r'\D','',phone or '')
    if len(digits)==10:digits='91'+digits
    if 11<=len(digits)<=15:webbrowser.open('https://wa.me/'+digits)
    try:
        root.clipboard_clear();root.clipboard_append(str(path));root.update()
    except Exception:pass
    messagebox.showinfo('WhatsApp - Colour Bill Image',
        f'Customer: {name}\nBill: {number}\n\nColour PNG selected in File Explorer.\n'
        'In WhatsApp click Attach > Photos & videos, select the PNG image, review and Send.\n\n'
        'Image file path is copied to clipboard.\nNothing is sent automatically.')

# --- V11: Invoice Recycle Bin (30 days) ---
# Only invoices are archived. Customer/product masters are never removed.
RECYCLE_PDFS=DATA/'Recycle_Bin_PDFs'
RECYCLE_PDFS.mkdir(parents=True,exist_ok=True)

def recycle_invoice(iid):
    inv=con.execute('SELECT * FROM invoices WHERE id=?',(iid,)).fetchone()
    if not inv:raise ValueError('Invoice not found or already deleted')
    name=con.execute('SELECT name FROM customers WHERE id=?',(inv[2],)).fetchone() if inv[2] else None
    items=rows('SELECT * FROM invoice_items WHERE invoice_id=?',(iid,))
    payments=rows('SELECT * FROM payments WHERE invoice_id=?',(iid,))
    # Match by invoice number AND customer to avoid touching unrelated advances.
    linked_advances=rows('SELECT * FROM customer_payments WHERE customer_id=? AND reference=?',
                         (inv[2],'Advance received with '+inv[1])) if inv[2] is not None else []
    payload=json.dumps({'invoice':inv,'items':items,'payments':payments,'linked_advances':linked_advances},ensure_ascii=False)
    original=pdf_location(iid)
    trashed=RECYCLE_PDFS/(f'{iid}_'+original.name)
    now=datetime.now()
    archived=con.execute('SELECT invoice_number FROM deleted_invoices WHERE invoice_id=?',(iid,)).fetchone()
    if archived:
        if archived[0] == inv[1]:
            raise ValueError('This invoice already has a matching recycle-bin record. No changes made; please restore or permanently delete the archived record first.')
        # Different invoice number: a legacy orphan archive reused this SQLite ID.
        # Move it intact into an audit table before creating the current archive.
        with con:
            old_archive=con.execute('SELECT invoice_id,invoice_number,customer_name,deleted_at,expires_at,payload,pdf_original,pdf_trashed FROM deleted_invoices WHERE invoice_id=?',(iid,)).fetchone()
            con.execute('''INSERT INTO archived_invoice_conflicts(original_invoice_id,invoice_number,customer_name,deleted_at,expires_at,payload,pdf_original,pdf_trashed,moved_at)
                           VALUES(?,?,?,?,?,?,?,?,?)''',(*old_archive,datetime.now().isoformat(timespec='seconds')))
            con.execute('DELETE FROM deleted_invoices WHERE invoice_id=?',(iid,))
    with con:
        con.execute('INSERT INTO deleted_invoices(invoice_id,invoice_number,customer_name,deleted_at,expires_at,payload,pdf_original,pdf_trashed) VALUES(?,?,?,?,?,?,?,?)',
                    (iid,inv[1],name[0] if name else 'Walk-in Customer',now.isoformat(timespec='seconds'),(now+timedelta(days=30)).isoformat(timespec='seconds'),payload,str(original),str(trashed) if original.is_file() else ''))
        for item in items:
            if item[2] is not None:
                con.execute('UPDATE products SET stock=stock+? WHERE id=?',(item[4],item[2]))
        con.execute('DELETE FROM payments WHERE invoice_id=?',(iid,))
        if linked_advances:
            con.executemany('DELETE FROM customer_payments WHERE id=?',[(a[0],) for a in linked_advances])
        con.execute('DELETE FROM invoice_items WHERE invoice_id=?',(iid,))
        con.execute('DELETE FROM invoices WHERE id=?',(iid,))
    if original.is_file():
        try:shutil.move(str(original),str(trashed))
        except OSError as ex:messagebox.showwarning('PDF move failed',f'Invoice was archived, but PDF could not be moved: {ex}')

def restore_invoice(iid):
    record=con.execute('SELECT payload,pdf_original,pdf_trashed FROM deleted_invoices WHERE invoice_id=?',(iid,)).fetchone()
    if not record:raise ValueError('Invoice not found in Recycle Bin')
    data=json.loads(record[0]);inv=data['invoice']
    if con.execute('SELECT 1 FROM invoices WHERE id=? OR number=?',(iid,inv[1])).fetchone():
        raise ValueError('An invoice with this ID or number already exists; restore cancelled')
    for item in data['items']:
        if item[2] is not None:
            product=con.execute('SELECT stock FROM products WHERE id=?',(item[2],)).fetchone()
            if not product:raise ValueError('A product used in this bill no longer exists; restore cancelled')
            if product[0]+0.0001<item[4]:
                raise ValueError('Insufficient current stock to restore this invoice. Adjust stock first.')
    with con:
        con.execute('INSERT INTO invoices VALUES('+','.join('?'*len(inv))+')',inv)
        for item in data['items']:
            con.execute('INSERT INTO invoice_items VALUES('+','.join('?'*len(item))+')',item)
            if item[2] is not None:
                con.execute('UPDATE products SET stock=stock-? WHERE id=?',(item[4],item[2]))
        for payment in data['payments']:
            con.execute('INSERT INTO payments VALUES('+','.join('?'*len(payment))+')',payment)
        for advance_payment in data.get('linked_advances',[]):
            # Do not overwrite another payment if a legacy DB reused the ID.
            if con.execute('SELECT 1 FROM customer_payments WHERE id=?',(advance_payment[0],)).fetchone():
                raise ValueError('Advance payment ID already exists; restore cancelled to protect data')
            con.execute('INSERT INTO customer_payments VALUES('+','.join('?'*len(advance_payment))+')',advance_payment)
        con.execute('DELETE FROM deleted_invoices WHERE invoice_id=?',(iid,))
    if record[2] and Path(record[2]).is_file():
        try:
            target=Path(record[1]);target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():shutil.move(record[2],str(target))
        except OSError as ex:messagebox.showwarning('PDF restore',f'Invoice restored, but PDF move failed: {ex}')

def permanently_delete_invoice(iid):
    record=con.execute('SELECT pdf_trashed FROM deleted_invoices WHERE invoice_id=?',(iid,)).fetchone()
    if not record:raise ValueError('Archived invoice not found')
    with con:con.execute('DELETE FROM deleted_invoices WHERE invoice_id=?',(iid,))
    if record[0]:
        try:Path(record[0]).unlink(missing_ok=True)
        except OSError:pass

def purge_expired_recycle():
    expired=rows('SELECT invoice_id FROM deleted_invoices WHERE expires_at<=?',(datetime.now().isoformat(timespec='seconds'),))
    for (iid,) in expired:permanently_delete_invoice(iid)

recycle_tab=tabs['Recycle Bin']
ttk.Label(recycle_tab,text='Deleted Invoices — 30-Day Recycle Bin',font=('Segoe UI',17,'bold'),foreground=GREEN).pack(anchor='w',padx=12,pady=(12,4))
ttk.Label(recycle_tab,text='Deleted bills are excluded from sales and customer balances. Restore within 30 days; expired bills are purged when software starts.').pack(anchor='w',padx=12,pady=(0,10))
# Reserve the bottom of the tab for actions BEFORE packing the expanding invoice list.
# This keeps action buttons visible at Windows display scaling and smaller heights.
recycle_actions=ttk.Frame(recycle_tab)
recycle_actions.pack(side='bottom',fill='x',padx=12,pady=(8,12))
recycle_tree=table(recycle_tab,('Invoice ID','Invoice No','Customer','Deleted On','Auto Delete On'))
def refresh_recycle():
    fill(recycle_tree,rows('SELECT invoice_id,invoice_number,customer_name,deleted_at,expires_at FROM deleted_invoices ORDER BY deleted_at DESC'))
def selected_recycle_id():
    sel=recycle_tree.selection()
    if not sel:
        messagebox.showinfo('Select deleted bill','Select an invoice from Recycle Bin first.')
        return None
    return int(recycle_tree.item(sel[0])['values'][0])
def delete_bill_confirmed(iid):
    rec=con.execute('SELECT number,total FROM invoices WHERE id=?',(iid,)).fetchone()
    if not rec:return messagebox.showerror('Not found','Invoice no longer exists')
    if not messagebox.askyesno('Move bill to Recycle Bin',f'Invoice: {rec[0]}\nAmount: {money(rec[1])}\n\nMove this bill to Recycle Bin for 30 days?\nThis reverses its sale, payments, linked extra advances and product stock.\n\nYou can restore it from Recycle Bin.'):
        return
    try:
        recycle_invoice(iid);refresh_all();refresh_recycle()
        messagebox.showinfo('Moved to Recycle Bin','Invoice archived for 30 days. Restore it from Recycle Bin if needed.')
    except Exception as ex:messagebox.showerror('Delete error',str(ex))
def delete_history_invoice():
    selections=history_tree.selection()
    if not selections:
        return messagebox.showinfo('Select bills','Select one or more invoices. Use Ctrl+Click or Shift+Click to select multiple rows.')
    ids=[]
    for item in selections:
        vals=history_tree.item(item,'values')
        if vals:
            ids.append(int(vals[0]))
    ids=list(dict.fromkeys(ids))
    if not ids:return
    if len(ids)==1:
        return delete_bill_confirmed(ids[0])
    placeholders=','.join('?' for _ in ids)
    records=rows(f'SELECT id,number,total FROM invoices WHERE id IN ({placeholders})',ids)
    if len(records)!=len(ids):
        return messagebox.showerror('Selection changed','Some selected invoices no longer exist. Refresh and select again.')
    total=sum(float(r[2]) for r in records)
    if not messagebox.askyesno('Move multiple bills to Recycle Bin',
        f'Selected invoices: {len(records)}\\nTotal invoice value: {money(total)}\\n\\n'
        'Move ALL selected bills to the 30-day Recycle Bin?\\n'
        'This reverses the associated stock, invoice payments and linked advances.\\n'
        'You can restore each invoice from Recycle Bin.'):
        return
    completed=[]
    try:
        # Take a consistent SQLite backup before modifying multiple invoices.
        backup_dir=DATA/'Backups'
        backup_dir.mkdir(parents=True,exist_ok=True)
        backup_path=backup_dir/('Before_Multi_Bill_Delete_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
        with sqlite3.connect(str(backup_path)) as backup_con:
            con.backup(backup_con)
        for iid in ids:
            recycle_invoice(iid)
            completed.append(iid)
    except Exception as ex:
        refresh_all()
        refresh_recycle()
        return messagebox.showerror('Bulk delete interrupted',
            f'Moved {len(completed)} of {len(ids)} bills to Recycle Bin.\\n'
            f'Other bills were not deleted.\\n\\nError: {ex}\\n\\n'
            f'Pre-delete database backup: {backup_path if "backup_path" in locals() else "Not created"}')
    refresh_all()
    refresh_recycle()
    messagebox.showinfo('Bulk delete complete',
        f'{len(completed)} selected bills moved to Recycle Bin.\\n'
        f'Pre-delete database backup: {backup_path}')

def delete_dashboard_invoice():
    sel=recent_tree.selection()
    if not sel:return messagebox.showinfo('Select bill','Select an invoice from Recent Invoices first')
    number=recent_tree.item(sel[0])['values'][0]
    row=con.execute('SELECT id FROM invoices WHERE number=?',(number,)).fetchone()
    if row:delete_bill_confirmed(row[0])
def restore_selected_invoice():
    iid=selected_recycle_id()
    if iid is None:return
    if not messagebox.askyesno('Restore invoice','Restore this bill, its payments and its inventory movements?'):return
    try:
        restore_invoice(iid);refresh_all();refresh_recycle()
        messagebox.showinfo('Restored','Invoice restored to Payments & History.')
    except Exception as ex:messagebox.showerror('Restore error',str(ex))
def permanently_delete_selected():
    iid=selected_recycle_id()
    if iid is None:return
    if not messagebox.askyesno('PERMANENT DELETE','This permanently deletes the archived bill and its recycled PDF. It cannot be recovered without a database backup. Continue?'):return
    if not messagebox.askyesno('Final confirmation','Are you absolutely sure? This action cannot be undone.'):return
    try:permanently_delete_invoice(iid);refresh_recycle()
    except Exception as ex:messagebox.showerror('Delete error',str(ex))
ttk.Button(recycle_actions,text='Restore Selected Bill',command=restore_selected_invoice).pack(side='left',padx=5)
ttk.Button(recycle_actions,text='PERMANENT DELETE',command=permanently_delete_selected).pack(side='left',padx=5)
def empty_recycle_bin():
    archived=rows('SELECT invoice_id FROM deleted_invoices')
    if not archived:
        return messagebox.showinfo('Recycle Bin','Recycle Bin is already empty.')
    count=len(archived)
    if not messagebox.askyesno('EMPTY RECYCLE BIN',f'Permanently delete ALL {count} archived bills and their recycled PDFs?\n\nThis cannot be undone without a database backup.'):
        return
    if not messagebox.askyesno('FINAL CONFIRMATION',f'Confirm permanent deletion of all {count} archived bills?'):
        return
    try:
        for (iid,) in archived:
            permanently_delete_invoice(iid)
        refresh_recycle()
        messagebox.showinfo('Recycle Bin',f'{count} archived bill(s) permanently deleted.')
    except Exception as ex:
        refresh_recycle()
        messagebox.showerror('Delete error',str(ex))

ttk.Button(recycle_actions,text='EMPTY RECYCLE BIN',command=empty_recycle_bin).pack(side='left',padx=5)
ttk.Button(recycle_actions,text='Refresh',command=refresh_recycle).pack(side='left',padx=5)

# V53: Easy operations. New UI features operate on the same existing database.
# No database reset, replacement or destructive migration is performed.
BACKUP_DIR=DATA/'Automatic_Backups'
BACKUP_DIR.mkdir(parents=True,exist_ok=True)
def automatic_backup(force=False):
    day=datetime.now().strftime('%Y%m%d')
    dest=BACKUP_DIR/f'ASCT_{day}.db'
    if dest.exists() and not force:return dest
    if force:dest=BACKUP_DIR/f'ASCT_{datetime.now():%Y%m%d_%H%M%S_%f}.db'
    target=sqlite3.connect(str(dest))
    try:con.backup(target)
    finally:target.close()
    return dest
try:automatic_backup()
except Exception as backup_error:
    root.after(500,lambda error=str(backup_error):messagebox.showwarning('Automatic backup failed',error))

# Only one inline editor may exist.  Editing must update the cart model,
# not merely the Treeview text, and must dispose of old Entry overlays.
_active_cart_editor = {'widget': None, 'finish': None}
def edit_bill_cell(event):
    # Close any previous edit before locating the newly clicked cell.
    previous = _active_cart_editor.get('finish')
    if previous:
        previous(save=True)
    item = cart_tree.identify_row(event.y)
    col = cart_tree.identify_column(event.x)
    if not item or col not in ('#2', '#3'):
        return
    bbox = cart_tree.bbox(item, col)
    if not bbox:
        return
    index = cart_tree.index(item)
    if index >= len(cart):
        return
    key = 'qty' if col == '#2' else 'rate'
    record = cart[index]
    px, py, w, h = bbox
    editor = ttk.Entry(cart_tree)
    editor.place(x=px, y=py, width=w, height=h)
    editor.insert(0, f"{record[key]:g}")
    editor.select_range(0, 'end')
    editor.focus_set()
    closed = [False]
    def finish(save=True):
        if closed[0]:
            return True
        if save:
            try:
                value = num(editor.get().strip())
                if key == 'qty':
                    if value <= 0:
                        raise ValueError('Quantity must be greater than zero')
                    if record['name'] == 'Packing Bag' and not value.is_integer():
                        raise ValueError('Packing Bag quantity must be a whole number')
                    current = con.execute('SELECT stock FROM products WHERE id=?', (record['pid'],)).fetchone()
                    available = float(current[0]) if current else 0
                    other = sum(r['qty'] for i, r in enumerate(cart) if i != index and r['pid'] == record['pid'])
                    if value + other > available + 1e-8:
                        raise ValueError(f'Insufficient stock: {available:g} available')
                record[key] = value
                record['total'] = round(record['qty'] * record['rate'] * (1 + record['tax'] / 100), 2)
            except ValueError as ex:
                messagebox.showerror('Edit item', str(ex), parent=root)
                if editor.winfo_exists():
                    editor.focus_set()
                return False
        closed[0] = True
        _active_cart_editor['widget'] = None
        _active_cart_editor['finish'] = None
        if editor.winfo_exists():
            editor.destroy()
        if save:
            render_cart()
        return True
    _active_cart_editor['widget'] = editor
    _active_cart_editor['finish'] = finish
    def on_enter(event):
        finish(save=True)
        return 'break'
    def on_escape(event):
        finish(save=False)
        return 'break'
    def on_focus_out(event):
        # Defer so clicking another editable cell can commit the old edit first.
        if not closed[0]:
            editor.after_idle(lambda: finish(save=True) if not closed[0] else None)
    editor.bind('<Return>', on_enter)
    editor.bind('<KP_Enter>', on_enter)
    editor.bind('<Escape>', on_escape)
    editor.bind('<FocusOut>', on_focus_out)
cart_tree.bind('<Double-1>', edit_bill_cell)
ttk.Label(top,text='Tip: Double-click Qty or Rate below; Enter saves, Esc cancels.',foreground=GREEN).grid(row=3,column=4,columnspan=3,sticky='w')

def edit_stock_cell(event):
    item=product_tree.identify_row(event.y)
    column=product_tree.identify_column(event.x)
    if not item or column not in ('#4','#5','#6'):return
    vals=product_tree.item(item,'values')
    if not vals:return
    pid=product_display_id_map.get(int(vals[0]))
    if pid is None:return
    name=vals[1]
    field={'#4':'stock','#5':'cost','#6':'rate'}[column]
    old=float(con.execute(f'SELECT {field} FROM products WHERE id=?',(pid,)).fetchone()[0])
    dialog=tk.Toplevel(root);dialog.title('Edit '+name);dialog.transient(root);dialog.grab_set();dialog.resizable(False,False)
    box=ttk.Frame(dialog,padding=18);box.pack()
    ttk.Label(box,text=f'{name} — {field.upper()}',font=('Segoe UI',12,'bold')).pack(anchor='w',pady=4)
    ttk.Label(box,text=f'Current value: {old:g}').pack(anchor='w')
    inp=ttk.Entry(box,width=25);inp.insert(0,str(old));inp.pack(pady=7);inp.focus_set();inp.select_range(0,'end')
    mode=tk.StringVar(value='correct')
    if field=='stock':
        ttk.Radiobutton(box,text='Correct final stock (=)',variable=mode,value='correct').pack(anchor='w')
        ttk.Radiobutton(box,text='Add received stock (+)',variable=mode,value='add').pack(anchor='w')
    ttk.Label(box,text='Reason (required for stock)').pack(anchor='w',pady=(7,0))
    reason=ttk.Entry(box,width=38);reason.pack(pady=5)
    def apply():
        try:
            entered=num(inp.get());new=round(old+entered if field=='stock' and mode.get()=='add' else entered,4)
            if field=='stock' and not reason.get().strip():raise ValueError('Enter a stock adjustment reason')
            if not messagebox.askyesno('Confirm change',f'{name}\n{field}: {old:g} -> {new:g}\n\nSave change?',parent=dialog):return
            automatic_backup(force=True)
            with con:
                con.execute(f'UPDATE products SET {field}=? WHERE id=?',(new,pid))
                if field=='stock':con.execute('INSERT INTO stock_adjustments(product_id,created,old_stock,new_stock,difference,reason) VALUES(?,?,?,?,?,?)',(pid,datetime.now().isoformat(timespec='seconds'),old,new,round(new-old,4),reason.get().strip()))
                if field=='rate':con.execute('INSERT INTO daily_rates(product_id,changed,rate) VALUES(?,?,?)',(pid,datetime.now().isoformat(timespec='seconds'),new))
            dialog.destroy();refresh_all()
        except (ValueError,sqlite3.Error,OSError) as ex:messagebox.showerror('Update failed',str(ex),parent=dialog)
    ttk.Button(box,text='SAVE CHANGE',command=apply).pack(pady=8)
    dialog.bind('<Return>',lambda e:apply());dialog.bind('<Escape>',lambda e:dialog.destroy())
product_tree.bind('<Double-1>',edit_stock_cell)

# Fast customer filtering, while keeping actual customer IDs in the displayed values.
customer_search=tk.StringVar()
search_bar=ttk.Frame(top);search_bar.grid(row=0,column=4,columnspan=3,sticky='w',padx=8)
ttk.Label(search_bar,text='Find Customer:').pack(side='left')
ttk.Entry(search_bar,textvariable=customer_search,width=22).pack(side='left',padx=4)
def filter_bill_customers(*_):
    term=customer_search.get().strip().casefold()
    choices=rows('SELECT id,name,COALESCE(phone,"") FROM customers ORDER BY name')
    bill_customer.configure(values=[f'{cid} | {name}' for cid,name,phone in choices if term in name.casefold() or term in phone.casefold()])
customer_search.trace_add('write',filter_bill_customers)

# Unsaved bill drafts: file is local and never changes sales/stock until Save Bill.
DRAFT_FILE=DATA/'current_bill_draft.json'
def save_bill_draft():
    payload={'customer_id':combo_id(bill_customer.get()),'method':bill_method.get(),'paid':bill_paid.get(),'cart':cart,'saved':datetime.now().isoformat(timespec='seconds')}
    tmp=DRAFT_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(DRAFT_FILE)
    messagebox.showinfo('Draft saved','Bill draft saved locally. Stock and customer balances have not changed.')
def resume_bill_draft():
    if not DRAFT_FILE.exists():return messagebox.showinfo('Draft','No saved draft found.')
    if cart and not messagebox.askyesno('Resume draft','Replace the current unsaved bill items with saved draft?'):return
    try:
        data=json.loads(DRAFT_FILE.read_text(encoding='utf-8'))
        draft=data.get('cart',[])
        for x in draft:
            r=con.execute('SELECT name,stock,active FROM products WHERE id=?',(x['pid'],)).fetchone()
            if not r or not r[2]:raise ValueError('Draft product is no longer available: '+x['name'])
            if sum(y['qty'] for y in draft if y['pid']==x['pid'])>r[1]+1e-8:raise ValueError('Stock is insufficient for draft: '+x['name'])
        cart.clear();cart.extend(draft)
        cid=data.get('customer_id')
        if cid:
            r=con.execute('SELECT name FROM customers WHERE id=?',(cid,)).fetchone()
            if r:bill_customer.set(f'{cid} | {r[0]}')
        bill_method.set(data.get('method','Cash'))
        bill_paid.delete(0,'end');bill_paid.insert(0,str(data.get('paid','0')))
        render_cart();messagebox.showinfo('Draft resumed','Review rates and quantities before saving.')
    except (ValueError,KeyError,TypeError,sqlite3.Error) as ex:messagebox.showerror('Draft error',str(ex))

def save_and_print():
    iid=create_invoice()
    if iid is not None:
        try:print_pdf(existing_or_rebuilt_pdf(iid),iid)
        except Exception as ex:messagebox.showwarning('Bill saved; print failed',str(ex))

def share_last_bill_quick():
    if last_saved_invoice_id is None:
        return messagebox.showinfo('WhatsApp','Save a bill first, then share its colour image.')
    share_invoice_whatsapp(last_saved_invoice_id)
ttk.Button(bottom,text='WHATSAPP LAST BILL',command=share_last_bill_quick).pack(side='right',padx=4)
ttk.Button(bottom,text='SAVE + PRINT',command=save_and_print).pack(side='right',padx=4)
ttk.Button(bottom,text='SAVE DRAFT',command=save_bill_draft).pack(side='right',padx=4)
ttk.Button(bottom,text='RESUME DRAFT',command=resume_bill_draft).pack(side='right',padx=4)

# Payment shortcut: open the existing customer ledger rather than duplicating payment logic.
def quick_customer_payment():
    cid=combo_id(bill_customer.get())
    if not cid:return messagebox.showinfo('Select customer','Select a customer in New Bill first.')
    r=con.execute('SELECT name FROM customers WHERE id=?',(cid,)).fetchone()
    if not r:return
    nb.select(tabs['Customer Ledger'])
    ledger_customer.set(f'{cid} | {r[0]}')
    refresh_ledger();refresh_account_payment_history();ledger_amount.focus_set()
ttk.Button(top,text='RECEIVE CUSTOMER PAYMENT',command=quick_customer_payment).grid(row=4,column=0,columnspan=3,sticky='w',pady=5)

# Low stock thresholds are UI-only alerts; they do not alter inventory.
low_stock_bar=ttk.Frame(tabs['Products & Stock']);low_stock_bar.pack(fill='x',padx=10,pady=3)
low_stock_text=tk.StringVar()
ttk.Label(low_stock_bar,textvariable=low_stock_text,foreground='#A14D13').pack(side='left')
low_stock_threshold=tk.StringVar(value='10')
ttk.Label(low_stock_bar,text='Alert below:').pack(side='left',padx=(18,4))
ttk.Entry(low_stock_bar,textvariable=low_stock_threshold,width=8).pack(side='left')
def show_low_stock():
    try:limit=num(low_stock_threshold.get())
    except ValueError:return messagebox.showerror('Threshold','Enter a valid quantity')
    data=rows("SELECT name,unit,stock FROM products WHERE active=1 AND stock<? ORDER BY stock,name",(limit,))
    low_stock_text.set(f'Low stock items: {len(data)} (below {limit:g} in each product unit)')
    messagebox.showinfo('Low stock', '\n'.join(f'{n}: {q:g} {u}' for n,u,q in data) if data else 'No products below threshold')
ttk.Button(low_stock_bar,text='CHECK LOW STOCK',command=show_low_stock).pack(side='left',padx=8)

# Daily closing report: sales, cash collection, expenses, and inventory movements.
closing_frame=ttk.LabelFrame(tabs['Reports & Backup'],text='Daily Closing Report',padding=8)
closing_frame.pack(fill='x',padx=10,pady=6)
closing_date=tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
ttk.Label(closing_frame,text='Date YYYY-MM-DD').pack(side='left',padx=5)
ttk.Entry(closing_frame,textvariable=closing_date,width=15).pack(side='left')
def closing_report():
    try:day=datetime.strptime(closing_date.get().strip(),'%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:return messagebox.showerror('Date','Use YYYY-MM-DD')
    sales=con.execute('SELECT COALESCE(SUM(total),0) FROM invoices WHERE substr(created,1,10)=?',(day,)).fetchone()[0]
    paid=con.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE substr(created,1,10)=?',(day,)).fetchone()[0]
    account=con.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE substr(created,1,10)=?',(day,)).fetchone()[0]
    expenses=con.execute('SELECT COALESCE(SUM(amount),0) FROM expenses WHERE substr(created,1,10)=?',(day,)).fetchone()[0]
    stock=stock_register_rows(day)
    messagebox.showinfo('Daily closing '+day,f'Sales: {money(sales)}\nInvoice payments: {money(paid)}\nAccount receipts: {money(account)}\nExpenses: {money(expenses)}\nNet cash receipts less expenses: {money(paid+account-expenses)}\n\nStock IN / OUT by product: see Daily Stock Register.\nNote: this is cash movement, NOT net profit.')
    if messagebox.askyesno('Export closing report','Export daily closing and product stock as CSV?'):
        dest=filedialog.asksaveasfilename(defaultextension='.csv',initialfile=f'ASCT_Closing_{day}.csv',filetypes=[('CSV','*.csv')])
        if dest:
            with open(dest,'w',newline='',encoding='utf-8-sig') as fp:
                writer=csv.writer(fp)
                for label,val in [('Date',day),('Sales',sales),('Invoice payments',paid),('Customer account receipts',account),('Expenses',expenses),('Net cash less expenses',paid+account-expenses)]:writer.writerow([label,val])
                writer.writerow([]);writer.writerow(['Product','Unit','Opening','Stock IN','Stock OUT','Closing'])
                writer.writerows(stock)
ttk.Button(closing_frame,text='VIEW / EXPORT DAILY CLOSING',command=closing_report).pack(side='left',padx=9)

# V61: Owner-only daily close. Never modifies financial or inventory records.
OWNER_WHATSAPP='919361866945'
CLOSING_DIR=DATA/'Daily_Closing_Reports'
CLOSING_DIR.mkdir(parents=True,exist_ok=True)

def v63_amount(value):
    return 'Rs '+format(float(value or 0),',.2f')

def v63_quantity(value):
    return format(float(value or 0),'.3f').rstrip('0').rstrip('.') or '0'

def v63_report(day):
    # Read-only report. Keep all product quantities in their own units.
    datetime.strptime(day,'%Y-%m-%d')
    sales,bills=con.execute('SELECT COALESCE(SUM(total),0),COUNT(*) FROM invoices WHERE substr(created,1,10)=?',(day,)).fetchone()
    purchase=con.execute('SELECT COALESCE(SUM(amount),0) FROM purchases WHERE substr(created,1,10)=?',(day,)).fetchone()[0]
    expenses=con.execute('SELECT COALESCE(SUM(amount),0) FROM expenses WHERE substr(created,1,10)=?',(day,)).fetchone()[0]
    initial=con.execute('SELECT COALESCE(SUM(paid),0) FROM invoices WHERE substr(created,1,10)=?',(day,)).fetchone()[0]
    receipts=con.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE substr(created,1,10)=?',(day,)).fetchone()[0]
    account=con.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE substr(created,1,10)=?',(day,)).fetchone()[0]
    sections=[['AS COCONUT TRADERS | '+day,'DAILY CLOSING (OWNER ONLY)']]
    cust=['CUSTOMER SALES / PAYMENTS']
    for cid,name in con.execute('SELECT id,name FROM customers ORDER BY name').fetchall():
        items=con.execute('''SELECT ii.description,SUM(ii.qty),SUM(ii.line_total),p.unit FROM invoice_items ii
          JOIN invoices i ON i.id=ii.invoice_id LEFT JOIN products p ON p.id=ii.product_id
          WHERE i.customer_id=? AND substr(i.created,1,10)=?
          GROUP BY ii.description,p.unit ORDER BY ii.description''',(cid,day)).fetchall()
        todays_bills=con.execute('SELECT COALESCE(SUM(total),0),COALESCE(SUM(paid),0) FROM invoices WHERE customer_id=? AND substr(created,1,10)=?',(cid,day)).fetchone()
        extra=con.execute('''SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN invoices i ON i.id=p.invoice_id
          WHERE i.customer_id=? AND substr(p.created,1,10)=?''',(cid,day)).fetchone()[0]
        extra+=con.execute('SELECT COALESCE(SUM(amount),0) FROM customer_payments WHERE customer_id=? AND substr(created,1,10)=?',(cid,day)).fetchone()[0]
        if not items and not extra and not todays_bills[0]:continue
        cust.append(str(name)+': '+('; '.join(str(n)+' '+v63_quantity(q)+' '+str(u or '')+' '+v63_amount(amt) for n,q,amt,u in items) if items else 'No sales'))
        cust.append('  Bill '+v63_amount(todays_bills[0])+' | Collected '+v63_amount(todays_bills[1]+extra))
    if len(cust)==1:cust.append('No customer activity')
    sections.append(cust)
    received=['TODAY PURCHASES']
    for supplier,name,unit,qty,amount in con.execute('''SELECT p.supplier,pr.name,pr.unit,SUM(p.qty),SUM(p.amount)
       FROM purchases p JOIN products pr ON pr.id=p.product_id WHERE substr(p.created,1,10)=?
       GROUP BY p.supplier,pr.name,pr.unit ORDER BY pr.name,p.supplier''',(day,)).fetchall():
        received.append(str(name)+' '+v63_quantity(qty)+' '+str(unit)+' '+v63_amount(amount)+' ('+str(supplier or 'Supplier not set')+')')
    if len(received)==1:received.append('No purchases')
    sections.append(received)
    # V65: Human-readable stock movement summary. No database writes.
    # "Added" is the register's movement total, not necessarily purchases.
    stock=['STOCK BALANCE (Kg / Nos shown separately)']
    alerts=[]
    register=stock_register_rows(day)
    for name,unit,opening,stock_in,stock_out,closing in register:
        if all(abs(float(x))<0.0001 for x in (opening,stock_in,stock_out,closing)):
            continue  # Hide inactive zero-movement lines only in WhatsApp report.
        unit_label=str(unit or '').strip()
        stock.append(str(name)+' | Balance '+v63_quantity(closing)+' '+unit_label)
        details=[]
        if abs(opening)>0.0001:details.append('Open '+v63_quantity(opening))
        if abs(stock_in)>0.0001:details.append('Added '+v63_quantity(stock_in))
        if abs(stock_out)>0.0001:details.append('Sold/Out '+v63_quantity(stock_out))
        if details:stock.append('  '+ ' | '.join(details)+' ('+unit_label+')')
        if closing < -0.0001:alerts.append('Negative stock: '+str(name))
        if day==datetime.now().strftime('%Y-%m-%d'):
            live=con.execute('SELECT stock FROM products WHERE name=?',(name,)).fetchone()
            if live and abs(float(live[0])-float(closing))>0.01:alerts.append('Stock mismatch: '+str(name))
    if len(stock)==1:stock.append('No stock movement or balance recorded')
    stock.append('Added = purchases + manual stock entries/adjustments (where applicable)')
    sections.append(stock)
    balances=['CUSTOMER PENDING / ADVANCE']
    total_due=total_adv=0
    for cid,name in con.execute('SELECT id,name FROM customers ORDER BY name').fetchall():
        due,adv=customer_account_position(cid)
        total_due+=due;total_adv+=adv
        if due>0.005:balances.append(str(name)+' pending '+v63_amount(due))
        if adv>0.005:balances.append(str(name)+' advance '+v63_amount(adv))
    if len(balances)==1:balances.append('No pending / advance')
    sections.append(balances)
    sections.append(['SUMMARY','Bills '+str(bills)+' | Sales '+v63_amount(sales),
        'Purchase '+v63_amount(purchase)+' | Collection '+v63_amount(initial+receipts+account),
        'Expenses '+v63_amount(expenses),
        'Pending '+v63_amount(total_due)+' | Advance '+v63_amount(total_adv)])
    try:
        check=con.execute('PRAGMA quick_check').fetchone()[0]
        if check!='ok':alerts.append('Database integrity: '+str(check))
    except Exception as exc:alerts.append('Database check failed: '+str(exc))
    sections.append(['CHECKS: '+('; '.join(alerts) if alerts else 'No basic errors found')])
    # Never invent daily profit: no verified historical COGS ledger.
    return sections,alerts

def v63_split_sections(sections,limit=3500):
    # Prefer ONE message; only split when the complete message is too long.
    full='\n\n'.join('\n'.join(s) for s in sections)
    if len(full)<=limit:return [full]
    chunks=[];current=''
    for section in sections:
        block='\n'.join(section)
        # Split oversized sections on complete lines, not arbitrary characters.
        for line in block.split('\n'):
            if len(line)>limit-100:
                raise ValueError('A report line is too long for safe WhatsApp text. Review saved TXT report.')
            if current and len(current)+len(line)+1>limit-100:
                chunks.append(current);current=''
            current+=(('\n' if current else '')+line)
        if current:current+='\n'
    if current.strip():chunks.append(current.strip())
    return ['DAILY REPORT '+day_marker+' | Part '+str(i+1)+'/'+str(len(chunks))+'\n'+part.strip()
            for i,part in enumerate(chunks)] if (day_marker:=sections[0][0].split(' | ')[-1]) else chunks

def v63_clipboard(message):
    root.clipboard_clear();root.clipboard_append(message);root.update()

def v63_prepare_report():
    day=closing_date.get().strip()
    try:
        sections,alerts=v63_report(day)
        backup_file=automatic_backup(force=True)
        if not backup_file.is_file() or backup_file.stat().st_size==0:
            raise RuntimeError('Backup file missing or empty; report not opened.')
        sections.append(['BACKUP: OK'])
        report='\n\n'.join('\n'.join(section) for section in sections)
        file=CLOSING_DIR/('ASCT_Daily_Closing_'+day+'_'+datetime.now().strftime('%H%M%S')+'.txt')
        file.write_text(report,encoding='utf-8-sig')
        parts=v63_split_sections(sections)
        if len(parts)==1:
            v63_clipboard(parts[0])
            webbrowser.open('https://web.whatsapp.com/send?phone='+OWNER_WHATSAPP+'&text='+quote(parts[0]) if len(parts[0])<=1700 else 'https://web.whatsapp.com/send?phone='+OWNER_WHATSAPP)
            note=('Report prepared as ONE WhatsApp text.\n'
                  'If the text is not prefilled, click the WhatsApp message box and press Ctrl+V.\n'
                  'Press Send, then confirm below.\n\nBackup: '+str(backup_file)+'\nSaved: '+str(file))
            if alerts:note+='\n\nCHECKS: '+ '; '.join(alerts[:5])
            messagebox.showinfo('Daily closing - one message',note)
        else:
            webbrowser.open('https://web.whatsapp.com/send?phone='+OWNER_WHATSAPP)
            if not messagebox.askokcancel('Long report - '+str(len(parts))+' parts',
                'A single message exceeds the safe text size.\n'
                'Only now the report will be split into '+str(len(parts))+' parts.\n'
                'Each part is copied in order. Paste with Ctrl+V and SEND before continuing.\n'
                'Cancel to stop without confirming delivery.'):
                return
            for index,part in enumerate(parts,1):
                v63_clipboard(part)
                if not messagebox.askokcancel('WhatsApp Part '+str(index)+'/'+str(len(parts)),
                    'Part '+str(index)+'/'+str(len(parts))+' copied.\nPaste into WhatsApp and press Send.\n'
                    'Only click OK AFTER sending this part.\nCancel stops further parts.'):
                    return
        if messagebox.askyesno('Confirm WhatsApp send',
            'Did you SEND '+('the single complete report?' if len(parts)==1 else 'ALL '+str(len(parts))+' parts?')+
            '\nChoose NO if anything was not sent.'):
            status=CLOSING_DIR/('ASCT_Confirmed_Sent_'+day+'.txt')
            status.write_text('User-confirmed WhatsApp Send (delivery not independently verified) at '+datetime.now().isoformat(timespec='seconds')+
                '\nParts: '+str(len(parts))+'\nReport: '+str(file),encoding='utf-8')
    except Exception as ex:
        messagebox.showerror('Daily closing failed','No sent confirmation recorded.\n'+str(ex))

ttk.Button(closing_frame,text='CLOSE DAY: SEND OWNER WHATSAPP',command=v63_prepare_report).pack(side='left',padx=9)

def v64_report_state(day):
    # User confirmation is not proof of delivery; never mark a report sent automatically.
    sent=CLOSING_DIR/('ASCT_Confirmed_Sent_'+day+'.txt')
    if not sent.is_file():return 'unsent'
    try:
        sent_time=datetime.fromtimestamp(sent.stat().st_mtime)
        # A new transaction after confirmation makes the previously prepared report stale.
        for table in ('invoices','payments','customer_payments','purchases','expenses','stock_adjustments','daily_rates'):
            last=con.execute('SELECT MAX(created) FROM '+table+' WHERE substr(created,1,10)=?',(day,)).fetchone()[0] if table not in ('daily_rates',) else con.execute('SELECT MAX(changed) FROM daily_rates WHERE substr(changed,1,10)=?',(day,)).fetchone()[0]
            if last and datetime.fromisoformat(last)>sent_time:return 'revised'
    except (OSError,ValueError,sqlite3.Error):return 'review'
    return 'confirmed'

def v61_shutdown():
    day=datetime.now().strftime('%Y-%m-%d')
    state=v64_report_state(day)
    if state!='confirmed':
        reason={'unsent':'Today\'s owner WhatsApp report is NOT confirmed sent.',
                'revised':'New business entries were recorded AFTER the last report. A revised report is needed.',
                'review':'Unable to verify today\'s report status. Please review.'}[state]
        choice=messagebox.askyesnocancel('Daily closing reminder',reason+
            '\n\nYES: Prepare backup and report now\nNO: Exit without sending\nCANCEL: Keep software open')
        if choice is None:return
        if choice:
            closing_date.set(day)
            v63_prepare_report()
            if v64_report_state(day)!='confirmed':return
    root.destroy()
root.protocol('WM_DELETE_WINDOW',v61_shutdown)

def v61_reminder():
    now=datetime.now()
    if (now.hour,now.minute)>=(23,30) and v64_report_state(now.strftime('%Y-%m-%d'))!='confirmed':
        messagebox.showwarning('11:30 PM closing reminder','Daily closing WhatsApp report not confirmed sent. Open Reports & Backup to prepare it before shutting down.')
    root.after(60*60*1000,v61_reminder)
root.after(60*1000,v61_reminder)

# Global shortcut: Ctrl+S saves only while the New Bill page is active.
def save_shortcut(event):
    if nb.tab(nb.select(),'text')=='New Bill':create_invoice()
root.bind('<Control-s>',save_shortcut)

# V81: Owner-authorized complete business reset. Disabled unless an official
# WhatsApp Business Cloud API integration is configured. No unofficial auto-send.
V81_SECURITY_DIR=DATA/'Owner_Security'
V81_SECURITY_DIR.mkdir(parents=True,exist_ok=True)
V81_PIN_FILE=V81_SECURITY_DIR/'owner_pin.json'
V81_RESET_BACKUPS=DATA/'Pre_Reset_Backups'
V81_RESET_BACKUPS.mkdir(parents=True,exist_ok=True)
V81_PHONE=os.environ.get('ASCT_OWNER_WHATSAPP','9361866945').lstrip('+')
V81_WA_PHONE_ID=os.environ.get('ASCT_WA_PHONE_NUMBER_ID','').strip()
V81_WA_TOKEN=os.environ.get('ASCT_WA_ACCESS_TOKEN','').strip()
V81_WA_TEMPLATE=os.environ.get('ASCT_WA_RESET_TEMPLATE','').strip()
V81_WA_COMPLETE_TEMPLATE=os.environ.get('ASCT_WA_COMPLETE_TEMPLATE','').strip()

def v81_pin_hash(pin,salt):
    return hashlib.pbkdf2_hmac('sha256',pin.encode('utf-8'),bytes.fromhex(salt),300000).hex()

def v81_setup_pin():
    if V81_PIN_FILE.exists():
        return messagebox.showinfo('Owner PIN','Owner PIN is already configured. Contact the owner to change it.')
    a=simpledialog.askstring('Owner PIN setup','Create a 6-12 digit owner PIN:',show='*',parent=root)
    if a is None:return
    if not a.isdigit() or not 6<=len(a)<=12:
        return messagebox.showerror('Invalid PIN','Use 6-12 digits.')
    b=simpledialog.askstring('Confirm PIN','Enter the same PIN again:',show='*',parent=root)
    if a!=b:return messagebox.showerror('PIN mismatch','PIN was not saved.')
    salt=secrets.token_hex(16)
    tmp=V81_PIN_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'salt':salt,'hash':v81_pin_hash(a,salt)}),encoding='utf-8')
    os.replace(tmp,V81_PIN_FILE)
    messagebox.showinfo('Owner PIN','PIN configured. Keep it private and secure.')

def v81_verify_pin(pin):
    try:
        stored=json.loads(V81_PIN_FILE.read_text(encoding='utf-8'))
        return secrets.compare_digest(v81_pin_hash(pin,stored['salt']),stored['hash'])
    except (OSError,ValueError,KeyError):return False

def v81_send_reset_alert(stage):
    # WhatsApp Cloud API template must be pre-approved and have no parameters.
    # HTTP acceptance is not proof of WhatsApp delivery or owner approval.
    if not all((V81_WA_PHONE_ID,V81_WA_TOKEN,V81_WA_TEMPLATE,V81_WA_COMPLETE_TEMPLATE)):
        raise RuntimeError('Official WhatsApp Cloud API is not configured. Reset is disabled.')
    payload={'messaging_product':'whatsapp','to':V81_PHONE,'type':'template',
             'template':{'name':V81_WA_TEMPLATE if stage=='request' else V81_WA_COMPLETE_TEMPLATE,'language':{'code':'en_US'}}}
    url='https://graph.facebook.com/v22.0/'+V81_WA_PHONE_ID+'/messages'
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+V81_WA_TOKEN,'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=15) as response:
        body=json.load(response)
    if not body.get('messages'):
        raise RuntimeError('WhatsApp API did not accept the '+stage+' alert.')
    return body['messages'][0].get('id','')

def v81_reset_business_data():
    if not V81_PIN_FILE.exists():
        return messagebox.showerror('Owner PIN required','Set the owner PIN first.')
    if not all((V81_WA_PHONE_ID,V81_WA_TOKEN,V81_WA_TEMPLATE,V81_WA_COMPLETE_TEMPLATE)):
        return messagebox.showerror('WhatsApp not configured',
            'Reset is locked until the official WhatsApp Business Cloud API is configured.\n'
            'Set ASCT_WA_PHONE_NUMBER_ID, ASCT_WA_ACCESS_TOKEN and ASCT_WA_RESET_TEMPLATE and ASCT_WA_COMPLETE_TEMPLATE.')
    if not messagebox.askyesno('DANGER: Complete Business Reset',
        'This permanently clears all customers, suppliers, invoices, purchases, payments, stock history and recycle bin.\n'
        'A separate backup will be saved. Continue?',parent=root):return
    pin=simpledialog.askstring('Owner Authorization','Enter your owner PIN:',show='*',parent=root)
    if pin is None:return
    # Persist lockout state across attempts, preventing brute-force by reopening UI.
    lockfile=V81_SECURITY_DIR/'pin_attempts.json'
    try:state=json.loads(lockfile.read_text())
    except (OSError,ValueError):state={'count':0,'until':0}
    import time
    if time.time()<state.get('until',0):
        return messagebox.showerror('Locked','Too many incorrect PINs. Try again after 15 minutes.')
    if not v81_verify_pin(pin):
        state['count']=state.get('count',0)+1
        if state['count']>=5:state={'count':0,'until':time.time()+900}
        lockfile.write_text(json.dumps(state))
        return messagebox.showerror('Invalid PIN','Owner PIN incorrect. No data was changed.')
    lockfile.write_text(json.dumps({'count':0,'until':0}))
    confirm=simpledialog.askstring('Final Confirmation',
        'Type RESET ALL BUSINESS DATA to permanently clear records:',parent=root)
    if confirm!='RESET ALL BUSINESS DATA':return
    backup=V81_RESET_BACKUPS/('ASCT_PRE_RESET_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
    try:
        # SQLite online backup preserves consistency, including WAL contents.
        with sqlite3.connect(backup) as target:con.backup(target)
        with sqlite3.connect(backup) as check:
            if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise RuntimeError('Pre-reset backup integrity check failed')
        v81_send_reset_alert('request')
        # Temporarily disable FK enforcement for the all-table wipe. SQLite cannot
        # reliably clear cyclic/parent-child tables in arbitrary schema order.
        # Validate all foreign keys before committing, and always restore enforcement.
        con.execute('PRAGMA foreign_keys=OFF')
        try:
          with con:
            # Keep the schema and business branding; clear all transactional rows.
            tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for name in tables:
                if name=='business_settings':continue
                if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',name):raise RuntimeError('Unexpected table name')
                con.execute('DELETE FROM "'+name+'"')
            for name,unit in PRODUCT_CATALOG+[('Packing Bag','Nos')]:
                con.execute('INSERT INTO products(name,unit,stock,cost,rate,hsn,tax,active) VALUES(?,?,0,0,0,"",0,1)',(name,unit))
            con.execute('INSERT INTO invoice_sequence(id,last_number) VALUES(1,0)')
            con.execute("INSERT INTO stock_register_baseline(product_id,initial_qty,started) SELECT id,0,datetime('now','localtime') FROM products")
            if con.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('Foreign key check failed; reset rolled back.')
        finally:
          con.execute('PRAGMA foreign_keys=ON')
        # Post-reset alert is best effort; failure must be clearly reported.
        try:
            v81_send_reset_alert('completed')
            messagebox.showinfo('Reset completed','Fresh business data created.\nBackup: '+str(backup))
        except Exception as ex:
            messagebox.showwarning('Reset completed - alert issue',
                'Reset succeeded, but completion WhatsApp alert was not accepted.\n'+str(ex)+'\nBackup: '+str(backup))
        refresh_all()
    except Exception as ex:
        messagebox.showerror('Reset stopped','Reset did not complete.\n'+str(ex)+'\nBackup: '+str(backup))

v81_security=ttk.LabelFrame(tabs['Shop Settings'],text='V81 Owner Security & Complete Business Reset',padding=12)
v81_security.pack(fill='x',padx=15,pady=10)
ttk.Label(v81_security,text='DANGER: Reset clears all business records; shop branding is retained. WhatsApp Business API required.').pack(anchor='w')
ttk.Button(v81_security,text='SET UP OWNER PIN',command=v81_setup_pin).pack(side='left',padx=5,pady=8)
ttk.Button(v81_security,text='COMPLETE BUSINESS RESET (BACKUP + ALERT + PIN)',command=v81_reset_business_data).pack(side='left',padx=5,pady=8)

purge_expired_recycle()
refresh_recycle()
nb.bind('<<NotebookTabChanged>>',lambda event:refresh_recycle() if nb.tab(nb.select(),'text')=='Recycle Bin' else None,add='+')

nb.bind('<<NotebookTabChanged>>',lambda event: (refresh_ledger_customers(),refresh_ledger()) if nb.tab(nb.select(),'text')=='Customer Ledger' else None,add='+')
def refresh_all():
    refresh_customers();refresh_opening_table();refresh_products();refresh_stock_history();refresh_profit_loss();refresh_purchases();refresh_supplier_accounts();v66_refresh_management();refresh_bag_management();refresh_history();refresh_reports();refresh_dashboard();refresh_sales_customers();refresh_sales_report();refresh_account_payment_history();refresh_daily_stock_register()
    refresh_combo(cp_customer,'SELECT id,name FROM customers ORDER BY name',blank=True)
    refresh_combo(bill_customer,'SELECT id,name FROM customers ORDER BY name',blank=True)
    # Order dropdowns by the 14-item catalog; IDs remain unchanged in SQLite.
    product_order = "CASE name " + " ".join(f"WHEN '{name}' THEN {i}" for i,(name,unit) in enumerate(PRODUCT_CATALOG,1)) + " ELSE 99 END, name"
    refresh_combo(bill_product,f"SELECT id,name FROM products WHERE active=1 AND name <> 'Packing Bag' ORDER BY {product_order}")
    refresh_combo(purchase_product,f"SELECT id,name FROM products WHERE active=1 AND name <> 'Packing Bag' ORDER BY {product_order}")
    refresh_combo(daily_product,f"SELECT id,name FROM products WHERE active=1 AND name <> 'Packing Bag' ORDER BY {product_order}")
refresh_all()
root.mainloop()
con.close()
