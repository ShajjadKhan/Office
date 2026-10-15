# OfficeWork — Monthly Attendance & Salary Suite

A standalone, automated monthly attendance timesheet and salary reporting suite built for hotel buyout personnel and outsourced staffing operations.

## Features
- **Dynamic Attendance Grid**: Interactive monthly calendar with auto Weekly Off (`WO`) assignments, configurable stamp codes (8h, WO, PH, SL, AL, A, V), and live totals calculation.
- **Shopping Cart System**:
  - **Associates Cart**: Remove associates on vacation or off-schedule from the active month report with 1 click (`✕`); re-add them anytime from the dropdown.
  - **Authorizer Signers Cart**: Add or remove report authorizers per month dynamically (e.g. if someone is on leave).
- **Official Report Exports**:
  - **Master Excel**: Comprehensive monthly attendance matrix with dynamic Excel `COUNTIF` formulas.
  - **Company Excels**: Multi-sheet workbook with Sheet 1 (Daily Attendance Matrix) and Sheet 2 (Overtime Transaction Records).
  - **Landscape PDFs**: Preformatted landscape A4 PDFs matching hotel standards with dynamic stamp badge styling and centered signature blocks.
  - **All-in-One ZIP**: Bundles all PDFs and Excel files in a single download.
- **Slide-Over Master Data Drawer**:
  - Authorizer signature titles & person names (e.g. Eng. Khalid Al-Otaibi).
  - Associates database (Name, Iqama, Company, Property, Dept).
  - Buyout companies & hotel properties.
  - Stamp definitions & hourly values.

## Tech Stack
- **Backend**: FastAPI, Uvicorn, Python 3
- **Reports**: OpenPyXL, ReportLab
- **Templates**: Jinja2, HTML5, CSS3, Vanilla JS
- **Process Supervisor**: Systemd (`officework.service`)

## Installation & Running
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn main:app --host 0.0.0.0 --port 1212
```

## Systemd Service
The application runs as a systemd service:
```bash
sudo systemctl status officework.service
sudo systemctl restart officework.service
```
