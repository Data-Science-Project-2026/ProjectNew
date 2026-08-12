DROP TABLE IF EXISTS top15_activity;

CREATE TABLE top15_activity AS

WITH activity_table AS (

    SELECT DISTINCT
        posts.id AS post_id,

        TRIM(
            regexp_replace(
                regexp_replace(
                    unnest(
                    string_to_array(
                        human_activities,
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

    FROM image_qwen_detail

    LEFT JOIN images
        ON images.id = image_qwen_detail.image_id

    LEFT JOIN posts
        ON images.post_id = posts.id

),


clean_activity AS (

    SELECT
        activity

    FROM activity_table

    WHERE activity IS NOT NULL
      AND activity <> ''

),


activity_count AS (

    SELECT

        activity,

        COUNT(*) AS number


    FROM clean_activity


    GROUP BY activity

),


ranked AS (

    SELECT

        activity,

        number,

        ROW_NUMBER() OVER(
            ORDER BY number DESC
        ) AS rank


    FROM activity_count

)


SELECT

    activity,

    number,

    rank


FROM ranked


WHERE rank <= 15


ORDER BY rank;