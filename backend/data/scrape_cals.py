#!/usr/bin/env python3
"""
Scraper for ISU College of Agriculture and Life Sciences faculty directory.
"""
import requests
from bs4 import BeautifulSoup
import json
import hashlib
import re
import time

def generate_id(name):
    """Generate consistent ID from name."""
    return hashlib.md5(name.lower().encode()).hexdigest()[:12]

def is_faculty(title):
    """Check if person is faculty (not staff only)."""
    faculty_keywords = [
        "professor", "lecturer", "instructor", "faculty", "dean", 
        "director", "specialist", "scientist"
    ]
    
    title_lower = title.lower()
    for kw in faculty_keywords:
        if kw in title_lower:
            return True
    return False

def scrape_cals_directory():
    """Scrape the CALS directory from the main page."""
    base_url = "https://www.cals.iastate.edu/people"
    
    faculty_data = []
    
    print("Fetching CALS directory...")
    response = requests.get(base_url, timeout=30)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.content, "html.parser")
    
    # Find all profile links
    profile_links = soup.find_all("a", href=lambda h: h and "/people/" in h and h != "/people")
    
    seen_names = set()
    
    for link in profile_links:
        try:
            name = link.get_text().strip()
            if not name or name in seen_names:
                continue
                
            # Skip non-name links
            if "@" in name or name.startswith("http") or len(name) < 3:
                continue
            
            # Skip structural links
            if name.lower() in ["people", "faculty", "staff"]:
                continue
                
            seen_names.add(name)
            
            # Get profile URL for more details
            profile_url = link.get("href", "")
            if not profile_url.startswith("http"):
                profile_url = "https://www.cals.iastate.edu" + profile_url
            
            # Try to get more details from profile page
            title = "Faculty"
            department = "College of Agriculture and Life Sciences"
            email = ""
            
            try:
                time.sleep(0.2)  # Be polite
                prof_response = requests.get(profile_url, timeout=10)
                if prof_response.status_code == 200:
                    prof_soup = BeautifulSoup(prof_response.content, "html.parser")
                    
                    # Look for title
                    title_elem = prof_soup.find("div", class_="field--name-field-title")
                    if title_elem:
                        title = title_elem.get_text().strip()
                    
                    # Look for department
                    dept_elem = prof_soup.find("div", class_="field--name-field-department")
                    if dept_elem:
                        department = dept_elem.get_text().strip()
                    
                    # Look for email
                    email_elem = prof_soup.find("a", href=lambda h: h and "mailto:" in h)
                    if email_elem:
                        email = email_elem.get("href", "").replace("mailto:", "").strip()
                        
            except Exception:
                pass
            
            # Create faculty entry
            faculty_entry = {
                "id": generate_id(name),
                "name": name,
                "title": title,
                "department": department,
                "college": "College of Agriculture and Life Sciences",
                "email": email,
                "research_interests": [],
                "courses_taught": [],
                "is_teaching_faculty": "teaching" in title.lower() or "lecturer" in title.lower()
            }
            
            faculty_data.append(faculty_entry)
            print(f"  Added: {name}")
            
        except Exception as e:
            continue
    
    return faculty_data

def scrape_cals_departments():
    """Scrape faculty from CALS department pages."""
    departments = [
        ("https://www.agron.iastate.edu/people", "Agronomy"),
        ("https://www.ans.iastate.edu/people", "Animal Science"),
        ("https://www.abe.iastate.edu/people", "Agricultural and Biosystems Engineering"),
        ("https://www.econ.iastate.edu/people", "Economics"),
        ("https://www.ent.iastate.edu/people", "Entomology"),
        ("https://www.fshn.hs.iastate.edu/people", "Food Science and Human Nutrition"),
        ("https://www.gdcb.iastate.edu/people", "Genetics, Development and Cell Biology"),
        ("https://www.nrem.iastate.edu/people", "Natural Resource Ecology and Management"),
        ("https://www.plantpath.iastate.edu/people", "Plant Pathology and Microbiology"),
        ("https://www.soc.iastate.edu/people", "Sociology and Criminal Justice"),
    ]
    
    faculty_data = []
    seen_names = set()
    
    for dept_url, dept_name in departments:
        print(f"\nFetching {dept_name}...")
        try:
            response = requests.get(dept_url, timeout=30)
            if response.status_code != 200:
                continue
                
            soup = BeautifulSoup(response.content, "html.parser")
            
            # Find all profile links
            profile_links = soup.find_all("a", href=lambda h: h and "/people/" in h)
            
            for link in profile_links:
                name = link.get_text().strip()
                if not name or name in seen_names or len(name) < 3:
                    continue
                if "@" in name or name.startswith("http"):
                    continue
                if name.lower() in ["people", "faculty", "staff"]:
                    continue
                    
                seen_names.add(name)
                
                faculty_entry = {
                    "id": generate_id(name),
                    "name": name,
                    "title": "Faculty",
                    "department": dept_name,
                    "college": "College of Agriculture and Life Sciences",
                    "email": "",
                    "research_interests": [],
                    "courses_taught": [],
                    "is_teaching_faculty": False
                }
                
                faculty_data.append(faculty_entry)
                
        except Exception as e:
            print(f"  Error: {e}")
            continue
    
    return faculty_data

def main():
    print("=" * 60)
    print("Scraping College of Agriculture and Life Sciences Directory")
    print("=" * 60)
    
    # First try main directory
    faculty = scrape_cals_directory()
    
    # Then try department pages if we got few results
    if len(faculty) < 50:
        print("\nTrying department pages...")
        dept_faculty = scrape_cals_departments()
        
        # Merge, avoiding duplicates
        seen_names = {f["name"].lower() for f in faculty}
        for f in dept_faculty:
            if f["name"].lower() not in seen_names:
                faculty.append(f)
                seen_names.add(f["name"].lower())
    
    print(f"\nTotal: {len(faculty)} faculty members")
    
    # Save to JSON
    output_file = "cals_faculty.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(faculty, f, indent=2, ensure_ascii=False)
    
    print(f"Saved to {output_file}")

if __name__ == "__main__":
    main()
