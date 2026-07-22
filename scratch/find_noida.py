from bs4 import BeautifulSoup

with open("scratch/beatbox_gym.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
for node in soup.find_all(True):
    # Find tag containing Noida
    if node.string and "noida" in node.string.lower():
        print(f"Tag: <{node.name} class='{node.get('class', [])}'> - {node.string}")
        parent = node.parent
        print(f"  Parent: <{parent.name} class='{parent.get('class', [])}'>")
        grand = parent.parent
        print(f"    Grandparent: <{grand.name} class='{grand.get('class', [])}'>")
