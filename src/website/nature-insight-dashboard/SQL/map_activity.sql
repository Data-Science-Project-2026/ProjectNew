DROP TABLE IF EXISTS activity_map_stats;


CREATE TABLE activity_map_stats AS


WITH activity_post AS (

    SELECT DISTINCT

        po.id AS post_id,

        p.province_en,

        p.province_zh,


        TRIM(
            regexp_replace(
                regexp_replace(
                    a.activity,
                    '[\[\]"{}]',
                    '',
                    'g'
                ),
                '^(activity:|activity=)',
                '',
                'i'
            )
        ) AS activity


    FROM image_qwen_detail q


    JOIN images i

        ON q.image_id=i.id


    JOIN posts po

        ON i.post_id=po.id


    JOIN parks_with_coordinates p

        ON po.park=p.park_name_in_post



    CROSS JOIN LATERAL

    unnest(

        string_to_array(
            q.human_activities,
            ','
        )

    ) AS a(activity)

),



activity_count AS (

    SELECT

        province_zh,

        activity,

        COUNT(DISTINCT post_id) AS value


    FROM activity_post


    WHERE activity IS NOT NULL

    AND activity <> ''


    GROUP BY

        province_zh,

        activity

)



SELECT


    cp.province_en,

    cp.province_zh,

    a.activity,


    COALESCE(
        ac.value,
        0
    ) AS value



FROM china_provinces cp



CROSS JOIN (

    SELECT DISTINCT activity

    FROM activity_count

) a



LEFT JOIN activity_count ac


ON cp.province_zh = ac.province_zh


AND a.activity = ac.activity;