# Dashboard for Visualization of the Data

The project utilizes **Metabase** as the primary open-source tool for data visualization. It provides an intuitive interface for exploring biological datasets and social activity patterns collected from urban parks.

## Dashboard Data Pipeline

The dashboard relies on a set of precomputed analytical tables rather than querying raw data directly.  
All data processing, transformation, and feature engineering are implemented in:

```text
src/dashboard/data script/script.ipynb
```

This notebook is the core data pipeline of the project, responsible for building all datasets required by Metabase dashboards and custom visualization components.

---

## Overview of Data Processing Workflow

The pipeline follows a structured ETL (Extract → Transform → Load) process:

1. Database restoration from dump files  
2. Reference dataset integration  
3. Feature engineering and aggregation  
4. Network construction (co-occurrence & emotion analysis)  
5. Dashboard-ready table generation  

---

## 1. Database Initialization

The pipeline starts by rebuilding the PostgreSQL database from a dump file.

### Input:
- `dashboard_database.dump`

### Operations:
- Stop existing database connections
- Drop and recreate the database
- Restore schema and raw data using PostgreSQL Docker container

This ensures a clean and reproducible environment for all downstream analysis.

---

## 2. Reference Data Loading

The following external datasets are imported into PostgreSQL:

### Species Classification
```text
Category1.csv
List_of_Species.csv
```

These files are used to construct:
- `category_list`
- `species_details`

Functions:
- Standardize taxonomy hierarchy (kingdom → genus → species)
- Map scientific names to common names
- Enable filtering in dashboard visualizations

---

### Geographic Data
```text
parks_with_coordinates.xlsx
```

Used to create:
- `parks_with_coordinates`

Functions:
- Provide latitude/longitude for visualization
- Normalize park-level geographic identifiers
- Support map-based dashboards

---

## 3. Time-Series Feature Engineering

### Output Table:
```text
monthly_genus_stats
```

### Purpose:
Used for monthly trend analysis of species observations (2019–2024).

### Processing Steps:
- Extract species occurrences from image data
- Filter low-confidence detections
- Map species to genus-level taxonomy
- Aggregate monthly counts
- Fill missing months with zero values

### Used in:
- Trend charts
- Genus-level comparison
- Temporal filtering dashboards

---

## 4. Geographic Aggregation

### Output Table:
```text
province_park_stats
```

### Purpose:
Provides park distribution statistics across provinces.

### Processing Steps:
- Aggregate parks by administrative region
- Normalize region names
- Count total parks per province

### Used in:
- Geographic overview maps
- Regional comparison visualizations

---

## 5. Co-occurrence & Emotion Network

### Output Table:
```text
cooccur_edges
```

This table combines two relationship types:

### (1) Species–Emotion Relationships
- Extract emotions from textual descriptions
- Map emotions to detected species
- Compute frequency-based weights

Example:
```text
Bird → Relaxing
Flower → Beautiful
Butterfly → Peaceful
```

---

### (2) Species–Species Co-occurrence
- Detect multiple species in the same image
- Compute co-occurrence frequency
- Normalize weights
- Keep top-5 strongest relationships per species

Example:
```text
Sparrow → Tree
Butterfly → Flower
Lotus → Dragonfly
```

Used in:
- Network graphs
- Interactive relationship visualization

---

## 6. Top-K Ranking Features

### Output Table:
```text
top10_things
```

### Purpose:
Provides ranked lists for dashboard visualization.

### Categories:

#### Species Ranking
Based on:
- Number of posts containing each species

#### Activity Ranking
Based on:
- Frequency of detected human activities

### Output Schema:
```text
Category | Item | Count | Rank
```

### Used in:
- Top-10 charts
- Ranking visualizations

---

## Final Generated Tables

The notebook produces the following structured datasets:

| Table Name | Description |
|-------------|------------|
| `category_list` | Taxonomy classification |
| `species_details` | Species reference mapping |
| `parks_with_coordinates` | Geographic metadata |
| `monthly_genus_stats` | Temporal trend analysis |
| `province_park_stats` | Regional statistics |
| `cooccur_edges` | Species relationship network |
| `top10_things` | Ranking metrics |

---

## Notes

- All tables are designed for direct consumption by Metabase dashboards.
- The pipeline should be re-run after any update to the raw database.
- Outputs are optimized for visualization performance and filtering efficiency.

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

1. Download the Dashboard Database Dump

   The dashboard database dump is not stored in the GitHub repository due to its large size.

   Download the file from the following link:

   https://helsinkifi-my.sharepoint.com/:u:/g/personal/zhouruij_ad_helsinki_fi/IQACZMAp8x8KRZv_u04JiRaxAZ1o4d96NlRD13X-Wc2M92A?e=NSg8oL

   After downloading, move the dump file into:

   ```text
   src/dashboard/db/init/
   ```

   The folder should contain:

   ```text
   src/dashboard/db/init/
   ├── dashboard_database.dump
   └── metabase_app_db.dump
   ```

2. Navigate to the dashboard folder
   ```bash
      cd src/dashboard
   ```
3. Start the containers
   ```bash 
      docker-compose up -d
   ```
4. Access Dashboard
Open your browser and navigate to:
   ```bash
      http://localhost:3000
   ```
*Note: We use the `.dump` format (PostgreSQL Custom Format) for better compression and faster restoration.*
Metabase may ask you to enter your username and password: 
username: zhou_ruijia1119@163.com,
password: datascience5

Sync Data: Go to Admin Settings -> Databases and click "Sync database schema now" to ensure all imported data is visible.
