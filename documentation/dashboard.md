# Dashboard for Visualization of the Data

The project utilizes **Metabase** as the primary open-source tool for data visualization. It provides an intuitive interface for exploring biological datasets and social activity patterns collected from urban parks.

## System Architecture

The dashboard is fully containerized using **Docker**, ensuring a consistent environment from development to deployment.

*   **Core Engine**: Metabase (Open Source Edition).
*   **Database Backend**: PostgreSQL 17.
*   **Data Persistence**: 
    *   Metabase is configured to use an external PostgreSQL database to store its application data (dashboards, questions, and settings).
    *   All configurations and visualized data are persisted through a Docker volume: `./postgres_data:/var/lib/postgresql/data`. This ensures that all dashboard progress is saved even if containers are stopped or removed.

---

## Deployment

The Metabase service is managed via `docker-compose.yml`. The following environment variables link Metabase to the project's central database:

```yaml
 metabase:
    image: metabase/metabase:v0.58.1
    container_name: metabase_app
    restart: always
    depends_on:
      - db
    ports:
      - "3000:3000"
    environment:
      MB_DB_TYPE: postgres
      MB_DB_DBNAME: metabase_app_db
      MB_DB_PORT: 5432
      MB_DB_USER: dashboard
      MB_DB_PASS: dashboard
      MB_DB_HOST: db
```

---

## Visualized Content
The dashboard integrates diverse data sources into a unified view:

1. Species Analysis 
Genus Distribution: Visualizes the presence of various genera across parks.

Taxonomic Filtering: Allows users to filter data by kingdom (e.g., Animalia, Plantae) and species category.

Monthly Trends: Tracks the frequency of species observations over time (2019–2024), automatically filtering out genera with zero annual observations to maintain performance.

2. Custom External Integrations
Beyond native Metabase charts, we embed custom Python-generated interactive components using Iframe cards:

Co-occurrence Graphs: Visualizing biological relationships and social interactions via a FastAPI backend.

Custom Heatmaps: High-fidelity species distribution maps served through a secondary web service.

---

## Setup and Access

To restore the species data and Metabase dashboard configurations:

1. Navigate to the dashboard folder
   ```bash
      cd src/dashboard
   ```
2. Start the containers
   ```bash 
      docker-compose up -d
   ```
3. Access Dashboard
Open your browser and navigate to:
   ```bash
      http://localhost:3000
   ```
*Note: We use the `.dump` format (PostgreSQL Custom Format) for better compression and faster restoration.*
Metabase may ask you to enter your username and password: 
username: zhou_ruijia1119@163.com,
password: datascience5

Sync Data: Go to Admin Settings -> Databases and click "Sync database schema now" to ensure all imported data is visible.
