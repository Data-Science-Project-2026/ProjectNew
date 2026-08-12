from fastapi import APIRouter, Query
from sqlalchemy import text

from database import engine


router = APIRouter()



@router.get("/top15")
def emotion_top15():

    sql = """

    SELECT

        emotion,
        count

    FROM top15_emotion

    ORDER BY count DESC

    """


    with engine.connect() as conn:

        rows = conn.execute(
            text(sql)
        ).fetchall()



    result = [

        {
            "emotion": row[0],
            "value": row[1]
        }

        for row in rows

    ]


    return result




@router.get("/map")
def emotion_map(

    emotion: str = Query(...)

):


    sql = """

    SELECT


        province_en,

        province_zh,

        value



    FROM human_response_map_stats



    WHERE emotion = :emotion



    ORDER BY value DESC


    """



    with engine.connect() as conn:


        rows = conn.execute(

            text(sql),

            {
                "emotion": emotion
            }

        ).fetchall()



    return [

        {

            "province_en": row[0],

            "province_zh": row[1],

            "value": row[2]

        }

        for row in rows

    ]


@router.get("/trend")
def emotion_trend(
    response: str = Query(...),
    year: str = Query(...)
):

    sql = """

    SELECT

        year,
        month,
        post_num

    FROM response_trend_stats

    WHERE response = :response

    AND year = :year

    ORDER BY month

    """


    with engine.connect() as conn:

        rows = conn.execute(
            text(sql),
            {
                "response": response,
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
def emotion_trend_years(
    response: str = Query(...)
):

    sql = """

    SELECT DISTINCT

        year

    FROM response_trend_stats

    WHERE response = :response
    AND CAST(year as INTEGER) >= 2019

    ORDER BY year

    """


    with engine.connect() as conn:

        rows = conn.execute(
            text(sql),
            {
                "response": response
            }
        )


        return [

            r.year

            for r in rows

        ]