#!/usr/bin/env python3
"""Standalone test to verify faculty data loading without FastAPI"""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FACULTY_FILE = os.path.join(DATA_DIR, "faculty.json")

# Load from verified_faculty_data
from verified_faculty_data import VERIFIED_FACULTY_DATA

# Load LAS data
las_faculty = []
las_data_path = os.path.join(DATA_DIR, "las_faculty.json")
if os.path.exists(las_data_path):
    with open(las_data_path, "r", encoding="utf-8") as f:
        las_faculty = json.load(f)
    print(f"LAS faculty: {len(las_faculty)}")

# Load CoE data
coe_faculty = []
coe_data_path = os.path.join(DATA_DIR, "coe_faculty.json")
if os.path.exists(coe_data_path):
    with open(coe_data_path, "r", encoding="utf-8") as f:
        coe_faculty = json.load(f)
    print(f"CoE faculty: {len(coe_faculty)}")

# Count verified
print(f"Verified faculty: {len(VERIFIED_FACULTY_DATA)}")

# Merge (simulating main.py logic)
verified_map = {f['id']: f for f in VERIFIED_FACULTY_DATA}
verified_names = {f['name'].lower(): f['id'] for f in VERIFIED_FACULTY_DATA}
final_faculty_list = list(VERIFIED_FACULTY_DATA)
added_ids = set(verified_map.keys())
added_names = set(verified_names.keys())

# Add LAS
for person in las_faculty:
    if person['id'] in added_ids or person['name'].lower() in added_names:
        continue
    final_faculty_list.append(person)
    added_ids.add(person['id'])
    added_names.add(person['name'].lower())

# Add CoE
for person in coe_faculty:
    if person.get('id') in added_ids or person['name'].lower() in added_names:
        continue
    final_faculty_list.append(person)
    added_ids.add(person.get('id', ''))
    added_names.add(person['name'].lower())

print(f"\nTotal merged faculty: {len(final_faculty_list)}")

# Count by department
depts = {}
for f in final_faculty_list:
    d = f.get("department", "Unknown")
    depts[d] = depts.get(d, 0) + 1

print("\nTop 20 departments:")
for dept, count in sorted(depts.items(), key=lambda x: -x[1])[:20]:
    print(f"  {dept}: {count}")

# Count by college
colleges = {}
for f in final_faculty_list:
    c = f.get("college", "Unknown")
    colleges[c] = colleges.get(c, 0) + 1

print("\nBy college:")
for college, count in sorted(colleges.items(), key=lambda x: -x[1]):
    print(f"  {college}: {count}")

# Save to faculty.json
with open(FACULTY_FILE, "w", encoding="utf-8") as f:
    json.dump(final_faculty_list, f, indent=2)
print(f"\nSaved to {FACULTY_FILE}")
