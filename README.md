# 🚚 Spotter Trucks: Advanced ELD & HOS Engine

A professional, full-stack simulation platform designed to automate **Electronic Logging Device (ELD)** compliance and **Hours of Service (HOS)** reporting for the transportation industry. This system calculates complex driving rules and generates official, regulatory-compliant daily logs.

---

## 🚀 Key Features

### ⚖️ Regulatory Compliance (DOT Rules)
- **11-Hour Driving Limit:** Automatically enforces driving limits.
- **14-Hour Duty Limit:** Tracks combined on-duty and driving time.
- **70-Hour / 8-Day Cycle:** Cumulative tracking of cycle usage with automated **34-hour restart** logic.
- **Mandatory Breaks:** Integration of 30-minute rest breaks and 10-hour off-duty periods.
- **Morning Start Discipline:** Ensures workdays always begin at the driver's preferred start time.

### 📄 Professional PDF Reporting
- **Official Daily Log:** Generates multi-page PDFs mimicking official ELD forms.
- **Cumulative Recap:** Real-time calculation of "Hours available tomorrow" and cycle totals.
- **Automatic Mileage Tracking:** Individual segment mileage and daily totals calculated via routing.
- **Dynamic Remarks:** Automated inspection, fueling, and loading markers with specialized diagonal text styling.

### 🗺️ Interactive Route Simulation
- **Photon Geocoding:** Real-time location search and autocomplete.
- **OSRM Routing:** Professional-grade road network calculation for distance and duration.
- **Live Map:** Leaflet-based visualization of trip segments and stop markers.

---

## 🛠️ Tech Stack

- **Backend:** Python 3.x, Django 5.x.
- **PDF Engine:** PyMuPDF (fitz) for high-performance vector graphics.
- **Frontend:** React 18, Vite, TailwindCSS (Modern Glassmorphism UI).
- **APIs:** Photon (OpenStreetMap) & OSRM (Routing).
- **Deployment:** Optimized for Vercel (Serverless Functions + Static Hosting).

---

## 📂 Project Structure

```text
trucksLogs/
├── backend/                # Django Application
│   ├── core/               # Project Settings
│   ├── logs/               # HOS Engine, PDF Logic & API Views
│   └── requirements.txt    # Python Dependencies
├── frontend/               # React Application (Vite)
│   ├── src/
│   │   ├── components/     # UI Components (LogGrid, Map, etc.)
│   │   └── App.jsx         # Main Logic
│   └── package.json        # JS Dependencies
├── vercel.json             # Mono-repo deployment config
└── README.md               # Documentation
```

---

## ⚡ Quick Start

### Prerequisites
- Python 3.9+
- Node.js 18+

### 1. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

---

## 🌍 Deployment on Vercel

The project is pre-configured for a seamless Vercel deployment.
1. Connect your GitHub repository to Vercel.
2. Vercel will automatically detect `vercel.json`.
3. The backend will be deployed as a Python Serverless Function and the frontend as a static Vite app.

---

## 📝 License
Proprietary - Developed for Spotter Trucks.
