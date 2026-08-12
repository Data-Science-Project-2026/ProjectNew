DROP TABLE IF EXISTS cooccur_edges; 
CREATE TABLE cooccur_edges AS 
WITH species_split AS ( 
SELECT p.id, p.post_id, trim(v.species) AS species, trim(t.mention) AS mention 
FROM post_qwen_detail p CROSS JOIN LATERAL unnest(string_to_array(p.text_species_mentions, ',')) 
WITH ORDINALITY AS v(species, pos) JOIN LATERAL unnest(string_to_array(p.feeling_correlated_to_text_species, ',')) 
WITH ORDINALITY AS t(mention, pos) ON v.pos = t.pos ), 
species_match AS ( SELECT DISTINCT sp.id, sp.post_id, 
r.scientific_name AS matched_species, sp.species, cl.kingdom, 
regexp_replace( split_part(lower(sp.mention), '-', 2), '[\[\]"]', '', 'g' ) AS feeling 
FROM species_split sp 
JOIN species_details r 
ON ( lower(r.common_names) = lower(sp.species) ) OR ( lower(r.scientific_name) = lower(sp.species) OR split_part(lower(r.scientific_name), ' ', 1) = lower(sp.species) ) 
LEFT JOIN category_list cl 
ON r.category = cl.id 
WHERE lower(sp.species) NOT IN ('tree','grass','trees') 
AND regexp_replace( split_part(lower(sp.mention), '-', 2), '[\[\]"]', '', 'g' ) <> '' ), 
feeling_count AS ( SELECT matched_species, kingdom, feeling, 
COUNT(*) AS feeling_count 
FROM species_match 
GROUP BY matched_species, kingdom, feeling ), 
weighted AS ( SELECT *, feeling_count::float / SUM(feeling_count) OVER( PARTITION BY matched_species ) AS weight FROM feeling_count ), 
ranked AS ( SELECT *, ROW_NUMBER() OVER( PARTITION BY matched_species ORDER BY weight DESC ) 
AS rn FROM weighted ) 
SELECT matched_species as source, feeling as target, 
ROUND(weight::numeric,3) AS weight, 'emotion' as type
FROM ranked WHERE rn <= 5 ORDER BY matched_species, weight DESC ;
INSERT INTO cooccur_edges (source, target, weight, type) 
WITH target_species AS 
( SELECT DISTINCT i.image_id, sd.scientific_name AS species_a 
FROM image_species i 
JOIN species_details sd 
ON split_part( regexp_replace(lower(i.species), '\s+x\s+', ' '), ' ', 1 ) = lower(split_part(sd.scientific_name, ' ', 1)) 
WHERE i.Confidence > 0.4 ), 
all_species AS 
( SELECT DISTINCT image_id, split_part( regexp_replace(species, '\s+x\s+', ' '), ' ', 1 ) AS species_b 
FROM image_species 
WHERE Confidence > 0.4 ), 
co_occurrence AS 
( SELECT a.species_a, b.species_b, COUNT(DISTINCT a.image_id) AS co_count 
FROM target_species a 
JOIN all_species b ON a.image_id = b.image_id 
WHERE lower(a.species_a) <> lower(b.species_b) 
GROUP BY a.species_a, b.species_b ), 
with_category AS 
( SELECT c.species_a, c.species_b, c.co_count, cl.kingdom 
FROM co_occurrence c 
JOIN species_details sd ON lower(split_part(sd.scientific_name, ' ', 1)) = lower(c.species_a) 
LEFT JOIN category_list cl ON sd.category = cl.id ), 
weighted AS ( SELECT *, co_count::float / SUM(co_count) OVER(PARTITION BY species_a) AS weight 
FROM with_category ), 
ranked AS ( SELECT *, ROW_NUMBER() OVER(PARTITION BY species_a ORDER BY weight DESC) AS rn FROM weighted ) 
SELECT species_a AS source, species_b AS target, ROUND(weight::numeric, 4) AS weight, 'species' as type
FROM ranked WHERE rn <= 5 ORDER BY species_a, rn;