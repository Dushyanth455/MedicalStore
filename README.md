# MediStore Pro — Pharmacy Management System

## Quick Start

### 1. Install dependency
```bash
pip install flask
```

### 2. Run the app
```bash
python start.py
```
**Or** directly:
```bash
python app.py
```

### 3. Open in browser
```
http://localhost:5000
```
> Requires internet connection for Google Fonts, Lucide Icons, and Animate.css CDN.

---

## Features

| Module | What it does |
|---|---|
| **Dashboard** | Live metrics — profit, alerts, queue, served count |
| **Inventory** | Add/delete medicines with expiry, stock, free samples |
| **Billing** | Create bills, dosage, days, print receipts |
| **Patient Queue** | Add patients, priority sorting (urgent/senior/normal) |
| **Served Patients** | Full history with notes, card & table view, filter by date |
| **Alerts** | Expiry alerts (30d) + Low stock (< threshold) |
| **Profit & Loss** | Revenue, cost, free sample value, net profit |

## Database — SQLite (`medistore.db`)

| Table | Contents |
|---|---|
| `medicines` | Inventory with stock, pricing, expiry, batches |
| `queue` | Currently waiting patients |
| `served_patients` | All served patients with arrival/served timestamps & notes |
| `sales` | Bill headers |
| `sale_items` | Per-medicine line items per bill |

## Project Files

```
medistore_web/
├── app.py           ← Flask backend + REST API
├── start.py         ← Easy launcher (opens browser automatically)
├── medistore.db     ← SQLite database (auto-created on first run)
├── README.md
└── templates/
    └── index.html   ← Frontend (uses Google Fonts + Lucide Icons CDN)
```

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | /api/medicines | List all medicines |
| POST | /api/medicines | Add medicine |
| DELETE | /api/medicines/:id | Delete medicine |
| GET | /api/queue | List waiting patients |
| POST | /api/queue | Add patient to queue |
| POST | /api/queue/:id/serve | Move to served patients |
| DELETE | /api/queue/:id | Remove from queue |
| GET | /api/served | List all served patients |
| DELETE | /api/served/:id | Delete served record |
| GET | /api/sales | List all sales |
| POST | /api/sales | Create sale + deduct stock |
| GET | /api/stats | Aggregated dashboard stats |
