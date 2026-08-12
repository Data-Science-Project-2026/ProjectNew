from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import psycopg2

app = FastAPI()

# Allow the Metabase page (localhost:3000) to request your API (optional, but recommended)
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # Allow all ports, including the current 8080, to access
    allow_credentials=False,       # Must be False when origins is "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

# Before change
# GRAPH_HTML_PATH = os.path.join(os.path.dirname(__file__), "graph.html")

# After change: explicitly point to the html subfolder
BASE_DIR = os.path.dirname(__file__)
HTML_DIR = os.path.join(BASE_DIR, "html")
GRAPH_HTML_PATH = os.path.join(HTML_DIR, "graph.html")
MODIFIES_HTML_PATH = os.path.join(HTML_DIR, "species_modifies.html")

def get_conn():
    # Connect to the database defined in docker-compose in a unified way
    return psycopg2.connect(
        host=os.getenv("PGHOST", "db"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname="dashboard_database",  # Use the new database name
        user="dashboard",             # Use the new username
        password="dashboard",         # Use the new password
    )

def get_conn_species():
    # The logic is the same as above because all tables are now in one database
    return get_conn()

def add_iframe_headers(resp):
    # MutableHeaders does not have pop, so use del
    if "x-frame-options" in resp.headers:
        del resp.headers["x-frame-options"]

    # If CSP frame-ancestors was previously set, remove or reset it
    if "content-security-policy" in resp.headers:
        del resp.headers["content-security-policy"]

    # Allow embedding in an iframe (restrict the source as needed)
    # Note: frame-ancestors is recommended to specify your Metabase domain; for local use, http://localhost:3000 is okay for now
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'self' http://localhost:3000"

    return resp


@app.get("/graph.html")
def serve_graph_html():
    with open(GRAPH_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    resp = HTMLResponse(html)
    return add_iframe_headers(resp)

MAP_HTML_PATH = os.path.join(os.path.dirname(__file__), "species_map.html")


@app.get("/species_modifies.html")
def serve_species_modifies():
    with open(MODIFIES_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    resp = HTMLResponse(html)
    return add_iframe_headers(resp)  # Must call this function to inject headers

@app.get("/animals")
def animals():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source FROM cooccur_edges ORDER BY 1;")
        return [r[0] for r in cur.fetchall()]

@app.get("/graph")
def graph(animal: str):
    with get_conn() as conn, conn.cursor() as cur:
        # edges: only fetch neighbors of this animal (plant/emotion)
        cur.execute(
            "SELECT source, target, weight FROM cooccur_edges WHERE source=%s ORDER BY weight DESC;",
            (animal,),
        )
        edges = cur.fetchall()

        # node types (read from cooccur_nodes)
        type_map = {i: t for (i, t) in cur.fetchall()}

    # build nodes
    nodes = []
    # center node
    nodes.append({"id": animal, "type": "animal", "value": 1.0})
    # neighbor nodes
    seen = set([animal])
    for s, t, w in edges:
        if t not in seen:
            # type is obtained from type_map here; if missing, use a default value such as "unknown"
            nodes.append({"id": t, "type": type_map.get(t, "unknown"), "value": float(w)})
            seen.add(t)

    links = [{"source": s, "target": t, "value": float(w)} for (s, t, w) in edges]
    return {"center": animal, "nodes": nodes, "links": links}

@app.get("/api/species")
def get_species(city: str = Query(None)):
    with get_conn_species() as conn, conn.cursor() as cur:
        # Updated SQL:
        # 1. Extract the genus name (genus)
        # 2. Join species_details to get the category ID
        # 3. Join category_list to get the kingdom and category names
        query = """
            SELECT DISTINCT ON (i.post_id) 
                p.city_en, 
                p.latitude, 
                p.longitude, 
                split_part(s.species, ' ', 1) AS genus,
                cl.category AS category_name,
                cl.kingdom
            FROM image_species s 
            JOIN images i ON s.image_id = i.id 
            JOIN posts po ON i.post_id = po.id 
            JOIN parks_with_coordinates p ON po.park = p.park_name_in_post
            -- Key join --
            JOIN species_details sd ON split_part(s.species, ' ', 1) = sd.scientific_name
            JOIN category_list cl ON sd.category = cl.id
            --------------
            WHERE s.confidence > 0.4 
        """

        params = []
        if city:
            query += " AND p.city_en = %s"
            params.append(city)

        # query += " ORDER BY i.post_id, s.confidence DESC"

        cur.execute(query, params)
        rows = cur.fetchall()

    # Build the JSON returned to the frontend
    data = [
        {
            "city": r[0],
            "lat": float(r[1]),
            "lng": float(r[2]),
            "genus": r[3],    # Added
            "category": r[4], # Added
            "kingdom": r[5]   # Added
        }
        for r in rows
    ]

    return JSONResponse(data)


@app.get("/api/species_for_graph")
def get_species_for_graph():
    with get_conn() as conn, conn.cursor() as cur:
        query = """
        WITH all_names AS (
            SELECT source AS name FROM cooccur_edges
        )
        SELECT DISTINCT
            an.name,
            split_part(an.name, ' ', 1) AS genus,
            cl.kingdom,
            cl.category
        FROM all_names an
        JOIN species_details sd ON an.name = sd.scientific_name
        LEFT JOIN category_list cl ON sd.category = cl.id
        WHERE an.name IS NOT NULL AND trim(an.name) != ''
        """
        cur.execute(query)
        rows = cur.fetchall()
    # Group by genus and build the return format
    genus_map = {}
    for row in rows:
        name = row[0]
        genus = row[1] if row[1] else "Unknown genus"
        kingdom = row[2] if row[2] else "Uncategorised"
        category = row[3] if row[3] else "Uncategorised"
        if genus and genus not in genus_map:
            genus_map[genus] = {
                "kingdom": kingdom,
                "category": category,
                "species_example": name
            }

    data = [
        {
            "kingdom": info["kingdom"],
            "category": info["category"],
            "genus": genus,
            "species": info["species_example"]
        }
        for genus, info in genus_map.items()
    ]
    return JSONResponse(data)

