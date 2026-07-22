from bs4 import BeautifulSoup
import re

with open("scratch/beatbox_gym_filtered.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

print("=== H1 === ")
print(soup.find("h1"))

print("\n=== Tables === ")
for i, t in enumerate(soup.find_all("table")):
    print(f"\nTable {i}:")
    print(t.get_text(separator=" | ", strip=True)[:400])

print("\n=== Lists === ")
for i, l in enumerate(soup.find_all(["ul", "ol"])):
    print(f"\nList {i}:")
    print(l.get_text(separator=" | ", strip=True)[:400])

print("\n=== Anchor links === ")
for a in soup.find_all("a", href=True):
    print(f"Text: {a.get_text(strip=True)} | Href: {a['href']}")

print("\n=== Checking Noida / Address terms in elements === ")
for tag in soup.find_all(True):
    txt = tag.get_text(strip=True)
    if "noida" in txt.lower() or "address" in txt.lower() or "head office" in txt.lower():
        print(f"<{tag.name}> {txt[:100]}")
