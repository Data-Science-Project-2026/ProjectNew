DROP TABLE IF EXISTS top15_emotion;

CREATE TABLE top15_emotion (
    emotion TEXT PRIMARY KEY,
    count INTEGER
);


INSERT INTO top15_emotion
SELECT
    TRIM(emotion) AS emotion,
    COUNT(*) AS count
FROM
    post_qwen_detail,
    unnest(string_to_array(emotions, ',')) AS emotion
WHERE
    emotions IS NOT NULL
    AND emotions <> ''
GROUP BY
    TRIM(emotion)
ORDER BY
    count DESC
LIMIT 15;