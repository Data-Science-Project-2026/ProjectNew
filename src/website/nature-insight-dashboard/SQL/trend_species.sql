DROP TABLE IF EXISTS monthly_genus_stats;

CREATE TABLE monthly_genus_stats AS

WITH actual_data AS (

    SELECT 
        TO_CHAR(p.time, 'YYYY-MM') AS post_month,
        TO_CHAR(p.time, 'YYYY') AS post_year,

        split_part(i.species, ' ', 1) AS genus,

        i.species,

        p.id AS post_id,

        cl.kingdom AS species_kingdom,

        cl.category AS species_category


    FROM image_species i


    JOIN images img 
        ON i.image_id = img.id


    JOIN posts p 
        ON img.post_id = p.id


    JOIN species_details sd 
        ON split_part(i.species,' ',1)
        =
        sd.scientific_name


    JOIN category_list cl 
        ON sd.category = cl.id


    WHERE i.confidence > 0.4

),



/*
每个 genus 实际出现过的年份
*/

genus_year AS (

    SELECT DISTINCT

        genus,

        post_year,

        species_kingdom,

        species_category


    FROM actual_data

),



/*
只对存在数据的 genus-year 补月份
*/

month_grid AS (

    SELECT

        gy.genus,

        gy.post_year,

        gy.species_kingdom,

        gy.species_category,


        TO_CHAR(
            make_date(
                gy.post_year::int,
                m.month,
                1
            ),
            'YYYY-MM'
        ) AS post_month


    FROM genus_year gy


    CROSS JOIN generate_series(
        1,
        12
    ) AS m(month)

)



SELECT


    mg.post_year,

    mg.post_month,

    mg.genus,

    mg.species_kingdom,

    mg.species_category,


    COUNT(DISTINCT ad.post_id)
        AS post_num



FROM month_grid mg



LEFT JOIN actual_data ad

ON
    mg.genus = ad.genus

AND
    mg.post_month = ad.post_month



GROUP BY

    mg.post_year,

    mg.post_month,

    mg.genus,

    mg.species_kingdom,

    mg.species_category



ORDER BY

    mg.post_month,

    mg.genus;