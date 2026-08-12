from fastapi import APIRouter, Query
from sqlalchemy import text
from database import engine


router = APIRouter(
    prefix="/api/activity",
    tags=["activity"]
)



@router.get("/filter-options")
def activity_filter_options():

    sql = """
    SELECT
        activity
    FROM top15_activity

    ORDER BY rank
    """


    with engine.connect() as conn:

        rows = conn.execute(
            text(sql)
        )


        activities = [
            r.activity
            for r in rows
        ]


    return {
        "activities": activities
    }



@router.get("/map")
def activity_map(
    activity: str = Query(...)
):


    sql = """

    SELECT

        province_en,

        province_zh,

        value


    FROM activity_map_stats


    WHERE activity = :activity


    ORDER BY value DESC


    """



    with engine.connect() as conn:


        rows = conn.execute(

            text(sql),

            {
                "activity": activity
            }

        ).fetchall()



        return [

            {

                "province_en":
                    r.province_en,


                "province_zh":
                    r.province_zh,


                "value":
                    int(r.value)

            }


            for r in rows

        ]


@router.get("/trend")
def activity_trend(
    activity: str = Query(...),
    year: str = Query(...)
):

    sql = """

        SELECT
            year,
            month,
            post_num

        FROM activity_trend_stats

        WHERE LOWER(TRIM(activity)) = LOWER(TRIM(:activity))

        AND year = :year

        ORDER BY month

"""


    with engine.connect() as conn:

        rows = conn.execute(
            text(sql),
            {
                "activity": activity,
                "year": year
            }
        )


        return [

            {
                "year": r.year,
                "month": r.month,
                "post_num": int(r.post_num)
            }

            for r in rows

        ]



@router.get("/trend-years")
def activity_trend_years(
    activity: str = Query(...)
):

    sql = """

    SELECT DISTINCT

        year

    FROM activity_trend_stats

    WHERE activity = :activity
    AND CAST(year as INTEGER) >= 2019

    ORDER BY year

    """


    with engine.connect() as conn:

        rows = conn.execute(
            text(sql),
            {
                "activity": activity
            }
        )


        return [

            r.year

            for r in rows

        ]