DROP TABLE IF EXISTS response_trend_stats;


CREATE TABLE response_trend_stats AS


WITH response_post AS (


    SELECT DISTINCT


        pqd.post_id,


        TO_CHAR(
            p.time,
            'YYYY-MM'
        ) AS post_month,


        TO_CHAR(
            p.time,
            'YYYY'
        ) AS post_year,



        TRIM(

            regexp_replace(

                unnest(

                    string_to_array(

                        pqd.emotions,

                        ','

                    )

                ),

                '[\[\]"]',

                '',

                'g'

            )

        ) AS response



    FROM post_qwen_detail pqd



    JOIN posts p

        ON pqd.post_id = p.id



),



clean_data AS (


    SELECT *


    FROM response_post


    WHERE response IS NOT NULL

    AND response <> ''



),



response_month_count AS (


    SELECT


        post_year,


        post_month,


        response,



        COUNT(

            DISTINCT post_id

        ) AS post_num



    FROM clean_data



    GROUP BY


        post_year,


        post_month,


        response



)



SELECT


    post_year AS year,


    post_month AS month,


    response,


    post_num



FROM response_month_count



ORDER BY


    year,


    month,


    response;