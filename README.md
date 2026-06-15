#  SHE Management System - Backend

This is the backend API for the **Safety, Health, and Environment (SHE) Management System**, specifically designed to handle incident reporting, safety audits, and environmental compliance data for the energy and fuel sector.

---

##  Overview

Built with **FastAPI**, this backend provides a high-performance, scalable solution for managing workplace safety metrics. It serves as the data engine for the SHE Dashboard, ensuring that health and safety officers can track real-time data efficiently.

### Key Features
* **Incident Management:** Create, read, and track safety incidents.
* **SHE Metrics:** Aggregated data for dashboard visualizations.
* **Structured Validation:** Strict data integrity using Pydantic models.
* **Auto-Docs:** Interactive API documentation via Swagger and ReDoc.

---

##  Tech Stack

* **Framework:** [FastAPI](https://fastapi.tiangolo.com/)
* **Language:** Python 3.9+
* **Database:** SQLAlchemy / SQLModel
* **Server:** Uvicorn (ASGI)
* **Data Validation:** Pydantic

1. Environment Isolation
It is highly recommended to use a virtual environment:

Bash
# Create the environment
python -m venv venv

# Activate (Windows)
.\venv\Scripts\activate

# Activate (Mac/Linux)
source venv/bin/activate

2. Install Dependencies
Bash
pip install -r requirements.txt

uvicorn main:app --reload
API Documentation
FastAPI automatically generates documentation for your endpoints. You can access them here:

Swagger UI (Interactive): http://127.0.0.1:8000/docs

ReDoc (Structured): http://127.0.0.1:8000/redoc
