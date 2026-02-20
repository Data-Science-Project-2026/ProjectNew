from openai import OpenAI
from base64 import b64encode
from pathlib import Path


def image_file_to_data_url(image_path: str) -> str:
  path = Path(image_path)
  suffix = path.suffix.lower()
  mime_type_map = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
  }
  mime_type = mime_type_map.get(suffix, "application/octet-stream")
  encoded = b64encode(path.read_bytes()).decode("utf-8")
  return f"data:{mime_type};base64,{encoded}"

client = OpenAI(
    api_key="EMPTY",
    base_url="http://localhost:8000/v1",
)

image_1 = image_file_to_data_url("/home/dream/ProjectDATA/3Tianjin/3_1_Panshan_Scenic_Area_Jizhou_District_Tianjin/class_0/1天津市蓟州区盘山_203821_1.jpg")
image_2 = image_file_to_data_url("/home/dream/ProjectDATA/3Tianjin/3_1_Panshan_Scenic_Area_Jizhou_District_Tianjin/class_0/1天津市蓟州区盘山_203821_2.jpg")
image_3 = image_file_to_data_url("/home/dream/ProjectDATA/3Tianjin/3_1_Panshan_Scenic_Area_Jizhou_District_Tianjin/class_0/1天津市蓟州区盘山_203821_3.jpg")

response = client.chat.completions.create(
    model="Qwen/Qwen3-VL-8B-Instruct-FP8",
    messages=[{"role": "system", "content": """
You are a multimodal ecology + behavior analyst. You will be given:
1) A set of images taken by ONE user at the CURRENT location (a park) during a single visit or short time window.
2) The user’s comment text for this post.

Your tasks:
A) Across ALL images, identify EVERY distinct PLANT species and ANIMAL species visible.
   - Provide the most specific identification possible.
   - Use Latin scientific names (binomial: Genus species). If you can only identify to genus/family, use the best available taxonomic level and mark it explicitly (e.g., "Quercus sp." or "Asteraceae sp.").
   - Do NOT invent species. If unsure, output your best guess with a confidence score, or use "unknown" with a low confidence.
   - Deduplicate across images: return a unique list of species for the whole set.
   - For each species, include an approximate quantity descriptor: "1" or "multiple".
   - If multiple images show the same species, the quantity should reflect the total across the set (still "1" or "multiple").
   - Optionally indicate which image indices support each detection.

B) Detect human activities visible in the images.
   - Activities should be short labels (e.g., "walking", "running", "cycling", "birdwatching", "picnicking", "photography", "fishing", "sitting", "playing", etc.).
   - Provide an approximate quantity descriptor for people doing the activity: "1" or "multiple".
   - If there are no humans visible, return an empty list.

C) Analyze the user’s comment text and output a sentiment score in [0, 1].
   - 0 = very negative, 0.5 = neutral/mixed, 1 = very positive.
   - Base sentiment ONLY on the text content (not on what you think the user feels from images).
   - If the text is not in English, interpret it as-is and still produce a score.

D) Infer the association between the images and the comment with respect to time/context, and provide ONE concise combined conclusion.
   - Decide whether the comment likely refers to the same park visit captured by the images.
   - Use cues like: mentions of "today/now/this morning", weather, events, sightings, activities, mood, or location references.
   - Output:
     - an "association_likelihood" score in [0, 1] (1 = very likely the comment describes the images from this visit).
     - a single-sentence "association_summary" that combines: (i) what is in the photos, (ii) what the comment expresses, and (iii) the inferred time/context link.

IMPORTANT CONSTRAINTS:
- Output MUST be valid JSON ONLY (no Markdown, no extra commentary).
- Keep the JSON compact but complete.
- Do not include any personal identifiers (no user IDs, no faces description beyond activities).
- If you are uncertain about a species ID, reflect that uncertainty with "confidence" and/or coarser taxonomy.

Return the JSON with the following schema:

{
  "plants": [
    {
      "scientific_name": "<Latin name or best taxonomic level>",
      "common_name": "<optional common name if confident, else null>",
      "count_estimate": "1" | "multiple",
      "confidence": <float 0..1>,
      "evidence_images": [<int indices>]  // optional
    }
  ],
  "animals": [
    {
      "scientific_name": "<Latin name or best taxonomic level>",
      "common_name": "<optional common name if confident, else null>",
      "count_estimate": "1" | "multiple",
      "confidence": <float 0..1>,
      "evidence_images": [<int indices>]  // optional
    }
  ],
  "human_activities": [
    {
      "activity": "<string label>",
      "count_estimate": "1" | "multiple",
      "confidence": <float 0..1>,
      "evidence_images": [<int indices>]  // optional
    }
  ],
  "comment_sentiment": {
    "score": <float 0..1>,
    "brief_justification": "<one short phrase>"
  },
  "image_text_association": {
    "association_likelihood": <float 0..1>,
    "association_summary": "<ONE sentence combining image content + text sentiment + time/context link>"
  }
}

Now analyze the provided images (as a set) and the comment text, then output ONLY the JSON.
"""},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "不(;｀O´)o错，就是太贵了缆车，但是天津的后花园，没事散散心挺好的，以后有机会再来吧，就是缺点儿水景"},
                {
                    "type": "image_url",
                  "image_url": {"url": image_1},
                },
                {
                    "type": "image_url",
                  "image_url": {"url": image_2},
                },
                {
                    "type": "image_url",
                  "image_url": {"url": image_3},
                }
            ],
        }
    ],
    max_tokens=512,
    temperature=0.2
)

print("\nQwen3-VL:\n")
print(response.choices[0].message.content)