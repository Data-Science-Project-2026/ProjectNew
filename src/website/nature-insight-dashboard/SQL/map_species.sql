DROP TABLE IF EXISTS species_map_stats;


CREATE TABLE species_map_stats AS


WITH species_post AS (

    SELECT DISTINCT

        po.id AS post_id,

        p.province_en,

        p.province_zh,

        split_part(
            s.species,
            ' ',
            1
        ) AS genus


    FROM image_species s


    JOIN images i

        ON s.image_id = i.id


    JOIN posts po

        ON i.post_id = po.id


    JOIN parks_with_coordinates p

        ON po.park = p.park_name_in_post


    WHERE

        s.confidence > 0.4

),



genus_province_count AS (

    SELECT

        genus,

        province_en,

        province_zh,

        COUNT(
            DISTINCT post_id
        ) AS value


    FROM species_post


    GROUP BY

        genus,

        province_en,

        province_zh

),



all_genus AS (

    SELECT DISTINCT

        genus

    FROM species_post

)



SELECT

    g.genus,

    cp.province_en,

    cp.province_zh,


    COALESCE(

        gpc.value,

        0

    ) AS value



FROM all_genus g



CROSS JOIN china_provinces cp



LEFT JOIN genus_province_count gpc


ON

    g.genus = gpc.genus

AND

    cp.province_en = gpc.province_en



ORDER BY

    g.genus,

    value DESC;