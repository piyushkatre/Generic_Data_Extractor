from bs4 import BeautifulSoup

with open("scratch/beatbox_gym.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
tab = soup.find(id="tab-1")
if tab:
    print("=== tab-1 parent hierarchy ===")
    curr = tab
    while curr:
        print(f"<{curr.name} id='{curr.get('id')}' class='{curr.get('class', [])}'>")
        curr = curr.parent
        if curr.name == "html":
            break
else:
    print("tab-1 not found!")
