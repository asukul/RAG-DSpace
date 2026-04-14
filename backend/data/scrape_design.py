#!/usr/bin/env python3
"""
Scraper for ISU College of Design faculty directory.
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

def extract_title_department(title_text, name):
    """Extract clean title and try to determine department from title."""
    title = title_text.strip() if title_text else "Faculty"
    
    # Map common Design departments
    dept_keywords = {
        "Architecture": ["architecture", "Chair - Architecture"],
        "Art and Visual Culture": ["art and visual culture", "art", "visual culture", "Chair - Art"],
        "Community and Regional Planning": ["planning", "planner", "urban planning", "Chair - Urban"],
        "Graphic Design": ["graphic design", "Chair - Graphic"],
        "Industrial Design": ["industrial design", "Chair - Industrial"],
        "Interior Design": ["interior design", "Chair - Interior"],
        "Landscape Architecture": ["landscape architecture", "Chair - Landscape"],
        "Interdisciplinary Design": ["interdisciplinary"],
    }
    
    department = "College of Design"
    title_lower = title.lower()
    for dept, keywords in dept_keywords.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                department = dept
                break
    
    return title, department

def is_faculty(title):
    """Check if person is faculty (not staff only)."""
    faculty_keywords = [
        "professor", "lecturer", "instructor", "faculty", "chair", "dean",
        "teaching", "associate professor", "assistant professor"
    ]
    staff_only_keywords = [
        "coordinator", "administrator", "specialist", "manager", "director",
        "analyst", "recruiter", "advisor", "developer", "assistant to"
    ]
    
    title_lower = title.lower()
    
    # If has faculty keyword, include
    for kw in faculty_keywords:
        if kw in title_lower:
            return True
    
    return False

def scrape_design_directory():
    """Scrape the College of Design directory."""
    base_url = "https://www.design.iastate.edu/directory/"
    
    faculty_data = []
    
    print("Fetching Design directory...")
    response = requests.get(base_url, timeout=30)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.content, "html.parser")
    
    # Find all profile links
    profile_links = soup.find_all("a", href=lambda h: h and "/profiles/" in h)
    
    seen_names = set()
    
    for link in profile_links:
        try:
            name = link.get_text().strip()
            if not name or name in seen_names:
                continue
                
            # Skip non-name links
            if "@" in name or name.startswith("http"):
                continue
                
            seen_names.add(name)
            
            # Get title from sibling text
            parent = link.find_parent()
            title_text = ""
            if parent:
                # Look for title text after the name link
                for sibling in link.next_siblings:
                    if hasattr(sibling, "get_text"):
                        text = sibling.get_text().strip()
                        if text and "@" not in text and "(" not in text:
                            title_text = text
                            break
                    elif isinstance(sibling, str):
                        text = sibling.strip()
                        if text and "@" not in text:
                            title_text = text
                            break
            
            # Try to get title from surrounding text
            parent_text = parent.get_text() if parent else ""
            lines = [l.strip() for l in parent_text.split('\n') if l.strip()]
            
            # Find the line after the name
            title = ""
            for i, line in enumerate(lines):
                if name in line and i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if "@" not in next_line:
                        title = next_line
                    break
            
            if not title:
                title = title_text or "Faculty"
            
            # Skip non-faculty
            if not is_faculty(title):
                continue
            
            clean_title, department = extract_title_department(title, name)
            
            # Get email from nearby mailto link
            email = ""
            email_link = parent.find("a", href=lambda h: h and "mailto:" in h) if parent else None
            if email_link:
                email = email_link.get("href", "").replace("mailto:", "").strip()
            
            # Create faculty entry
            faculty_entry = {
                "id": generate_id(name),
                "name": name,
                "title": clean_title,
                "department": department,
                "college": "College of Design",
                "email": email,
                "research_interests": [],
                "courses_taught": [],
                "is_teaching_faculty": "teaching" in clean_title.lower() or "lecturer" in clean_title.lower()
            }
            
            faculty_data.append(faculty_entry)
            
        except Exception as e:
            continue
    
    return faculty_data

def main():
    print("=" * 60)
    print("Scraping College of Design Directory")
    print("=" * 60)
    
    faculty = scrape_design_directory()
    
    print(f"\nExtracted {len(faculty)} faculty members")
    
    # Save to JSON
    output_file = "design_faculty.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(faculty, f, indent=2, ensure_ascii=False)
    
    print(f"Saved to {output_file}")
    
    # Print sample
    print("\nSample entries:")
    for entry in faculty[:5]:
        print(f"  - {entry['name']}: {entry['title']} ({entry['department']})")

if __name__ == "__main__":
    main()
