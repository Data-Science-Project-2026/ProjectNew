from fastapi import APIRouter, Query
from sqlalchemy import text
from database import engine


router = APIRouter(
    prefix="/api/species",
    tags=["species"]
)



@router.get("/map")
def species_map(
    genus: str = Query(...)
):

    sql = """

    SELECT

        province_en,

        province_zh,

        value


    FROM species_map_stats


    WHERE genus = :genus


    ORDER BY value DESC;


    """


    with engine.connect() as conn:


        rows = conn.execute(

            text(sql),

            {
                "genus": genus
            }

        )


        return [

            {
                "province_en":
                    r.province_en
                    if r.province_en
                    else r.province_zh,

                "province_zh":
                    r.province_zh,

                "value":
                    int(r.value)

            }

            for r in rows

            ]

@router.get("/trend")
def species_trend(
    genus: str = Query(...),
    year: int = Query(...)
):

    sql = """

        SELECT

            post_month,
            post_num

        FROM monthly_genus_stats

        WHERE

            genus=:genus

        AND CAST(post_year AS INTEGER)=:year

        ORDER BY post_month

        """


    with engine.connect() as conn:

        rows = conn.execute(
            text(sql),
            {
                "genus": genus,
                "year": year
            }
        )


        return [
            {
                "month": r.post_month,
                "value": r.post_num
            }
            for r in rows
        ]

@router.get("/years")
def species_years(
    genus: str = Query(...)
):

    sql = """

    SELECT DISTINCT

    CAST(post_year AS INTEGER) AS year

    FROM monthly_genus_stats

    WHERE genus = :genus

    AND CAST(post_year AS INTEGER) >= 2019

    ORDER BY year

    """

    with engine.connect() as conn:

        rows = conn.execute(
            text(sql),
            {
                "genus": genus
            }
        )


        return [
            r.year
            for r in rows
        ]
    

from fastapi import APIRouter, Query
from sqlalchemy import text
from database import engine


@router.get("/network")
def species_network(
    genus: str = Query(...)
):

    sql = """

    SELECT
        source,
        target,
        weight,
        type

    FROM cooccur_edges

    WHERE source = :genus

    ORDER BY weight DESC

    """

    with engine.connect() as conn:

        rows = conn.execute(
            text(sql),
            {
                "genus": genus
            }
        ).fetchall()


    if not rows:

        return {
            "nodes": [],
            "links": []
        }


    nodes = {}

    links = []


    for r in rows:


        # source 一定是 species

        if r.source not in nodes:

            nodes[r.source] = {

                "id": r.source,

                "type": "species",

                "weight": 1

            }


        # target 类型直接读取数据库

        if r.target not in nodes:

            nodes[r.target] = {

                "id": r.target,

                "type": r.type,

                "weight": float(r.weight)

            }


        links.append({

            "source": r.source,

            "target": r.target,

            "weight": float(r.weight)

        })


    return {

        "nodes": list(nodes.values()),

        "links": links

    }