import sys
import os

# Set python path to find modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bs4 import BeautifulSoup
from modules.preprocessor import clean_html
from modules.adapter_loader import AdapterLoader
from modules.relevant_dom.builder import RelevantDOMBuilder
from modules.dataset_builder.deterministic_extractor import DeterministicExtractor

with open("scratch/beatbox_gym.html", "r", encoding="utf-8") as f:
    html = f.read()

# 1. Preprocessor cleaning
cleaned = clean_html(html)
print(f"Cleaned HTML length: {len(cleaned)}")

# 2. Adapter loading & Relevant DOM
adapter = AdapterLoader.load("https://www.franchisebazar.com/franchise-opportunity/beatbox-gym")
profile = adapter.get_profile()
dom_builder = RelevantDOMBuilder(profile, schema=adapter.schema)
filtered = dom_builder.build(cleaned, "https://www.franchisebazar.com/franchise-opportunity/beatbox-gym")
print(f"Filtered HTML length: {len(filtered)}")

# Save filtered html for manual inspection
with open("scratch/beatbox_gym_filtered.html", "w", encoding="utf-8") as f:
    f.write(filtered)

# 3. Running deterministic extraction
extractor = DeterministicExtractor(schema=adapter.schema, config=adapter.config)
res = extractor.extract(filtered, "https://www.franchisebazar.com/franchise-opportunity/beatbox-gym")
print("\n=== Deterministic Extracted Fields ===")
for k, v in res.items():
    print(f"{k}: {v}")

# 4. Let's find specific text/sections in the original HTML to see why they were removed
soup = BeautifulSoup(cleaned, "html.parser")
print("\n=== Checking presence of key terms in Cleaned HTML ===")
for term in ["about", "address", "noida", "city", "state", "facebook", "instagram"]:
    found = soup.find_all(text=lambda text: text and term in text.lower())
    print(f"'{term}' in Cleaned HTML: {len(found)} times")
