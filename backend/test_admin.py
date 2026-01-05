import requests
import json

API_URL = "http://localhost:8000"

def test_admin_api():
    print("Testing Admin API...")
    
    # 1. Scraper URLs
    print("\n[1] Testing Scraper URLs...")
    # Add
    payload = {"department": "Test Dept", "url": "http://test.com"}
    res = requests.post(f"{API_URL}/api/admin/scraper-urls", json=payload)
    if res.status_code == 200:
        added = res.json()
        print(f"[OK] Added: {added}")
        url_id = added["id"]
        
        # List
        res = requests.get(f"{API_URL}/api/admin/scraper-urls")
        urls = res.json()
        print(f"[OK] List count: {len(urls)}")
        assert any(u["id"] == url_id for u in urls)
        
        # Delete
        res = requests.delete(f"{API_URL}/api/admin/scraper-urls/{url_id}")
        assert res.status_code == 200
        print(f"[OK] Deleted: {url_id}")
    else:
        print(f"[ERR] Failed to add: {res.text}")

    # 2. DSpace URLs
    print("\n[2] Testing DSpace URLs...")
    # Add
    payload = {"name": "Test Collection", "url": "http://dspace.test.com"}
    res = requests.post(f"{API_URL}/api/admin/dspace-urls", json=payload)
    if res.status_code == 200:
        added = res.json()
        print(f"[OK] Added: {added}")
        url_id = added["id"]
        
        # List
        res = requests.get(f"{API_URL}/api/admin/dspace-urls")
        urls = res.json()
        print(f"[OK] List count: {len(urls)}")
        assert any(u["id"] == url_id for u in urls)
        
        # Delete
        res = requests.delete(f"{API_URL}/api/admin/dspace-urls/{url_id}")
        assert res.status_code == 200
        print(f"[OK] Deleted: {url_id}")
    else:
        print(f"[ERR] Failed to add: {res.text}")

def test_faculty_structure():
    print("\n[3] Testing Faculty Structure...")
    res = requests.get(f"{API_URL}/api/faculty")
    if res.status_code != 200:
        print("[ERR] Failed to fetch faculty")
        return
        
    faculty = res.json()
    print(f"[OK] Fetched {len(faculty)} faculty")
    
    missing_dept = 0
    missing_college = 0
    
    for f in faculty:
        if "department" not in f:
            missing_dept += 1
        if "college" not in f:
            missing_college += 1
            
    if missing_dept == 0 and missing_college == 0:
        print("[OK] All faculty have 'department' and 'college' fields")
    else:
        print(f"[ERR] Missing fields: Dept={missing_dept}, College={missing_college}")

if __name__ == "__main__":
    try:
        test_admin_api()
        test_faculty_structure()
    except Exception as e:
        print(f"[ERR] Error: {e}")
