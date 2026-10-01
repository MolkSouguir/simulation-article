# SimulationApp

A Monte Carlo discrete-event simulation of a ventilator fleet. Models corrective failures (Weibull-distributed), preventive maintenance cycles, machine replacements, and standby pool management to compute lifecycle costs and availability metrics.

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14 (Windows service: `postgresql-x64-14`)

---

## First-time setup

### 1. Python virtual environment

```powershell
# Create the venv (one time only)
python -m venv .venv
```

### 2. Install Python dependencies

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure the database connection

Copy `.env.example` to `.env` in the project root and put in your PostgreSQL password.
`.env` is ignored by git; never commit it.

```powershell
copy .env.example .env
```

### 4. Initialize the database

Make sure PostgreSQL is running, then seed the database (run once):

```powershell
.venv\Scripts\activate
python -m db.seed
```

This creates the database named in `DATABASE_URL` if it doesn't exist yet, creates the tables, and loads
everything needed to run simulations:

- **Fleet configuration** — 45 ventilators (with their sensors and batteries) and 75 dialysis machines,
  their Weibull failure parameters, repair cost profiles and preventive maintenance cycles.
- **Scenario profile "Ventilator Alternatives AHP"** — 12 ventilator fleet alternatives (38, 41 or 45
  machines × replacement every 7, 9, 12 or 15 years) ranked with AHP on crisis availability, total cost
  and three analyst scores.

To run your first simulation, start the API and the frontend (see below), open the **Simulation** page,
click **Load Profile**, pick "Ventilator Alternatives AHP" and click **Run Simulation**. Build your own scenarios on the
**Scenarios** page.

Running the seed again resets the fleet configuration and deletes the simulation results; your
scenario profiles and saved runs (History page) are kept.

### 5. Install frontend dependencies

```powershell
cd frontend
npm install
```

---

## Running the app

Every time you open a new terminal you need to activate the virtual environment first.

### Activate the virtual environment

```powershell
# Run this from the SimulationApp root
.venv\Scripts\activate
```

You'll see `(.venv)` at the start of your prompt when it's active.

### Start the API (FastAPI)

```powershell
# From SimulationApp root, with venv active
uvicorn api.main:app --reload
```

API will be available at **<http://localhost:8000>**  
Interactive docs at **<http://localhost:8000/docs>**

### Start the frontend (SvelteKit)

Open a second terminal:

```powershell
cd frontend
npm run dev
```

Frontend will be available at **<http://localhost:5176>**

---

## Running the simulation (CLI)

```powershell
# Single simulation scenario
python app.py

# Full AHP analysis across all 12 scenarios
python -m analysis.ahp
```

---

## Project structure

```text
SimulationApp/
├── app.py                    # CLI entry point
├── database.py               # Global in-memory state
├── .env                      # DB connection (from .env.example, not committed)
├── classes/                  # Simulation runtime and decision methods
├── db/
│   ├── models/               # SQLModel ORM, one file per domain area
│   ├── session.py            # Engine + session factory
│   ├── loader.py             # DB → domain objects
│   ├── seed.py               # One-time seed: fleet config + ventilator scenario
│   └── persistence.py        # Domain objects → DB
├── services/
│   ├── simulation_service.py # run_simulation()
│   └── ahp_service.py        # run_ahp()
├── api/
│   ├── main.py               # FastAPI app + CORS
│   ├── dependencies.py       # DB session dependency
│   └── routers/              # Endpoints per entity, simulation runs, tools
├── analysis/
│   ├── runner.py             # 12 scenario configurations
│   ├── ahp.py                # AHP pipeline + Excel export
│   ├── sensitivity.py        # Sensitivity analysis
│   ├── statistics.py         # Confidence intervals, convergence, bootstrap ranks
│   └── report.py, pdf_report.py  # Excel and PDF reports
├── visualization/
│   ├── timeline.py           # Event timeline (Plotly)
│   └── availability.py       # Availability & failure charts
├── functions/
│   └── helper_functions.py   # Weibull math, availability utils
└── frontend/                 # SvelteKit web app
    ├── src/
    │   ├── lib/
    │   │   ├── api/          # Typed API client
    │   │   └── components/   # Reusable App* components
    │   └── routes/           # Page components
    └── vite.config.ts
```
