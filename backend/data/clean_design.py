#!/usr/bin/env python3
"""
Clean the Design faculty JSON file to remove noise entries.
"""
import json

def clean_design_faculty():
    with open("design_faculty.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Filter out non-person entries
    noise_names = [
        "Directory", "Reset", "Faculty and Staff Directory", "College Directory",
        "Faculty", "Staff", "People", "A", "B", "C", "D", "E", "F", "G", "H", "I",
        "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"
    ]
    
    clean_data = []
    seen_names = set()
    
    for entry in data:
        name = entry.get("name", "").strip()
        
        # Skip noise entries
        if name in noise_names:
            continue
        
        # Must have at least 2 words (first and last name)
        if len(name.split()) < 2:
            continue
        
        # Skip duplicates
        if name.lower() in seen_names:
            continue
        
        seen_names.add(name.lower())
        clean_data.append(entry)
    
    # Save cleaned data
    with open("design_faculty.json", "w", encoding="utf-8") as f:
        json.dump(clean_data, f, indent=2, ensure_ascii=False)
    
    print(f"Cleaned: {len(clean_data)} entries (from {len(data)})")
    
    # Print sample
    print("\nSample entries:")
    for entry in clean_data[:10]:
        print(f"  - {entry['name']}: {entry['title']}")

if __name__ == "__main__":
    clean_design_faculty()
