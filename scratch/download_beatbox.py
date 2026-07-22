import urllib.request

url = "https://www.franchisebazar.com/franchise-opportunity/beatbox-gym"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
req = urllib.request.Request(url, headers=headers)

try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8")
    with open("c:/Users/piyus/OneDrive/Desktop/LeMiCi/Ai-extractor/scratch/beatbox_gym.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Downloaded successfully.")
except Exception as e:
    print(f"Error: {e}")
