from fastapi import FastAPI
from contextlib import asynccontextmanager

from routers import species, activity, emotion

from sqlalchemy import text
from database import engine

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from pathlib import Path
import sys
import threading
import webbrowser
import time



# =========================
# Browser startup
# =========================


@asynccontextmanager
async def lifespan(app: FastAPI):

    yield



app = FastAPI(
    lifespan=lifespan
)



# ==================================================
# Path configuration
# ==================================================

if getattr(sys, "frozen", False):

    # PyInstaller onefile
    BASE_DIR = Path(sys._MEIPASS)

else:

    # normal python execution
    BASE_DIR = Path(__file__).resolve().parent


PROJECT_ROOT = BASE_DIR.parent

CANDIDATE_FRONTEND_DIRS = [
    BASE_DIR / "static" / "dist",
    PROJECT_ROOT / "dist",
    BASE_DIR / "dist",
]

FRONTEND_DIR = next(
    (
        candidate
        for candidate in CANDIDATE_FRONTEND_DIRS
        if candidate.exists() and (candidate / "index.html").exists()
    ),
    CANDIDATE_FRONTEND_DIRS[0],
)

ASSET_DIR = FRONTEND_DIR / "assets"





# ==================================================
# CORS
# ==================================================

app.add_middleware(

    CORSMiddleware,

    allow_origins=[

        "http://localhost:5173",
        "http://127.0.0.1:5173"

    ],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)





# ==================================================
# API routers
# ==================================================

app.include_router(
    species.router
)


app.include_router(
    activity.router
)


app.include_router(
    emotion.router,
    prefix="/api/emotion"
)





# ==================================================
# Vue frontend
# ==================================================

if ASSET_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=ASSET_DIR),
        name="assets",
    )





@app.get("/")
def serve_frontend():

    return FileResponse(

        FRONTEND_DIR
        /
        "index.html"

    )








# ==================================================
# Species filter API
# ==================================================

@app.get(
    "/api/species/filter-options"
)
def get_species_filter_options():


    sql = """

    SELECT

        kingdom,

        category,

        genus


    FROM species_filter_options


    ORDER BY

        kingdom,

        category,

        genus

    """



    with engine.connect() as conn:


        rows = conn.execute(
            text(sql)
        ).fetchall()



    hierarchy = {}



    for row in rows:


        kingdom = row[0]

        category = row[1]

        genus = row[2]



        if kingdom not in hierarchy:

            hierarchy[kingdom] = {}



        if category not in hierarchy[kingdom]:

            hierarchy[kingdom][category] = set()



        hierarchy[kingdom][category].add(
            genus
        )



    result = {


        "kingdoms":

            list(
                hierarchy.keys()
            ),


        "categories": {},


        "genera": {}

    }



    for kingdom, categories in hierarchy.items():


        result["categories"][kingdom] = (

            list(
                categories.keys()
            )

        )



        for category, genera in categories.items():


            result["genera"][category] = (

                sorted(
                    list(genera)
                )

            )



    return result


@app.get("/{full_path:path}")
def serve_spa(full_path: str):

    requested_file = FRONTEND_DIR / full_path

    if requested_file.is_file():
        return FileResponse(requested_file)

    return FileResponse(FRONTEND_DIR / "index.html")



if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_config=None
    )

