DROP TABLE IF EXISTS activity_trend_stats;


CREATE TABLE activity_trend_stats AS


WITH activity_post AS (

    SELECT DISTINCT

        po.id AS post_id,

        TO_CHAR(
            po.time,
            'YYYY-MM'
        ) AS post_month,


        TO_CHAR(
            po.time,
            'YYYY'
        ) AS post_year,

        TRIM(
            regexp_replace(
                regexp_replace(
                    unnest(
                    string_to_array(
                        iqd.human_activities,
                        ','
                    )
                    ),
                    '[\[\]"{}]',
                    '',
                    'g'
                ),
                '^(activity:|activity=)',
                '',
                'i'
            )
        ) AS activity
        


    FROM image_qwen_detail iqd


    JOIN images img

        ON iqd.image_id = img.id


    JOIN posts po

        ON img.post_id = po.id



),



clean_data AS (


    SELECT *


    FROM activity_post


    WHERE activity IS NOT NULL

    AND activity <> ''

),



activity_month_count AS (


    SELECT

        post_year,

        post_month,

        activity,


        COUNT(
            DISTINCT post_id
        ) AS post_num


    FROM clean_data


    GROUP BY

        post_year,

        post_month,

        activity


)



SELECT

    post_year AS year,

    post_month AS month,

    activity,

    post_num


FROM activity_month_count


ORDER BY

    year,

    month,

    activity;