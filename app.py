import sqlite3, json, os, hashlib, secrets
from datetime import datetime, date
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, redirect, g, send_from_directory

app = Flask(__name__)
app.secret_key = 'medistore-bellary-2024-secret'
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'medistore.db')

ROLES = ['pharmacist_admin', 'doctor', 'pharmacist_staff', 'lab_tech']

# ─── DB ────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def rows(cur): return [dict(r) for r in cur]
def sha256(s): return hashlib.sha256(s.encode()).hexdigest()

def init_db():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name TEXT DEFAULT '',
        role TEXT NOT NULL,
        consultation_fee REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS medicines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        manufacturer TEXT DEFAULT '',
        category TEXT DEFAULT 'Tablet',
        buy_price REAL DEFAULT 0,
        sell_price REAL DEFAULT 0,
        qty_bought INTEGER DEFAULT 0,
        free_samples INTEGER DEFAULT 0,
        stock INTEGER DEFAULT 0,
        buy_date TEXT DEFAULT '',
        expiry_date TEXT NOT NULL,
        batch_no TEXT DEFAULT '',
        threshold INTEGER DEFAULT 50,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        age INTEGER,
        gender TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        address TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER REFERENCES patients(id),
        patient_name TEXT NOT NULL,
        age INTEGER,
        issue TEXT DEFAULT '',
        priority TEXT DEFAULT 'normal',
        status TEXT DEFAULT 'waiting',
        referred_to TEXT DEFAULT '',
        arrived_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS consultations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER REFERENCES patients(id),
        patient_name TEXT NOT NULL,
        patient_age INTEGER,
        doctor_id INTEGER REFERENCES users(id),
        doctor_name TEXT DEFAULT '',
        fee REAL DEFAULT 0,
        payment_method TEXT DEFAULT 'cash',
        payment_status TEXT DEFAULT 'paid',
        status TEXT DEFAULT 'active',
        notes TEXT DEFAULT '',
        visit_date TEXT DEFAULT (date('now','localtime')),
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS prescription_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consultation_id INTEGER REFERENCES consultations(id) ON DELETE CASCADE,
        medicine_name TEXT NOT NULL,
        medicine_id INTEGER,
        dosage_morning INTEGER DEFAULT 0,
        dosage_afternoon INTEGER DEFAULT 0,
        dosage_evening INTEGER DEFAULT 0,
        dosage_night INTEGER DEFAULT 0,
        quantity INTEGER DEFAULT 0,
        days INTEGER DEFAULT 0,
        instructions TEXT DEFAULT '',
        dispensed INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS bills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_no TEXT UNIQUE NOT NULL,
        patient_id INTEGER,
        patient_name TEXT DEFAULT '',
        patient_age INTEGER,
        doctor_name TEXT DEFAULT '',
        consultation_id INTEGER,
        pharmacist_id INTEGER,
        pharmacist_name TEXT DEFAULT '',
        subtotal REAL DEFAULT 0,
        discount REAL DEFAULT 0,
        total REAL DEFAULT 0,
        status TEXT DEFAULT 'active',
        cancelled_by TEXT DEFAULT '',
        cancelled_reason TEXT DEFAULT '',
        bill_date TEXT DEFAULT (date('now','localtime')),
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS bill_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER REFERENCES bills(id) ON DELETE CASCADE,
        medicine_id INTEGER,
        medicine_name TEXT NOT NULL,
        quantity INTEGER DEFAULT 0,
        sell_price REAL DEFAULT 0,
        buy_price REAL DEFAULT 0,
        line_total REAL DEFAULT 0,
        is_free_sample INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS lab_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_no TEXT UNIQUE NOT NULL,
        patient_id INTEGER,
        patient_name TEXT NOT NULL,
        patient_age INTEGER,
        doctor_name TEXT DEFAULT '',
        lab_tech_id INTEGER REFERENCES users(id),
        lab_tech_name TEXT DEFAULT '',
        total_fee REAL DEFAULT 0,
        payment_method TEXT DEFAULT 'cash',
        payment_status TEXT DEFAULT 'paid',
        status TEXT DEFAULT 'active',
        cancelled_by TEXT DEFAULT '',
        cancelled_reason TEXT DEFAULT '',
        test_date TEXT DEFAULT (date('now','localtime')),
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS lab_test_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lab_test_id INTEGER REFERENCES lab_tests(id) ON DELETE CASCADE,
        test_name TEXT NOT NULL,
        fee REAL DEFAULT 0,
        result TEXT DEFAULT '',
        notes TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS served_patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        queue_id INTEGER,
        patient_name TEXT NOT NULL,
        age INTEGER,
        issue TEXT DEFAULT '',
        priority TEXT DEFAULT 'normal',
        arrived_at TEXT,
        served_at TEXT DEFAULT (datetime('now','localtime')),
        notes TEXT DEFAULT '',
        served_by TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS lab_test_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_name TEXT UNIQUE NOT NULL,
        price REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    try:
        db.execute("ALTER TABLE queue ADD COLUMN session TEXT DEFAULT 'Morning'")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE queue ADD COLUMN fee REAL DEFAULT 0")
        db.execute("ALTER TABLE queue ADD COLUMN payment_method TEXT DEFAULT 'cash'")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE bills ADD COLUMN payment_method TEXT DEFAULT 'cash'")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE queue ADD COLUMN doctor_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("UPDATE bill_items SET quantity = CAST(ROUND(line_total / sell_price) AS INTEGER) WHERE quantity = 0 AND sell_price > 0")
    except sqlite3.OperationalError:
        pass
    db.commit()

    # Default users
    users = [
        ('admin',         'admin@123',    'Pharmacist Admin',  'pharmacist_admin', 0),
        ('doctor1',       'doctor@123',   'Dr. Ramesh Kumar',  'doctor',           300),
        ('pharmacist1',   'pharma@123',   'Srinivas (Staff)',  'pharmacist_staff', 0),
        ('labtech1',      'lab@123',      'Lab Tech Suresh',   'lab_tech',         0),
    ]
    for u in users:
        try:
            db.execute("INSERT OR IGNORE INTO users (username,password,full_name,role,consultation_fee) VALUES (?,?,?,?,?)",
                (u[0], sha256(u[1]), u[2], u[3], u[4]))
        except: pass

    # Default settings
    settings = [
        ('pharmacy_name', 'MediStore Pro'),
        ('pharmacy_city', 'Bellary'),
        ('pharmacy_address', 'Main Road, Bellary - 583101'),
        ('gstin', ''),
        ('bill_footer', 'Thank you! Visit again.'),
        ('low_stock_threshold', '50'),
        ('expiry_alert_days', '30'),
    ]
    for k, v in settings:
        db.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, v))

    # Seed medicines
    if db.execute("SELECT COUNT(*) FROM medicines").fetchone()[0] == 0:
        meds = [
            ('Paracetamol 500mg','Cipla','Tablet',2.50,4.00,200,20,'2025-01-10','2027-06-30','BT001',50),
            ('Amoxicillin 250mg','Sun Pharma','Capsule',8.00,14.00,100,10,'2025-02-15','2026-04-10','BT002',50),
            ('Cough Syrup 100ml','GSK','Syrup',45.00,75.00,50,5,'2025-03-01','2026-03-15','BT003',50),
            ('Metformin 500mg','Lupin','Tablet',3.00,6.00,300,30,'2025-01-20','2028-01-01','BT004',50),
            ('Azithromycin 500mg','Cipla','Tablet',12.00,22.00,30,0,'2025-03-10','2026-04-20','BT005',50),
            ('Cetirizine 10mg','Cipla','Tablet',1.50,3.00,200,20,'2025-02-20','2026-05-01','BT006',50),
            ('Pantoprazole 40mg','Torrent','Tablet',5.00,9.50,150,15,'2025-02-01','2027-11-30','BT007',50),
            ('Atorvastatin 10mg','Sun','Tablet',6.00,11.00,200,20,'2025-01-05','2027-09-30','BT008',50),
        ]
        for m in meds:
            db.execute("""INSERT INTO medicines (name,manufacturer,category,buy_price,sell_price,
                qty_bought,free_samples,stock,buy_date,expiry_date,batch_no,threshold)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (m[0],m[1],m[2],m[3],m[4],m[5],m[6],m[5]+m[6],m[7],m[8],m[9],m[10]))
    
    # Seed lab test catalog
    if db.execute("SELECT COUNT(*) FROM lab_test_catalog").fetchone()[0] == 0:
        tests = [
            ('Complete Blood Count (CBC)', 350.0),
            ('Blood Sugar Fasting (FBS)', 150.0),
            ('Lipid Profile', 600.0),
            ('Liver Function Test (LFT)', 750.0),
            ('Thyroid Profile', 550.0),
            ('Urine Routine', 120.0),
        ]
        for t in tests:
            db.execute("INSERT INTO lab_test_catalog (test_name, price) VALUES (?,?)", (t[0], t[1]))
            
    db.commit()
    db.close()

# ─── AUTH ──────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            if request.path.startswith('/api/'):
                return jsonify({'error':'Unauthorized'}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') not in roles:
                return jsonify({'error':'Forbidden'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

# ─── PAGES ─────────────────────────────────────────────────────
@app.route('/login')
def login_page():
    if session.get('user_id'): return redirect('/')
    return render_template('login.html')

@app.route('/sw.js')
def serve_sw():
    # This solves the 404 error on mobile by correctly serving the Service Worker
    if os.path.exists('sw.js'):
        return send_from_directory('.', 'sw.js')
    else:
        return send_from_directory('static', 'sw.js')

@app.route('/')
@login_required
def index():
    return render_template('index.html', role=session.get('role'), username=session.get('username'), full_name=session.get('full_name'))

# ─── AUTH API ──────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.json or {}
    username = d.get('username','').strip().lower()
    password = d.get('password','')
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=? AND password=?",
        (username, sha256(password))).fetchone()
    if not user:
        return jsonify({'error':'Invalid username or password'}), 401
    u = dict(user)
    session.permanent = True
    session['user_id']   = u['id']
    session['username']  = u['username']
    session['full_name'] = u['full_name']
    session['role']      = u['role']
    return jsonify({'ok':True,'role':u['role'],'username':u['username'],'full_name':u['full_name'],'id':u['id']})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'ok':True})

@app.route('/api/me')
@login_required
def api_me():
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    return jsonify(dict(u))

@app.route('/api/doctors')
@login_required
def get_doctors():
    db = get_db()
    docs = db.execute("SELECT id, full_name, consultation_fee FROM users WHERE role='doctor'").fetchall()
    return jsonify(rows(docs))

@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    d = request.json or {}
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=? AND password=?",
        (session['user_id'], sha256(d.get('current','')))).fetchone()
    if not user: return jsonify({'error':'Current password incorrect'}), 401
    if len(d.get('new_password','')) < 6: return jsonify({'error':'Min 6 characters'}), 400
    db.execute("UPDATE users SET password=? WHERE id=?", (sha256(d['new_password']), session['user_id']))
    db.commit()
    return jsonify({'ok':True})

# ─── USERS MGMT (admin only) ───────────────────────────────────
@app.route('/api/users')
@login_required
@role_required('pharmacist_admin')
def get_users():
    return jsonify(rows(get_db().execute("SELECT id,username,full_name,role,consultation_fee,created_at FROM users ORDER BY role")))

@app.route('/api/users', methods=['POST'])
@login_required
@role_required('pharmacist_admin')
def add_user():
    d = request.json or {}
    db = get_db()
    try:
        db.execute("INSERT INTO users (username,password,full_name,role,consultation_fee) VALUES (?,?,?,?,?)",
            (d['username'].lower(), sha256(d.get('password','pass@123')),
             d.get('full_name',''), d.get('role','pharmacist_staff'),
             float(d.get('consultation_fee',0))))
        db.commit()
        return jsonify({'ok':True}), 201
    except Exception as e:
        return jsonify({'error':str(e)}), 400

@app.route('/api/users/<int:uid>', methods=['DELETE'])
@login_required
@role_required('pharmacist_admin')
def delete_user(uid):
    if uid == session['user_id']: return jsonify({'error':'Cannot delete yourself'}), 400
    get_db().execute("DELETE FROM users WHERE id=?", (uid,))
    get_db().commit()
    return jsonify({'ok':True})

# ─── SETTINGS ──────────────────────────────────────────────────
@app.route('/api/settings')
@login_required
def get_settings():
    db = get_db()
    s = {r['key']:r['value'] for r in db.execute("SELECT key,value FROM settings")}
    return jsonify(s)

@app.route('/api/settings', methods=['POST'])
@login_required
@role_required('pharmacist_admin')
def update_setting():
    d = request.json or {}
    db = get_db()
    db.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (d['key'], d['value']))
    db.commit()
    return jsonify({'ok':True})

# ─── MEDICINES ─────────────────────────────────────────────────
@app.route('/api/medicines')
@login_required
def get_medicines():
    return jsonify(rows(get_db().execute("SELECT * FROM medicines ORDER BY name")))

@app.route('/api/medicines', methods=['POST'])
@login_required
@role_required('pharmacist_admin')
def add_medicine():
    d = request.json or {}
    db = get_db()
    stock = int(d.get('qty_bought',0)) + int(d.get('free_samples',0))
    cur = db.execute("""INSERT INTO medicines (name,manufacturer,category,buy_price,sell_price,
        qty_bought,free_samples,stock,buy_date,expiry_date,batch_no,threshold) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d['name'],d.get('manufacturer',''),d.get('category','Tablet'),
         float(d.get('buy_price',0)),float(d.get('sell_price',0)),
         int(d.get('qty_bought',0)),int(d.get('free_samples',0)),stock,
         d.get('buy_date',''),d['expiry_date'],d.get('batch_no',''),int(d.get('threshold',50))))
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM medicines WHERE id=?",(cur.lastrowid,)).fetchone())), 201

@app.route('/api/medicines/<int:mid>', methods=['DELETE'])
@login_required
@role_required('pharmacist_admin')
def delete_medicine(mid):
    get_db().execute("DELETE FROM medicines WHERE id=?", (mid,))
    get_db().commit()
    return jsonify({'ok':True})

# ─── PATIENTS ──────────────────────────────────────────────────
@app.route('/api/patients')
@login_required
def get_patients():
    return jsonify(rows(get_db().execute("SELECT * FROM patients ORDER BY created_at DESC LIMIT 100")))

@app.route('/api/patients', methods=['POST'])
@login_required
def add_patient():
    d = request.json or {}
    db = get_db()
    cur = db.execute("INSERT INTO patients (name,age,gender,phone,address) VALUES (?,?,?,?,?)",
        (d['name'],d.get('age'),d.get('gender',''),d.get('phone',''),d.get('address','')))
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM patients WHERE id=?",(cur.lastrowid,)).fetchone())), 201

# ─── QUEUE ─────────────────────────────────────────────────────
@app.route('/api/queue')
@login_required
def get_queue():
    q = get_db().execute("""SELECT * FROM queue WHERE status='waiting'
        ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'senior' THEN 2 ELSE 3 END, id""")
    return jsonify(rows(q))

@app.route('/api/queue', methods=['POST'])
@login_required
def add_queue():
    d = request.json or {}
    db = get_db()
    cur = db.execute("INSERT INTO queue (patient_name,age,issue,priority,referred_to,session,fee,payment_method,doctor_name) VALUES (?,?,?,?,?,?,?,?,?)",
        (d['patient_name'],d.get('age'),d.get('issue',''),d.get('priority','normal'),d.get('referred_to',''),d.get('session','Morning'), float(d.get('fee',0)), d.get('payment_method','cash'), d.get('doctor_name','')))
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM queue WHERE id=?",(cur.lastrowid,)).fetchone())), 201

@app.route('/api/queue/<int:qid>', methods=['PUT'])
@login_required
def update_queue(qid):
    d = request.json or {}
    db = get_db()
    fields = []
    vals = []
    for f in ['priority','status','referred_to','issue']:
        if f in d:
            fields.append(f+'=?')
            vals.append(d[f])
    if fields:
        vals.append(qid)
        db.execute(f"UPDATE queue SET {','.join(fields)} WHERE id=?", vals)
        db.commit()
    return jsonify({'ok':True})

@app.route('/api/queue/<int:qid>/serve', methods=['POST'])
@login_required
def serve_patient(qid):
    d = request.json or {}
    db = get_db()
    p = db.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone()
    if not p: return jsonify({'error':'Not found'}), 404
    p = dict(p)
    db.execute("""INSERT INTO served_patients (queue_id,patient_name,age,issue,priority,arrived_at,notes,served_by)
        VALUES (?,?,?,?,?,?,?,?)""",
        (p['id'],p['patient_name'],p['age'],p['issue'],p['priority'],p['arrived_at'],
         d.get('notes',''),session.get('full_name','staff')))
    db.execute("UPDATE queue SET status='served' WHERE id=?", (qid,))
    db.commit()
    return jsonify({'ok':True,'patient':p})

@app.route('/api/queue/<int:qid>', methods=['DELETE'])
@login_required
def delete_queue(qid):
    get_db().execute("DELETE FROM queue WHERE id=?", (qid,))
    get_db().commit()
    return jsonify({'ok':True})

@app.route('/api/served')
@login_required
def get_served():
    return jsonify(rows(get_db().execute("SELECT * FROM served_patients ORDER BY served_at DESC")))

# ─── CONSULTATIONS ─────────────────────────────────────────────
@app.route('/api/consultations')
@login_required
def get_consultations():
    db = get_db()
    role = session.get('role')
    today = date.today().isoformat()
    if role == 'doctor':
        query = "SELECT * FROM consultations WHERE doctor_id=? ORDER BY created_at DESC LIMIT 200"
        result = rows(db.execute(query, (session['user_id'],)))
    else:
        query = "SELECT * FROM consultations ORDER BY created_at DESC LIMIT 200"
        result = rows(db.execute(query))
    # attach prescription items
    for c in result:
        c['items'] = rows(db.execute("SELECT * FROM prescription_items WHERE consultation_id=?", (c['id'],)))
    return jsonify(result)

@app.route('/api/consultations/today-stats')
@login_required
def today_consultation_stats():
    db = get_db()
    today = date.today().isoformat()
    role = session.get('role')
    if role == 'doctor':
        uid = session['user_id']
        count = db.execute("SELECT COUNT(*) FROM consultations WHERE doctor_id=? AND visit_date=? AND status='active'",(uid,today)).fetchone()[0]
        total_fee = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE doctor_id=? AND visit_date=? AND status='active' AND payment_status='paid'",(uid,today)).fetchone()[0]
        cash = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE doctor_id=? AND visit_date=? AND payment_method='cash' AND status='active' AND payment_status='paid'",(uid,today)).fetchone()[0]
        online = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE doctor_id=? AND visit_date=? AND payment_method='online' AND status='active' AND payment_status='paid'",(uid,today)).fetchone()[0]
        upi = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE doctor_id=? AND visit_date=? AND payment_method='upi' AND status='active' AND payment_status='paid'",(uid,today)).fetchone()[0]
    else:
        count = db.execute("SELECT COUNT(*) FROM consultations WHERE visit_date=? AND status='active'", (today,)).fetchone()[0]
        total_fee = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE visit_date=? AND status='active' AND payment_status='paid'", (today,)).fetchone()[0]
        cash = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE visit_date=? AND payment_method='cash' AND status='active' AND payment_status='paid'", (today,)).fetchone()[0]
        online = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE visit_date=? AND payment_method='online' AND status='active' AND payment_status='paid'", (today,)).fetchone()[0]
        upi = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE visit_date=? AND payment_method='upi' AND status='active' AND payment_status='paid'", (today,)).fetchone()[0]
    return jsonify({'count':count,'total_fee':total_fee,'cash':cash,'online':online,'upi':upi})

@app.route('/api/consultations', methods=['POST'])
@login_required
@role_required('doctor')
def create_consultation():
    d = request.json or {}
    db = get_db()
    doctor = db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    cur = db.execute("""INSERT INTO consultations
        (patient_name,patient_age,doctor_id,doctor_name,fee,payment_method,payment_status,notes,visit_date)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (d['patient_name'],d.get('patient_age'),session['user_id'],
         session['full_name'],float(d.get('fee',dict(doctor)['consultation_fee'])),
         d.get('payment_method','cash'),d.get('payment_status','paid'),
         d.get('notes',''),d.get('visit_date',date.today().isoformat())))
    cid = cur.lastrowid
    for item in d.get('items',[]):
        db.execute("""INSERT INTO prescription_items
            (consultation_id,medicine_name,medicine_id,dosage_morning,dosage_afternoon,dosage_evening,dosage_night,quantity,days,instructions)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid,item.get('medicine_name',''),item.get('medicine_id'),
             int(item.get('dosage_morning',0)),int(item.get('dosage_afternoon',0)),
             int(item.get('dosage_evening',0)),int(item.get('dosage_night',0)),
             int(item.get('quantity',0)),int(item.get('days',0)),item.get('instructions','')))
    # Auto-add to queue
    try:
        db.execute("INSERT INTO queue (patient_name,age,issue,priority,referred_to) VALUES (?,?,?,?,?)",
            (d['patient_name'],d.get('patient_age'),'Post consultation - collect medicines','normal','pharmacist'))
    except: pass
    db.commit()
    c = dict(db.execute("SELECT * FROM consultations WHERE id=?", (cid,)).fetchone())
    c['items'] = rows(db.execute("SELECT * FROM prescription_items WHERE consultation_id=?", (cid,)))
    return jsonify(c), 201

@app.route('/api/consultations/<int:cid>/cancel', methods=['POST'])
@login_required
@role_required('doctor','pharmacist_admin')
def cancel_consultation(cid):
    d = request.json or {}
    db = get_db()
    db.execute("UPDATE consultations SET status='cancelled',cancelled_by=?,cancelled_reason=? WHERE id=?",
        (session['full_name'],d.get('reason',''),cid))
    db.commit()
    return jsonify({'ok':True})

# ─── BILLS ─────────────────────────────────────────────────────
@app.route('/api/bills')
@login_required
def get_bills():
    db = get_db()
    result = rows(db.execute("SELECT * FROM bills ORDER BY created_at DESC LIMIT 200"))
    for b in result:
        b['items'] = rows(db.execute("SELECT * FROM bill_items WHERE bill_id=?", (b['id'],)))
    return jsonify(result)

@app.route('/api/bills', methods=['POST'])
@login_required
@role_required('pharmacist_admin','pharmacist_staff')
def create_bill():
    d = request.json or {}
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM bills").fetchone()[0]
    bill_no = f"BILL-{count+1:04d}"
    subtotal = float(d.get('subtotal',0))
    discount = float(d.get('discount',0))
    total = subtotal - discount
    cur = db.execute("""INSERT INTO bills
        (bill_no,patient_name,patient_age,doctor_name,consultation_id,
         pharmacist_id,pharmacist_name,subtotal,discount,total,bill_date,payment_method)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (bill_no,d.get('patient_name',''),d.get('patient_age'),
         d.get('doctor_name',''),d.get('consultation_id'),
         session['user_id'],session['full_name'],subtotal,discount,total,
         d.get('bill_date',date.today().isoformat()), d.get('payment_method','cash')))
    bid = cur.lastrowid
    for item in d.get('items',[]):
        is_free = 1 if item.get('is_free_sample') else 0
        qty = int(item.get('quantity', item.get('units', 0)))
        db.execute("""INSERT INTO bill_items
            (bill_id,medicine_id,medicine_name,quantity,sell_price,buy_price,line_total,is_free_sample)
            VALUES (?,?,?,?,?,?,?,?)""",
            (bid,item.get('medicine_id'),item.get('medicine_name',''),
             qty,float(item.get('sell_price',0)),
             float(item.get('buy_price',0)),float(item.get('line_total',0)),is_free))
        if not is_free:
            db.execute("UPDATE medicines SET stock=MAX(0,stock-?) WHERE id=?",
                (qty, item.get('medicine_id')))
    db.commit()
    bill = dict(db.execute("SELECT * FROM bills WHERE id=?", (bid,)).fetchone())
    bill['items'] = rows(db.execute("SELECT * FROM bill_items WHERE bill_id=?", (bid,)))
    return jsonify(bill), 201

@app.route('/api/bills/<int:bid>/cancel', methods=['POST'])
@login_required
@role_required('pharmacist_admin')
def cancel_bill(bid):
    d = request.json or {}
    db = get_db()
    bill = db.execute("SELECT * FROM bills WHERE id=?", (bid,)).fetchone()
    if not bill: return jsonify({'error':'Not found'}), 404
    # Restore stock
    items = rows(db.execute("SELECT * FROM bill_items WHERE bill_id=?", (bid,)))
    for item in items:
        if not item['is_free_sample']:
            db.execute("UPDATE medicines SET stock=stock+? WHERE id=?",
                (item['quantity'], item['medicine_id']))
    db.execute("UPDATE bills SET status='cancelled',cancelled_by=?,cancelled_reason=? WHERE id=?",
        (session['full_name'],d.get('reason','Cancelled'),bid))
    db.commit()
    return jsonify({'ok':True})

# ─── LAB TESTS ─────────────────────────────────────────────────
@app.route('/api/lab-catalog')
@login_required
def get_lab_catalog():
    return jsonify(rows(get_db().execute("SELECT * FROM lab_test_catalog ORDER BY test_name")))

@app.route('/api/lab-catalog', methods=['POST'])
@login_required
@role_required('pharmacist_admin','doctor')
def add_lab_catalog():
    d = request.json or {}
    db = get_db()
    cur = db.execute("INSERT INTO lab_test_catalog (test_name,price) VALUES (?,?)", (d['test_name'], float(d.get('price',0))))
    db.commit()
    return jsonify({'ok':True,'id':cur.lastrowid})

@app.route('/api/lab-catalog/<int:tid>', methods=['DELETE'])
@login_required
@role_required('pharmacist_admin','doctor')
def delete_lab_catalog(tid):
    get_db().execute("DELETE FROM lab_test_catalog WHERE id=?", (tid,))
    get_db().commit()
    return jsonify({'ok':True})

@app.route('/api/lab-tests')
@login_required
def get_lab_tests():
    return jsonify(rows(get_db().execute("SELECT * FROM lab_tests ORDER BY created_at DESC LIMIT 200")))

@app.route('/api/lab-tests', methods=['POST'])
@login_required
@role_required('lab_tech','pharmacist_admin')
def create_lab_test():
    d = request.json or {}
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM lab_tests").fetchone()[0]
    test_no = f"LAB-{count+1:04d}"
    total_fee = sum(float(i.get('fee',0)) for i in d.get('items',[]))
    cur = db.execute("""INSERT INTO lab_tests
        (test_no,patient_name,patient_age,doctor_name,lab_tech_id,lab_tech_name,
         total_fee,payment_method,payment_status,test_date)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (test_no,d['patient_name'],d.get('patient_age'),d.get('doctor_name',''),
         session['user_id'],session['full_name'],total_fee,
         d.get('payment_method','cash'),d.get('payment_status','paid'),
         d.get('test_date',date.today().isoformat())))
    lid = cur.lastrowid
    for item in d.get('items',[]):
        db.execute("INSERT INTO lab_test_items (lab_test_id,test_name,fee,result,notes) VALUES (?,?,?,?,?)",
            (lid,item['test_name'],float(item.get('fee',0)),item.get('result',''),item.get('notes','')))
    db.commit()
    lt = dict(db.execute("SELECT * FROM lab_tests WHERE id=?", (lid,)).fetchone())
    lt['items'] = rows(db.execute("SELECT * FROM lab_test_items WHERE lab_test_id=?", (lid,)))
    return jsonify(lt), 201

@app.route('/api/lab-tests/<int:lid>/cancel', methods=['POST'])
@login_required
@role_required('pharmacist_admin','doctor')
def cancel_lab_test(lid):
    d = request.json or {}
    db = get_db()
    db.execute("UPDATE lab_tests SET status='cancelled',cancelled_by=?,cancelled_reason=? WHERE id=?",
        (session['full_name'],d.get('reason',''),lid))
    db.commit()
    return jsonify({'ok':True})

# ─── STATS / PROFIT ────────────────────────────────────────────
@app.route('/api/stats')
@login_required
def get_stats():
    db = get_db()
    role = session.get('role')
    today = date.today().isoformat()
    # basic stats visible to all
    s = {
        'queue_count': db.execute("SELECT COUNT(*) FROM queue WHERE status='waiting' AND DATE(arrived_at)=?", (today,)).fetchone()[0],
        'served_count': db.execute("SELECT COUNT(*) FROM served_patients WHERE DATE(served_at)=?", (today,)).fetchone()[0],
        'total_medicines': db.execute("SELECT COUNT(*) FROM medicines").fetchone()[0],
        'expiring_soon': db.execute("SELECT COUNT(*) FROM medicines WHERE expiry_date BETWEEN date('now') AND date('now','+30 days')").fetchone()[0],
        'low_stock': db.execute("SELECT COUNT(*) FROM medicines WHERE stock<threshold").fetchone()[0],
        'today_consultations': db.execute("SELECT COUNT(*) FROM consultations WHERE visit_date=? AND status='active'",(today,)).fetchone()[0],
        'today_lab_tests': db.execute("SELECT COUNT(*) FROM lab_tests WHERE test_date=? AND status='active'",(today,)).fetchone()[0],
    }
    if role in ('pharmacist_admin','doctor'):
        # Medicines profit (only sold medicines)
        bill_rev  = db.execute("SELECT COALESCE(SUM(b.total),0) FROM bills b WHERE b.status='active'").fetchone()[0]
        med_profit = db.execute("SELECT COALESCE(SUM((bi.sell_price - bi.buy_price)*bi.quantity),0) FROM bill_items bi JOIN bills b ON bi.bill_id=b.id WHERE b.status='active' AND bi.is_free_sample=0").fetchone()[0]
        bill_cost = db.execute("SELECT COALESCE(SUM(bi.buy_price*bi.quantity),0) FROM bill_items bi JOIN bills b ON bi.bill_id=b.id WHERE b.status='active' AND bi.is_free_sample=0").fetchone()[0]
        free_val  = db.execute("SELECT COALESCE(SUM(m.sell_price*m.free_samples),0) FROM medicines m").fetchone()[0]
        # Consultation fees
        consult_fee = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE status='active' AND payment_status='paid'").fetchone()[0]
        # Lab fees
        lab_fee = db.execute("SELECT COALESCE(SUM(total_fee),0) FROM lab_tests WHERE status='active' AND payment_status='paid'").fetchone()[0]
        # Monthly
        month = date.today().strftime('%Y-%m')
        # Monthly calculates strict profit
        m_bill_rev  = db.execute("SELECT COALESCE(SUM(b.total),0) FROM bills b WHERE b.status='active' AND b.bill_date LIKE ?",(f"{month}%",)).fetchone()[0]
        m_med_profit = db.execute("SELECT COALESCE(SUM((bi.sell_price - bi.buy_price)*bi.quantity),0) FROM bill_items bi JOIN bills b ON bi.bill_id=b.id WHERE b.status='active' AND b.bill_date LIKE ? AND bi.is_free_sample=0",(f"{month}%",)).fetchone()[0]
        m_bill_cost = db.execute("SELECT COALESCE(SUM(bi.buy_price*bi.quantity),0) FROM bill_items bi JOIN bills b ON bi.bill_id=b.id WHERE b.status='active' AND b.bill_date LIKE ? AND bi.is_free_sample=0",(f"{month}%",)).fetchone()[0]
        m_consult   = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE status='active' AND payment_status='paid' AND visit_date LIKE ?",(f"{month}%",)).fetchone()[0]
        m_lab       = db.execute("SELECT COALESCE(SUM(total_fee),0) FROM lab_tests WHERE status='active' AND payment_status='paid' AND test_date LIKE ?",(f"{month}%",)).fetchone()[0]
        
        # Privacy filter based on role
        if role == 'doctor':
            bill_rev = bill_cost = free_val = med_profit = m_bill_rev = m_bill_cost = 0
        elif role == 'pharmacist_admin':
            consult_fee = m_consult = 0

        # Specific period (if requested, else today)
        date_from = request.args.get('date_from') or today
        date_to = request.args.get('date_to') or today
        
        d_bill_rev  = db.execute("SELECT COALESCE(SUM(b.total),0) FROM bills b WHERE b.status='active' AND b.bill_date>=? AND b.bill_date<=?",(date_from, date_to)).fetchone()[0]
        # Calculate exactly (sell - buy)*qty avoiding discount reduction
        d_med_profit = db.execute("SELECT COALESCE(SUM((bi.sell_price - bi.buy_price)*bi.quantity),0) FROM bill_items bi JOIN bills b ON bi.bill_id=b.id WHERE b.status='active' AND b.bill_date>=? AND b.bill_date<=? AND bi.is_free_sample=0",(date_from, date_to)).fetchone()[0]
        d_bill_cost = db.execute("SELECT COALESCE(SUM(bi.buy_price*bi.quantity),0) FROM bill_items bi JOIN bills b ON bi.bill_id=b.id WHERE b.status='active' AND b.bill_date>=? AND b.bill_date<=? AND bi.is_free_sample=0",(date_from, date_to)).fetchone()[0]
        d_consult   = db.execute("SELECT COALESCE(SUM(fee),0) FROM consultations WHERE status='active' AND payment_status='paid' AND visit_date>=? AND visit_date<=?",(date_from, date_to)).fetchone()[0]
        d_lab       = db.execute("SELECT COALESCE(SUM(total_fee),0) FROM lab_tests WHERE status='active' AND payment_status='paid' AND test_date>=? AND test_date<=?",(date_from, date_to)).fetchone()[0]
        if role == 'doctor': d_bill_rev = d_bill_cost = d_med_profit = 0
        elif role == 'pharmacist_admin': d_consult = 0
        s.update({
            'specific_med_profit': d_med_profit,
            'specific_med_revenue': d_bill_rev,
            'specific_med_cost': d_bill_cost,
            'specific_consult': d_consult,
            'specific_lab': d_lab,
            'specific_total': d_med_profit + d_consult + d_lab
        })

        s.update({
            'med_revenue': bill_rev, 'med_cost': bill_cost,
            'free_sample_value': free_val,
            'med_profit': med_profit,
            'consult_fee_total': consult_fee,
            'lab_fee_total': lab_fee,
            'net_profit': med_profit + consult_fee + lab_fee,
            'monthly_med_profit': m_med_profit,
            'monthly_consult': m_consult,
            'monthly_lab': m_lab,
            'monthly_total': m_med_profit + m_consult + m_lab,
        })
    return jsonify(s)

if __name__ == '__main__':
    init_db()
    print("\n" + "═"*58)
    print("   MediStore Pro — Multi-Role System")
    print("═"*58)
    print("   http://localhost:5000")
    print("   Pharmacist Admin : admin      / admin@123")
    print("   Doctor           : doctor1    / doctor@123")
    print("   Pharmacist Staff : pharmacist1/ pharma@123")
    print("   Lab Technician   : labtech1   / lab@123")
    print("═"*58+"\n")
    app.run(host='0.0.0.0', debug=False, port=5000)
