# OfficeWork — Monthly Attendance & Salary Suite

A standalone, multi-tenant automated monthly attendance timesheet, salary reporting, and roster management suite built specifically for hotel buyout personnel and outsourced staffing operations (e.g., **Marriott Executive Apartments**, **Riyadh Marriott Hotel**, **Staff Housing**).

---

## 🧭 Executive Context & Quick AI/Developer Brief

> **AI / Developer Onboarding**: Read this section first before starting any new development or restarting a work session.

- **Primary Repository**: Local workspace `/Users/shajjadkhan/Office` (branch `main`), pushed to `origin main` on GitHub (`https://github.com/ShajjadKhan/Office`).
- **Production Server (`sk`)**:
  - **Host / IP**: `sk` via SSH (`100.123.152.121`, standard port 22, user `sk`).
  - **Remote App Path**: `/home/sk/officework`.
  - **HTTP Port**: `1212` (running at `http://100.123.152.121:1212`).
  - **Systemd Service**: `officework.service`.
  - **Deployment Flow**:
    ```bash
    git add . && git commit -m "Description" && git push origin main
    ssh sk "cd /home/sk/officework && git pull origin main && echo 'S#imul7270733' | sudo -S systemctl restart officework && systemctl status officework --no-pager"
    ```
- **Credentials & Roles**:
  - **Master Admin**: Username `shajjad` (Role: `admin`). Accesses the Master Admin Control Panel (`/`), user provisioning, universal stamps, and cross-department inspection.
  - **Department Colleagues**: Example user `mahabubalam` (Password: `12345678`, Department: `MEA HK`). Accesses only their department workspace timesheet (`templates/index.html`) with strict isolation from other departments.

---

## 🏢 System Architecture & Multi-Tenancy Model

### 1. Master Admin vs. Department Colleague Portals
- **Master Admin Portal (`templates/admin.html`)**:
  - Dedicated exclusively to user provisioning and corporate universal stamp management.
  - Has zero departmental clutter (no authorizers, properties, or staff forms on admin home).
  - Can inspect any colleague's timesheet in read/manage mode via the top **🏢 Inspect Department** switcher without disrupting the colleague's session.
- **Department Timesheet Dashboard (`templates/index.html`)**:
  - Used by department heads/colleagues (e.g. Housekeeping, Engineering, Laundry).
  - Features an interactive month-by-month attendance matrix with fast schedule stamping, cycle modes, and real-time total calculations.
  - Slide-Over Setup Drawer (`⚙️ Setup & Data`) with tabs:
    1. **✍️ Signatures**: Official report authorizers with active/inactive toggles.
    2. **👥 Staff**: Associate roster (Name, Iqama, Company, Property, Department).
    3. **🏢 Departments**: Create and edit department codes (`0430`, `0431`, `ENG`, etc.).
    4. **🤝 Companies**: Third-party buyout/supply companies.
    5. **🏨 Properties**: Hotel locations (`MEA`, `RMH`, `Housing`).
    6. **🏷️ Stamps & Hours**: Work shift codes, hours, and color badge definitions.

### 2. Workspace Storage & Data Isolation
```text
data/
├── users.json                   # User accounts (salted PBKDF2-SHA256 hashes, roles, workspaces)
├── sessions.json                # Server-side active login sessions
├── stamps.json                  # Universal standard corporate stamps
├── .api_key                     # Desktop script & automation secret key
└── workspaces/
    ├── mahabubalam/             # Department workspace directory
    │   ├── associates.json      # Staff registered in this department
    │   ├── companies.json       # Buyout contractors for this department
    │   ├── properties.json      # Configured properties for this department
    │   ├── departments.json     # Sub-department codes (e.g. 0430 MEA HK, 0431 Laundry)
    │   ├── authorizers.json     # Department-specific signers
    │   ├── default_settings.json# Department header metadata
    │   ├── stamps.json          # Custom shift modifications (or synced universal)
    │   └── saved_months/
    │       └── 2026_10.json     # Full daily attendance records per year & month
    └── <other_workspaces>/
```

### 3. Shared Department Workspaces
When multiple colleagues belong to the same department (e.g., two colleagues in `MEA HK`), `services/auth_service.py` connects them to the **same shared workspace directory**.
- Colleagues in the same department automatically share staff rosters, companies, authorizers, and monthly attendance.
- Colleagues in different departments (e.g. Engineering vs. Housekeeping) remain strictly isolated in their own blank workspaces.

### 4. Blank-Slate Initial Provisioning
When a new user is created in a brand-new department:
- Their staff, companies, and authorizers start with a **clean blank slate** (no pre-existing data from other departments or Master Admin).
- **Universal Standard Stamps** (`8`, `WO`, `PH`, `SL`, `AL`, `A`, `V`) and **Standard Hotel Properties** (`MEA`, `RMH`, `Housing`) are automatically pre-seeded so the colleague can start creating timesheets immediately.

---

## 📜 Business Rules & Corporate Standards

### 1. Universal Work Stamps
Corporate attendance codes are synchronized across all properties to prevent confusion across accounting and payroll:
| Code | Meaning | Assigned Hours | Default Color Scheme |
| :--- | :--- | :---: | :--- |
| **`8`** | Regular Work | 8.0 hrs | Slate Light (`#F1F5F9` on `#334155`) |
| **`WO`** | Weekly Off | 8.0 hrs | Amber Warm (`#FEF3C7` on `#B45309`) |
| **`PH`** | Public Holiday | 8.0 hrs | Emerald Green (`#D1FAE5` on `#065F46`) |
| **`SL`** | Sick Leave | 8.0 hrs | Sky Blue (`#E0F2FE` on `#0369A1`) |
| **`AL`** | Annual Leave | 0.0 hrs | Indigo Accent (`#E0E7FF` on `#3730A3`) |
| **`A`** | Absent | 0.0 hrs | Rose Red (`#FEE2E2` on `#991B1B`) |
| **`V`** | Vacation | 0.0 hrs | Pink Dark (`#FFE4E6` on `#9F1239`) |

*A 1-click **🔄 Restore Universal Stamps** button is available in both Master Admin and Department Drawer to instantly re-align codes.*

### 2. Official Hotel Properties (Never Append "Property")
Reports must always display the official corporate hotel name, never raw short codes or artificial suffixes like `"MEA Property"`:
- **`MEA`** / **`AL WIZARAT`** &rarr; **`Marriott Executive Apartments`**
- **`RMH`** / **`HQ`** &rarr; **`Riyadh Marriott Hotel`**
- **`Housing`** &rarr; **`Staff Housing`**
- Handled dynamically via `resolve_property_full_name()` in `main.py`.

### 3. Attendance Calculation Formulas
- **Calendar Days**: Dynamically determined by `calendar.monthrange(year, month)`.
- **Paid Days**: Count of days stamped with paid codes (`8`, `WO`, `PH`, `SL`).
- **Total Work Hours**: Sum of all assigned hours for each day of the month.
- **Overtime (OT) Hours**: `Total Work Hours - (Paid Days * 8)`.

---

## 🖨️ Official Document Exports

1. **Printable HTML Preview (`/print/{group_key}`)**:
   - Clean landscape A4 format ready for browser printing or saving as PDF (`Ctrl/Cmd + P`).
   - Includes official hotel title, company name, transaction period, daily grid, and bottom signature blocks.
2. **Company Excel (`/api/export/single-excel/{group_key}`)**:
   - Multi-sheet `.xlsx` formatted according to corporate financial audit standards.
   - **Sheet 1**: Daily attendance matrix with live Excel `COUNTIF` formulas.
   - **Sheet 2**: Overtime transaction breakdown.
3. **Landscape PDF (`/api/export/single-pdf/{group_key}`)**:
   - Generated via ReportLab with corporate font styling, badge colors, and dynamic authorizer signature lines.
4. **All-in-One ZIP (`/api/export/all-zip`)**:
   - Bundles all individual company Excels and PDFs plus the Master Roster into a single structured ZIP archive.

---

## 🛠️ Tech Stack & Dependencies

- **Language / Runtime**: Python 3.10+ (Server runs Python 3.12 in `/home/sk/officework/venv`).
- **Web Framework**: FastAPI with Starlette & Uvicorn.
- **Templating**: Jinja2 (`templates/admin.html`, `templates/index.html`, `templates/report_print.html`, `templates/login.html`).
- **Spreadsheets**: `openpyxl` with custom cell styling, borders, and pattern fills (`services/excel_generator.py`).
- **PDF Generation**: `reportlab` with Platypus flowable tables and canvas drawing (`services/pdf_generator.py`).
- **Process Supervisor**: Linux Systemd (`/etc/systemd/system/officework.service`).

---

## ⚙️ Maintenance, Deployment & Troubleshooting

### Daily Operations on Server (`sk`)
```bash
# Connect to server
ssh sk

# Navigate to project
cd /home/sk/officework

# View service status
systemctl status officework --no-pager

# Restart service after updates
echo 'S#imul7270733' | sudo -S systemctl restart officework

# Inspect live service logs
journalctl -u officework -f
```

### Git Update Procedure
```bash
# Pull latest changes from GitHub
git pull origin main

# Restart the application service
echo 'S#imul7270733' | sudo -S systemctl restart officework
```

### Running Locally for Development
```bash
# Clone and enter repo
cd /Users/shajjadkhan/Office

# Activate virtualenv (if configured) or run python
uvicorn main:app --host 0.0.0.0 --port 1212 --reload
```

---

## 📁 Repository Structure

```text
Office/
├── README.md                      # Comprehensive developer & AI onboarding guide
├── main.py                        # FastAPI application routes, monthly state, exports
├── requirements.txt               # Python package dependencies
├── services/
│   ├── auth_service.py            # Password hashing, user management, workspace isolation
│   ├── smart_attendance.py        # Calendar generation, stamp calculations, totals
│   ├── excel_generator.py         # OpenPyXL master & company timesheets
│   └── pdf_generator.py           # ReportLab landscape timesheet PDFs
├── templates/
│   ├── admin.html                 # Master Admin Control Panel (User provisioning, stamps)
│   ├── index.html                 # Department timesheet matrix & slide-over data drawer
│   ├── login.html                 # Secure login page
│   └── report_print.html          # Clean A4 printable report preview
├── static/                        # CSS, JS, corporate logos, and icons
└── data/                          # JSON data store, workspaces, and saved months
```
