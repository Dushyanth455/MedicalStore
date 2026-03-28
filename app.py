import sqlite3, json, os
from datetime import datetime
from flask import Flask, request, jsonify, render_template, g

app = Flask(__name__)
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'medistore.db')

# ─── DB CONNECTION ────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def rows(cursor): return [dict(r) for r in cursor]

# ─── INIT DB ──────────────────────────────────────────────────
def init_db():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS medicines (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        manufacturer  TEXT DEFAULT '',
        category      TEXT DEFAULT 'Tablet',
        buy_price     REAL DEFAULT 0,
        sell_price    REAL DEFAULT 0,
        qty_bought    INTEGER DEFAULT 0,
        free_samples  INTEGER DEFAULT 0,
        stock         INTEGER DEFAULT 0,
        buy_date      TEXT,
        expiry_date   TEXT NOT NULL,
        batch_no      TEXT DEFAULT '',
        threshold     INTEGER DEFAULT 50,
        created_at    TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS queue (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        age         INTEGER,
        issue       TEXT DEFAULT '',
        priority    TEXT DEFAULT 'normal',
        arrived_at  TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS served_patients (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        queue_id    INTEGER,
        name        TEXT NOT NULL,
        age         INTEGER,
        issue       TEXT DEFAULT '',
        priority    TEXT DEFAULT 'normal',
        arrived_at  TEXT,
        served_at   TEXT DEFAULT (datetime('now','localtime')),
        notes       TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS sales (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_no     TEXT NOT NULL UNIQUE,
        patient     TEXT DEFAULT '',
        age         INTEGER,
        doctor      TEXT DEFAULT '',
        bill_date   TEXT,
        revenue     REAL DEFAULT 0,
        cost        REAL DEFAULT 0,
        profit      REAL DEFAULT 0,
        created_at  TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS sale_items (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id         INTEGER REFERENCES sales(id) ON DELETE CASCADE,
        medicine_id     INTEGER,
        medicine_name   TEXT,
        units           INTEGER DEFAULT 0,
        dosage          TEXT DEFAULT '',
        days            INTEGER DEFAULT 0,
        instructions    TEXT DEFAULT '',
        sell_price      REAL DEFAULT 0,
        buy_price       REAL DEFAULT 0,
        line_total      REAL DEFAULT 0
    );
    """)
    db.commit()

    if db.execute("SELECT COUNT(*) FROM medicines").fetchone()[0] == 0:
        meds = [
            ('Paracetamol 500mg','Cipla Ltd.','Tablet',2.50,4.00,200,20,220,'2025-01-10','2027-06-30','BT2024001',50),
            ('Amoxicillin 250mg','Sun Pharma','Capsule',8.00,14.00,100,10,38,'2025-02-15','2026-04-10','BT2024002',50),
            ('Cough Syrup 100ml','GSK India','Syrup',45.00,75.00,50,5,12,'2025-03-01','2026-03-15','BT2024003',50),
            ('Metformin 500mg','Lupin Ltd.','Tablet',3.00,6.00,300,30,300,'2025-01-20','2028-01-01','BT2024004',50),
            ('Azithromycin 500mg','Cipla Ltd.','Tablet',12.00,22.00,30,0,0,'2025-03-10','2026-04-20','BT2024005',50),
            ('Pantoprazole 40mg','Torrent Pharma','Tablet',5.00,9.50,150,15,165,'2025-02-01','2027-11-30','BT2024006',50),
            ('Atorvastatin 10mg','Sun Pharma','Tablet',6.00,11.00,200,20,220,'2025-01-05','2027-09-30','BT2024007',50),
            ('Cetirizine 10mg','Cipla Ltd.','Tablet',1.50,3.00,500,50,45,'2025-02-20','2026-05-01','BT2024008',50),
        ]
        db.executemany("""INSERT INTO medicines
            (name,manufacturer,category,buy_price,sell_price,qty_bought,free_samples,stock,buy_date,expiry_date,batch_no,threshold)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", meds)
        queue_seed = [
            ('Rajesh Kumar',45,'BP medication refill','normal'),
            ('Meena Devi',72,'Diabetes medicine','senior'),
            ('Arjun S.',28,'High fever — needs urgent attention','urgent'),
        ]
        db.executemany("INSERT INTO queue (name,age,issue,priority) VALUES (?,?,?,?)", queue_seed)
        db.commit()
    db.close()

# ─── FRONTEND ─────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

# ─── MEDICINES API ────────────────────────────────────────────
@app.route('/api/medicines', methods=['GET'])
def get_medicines():
    db = get_db()
    return jsonify(rows(db.execute("SELECT * FROM medicines ORDER BY name")))

@app.route('/api/medicines', methods=['POST'])
def add_medicine():
    d = request.json
    db = get_db()
    stock = int(d.get('qty_bought', 0)) + int(d.get('free_samples', 0))
    cur = db.execute("""INSERT INTO medicines
        (name,manufacturer,category,buy_price,sell_price,qty_bought,free_samples,stock,buy_date,expiry_date,batch_no,threshold)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d['name'], d.get('manufacturer',''), d.get('category','Tablet'),
         float(d.get('buy_price',0)), float(d.get('sell_price',0)),
         int(d.get('qty_bought',0)), int(d.get('free_samples',0)),
         stock, d.get('buy_date',''), d['expiry_date'],
         d.get('batch_no',''), int(d.get('threshold',50))))
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM medicines WHERE id=?", (cur.lastrowid,)).fetchone())), 201

@app.route('/api/medicines/<int:mid>', methods=['DELETE'])
def delete_medicine(mid):
    get_db().execute("DELETE FROM medicines WHERE id=?", (mid,))
    get_db().commit()
    return jsonify({'ok': True})

# ─── QUEUE API ────────────────────────────────────────────────
@app.route('/api/queue', methods=['GET'])
def get_queue():
    db = get_db()
    q = db.execute("""SELECT * FROM queue
        ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'senior' THEN 2 ELSE 3 END, id""")
    return jsonify(rows(q))

@app.route('/api/queue', methods=['POST'])
def add_queue():
    d = request.json
    db = get_db()
    cur = db.execute("INSERT INTO queue (name,age,issue,priority) VALUES (?,?,?,?)",
        (d['name'], d.get('age'), d.get('issue',''), d.get('priority','normal')))
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM queue WHERE id=?", (cur.lastrowid,)).fetchone())), 201

@app.route('/api/queue/<int:qid>/serve', methods=['POST'])
def serve_patient(qid):
    d = request.json or {}
    db = get_db()
    p = db.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone()
    if not p: return jsonify({'error': 'Not found'}), 404
    p = dict(p)
    db.execute("""INSERT INTO served_patients (queue_id,name,age,issue,priority,arrived_at,notes)
        VALUES (?,?,?,?,?,?,?)""",
        (p['id'], p['name'], p['age'], p['issue'], p['priority'], p['arrived_at'], d.get('notes','')))
    db.execute("DELETE FROM queue WHERE id=?", (qid,))
    db.commit()
    return jsonify({'ok': True, 'patient': p})

@app.route('/api/queue/<int:qid>', methods=['DELETE'])
def delete_queue(qid):
    get_db().execute("DELETE FROM queue WHERE id=?", (qid,))
    get_db().commit()
    return jsonify({'ok': True})

# ─── SERVED PATIENTS API ──────────────────────────────────────
@app.route('/api/served', methods=['GET'])
def get_served():
    return jsonify(rows(get_db().execute("SELECT * FROM served_patients ORDER BY served_at DESC")))

@app.route('/api/served/<int:sid>', methods=['DELETE'])
def delete_served(sid):
    get_db().execute("DELETE FROM served_patients WHERE id=?", (sid,))
    get_db().commit()
    return jsonify({'ok': True})

# ─── SALES API ────────────────────────────────────────────────
@app.route('/api/sales', methods=['GET'])
def get_sales():
    db = get_db()
    result = []
    for s in rows(db.execute("SELECT * FROM sales ORDER BY created_at DESC")):
        s['items'] = rows(db.execute("SELECT * FROM sale_items WHERE sale_id=?", (s['id'],)))
        result.append(s)
    return jsonify(result)

@app.route('/api/sales', methods=['POST'])
def create_sale():
    d = request.json
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    bill_no = 'BILL-{:04d}'.format(count + 1)
    cur = db.execute("""INSERT INTO sales (bill_no,patient,age,doctor,bill_date,revenue,cost,profit)
        VALUES (?,?,?,?,?,?,?,?)""",
        (bill_no, d.get('patient',''), d.get('age'), d.get('doctor',''),
         d.get('bill_date', datetime.now().strftime('%Y-%m-%d')),
         float(d.get('revenue',0)), float(d.get('cost',0)), float(d.get('profit',0))))
    sid = cur.lastrowid
    for it in d.get('items', []):
        db.execute("""INSERT INTO sale_items
            (sale_id,medicine_id,medicine_name,units,dosage,days,instructions,sell_price,buy_price,line_total)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (sid, it.get('medicine_id'), it.get('medicine_name',''),
             it.get('units',0), it.get('dosage',''), it.get('days',0),
             it.get('instructions',''), float(it.get('sell_price',0)),
             float(it.get('buy_price',0)), float(it.get('line_total',0))))
        db.execute("UPDATE medicines SET stock = MAX(0, stock - ?) WHERE id=?",
            (it.get('units',0), it.get('medicine_id')))
    db.commit()
    sale = dict(db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone())
    sale['items'] = rows(db.execute("SELECT * FROM sale_items WHERE sale_id=?", (sid,)))
    return jsonify(sale), 201

# ─── STATS API ────────────────────────────────────────────────
@app.route('/api/stats', methods=['GET'])
def get_stats():
    db = get_db()
    def one(q, *a): return db.execute(q, a).fetchone()[0]
    revenue   = one("SELECT COALESCE(SUM(revenue),0) FROM sales")
    cost      = one("SELECT COALESCE(SUM(cost),0) FROM sales")
    sample_v  = one("SELECT COALESCE(SUM(free_samples*sell_price),0) FROM medicines")
    return jsonify({
        'total_medicines': one("SELECT COUNT(*) FROM medicines"),
        'expiring_soon':   one("SELECT COUNT(*) FROM medicines WHERE expiry_date BETWEEN date('now') AND date('now','+30 days')"),
        'low_stock':       one("SELECT COUNT(*) FROM medicines WHERE stock < threshold"),
        'out_of_stock':    one("SELECT COUNT(*) FROM medicines WHERE stock = 0"),
        'queue_count':     one("SELECT COUNT(*) FROM queue"),
        'served_count':    one("SELECT COUNT(*) FROM served_patients"),
        'sales_count':     one("SELECT COUNT(*) FROM sales"),
        'revenue':         revenue,
        'cost':            cost,
        'sample_value':    sample_v,
        'net_profit':      revenue - cost + sample_v,
    })

if __name__ == '__main__':
    init_db()
    print("\n" + "═"*52)
    print("   MediStore Pro  —  Pharmacy Management")
    print("═"*52)
    print("   http://localhost:5000")
    print("   Database: medistore.db  (SQLite)")
    print("   Press Ctrl+C to stop")
    print("═"*52 + "\n")
    app.run(host='0.0.0.0', debug=False, port=5000)
