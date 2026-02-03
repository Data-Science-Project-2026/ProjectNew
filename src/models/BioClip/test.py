import torch
from PIL import Image
import open_clip

# Load BioCLIP 2 model, tokenizer, and preprocessing
model, _, preprocess = open_clip.create_model_and_transforms(
    "hf-hub:imageomics/bioclip-2"
)
model.eval()
tokenizer = open_clip.get_tokenizer("hf-hub:imageomics/bioclip-2")

# Define species names
text_inputs = [
    "Helianthus annuus",   # sunflower
    "Bellis perennis",     # daisy (common daisy)
    "Rosa spp.",           # rose (genus-level; many species)
    "Tulipa gesneriana"    # tulip (common garden tulip)
]
text_tokens = tokenizer(text_inputs)
text = tokenizer(text_inputs)

# Image
path = "sunflower.jpg"
image = preprocess(Image.open(path)).unsqueeze(0)

# Compare
with torch.no_grad(), torch.autocast("cuda"):
    image_features = model.encode_image(image)
    text_features = model.encode_text(text)
    image_features /= image_features.norm(dim=-1, keepdim=True)
    text_features /= text_features.norm(dim=-1, keepdim=True)

    text_probs = (100.0 * image_features @ text_features.T).softmax(dim=-1)

print("Label probs:", text_probs)
# Label probs: tensor([[1.0000e+00, 2.5945e-08, 2.4504e-08, 4.3175e-06]])