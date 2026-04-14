#!/usr/bin/env python3
"""Debug Ivy Business directory HTML structure"""
import requests
from bs4 import BeautifulSoup

url = "https://www.ivybusiness.iastate.edu/directory/?FirstLetter=A"
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.text, 'html.parser')

print(f"Status: {r.status_code}")
print(f"Content length: {len(r.text)}")
print()

# Find all links with /directory/ in href
links = []
for a in soup.find_all('a', href=True):
    href = a['href']
    text = a.get_text(strip=True)
    if '/directory/' in href and text and len(text) > 1:
        # Skip letter links (single character)
        if len(text) == 1:
            continue
        # Skip navigation links  
        if 'FirstLetter' in href:
            continue
        links.append({'name': text, 'href': href})

print(f"Found {len(links)} profile links:")
for l in links[:15]:
    print(f"  - {l['name']}: {l['href']}")
