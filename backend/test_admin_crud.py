import requests
import json

API_URL = "http://localhost:8000"

def test_faculty_crud():
    print("\n[1] Testing Faculty CRUD...")
    
    # Create
    new_faculty = {
        "id": "test-faculty-001",
        "name": "Prof. Test Dummy",
        "rank": "Assistant Test Professor",
        "department": "Department of Testing",
        "college": "College of Testing",
        "research_interests": ["Testing", "Quality Assurance"],
        "courses_taught": ["TEST 101"]
    }
    
    print(f"Creating faculty: {new_faculty['name']}")
    res = requests.post(f"{API_URL}/api/admin/faculty", json=new_faculty)
    if res.status_code != 200:
        print(f"[ERR] Failed to create: {res.text}")
        return

    # Read
    res = requests.get(f"{API_URL}/api/admin/faculty")
    faculty_list = res.json()
    created = next((f for f in faculty_list if f["id"] == "test-faculty-001"), None)
    if created:
        print("[OK] Faculty created and found in list.")
    else:
        print("[ERR] Faculty not found in list.")
        return

    # Update
    new_faculty["rank"] = "Teleported Professor"
    res = requests.post(f"{API_URL}/api/admin/faculty", json=new_faculty)
    if res.status_code == 200:
        res = requests.get(f"{API_URL}/api/admin/faculty")
        updated = next((f for f in res.json() if f["id"] == "test-faculty-001"), None)
        if updated and updated["rank"] == "Teleported Professor":
            print("[OK] Faculty updated successfully.")
        else:
             print("[ERR] Faculty update verification failed.")

    # Delete
    res = requests.delete(f"{API_URL}/api/admin/faculty/test-faculty-001")
    if res.status_code == 200:
        res = requests.get(f"{API_URL}/api/admin/faculty")
        deleted = next((f for f in res.json() if f["id"] == "test-faculty-001"), None)
        if not deleted:
            print("[OK] Faculty deleted successfully.")
        else:
            print("[ERR] Faculty still in list after delete.")
    else:
        print(f"[ERR] Delete failed: {res.text}")

def test_document_crud():
    print("\n[2] Testing Manual Document CRUD...")
    
    # Create
    new_doc = {
        "title": "Manual Test Document",
        "abstract": "This is a manually added document for testing purposes.",
        "authors": ["Test Person", "Other Person"],
        "date": "2024",
        "url": "http://example.com/test-doc",
        "type": "publication"
    }
    
    res = requests.post(f"{API_URL}/api/admin/documents", json=new_doc)
    if res.status_code != 200:
        print(f"[ERR] Failed to create doc: {res.text}")
        return
        
    created_doc = res.json()
    doc_id = created_doc.get("id")
    print(f"[OK] Document created with ID: {doc_id}")

    # Read All
    res = requests.get(f"{API_URL}/api/admin/documents")
    docs = res.json()
    if any(d["id"] == doc_id for d in docs):
        print("[OK] Document found in list.")
    else:
        print("[ERR] Document not found in list.")

    # Search Verification
    print("Testing Search integration...")
    res = requests.post(f"{API_URL}/api/search", json={"query": "Manual Test Document", "limit": 10})
    search_res = res.json()
    if any(s.get("title") == "Manual Test Document" for s in search_res["sources"]):
        print("[OK] Manual document found in search results.")
    else:
        print("[ERR] Manual document NOT found in search results.")

    # Delete
    res = requests.delete(f"{API_URL}/api/admin/documents/{doc_id}")
    if res.status_code == 200:
        print("[OK] Document deleted.")
    else:
        print(f"[ERR] Failed to delete document: {res.text}")

if __name__ == "__main__":
    try:
        test_faculty_crud()
        test_document_crud()
    except Exception as e:
        print(f"[ERR] Exception: {e}")
