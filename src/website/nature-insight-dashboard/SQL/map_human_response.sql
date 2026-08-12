
DROP TABLE IF EXISTS human_response_map_stats;


CREATE TABLE human_response_map_stats (

    emotion TEXT,

    province_en TEXT,

    province_zh TEXT,

    value INTEGER,

    PRIMARY KEY (
        emotion,
        province_en
    )

);


INSERT INTO human_response_map_stats
(
    emotion,
    province_en,
    province_zh,
    value
)


SELECT

    TRIM(e.emotion) AS emotion,

    p.province_en,

    p.province_zh,

    COUNT(DISTINCT q.post_id) AS value


FROM

    post_qwen_detail q


JOIN posts po

ON q.post_id = po.id


JOIN parks_with_coordinates p

ON po.park = p.park_name_in_post



CROSS JOIN LATERAL

unnest(
    string_to_array(q.emotions, ',')
) AS e(emotion)



WHERE

    q.emotions IS NOT NULL

    AND q.emotions <> ''



GROUP BY

    TRIM(e.emotion),

    p.province_en,

    p.province_zh;