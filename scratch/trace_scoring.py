import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bs4 import BeautifulSoup, Tag
from modules.preprocessor import clean_html
from modules.adapter_loader import AdapterLoader
from modules.relevant_dom.builder import RelevantDOMBuilder

with open("scratch/beatbox_gym.html", "r", encoding="utf-8") as f:
    html = f.read()

cleaned = clean_html(html)
adapter = AdapterLoader.load("https://www.franchisebazar.com/franchise-opportunity/beatbox-gym")
profile = adapter.get_profile()
builder = RelevantDOMBuilder(profile, schema=adapter.schema)

soup = BeautifulSoup(cleaned, "html.parser")
root = soup.find("body") or soup

def trace_scoring(node, depth=0):
    if not node:
        return
    for child in node.children:
        if isinstance(child, Tag):
            if child.name in builder._SCORING_TAGS:
                score = builder._score_element(child)
                is_critical = builder._is_critical_node(child)
                print(f"{'  ' * depth}<{child.name} id='{child.get('id')}' class='{child.get('class', [])}'>: Score = {score}, Critical = {is_critical}")
                
                # Check if it has tab-1 as a descendant
                if child.find(id="tab-1"):
                    print(f"{'  ' * depth}  *** [Contains tab-1] ***")
                    
                if score < builder.profile.keep_threshold and not is_critical:
                    print(f"{'  ' * depth}  -> DECOMPOSED")
                else:
                    trace_scoring(child, depth + 1)
            else:
                trace_scoring(child, depth)

trace_scoring(root)
