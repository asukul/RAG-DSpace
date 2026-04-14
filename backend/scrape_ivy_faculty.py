#!/usr/bin/env python3
"""
Scrape Ivy College of Business Faculty Directory
https://www.ivybusiness.iastate.edu/directory/
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import time

BASE_URL = "https://www.ivybusiness.iastate.edu"
DIRECTORY_URL = f"{BASE_URL}/directory/"

# Faculty title patterns
FACULTY_PATTERNS = [
    'professor', 'lecturer', 'instructor', 'faculty', 'dean', 'director'
]

def is_faculty(title):
    """Check if a title indicates faculty (not staff)"""
    if not title:
        return False
    title_lower = title.lower()
    return any(p in title_lower for p in FACULTY_PATTERNS)

def scrape_directory_page(letter=None):
    """Scrape a single page of the directory"""
    url = DIRECTORY_URL
    if letter:
        url = f"{DIRECTORY_URL}?FirstLetter={letter}"
    
    print(f"Fetching: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def parse_directory_page(html):
    """Parse directory page to extract people"""
    soup = BeautifulSoup(html, 'html.parser')
    people = []
    
    # Find all person entries - they appear as links with /directory/ paths
    for link in soup.find_all('a', href=re.compile(r'/directory/[a-zA-Z0-9]+$')):
        name = link.get_text(strip=True)
        if not name or len(name) < 2:
            continue
            
        profile_url = BASE_URL + link['href'] if not link['href'].startswith('http') else link['href']
        
        # Find email nearby - typically in the same container
        parent = link.find_parent()
        email = None
        phone = None
        
        # Look for mailto link nearby
        container = parent
        for _ in range(3):  # Go up a few levels
            if container:
                mailto = container.find('a', href=re.compile(r'mailto:'))
                if mailto:
                    email = mailto['href'].replace('mailto:', '')
                    break
                container = container.find_parent()
        
        if name and profile_url:
            people.append({
                'name': name,
                'profile_url': profile_url,
                'email': email
            })
    
    return people

def get_person_details(profile_url):
    """Fetch individual profile page for more details"""
    print(f"  Fetching profile: {profile_url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        response = requests.get(profile_url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        details = {}
        
        # Get title - usually in a heading or specific class
        title_el = soup.find(['h2', 'h3', 'p'], class_=re.compile(r'title|position|role', re.I))
        if title_el:
            details['title'] = title_el.get_text(strip=True)
        
        # Try to find title in meta or structured data
        if not details.get('title'):
            # Look for text near "Professor" or similar
            for p in soup.find_all(['p', 'div', 'span']):
                text = p.get_text(strip=True)
                if any(x in text.lower() for x in ['professor', 'lecturer', 'dean']):
                    if len(text) < 200:  # Reasonable length for a title
                        details['title'] = text
                        break
        
        # Get photo
        img = soup.find('img', class_=re.compile(r'profile|portrait|photo', re.I))
        if img and img.get('src'):
            src = img['src']
            if not src.startswith('http'):
                src = BASE_URL + src
            details['photo_url'] = src
        
        # Try alternative photo selectors
        if not details.get('photo_url'):
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if 'profile' in src.lower() or 'portrait' in src.lower() or 'headshot' in src.lower():
                    if not src.startswith('http'):
                        src = BASE_URL + src
                    details['photo_url'] = src
                    break
        
        # Get department
        for el in soup.find_all(['p', 'div', 'span', 'a']):
            text = el.get_text(strip=True)
            if 'department' in text.lower() or any(d in text.lower() for d in ['accounting', 'finance', 'management', 'marketing', 'supply chain', 'information systems', 'business analytics']):
                if len(text) < 100:
                    details['department'] = text
                    break
        
        return details
    except Exception as e:
        print(f"  Error fetching profile: {e}")
        return {}

def main():
    print("Scraping Ivy College of Business Directory")
    print("=" * 50)
    
    all_people = []
    seen_urls = set()
    
    # Scrape each letter
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    
    for letter in letters:
        html = scrape_directory_page(letter)
        if html:
            people = parse_directory_page(html)
            for p in people:
                if p['profile_url'] not in seen_urls:
                    seen_urls.add(p['profile_url'])
                    all_people.append(p)
        time.sleep(0.5)  # Be polite
    
    print(f"\nFound {len(all_people)} total people in directory")
    
    # Get details for first 20 people to identify faculty vs staff
    print("\nFetching individual profiles to identify faculty...")
    faculty_list = []
    
    sample_count = min(50, len(all_people))  # Sample to identify faculty
    
    for i, person in enumerate(all_people[:sample_count]):
        details = get_person_details(person['profile_url'])
        person.update(details)
        
        if is_faculty(person.get('title', '')):
            person['college'] = 'Ivy College of Business'
            person['id'] = person['profile_url'].split('/')[-1]
            faculty_list.append(person)
            print(f"  ✓ Faculty: {person['name']} - {person.get('title', 'N/A')}")
        else:
            print(f"  × Staff: {person['name']} - {person.get('title', 'N/A')}")
        
        time.sleep(0.3)
    
    print(f"\nIdentified {len(faculty_list)} faculty in first {sample_count} entries")
    
    # Save results
    output_file = "../data/ivy_faculty.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(faculty_list, f, indent=2)
    
    print(f"Saved to {output_file}")
    
    return faculty_list

if __name__ == "__main__":
    main()
