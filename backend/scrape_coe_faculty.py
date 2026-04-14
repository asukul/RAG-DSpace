"""
College of Engineering Faculty Scraper for ISU Research Search
Scrapes faculty data from https://www.engineering.iastate.edu/people/search/

Uses the correct form parameters and pagination handling discovered during
browser exploration.
"""
import requests
from bs4 import BeautifulSoup
import json
import os
import time
from urllib.parse import urljoin, urlencode

# Configuration
COE_BASE_URL = "https://www.engineering.iastate.edu"
COE_SEARCH_URL = "https://www.engineering.iastate.edu/people/search/"
OUTPUT_FILE = "../data/coe_faculty.json"

# Department filter IDs (discovered from the dropdown options)
# Format: {"name": department name, "id": ofdepartment value}
COE_DEPARTMENTS = [
    {"name": "Aerospace Engineering", "id": "1035"},
    {"name": "Agricultural and Biosystems Engineering", "id": "1072"},
    {"name": "Chemical and Biological Engineering", "id": "1075"},
    {"name": "Civil, Construction and Environmental Engineering", "id": "1081"},
    {"name": "Electrical and Computer Engineering", "id": "1121"},
    {"name": "Industrial and Manufacturing Systems Engineering", "id": "1150"},
    {"name": "Materials Science and Engineering", "id": "1158"},
    {"name": "Mechanical Engineering", "id": "1168"}
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

def get_soup(url, params=None):
    """Fetch a page and return BeautifulSoup object."""
    try:
        if params:
            full_url = f"{url}?{urlencode(params)}"
        else:
            full_url = url
        response = requests.get(full_url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def parse_faculty_from_soup(soup, dept_name):
    """Parse faculty entries from a search results page."""
    faculty = []
    
    # The site uses article.profile elements for each faculty member
    profiles = soup.find_all('article', class_='profile')
    
    for profile in profiles:
        person = {
            "department": dept_name,
            "college": "College of Engineering",
            "source_url": COE_SEARCH_URL
        }
        
        # Extract Name and Profile URL from entry-title
        name_link = profile.select_one('.entry-title a')
        if name_link:
            person['name'] = name_link.get_text().strip()
            person['profile_url'] = urljoin(COE_BASE_URL, name_link.get('href', ''))
        else:
            # Try alternative selectors
            name_elem = profile.find('h2') or profile.find('h3')
            if name_elem:
                person['name'] = name_elem.get_text().strip()
                link = name_elem.find('a')
                if link:
                    person['profile_url'] = urljoin(COE_BASE_URL, link.get('href', ''))
                else:
                    person['profile_url'] = ""
            else:
                continue  # Skip if no name found
        
        # Generate ID from name
        person['id'] = person['name'].lower().replace(' ', '-').replace('.', '').replace(',', '').replace("'", "")
        
        # Extract Title from entry-content paragraph
        title_elem = profile.select_one('.entry-content p')
        if title_elem:
            person['title'] = title_elem.get_text().strip()
        else:
            # Try finding in .title class
            title_div = profile.find('div', class_='title') or profile.find('span', class_='title')
            if title_div:
                person['title'] = title_div.get_text().strip()
            else:
                person['title'] = "Faculty"
        
        # Extract rank from title
        title_lower = person.get('title', '').lower()
        if 'professor emeritus' in title_lower or 'emeritus' in title_lower:
            person['rank'] = "Professor Emeritus"
        elif 'distinguished professor' in title_lower:
            person['rank'] = "Distinguished Professor"
        elif 'university professor' in title_lower:
            person['rank'] = "University Professor"
        elif 'associate professor' in title_lower:
            person['rank'] = "Associate Professor"
        elif 'assistant professor' in title_lower:
            person['rank'] = "Assistant Professor"
        elif 'professor' in title_lower:
            person['rank'] = "Professor"
        elif 'lecturer' in title_lower:
            person['rank'] = "Lecturer"
        elif 'instructor' in title_lower:
            person['rank'] = "Instructor"
        else:
            person['rank'] = person.get('title', 'Faculty')
        
        # Extract Email
        email_link = profile.find('a', href=lambda h: h and h.startswith('mailto:'))
        if email_link:
            email = email_link.get('href', '').replace('mailto:', '').split('?')[0]
            person['email'] = email
        else:
            person['email'] = None
        
        # Extract Photo URL
        # Try img.pull-right first, then any img with data-src or src
        img = profile.select_one('img.pull-right') or profile.find('img')
        if img:
            photo_url = img.get('data-src') or img.get('src', '')
            if photo_url:
                person['photo_url'] = urljoin(COE_BASE_URL, photo_url)
            else:
                person['photo_url'] = None
        else:
            person['photo_url'] = None
        
        # Research interests (often not on search page, leave empty)
        person['research_interests'] = []
        
        # Teaching faculty flag
        person['is_teaching_faculty'] = False
        
        faculty.append(person)
    
    return faculty


def get_next_page_url(soup):
    """Check if there's a 'next page' (older posts) link and return it."""
    older_link = soup.select_one('.nav-previous a')
    if older_link:
        return older_link.get('href')
    return None


def scrape_department(dept_name, dept_id):
    """Scrape all faculty from a department, handling pagination."""
    print(f"  Searching department ID: {dept_id}")
    
    all_faculty = []
    page = 1
    
    # First page - use query parameters
    params = {"ofdepartment": dept_id}
    soup = get_soup(COE_SEARCH_URL, params)
    
    if not soup:
        print(f"  Failed to fetch first page")
        return []
    
    while soup:
        faculty = parse_faculty_from_soup(soup, dept_name)
        print(f"    Page {page}: Found {len(faculty)} faculty")
        all_faculty.extend(faculty)
        
        # Check for next page
        next_url = get_next_page_url(soup)
        if next_url:
            page += 1
            time.sleep(0.5)  # Be polite
            soup = get_soup(next_url)
        else:
            break
    
    return all_faculty


def main():
    """Main scraper function."""
    # Ensure data directory exists
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, '..', 'data')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    
    output_path = os.path.join(data_dir, 'coe_faculty.json')
    
    all_faculty = []
    
    print("=" * 60)
    print("College of Engineering Faculty Scraper")
    print("=" * 60)
    
    for dept in COE_DEPARTMENTS:
        print(f"\nProcessing: {dept['name']}")
        print("-" * 40)
        
        dept_faculty = scrape_department(dept['name'], dept['id'])
        print(f"  Total for {dept['name']}: {len(dept_faculty)} faculty")
        
        all_faculty.extend(dept_faculty)
        
        # Be polite between departments
        time.sleep(1)
    
    # Remove duplicates by profile_url
    seen_urls = set()
    unique_faculty = []
    for f in all_faculty:
        url = f.get('profile_url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_faculty.append(f)
        elif not url:
            unique_faculty.append(f)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print(f"   Total scraped: {len(all_faculty)}")
    print(f"   After dedup:   {len(unique_faculty)}")
    print("=" * 60)
    
    # Save results
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(unique_faculty, f, indent=2, ensure_ascii=False)
    
    print(f"\nData saved to: {output_path}")
    
    # Print department breakdown
    print("\nBreakdown by Department:")
    dept_counts = {}
    for f in unique_faculty:
        dept = f.get('department', 'Unknown')
        dept_counts[dept] = dept_counts.get(dept, 0) + 1
    
    for dept, count in sorted(dept_counts.items()):
        print(f"   - {dept}: {count}")


if __name__ == "__main__":
    main()
