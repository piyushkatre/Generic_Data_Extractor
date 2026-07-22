from bs4 import BeautifulSoup

with open("scratch/beatbox_gym.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

for tab_id in ["tab-1", "tab-7", "tab-3", "tab-4", "tab-2", "tab-5"]:
    tab = soup.find(id=tab_id)
    if tab:
        print(f"\n================= {tab_id} =================")
        print(tab.get_text(separator=" \n ", strip=True)[:1000])
    else:
        # Search class
        tab_c = soup.find(class_=tab_id)
        if tab_c:
            print(f"\n================= Class {tab_id} =================")
            print(tab_c.get_text(separator=" \n ", strip=True)[:1000])
