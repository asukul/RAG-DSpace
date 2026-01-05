import requests
from bs4 import BeautifulSoup
import json
import os
import time
from urllib.parse import urljoin, urlparse

# Configuration
LAS_DEPARTMENTS_URL = "https://las.iastate.edu/academics/academic-departments/"
OUTPUT_FILE = "data/las_faculty.json"

# Directory heuristics to try for each department site
DIRECTORY_PATHS = [
    "/people",
    "/people/faculty",
    "/faculty",
    "/directory",
    "/about/people",
    "/about/faculty"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def get_soup(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def get_las_departments():
    print(f"Fetching departments from {LAS_DEPARTMENTS_URL}...")
    soup = get_soup(LAS_DEPARTMENTS_URL)
    if not soup:
        return []

    departments = []
    # Targeted extraction based on the LAS page structure
    # Looking for the list of departments, typically in a specific section or list
    # Based on the read_url_content output earlier, it seems they are in a list under "Departments" header
    
    # Logic to find the list after "Departments" header
    # This is a bit heuristic, might need adjustment based on exact DOM
    content_div = soup.find('div', class_='entry-content') or soup.find('main')
    if not content_div:
        print("Could not find main content area.")
        return []

    # Find all links in the content area
    for link in content_div.find_all('a'):
        href = link.get('href')
        text = link.get_text().strip()
        
        if not href or not text:
            continue
            
        # Basic filtering to ensure it's an external link (likely a dept site) or absolute path
        if 'iastate.edu' in href and 'las.iastate.edu/academics' not in href:
            departments.append({
                "name": text,
                "url": href.rstrip('/')
            })
            
    # Remove duplicates
    unique_depts = {d['url']: d for d in departments}.values()
    return list(unique_depts)

def find_faculty_page(dept_url):
    """
    Try to find the main faculty/people page for a department.
    """
    # 1. Try heuristics
    for path in DIRECTORY_PATHS:
        full_url = urljoin(dept_url, path)
        print(f"  Checking {full_url}...")
        try:
            resp = requests.head(full_url, headers=HEADERS, timeout=5, allow_redirects=True)
            if resp.status_code == 200:
                # Double check content type to ensure it's html
                if 'text/html' in resp.headers.get('Content-Type', ''):
                    return full_url
        except:
            continue
            
    # 2. If heuristics fail, try to scrape the homepage for a "People" or "Faculty" link
    soup = get_soup(dept_url)
    if soup:
        for a in soup.find_all('a', string=lambda t: t and 'People' in t):
            return urljoin(dept_url, a['href'])
        for a in soup.find_all('a', string=lambda t: t and 'Faculty' in t):
            return urljoin(dept_url, a['href'])
            
    return None

def scrape_faculty_from_page(dept_name, url):
    """
    Generic scraper for ISU directory pages (Drupal/Standard ISU theme).
    """
    print(f"  Scraping faculty from {url}...")
    soup = get_soup(url)
    if not soup:
        return []
    
    faculty = []
    
    # Common ISU Drupal View structure for directories
    # Look for views-row or specific person cards
    
    # Strategy 1: Look for "views-row" which is common in ISU Drupal sites
    rows = soup.find_all('div', class_='views-row')
    
    # Strategy 2: If no views-rows, look for generic profile cards
    if not rows:
        rows = soup.find_all('div', class_='profile-teaser') # Another common pattern
        
    if not rows:
        # Fallback: Look for any article or div that looks like a person
        rows = soup.find_all('article')

    print(f"  Found {len(rows)} potential entries.")

    for row in rows:
        person = {
            "department": dept_name,
            "source_url": url
        }
        
        # Extract Name and Link
        name_tag = row.find('h3') or row.find('h2') or row.find('div', class_='field-name-title')
        if not name_tag:
            continue
            
        link = name_tag.find('a')
        if link:
            person['name'] = link.get_text().strip()
            person['profile_url'] = urljoin(url, link['href'])
        else:
            person['name'] = name_tag.get_text().strip()
            person['profile_url'] = url
            
        # Cleanup Name (remove extra whitespace/newlines)
        person['name'] = " ".join(person['name'].split())
        
        # ID generation
        person['id'] = person['name'].lower().replace(' ', '-').replace('.', '').replace('(', '').replace(')', '')

        # Extract Title/Rank
        # Titles often in a div with class field-name-field-person-title or similar
        # Many departments use the "horizontal card" theme where titles are in ul.isu-people_position-list li
        title_selectors = [
            ('div', 'field--name-field-person-title'),
            ('div', 'field-name-field-person-title'),
            ('div', 'views-field-field-person-title'),
            ('div', 'field-name-field-person-professional-title'),
            ('span', 'title'),
            ('div', 'person-title')
        ]
        
        found_title = None
        for tag, cls in title_selectors:
            title_tag = row.find(tag, class_=cls)
            if title_tag:
                found_title = title_tag.get_text().strip()
                break
        
        # Check for the list-based titles (Horizontal Card theme common in ISU)
        if not found_title:
            pos_list = row.find('ul', class_='isu-people_position-list')
            if pos_list:
                titles = [li.get_text().strip() for li in pos_list.find_all('li')]
                if titles:
                    found_title = " | ".join(titles)
        
        person['title'] = found_title if found_title else "Faculty"
            
        # Extract Email
        email_tag = row.find('a', href=lambda h: h and 'mailto:' in h)
        if email_tag:
            person['email'] = email_tag.get_text().strip()
            
        # Extract Photo
        img_tag = row.find('img')
        if img_tag:
            # Skip common icons like email icons
            if 'icon' not in img_tag.get('src', '') and 'logo' not in img_tag.get('src', ''):
                person['photo_url'] = urljoin(url, img_tag['src'])
        
        # Extract Research Interests (if available in teaser)
        # Often not in teaser, might need deep crawl, but let's try to find keywords
        # This is hard to get reliably from the list view, leaving empty for now or looking for 'tags'
        person['research_interests'] = []
        
        # Filter for likely faculty (exclude staff/grad students if possible based on title)
        # We'll be inclusive for now
        
        faculty.append(person)
        
    return faculty

def main():
    if not os.path.exists("data"):
        os.makedirs("data")
        
    all_faculty = []
    
    # 1. Get Departments
    depts = get_las_departments()
    print(f"Found {len(depts)} departments.")
    
    for dept in depts:
        print(f"\nProcessing {dept['name']} ({dept['url']})")
        
        # 2. Find Faculty Page
        faculty_url = find_faculty_page(dept['url'])
        
        if faculty_url:
            print(f"  Found directory: {faculty_url}")
            # 3. Scrape Data
            people = scrape_faculty_from_page(dept['name'], faculty_url)
            print(f"  Scraped {len(people)} people.")
            all_faculty.extend(people)
        else:
            print("  Could not locate faculty directory.")
            
        # Be polite
        time.sleep(1)
        
    # 4. Save Data
    print(f"\nTotal faculty scraped: {len(all_faculty)}")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_faculty, f, indent=2)
    print(f"Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
