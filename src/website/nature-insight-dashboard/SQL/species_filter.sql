DROP TABLE IF EXISTS species_filter_options;


CREATE TABLE species_filter_options AS


WITH species_base AS (

    SELECT DISTINCT

        split_part(
            s.species,
            ' ',
            1
        ) AS genus


    FROM image_species s


    WHERE s.confidence > 0.4

)


SELECT DISTINCT


    cl.kingdom,

    cl.category,

    sb.genus



FROM species_base sb


JOIN species_details sd

    ON sb.genus =
       sd.scientific_name



JOIN category_list cl

    ON sd.category =
       cl.id



ORDER BY

    cl.kingdom,

    cl.category,

    sb.genus;