# Database for dashboard

## Dataset

**Source**: Crowdsourced data from Ctrip.com (similar to TripAdvisor)

**Scope**: 720 representative urban parks in 36 cities in China

**Volume**: Around 853,977 pieces of social media texts and 985,025 social media images in total

**Metadata**: Geotags and timestamps

## Database

### Data Ingestion into PostgreSQL

The orchestrator imports CSV files and images into PostgreSQL. The CSV files must contain columns like `city`, `park`, `username`, `comment`, `timestamp`, `rating`, and optionally `image` (relative path).

#### Upload posts and images in one command

Place CSV files in `data/csvs/` and images in `data/images/` on the host and run:

```bash
docker-compose run --rm orchestrator \
  --db-dsn "dbname=mydb user=myuser password=mypass host=postgres port=5432" \
    upload --csv-folder /data/csvs --image-folder /data/images
```

If the input is mounted under a generic container folder such as `/input`, pass
`--city` explicitly so the stored `posts.city` value does not fall back to the
mount name.

The pipeline stores original file locations in `images.path` and analyzes those
original files directly. PostgreSQL stores metadata only, not image binary blobs.

### Schema

PostgreSQL stores post/image/Qwen metadata in normalized tables. Image binaries remain on disk.

#### `posts`

| Column                 | Type      | Constraints     | Description |
| ---------------------- | --------- | --------------- | ----------- |
| `id`                   | SERIAL    | PRIMARY KEY     | Post identifier |
| `city`                 | TEXT      | NOT NULL        | City name |
| `park`                 | TEXT      | NOT NULL        | Park name |
| `username_hash`        | TEXT      | NOT NULL        | SHA256 hash for privacy |
| `comment`              | TEXT      |                 | User comment |
| `time`                 | TIMESTAMP |                 | Comment timestamp |
| `rating`               | TEXT      |                 | Rating value |
| `sentiment_score`      | REAL      |                 | Legacy/general sentiment score |
| `bert_sentiment_score` | REAL      |                 | Bert sentiment score |
| `bert_sentiment_label` | TEXT      |                 | Bert label |
| `qwen_sentiment_score` | REAL      |                 | Qwen sentiment score |
| `bert_status`          | TEXT      | NOT NULL, DEFAULT `pending` | Bert model row status |
| `bert_processing_started_at` | TIMESTAMP |          | Bert processing start time |
| `bert_error`           | TEXT      |                 | Last Bert failure message |
| `qwen_status`          | TEXT      | NOT NULL, DEFAULT `pending` | Qwen text model row status |
| `qwen_processing_started_at` | TIMESTAMP |          | Qwen text processing start time |
| `qwen_error`           | TEXT      |                 | Last Qwen text failure message |

#### `images`

| Column          | Type    | Constraints                    | Description |
| --------------- | ------- | ------------------------------ | ----------- |
| `id`            | SERIAL  | PRIMARY KEY                    | Image identifier |
| `post_id`       | INTEGER | FK → `posts(id)`, nullable     | Linked post (optional for standalone uploads) |
| `username_hash` | TEXT    |                                | Optional hash parsed from image/file context |
| `path`          | TEXT    |                                | Stored source/relative image path metadata |
| `analyzed_bio`  | BOOLEAN | NOT NULL, DEFAULT `FALSE`      | Marker to avoid repeated BioCLIP reprocessing |
| `bioclip_status` | TEXT   | NOT NULL, DEFAULT `pending`    | BioClip model row status |
| `bioclip_processing_started_at` | TIMESTAMP |               | BioClip processing start time |
| `bioclip_error` | TEXT    |                                | Last BioClip failure message |
| `qwen_status`   | TEXT    | NOT NULL, DEFAULT `pending`    | Qwen image model row status |
| `qwen_processing_started_at` | TIMESTAMP |                  | Qwen image processing start time |
| `qwen_error`    | TEXT    |                                | Last Qwen image failure message |

Model status lifecycle is `pending -> processing -> ready`, or `failed` on
error. Rows that remain in `processing` for more than 1 hour are reset to
`pending` before the next claim.

#### `image_species`

| Column       | Type    | Constraints                    | Description |
| ------------ | ------- | ------------------------------ | ----------- |
| `id`         | SERIAL  | PRIMARY KEY                    | Row identifier |
| `image_id`   | INTEGER | NOT NULL, FK → `images(id)`    | Associated image |
| `species`    | TEXT    | NOT NULL                       | BioCLIP species label |
| `confidence` | REAL    |                                | BioCLIP confidence score |

#### `image_activity`

| Column     | Type    | Constraints                    | Description |
| ---------- | ------- | ------------------------------ | ----------- |
| `id`       | SERIAL  | PRIMARY KEY                    | Row identifier |
| `image_id` | INTEGER | NOT NULL, FK → `images(id)`    | Associated image |
| `activity` | TEXT    | NOT NULL                       | Detected human activity (legacy/manual table) |

#### `post_qwen_detail`

| Column                                              | Type      | Constraints | Description |
| --------------------------------------------------- | --------- | ----------- | ----------- |
| `id`                                                | SERIAL    | PRIMARY KEY | Detail identifier |
| `post_id`                                           | INTEGER   | NOT NULL, FK → `posts(id)` | Linked post |
| `emotions`                                          | TEXT      |             | JSON/text emotions list |
| `influence_of_emotions`                             | TEXT      |             | Narrative explanation |
| `text_species_mentions`                             | TEXT      |             | Species entities from text |
| `feeling_correlated_to_text_species`                | TEXT      |             | Feeling correlation for species mentions |
| `text_activities_or_facilities`                     | TEXT      |             | Activity/facility mentions from text |
| `feeling_correlated_to_text_activities_or_facilities` | TEXT   |             | Feeling correlation for activities/facilities |
| `raw_response`                                      | TEXT      |             | Raw model output |
| `created_at`                                        | TIMESTAMP | DEFAULT NOW() | Creation timestamp |

#### `image_qwen_detail`

| Column               | Type    | Constraints                                      | Description |
| -------------------- | ------- | ------------------------------------------------ | ----------- |
| `id`                 | SERIAL  | PRIMARY KEY                                      | Detail row identifier |
| `image_id`           | INTEGER | NOT NULL, FK → `images(id)`, UNIQUE              | Linked image (one Qwen row per image) |
| `image_summary`      | TEXT    |                                                  | Image-level summary |
| `visible_species`    | TEXT    |                                                  | JSON-encoded visible species |
| `landscape_elements` | TEXT    |                                                  | JSON-encoded landscape elements |
| `human_activities`   | TEXT    |                                                  | JSON-encoded activities |
| `plants_detected`    | TEXT    |                                                  | JSON-encoded structured plant detections |
| `animals_detected`   | TEXT    |                                                  | JSON-encoded structured animal detections |
| `human_activities_detected` | TEXT |                                             | JSON-encoded structured human-activity detections |
| `raw_response`       | TEXT    |                                                  | Raw JSON model response |
| `created_at`         | TIMESTAMP | DEFAULT NOW()                                  | Creation timestamp |

> Qwen-image outputs are consolidated in `image_qwen_detail` and do **not** write into `image_species` / `image_activity`.

#### `ingestion_status`

| Column               | Type      | Constraints            | Description |
| -------------------- | --------- | ---------------------- | ----------- |
| `id`                 | SERIAL    | PRIMARY KEY            | Row identifier |
| `filename`           | TEXT      | UNIQUE                 | CSV/folder path tracked by orchestrator |
| `status`             | TEXT      |                        | Pipeline status (`processing`, `done`, etc.) |
| `last_processed_row` | INTEGER   |                        | Resume checkpoint |
| `created_at`         | TIMESTAMP | DEFAULT NOW()          | Initial insert time |
| `updated_at`         | TIMESTAMP |                        | Last status update |

```mermaid
classDiagram
    class posts {
        int id
        text city
        text park
        text username_hash
        text comment
        timestamp time
        text rating
        real sentiment_score
        real bert_sentiment_score
        text bert_sentiment_label
        real qwen_sentiment_score
    }
    class images {
        int id
        int post_id
        text username_hash
        text path
        bool analyzed_bio
    }
    class image_species {
        int id
        int image_id
        text species
        real confidence
    }
    class image_activity {
        int id
        int image_id
        text activity
    }
    class post_qwen_detail {
        int id
        int post_id
        text emotions
        text influence_of_emotions
        text text_species_mentions
        text feeling_correlated_to_text_species
        text text_activities_or_facilities
        text feeling_correlated_to_text_activities_or_facilities
        text raw_response
        timestamp created_at
    }
    class image_qwen_detail {
        int id
        int image_id
        text image_summary
        text visible_species
        text landscape_elements
        text human_activities
        text plants_detected
        text animals_detected
        text human_activities_detected
        text raw_response
        timestamp created_at
    }
    class ingestion_status {
        int id
        text filename
        text status
        int last_processed_row
        timestamp created_at
        timestamp updated_at
    }

    posts "1" <-- "0..*" images : has
    images "1" <-- "0..*" image_species : has
    images "1" <-- "0..*" image_activity : has
    posts "1" <-- "0..*" post_qwen_detail : details
    images "1" <-- "0..1" image_qwen_detail : details
```

### Postgres setup (local and Docker)

This project uses PostgreSQL for its primary datastore. Use one of the approaches below to create the database and user before running ingestion:

- Start PostgreSQL via Docker Compose (recommended for local development):

```bash
docker-compose up -d postgres
```

- Create the database and user inside the running container (example):

```bash
docker-compose exec postgres psql -U postgres -c "CREATE USER myuser WITH PASSWORD 'mypass'; CREATE DATABASE mydb; GRANT ALL PRIVILEGES ON DATABASE mydb TO myuser;"
```

- Or use the host `psql` client against the container:

```bash
# from host, after postgres container is up
psql -h localhost -U postgres -c "CREATE USER myuser WITH PASSWORD 'mypass'; CREATE DATABASE mydb; GRANT ALL PRIVILEGES ON DATABASE mydb TO myuser;"
```

Sample environment variables used by `docker-compose.yml` (already present in the repo):

```
POSTGRES_USER=myuser
POSTGRES_PASSWORD=mypass
POSTGRES_DB=mydb
```

Once the DB and user exist you can use the DSN shown below when running the orchestrator or other tools.

To connect to the PostgreSQL database directly:

To connect to the PostgreSQL database directly:

```bash
psql -U myuser -d mydb -h localhost -p 5432
```

Then run queries like:

```sql
SELECT COUNT(*) FROM posts;
SELECT COUNT(*) FROM images;
SELECT * FROM image_species WHERE image_id = 42;
SELECT id, post_id, created_at FROM post_qwen_detail ORDER BY created_at DESC LIMIT 10;
SELECT image_id, image_summary, plants_detected, animals_detected, human_activities_detected FROM image_qwen_detail LIMIT 10;
SELECT filename, status, last_processed_row FROM ingestion_status ORDER BY updated_at DESC NULLS LAST;
```

### Preview post render

You can load a post and render all associated images using Matplotlib and Pillow.

#### 1. Install dependencies

Make sure you have the plotting and image libraries:

```bash
pip install matplotlib pillow
```

**Chinese font (for CJK comments and titles)**

On Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y fonts-noto-cjk
```

Then confirm the font path (optional):

```bash
fc-list | grep "NotoSansCJK"
```

Update `FONT_PATH` in `src/database/render_post_with_id.py` if needed:

```python
FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
```

#### 2. Render a post by ID

From the project root:

```bash
python -m src.database.render_post_with_id 42 --db src/database/data.db
```

Where:

- `42` is the `posts.id` you want to inspect  
- `--db` points to a local SQLite database file

This will:

- open a Matplotlib window showing all images for the post (up to 3 columns, multiple rows)
- render a title showing City, Park, username hash, rating, time, and a wrapped comment
- print a copy‑pastable metadata block to the terminal for documentation or analysis.

**Chinese font (for CJK comments and titles)**

On Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y fonts-noto-cjk
```

Then confirm the font path (optional):

```bash
fc-list | grep "NotoSansCJK"
```

Update `FONT_PATH` in `src/database/render_post_with_id.py` if needed:

```python
FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
```
