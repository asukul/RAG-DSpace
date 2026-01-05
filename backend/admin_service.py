import os
import json
from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field
import logging
import uuid # Added for reseed and ID generation

logger = logging.getLogger(__name__)

# Define Data Paths (Same as main.py)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FACULTY_FILE = os.path.join(DATA_DIR, "faculty.json")
MANUAL_DOCS_FILE = os.path.join(DATA_DIR, "manual_documents.json")
ADMIN_URLS_FILE = os.path.join(DATA_DIR, "admin_urls.json")

# Import seeding logic - hacky import to reuse main.py logic or redefine it?
# Better to import from main if possible, but circular import risk.
# Instead, we'll implement a standalone reseed function here that imports verified data.
from verified_faculty_data import VERIFIED_FACULTY_DATA

# Helper to load LAS data for seeding
def load_las_faculty_for_seed():
    las_path = os.path.join(DATA_DIR, "las_faculty.json")
    if os.path.exists(las_path):
        with open(las_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

# Data Models
class ScraperUrl(BaseModel):
    department: str
    url: str
    id: Optional[str] = None

class DSpaceUrl(BaseModel):
    name: str
    url: str
    type: str = "collection" # collection or community
    id: Optional[str] = None

# Service Class
class AdminService:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = os.path.join(os.path.dirname(__file__), data_dir)
        self.urls_file = ADMIN_URLS_FILE # Use the globally defined path
        self._ensure_data_dir()
        self._ensure_file()

    def _ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

    def _ensure_file(self):
        if not os.path.exists(self.urls_file):
            default_data = {
                "scraper_urls": [],
                "dspace_urls": []
            }
            self._save_data(default_data)

    def _load_data(self) -> Dict:
        try:
            with open(self.urls_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading admin URLs: {e}")
            return {"scraper_urls": [], "dspace_urls": []}

    def _save_data(self, data: Dict):
        try:
            with open(self.urls_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving admin URLs: {e}")

    # Scraper URL Methods
    def get_scraper_urls(self) -> List[Dict]:
        data = self._load_data()
        return data.get("scraper_urls", [])

    def add_scraper_url(self, url_data: ScraperUrl) -> Dict:
        data = self._load_data()
        entry = url_data.dict()
        entry["id"] = str(uuid.uuid4())
        
        # Check for duplicates
        if any(u["url"] == entry["url"] for u in data["scraper_urls"]):
             raise HTTPException(status_code=400, detail="URL already exists")
             
        data["scraper_urls"].append(entry)
        self._save_data(data)
        return entry

    def delete_scraper_url(self, url_id: str):
        data = self._load_data()
        original_len = len(data["scraper_urls"])
        data["scraper_urls"] = [u for u in data["scraper_urls"] if u["id"] != url_id]
        if len(data["scraper_urls"]) == original_len:
            raise HTTPException(status_code=404, detail="URL not found")
        self._save_data(data)
        return {"status": "deleted"}

    # DSpace URL Methods
    def get_dspace_urls(self) -> List[Dict]:
        data = self._load_data()
        return data.get("dspace_urls", [])

    def add_dspace_url(self, url_data: DSpaceUrl) -> Dict:
        data = self._load_data()
        entry = url_data.dict()
        entry["id"] = str(uuid.uuid4())
        
        if any(u["url"] == entry["url"] for u in data["dspace_urls"]):
             raise HTTPException(status_code=400, detail="URL already exists")

        data["dspace_urls"].append(entry)
        self._save_data(data)
        return entry
        
    def delete_dspace_url(self, url_id: str):
        data = self._load_data()
        original_len = len(data["dspace_urls"])
        data["dspace_urls"] = [u for u in data["dspace_urls"] if u["id"] != url_id]
        if len(data["dspace_urls"]) == original_len:
            raise HTTPException(status_code=404, detail="URL not found")
        self._save_data(data)
        return {"status": "deleted"}

# Router Setup
router = APIRouter(prefix="/api/admin", tags=["admin"])
admin_service = AdminService()

@router.get("/scraper-urls")
async def get_scraper_urls():
    return admin_service.get_scraper_urls()

@router.post("/scraper-urls")
async def add_scraper_url(url: ScraperUrl):
    return admin_service.add_scraper_url(url)

@router.delete("/scraper-urls/{url_id}")
async def delete_scraper_url(url_id: str):
    return admin_service.delete_scraper_url(url_id)

@router.get("/dspace-urls")
async def get_dspace_urls():
    return admin_service.get_dspace_urls()

@router.post("/dspace-urls")
async def add_dspace_url(url: DSpaceUrl):
    return admin_service.add_dspace_url(url)

@router.delete("/dspace-urls/{url_id}")
async def delete_dspace_url(url_id: str):
    return admin_service.delete_dspace_url(url_id)

# ==========================================================
# New CRUD Endpoints
# ==========================================================

class FacultyMember(BaseModel):
    id: str
    name: str
    rank: Optional[str] = "Unknown"
    title: Optional[str] = None
    email: Optional[str] = None
    photo_url: Optional[str] = None
    profile_url: Optional[str] = None
    group: Optional[str] = "Other"
    department: str = "Department of Computer Science"
    college: str = "College of Liberal Arts and Sciences"
    research_areas: List[str] = []
    research_interests: List[str] = []
    courses_taught: List[str] = []
    is_teaching_faculty: bool = False

class ManualDocument(BaseModel):
    id: Optional[str] = None
    title: str
    abstract: str
    authors: List[str]
    date: str
    url: str
    type: str = "publication"

# Extend AdminService
class AdminServiceExtended(AdminService):
    def __init__(self):
        super().__init__()
        self.faculty_file = FACULTY_FILE # Use global path
        self.manual_docs_file = MANUAL_DOCS_FILE # Use global path
        self._ensure_extended_files()

    def _ensure_extended_files(self):
        if not os.path.exists(self.manual_docs_file):
            with open(self.manual_docs_file, "w", encoding="utf-8") as f:
                json.dump([], f)
        # faculty.json is managed by main.py startup/seeding, but ensure exists here too
        if not os.path.exists(self.faculty_file):
             # Just create empty valid JSON if missing, main.py should populate it
             with open(self.faculty_file, "w", encoding="utf-8") as f:
                json.dump([], f)

    def _load_json(self, filepath: str) -> List[Dict]:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")
            return []

    def _save_json(self, filepath: str, data: List[Dict]):
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving {filepath}: {e}")

    # Faculty Methods
    def get_all_faculty(self) -> List[Dict]:
        return self._load_json(self.faculty_file)

    def save_faculty(self, faculty: FacultyMember) -> Dict:
        data = self._load_json(self.faculty_file)
        entry = faculty.dict()
        
        # Check if ID exists (Update) or New
        existing_idx = next((i for i, f in enumerate(data) if f["id"] == entry["id"]), -1)
        
        if existing_idx >= 0:
            data[existing_idx] = entry # Update
        else:
            data.append(entry) # Add
            
        self._save_json(self.faculty_file, data)
        return entry

    def delete_faculty(self, faculty_id: str):
        data = self._load_json(self.faculty_file)
        original_len = len(data)
        data = [f for f in data if f["id"] != faculty_id]
        if len(data) == original_len:
            raise HTTPException(status_code=404, detail="Faculty not found")
        self._save_json(self.faculty_file, data)
        return {"status": "deleted"}

    # Manual Document Methods
    def get_manual_documents(self) -> List[Dict]:
        return self._load_json(self.manual_docs_file)

    def save_manual_document(self, doc: ManualDocument) -> Dict:
        data = self._load_json(self.manual_docs_file)
        entry = doc.dict()
        if not entry.get("id"):
            entry["id"] = str(uuid.uuid4())
            
        existing_idx = next((i for i, d in enumerate(data) if d["id"] == entry["id"]), -1)
        
        if existing_idx >= 0:
            data[existing_idx] = entry
        else:
            data.append(entry)
            
        self._save_json(self.manual_docs_file, data)
        return entry
        
    def delete_manual_document(self, doc_id: str):
        data = self._load_json(self.manual_docs_file)
        original_len = len(data)
        data = [d for d in data if d["id"] != doc_id]
        if len(data) == original_len:
             raise HTTPException(status_code=404, detail="Document not found")
        self._save_json(self.manual_docs_file, data)
        return {"status": "deleted"}

# Upgrade singleton
admin_service = AdminServiceExtended()

@router.get("/faculty")
async def get_admin_faculty():
    return admin_service.get_all_faculty()

@router.post("/faculty")
async def save_admin_faculty(faculty: FacultyMember):
    return admin_service.save_faculty(faculty)

@router.delete("/faculty/{faculty_id}")
async def delete_admin_faculty(faculty_id: str):
    return admin_service.delete_faculty(faculty_id)

@router.get("/documents")
async def get_manual_documents():
    return admin_service.get_manual_documents()

@router.post("/documents")
async def save_manual_document(doc: ManualDocument):
    return admin_service.save_manual_document(doc)

@router.delete("/documents/{doc_id}")
async def delete_manual_document(doc_id: str):
    service = AdminServiceExtended()
    # The original delete_manual_document already raises HTTPException
    # if not found, so we can just return its result.
    return service.delete_manual_document(doc_id)

@router.get("/stats")
async def get_admin_stats():
    service = AdminServiceExtended()
    
    # Counts
    faculty_count = len(service.get_all_faculty())
    docs_count = len(service.get_manual_documents())
    
    # Use the existing _load_data method from AdminService for scraper/dspace URLs
    urls_data = service._load_data()
    scraper_count = len(urls_data.get("scraper_urls", []))
    dspace_count = len(urls_data.get("dspace_urls", []))

    return {
        "faculty_count": faculty_count,
        "manual_documents_count": docs_count,
        "scraper_sources_count": scraper_count,
        "dspace_collections_count": dspace_count,
        "gemini_file_count": "N/A (API limitation)" # Placeholder
    }

@router.post("/reseed-faculty")
async def reseed_faculty():
    # Force re-seed
    verified = VERIFIED_FACULTY_DATA
    las = load_las_faculty_for_seed()
    
    # Merge logic (simplified from main.py)
    merged = {f["name"]: f for f in verified}
    
    for f in las:
        if f["name"] not in merged:
             # Add defaults
             f["department"] = f.get("department", "Department of Computer Science")
             f["college"] = f.get("college", "College of Liberal Arts and Sciences")
             merged[f["name"]] = f
             
    final_list = list(merged.values())
    
    # Add IDs if missing
    for f in final_list:
        if "id" not in f:
            f["id"] = str(uuid.uuid4())
            
    # Save
    with open(FACULTY_FILE, "w", encoding="utf-8") as f:
        json.dump(final_list, f, indent=2)
        
    return {"message": f"Reseeded with {len(final_list)} faculty members", "count": len(final_list)}

# ============================================================
# Group Management Endpoints
# ============================================================

@router.get("/groups")
async def get_groups():
    """Get all unique department groups from faculty data."""
    try:
        if os.path.exists(FACULTY_FILE):
            with open(FACULTY_FILE, "r", encoding="utf-8") as f:
                faculty = json.load(f)
        else:
            faculty = []
        
        # Extract unique departments with counts
        groups = {}
        for fac in faculty:
            dept = fac.get("department", "Other")
            if dept not in groups:
                groups[dept] = {"name": dept, "count": 0}
            groups[dept]["count"] += 1
        
        return list(groups.values())
    except Exception as e:
        logger.error(f"Error getting groups: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class RenameGroupRequest(BaseModel):
    old_name: str
    new_name: str

@router.post("/groups/rename")
async def rename_group(req: RenameGroupRequest):
    """Rename a department group (updates all faculty in that group)."""
    try:
        if not os.path.exists(FACULTY_FILE):
            raise HTTPException(status_code=404, detail="Faculty data not found")
        
        with open(FACULTY_FILE, "r", encoding="utf-8") as f:
            faculty = json.load(f)
        
        updated_count = 0
        for fac in faculty:
            if fac.get("department") == req.old_name:
                fac["department"] = req.new_name
                updated_count += 1
        
        if updated_count == 0:
            raise HTTPException(status_code=404, detail=f"No faculty found in group '{req.old_name}'")
        
        with open(FACULTY_FILE, "w", encoding="utf-8") as f:
            json.dump(faculty, f, indent=2)
        
        return {"message": f"Renamed '{req.old_name}' to '{req.new_name}'", "updated_count": updated_count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error renaming group: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class MergeGroupsRequest(BaseModel):
    source_group: str
    target_group: str

@router.post("/groups/merge")
async def merge_groups(req: MergeGroupsRequest):
    """Merge source group into target group (moves all faculty)."""
    try:
        if not os.path.exists(FACULTY_FILE):
            raise HTTPException(status_code=404, detail="Faculty data not found")
        
        with open(FACULTY_FILE, "r", encoding="utf-8") as f:
            faculty = json.load(f)
        
        merged_count = 0
        for fac in faculty:
            if fac.get("department") == req.source_group:
                fac["department"] = req.target_group
                merged_count += 1
        
        if merged_count == 0:
            raise HTTPException(status_code=404, detail=f"No faculty found in group '{req.source_group}'")
        
        with open(FACULTY_FILE, "w", encoding="utf-8") as f:
            json.dump(faculty, f, indent=2)
        
        return {"message": f"Merged '{req.source_group}' into '{req.target_group}'", "merged_count": merged_count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error merging groups: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class MergeFacultyRequest(BaseModel):
    primary_id: str
    secondary_ids: List[str]

@router.post("/faculty/merge")
async def merge_faculty(req: MergeFacultyRequest):
    """Merge multiple faculty records into one. Combines research interests, keeps primary's info."""
    try:
        if not os.path.exists(FACULTY_FILE):
            raise HTTPException(status_code=404, detail="Faculty data not found")
        
        with open(FACULTY_FILE, "r", encoding="utf-8") as f:
            faculty = json.load(f)
        
        # Find primary and secondary records
        primary = None
        secondaries = []
        remaining = []
        
        for fac in faculty:
            if fac.get("id") == req.primary_id:
                primary = fac
            elif fac.get("id") in req.secondary_ids:
                secondaries.append(fac)
            else:
                remaining.append(fac)
        
        if not primary:
            raise HTTPException(status_code=404, detail="Primary faculty not found")
        
        # Merge research interests
        combined_interests = set(primary.get("research_interests", []) or [])
        for sec in secondaries:
            combined_interests.update(sec.get("research_interests", []) or [])
        primary["research_interests"] = list(combined_interests)
        
        # Keep primary, discard secondaries
        remaining.append(primary)
        
        with open(FACULTY_FILE, "w", encoding="utf-8") as f:
            json.dump(remaining, f, indent=2)
        
        return {"message": f"Merged {len(secondaries)} records into '{primary.get('name')}'", "merged_count": len(secondaries)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error merging faculty: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/faculty/duplicates")
async def detect_duplicates():
    """Detect potential duplicate faculty based on name similarity."""
    try:
        if not os.path.exists(FACULTY_FILE):
            return []
        
        with open(FACULTY_FILE, "r", encoding="utf-8") as f:
            faculty = json.load(f)
        
        def normalize_name(name: str) -> str:
            """Normalize name for comparison: lowercase, remove titles, standardize spacing."""
            if not name:
                return ""
            normalized = name.lower().strip()
            # Remove common titles/suffixes
            for title in ["dr.", "dr ", "prof.", "prof ", "professor ", "phd", "ph.d.", "ph.d", "md", "m.d."]:
                normalized = normalized.replace(title, "")
            # Remove extra spaces
            normalized = " ".join(normalized.split())
            return normalized
        
        def name_similarity(name1: str, name2: str) -> float:
            """Calculate similarity score between two names."""
            n1 = normalize_name(name1)
            n2 = normalize_name(name2)
            if n1 == n2:
                return 1.0
            
            # Check if one name contains the other
            if n1 in n2 or n2 in n1:
                return 0.9
            
            # Check last name match (often most reliable)
            parts1 = n1.split()
            parts2 = n2.split()
            if parts1 and parts2 and parts1[-1] == parts2[-1]:
                # Same last name - check first name similarity
                if len(parts1) > 1 and len(parts2) > 1:
                    # Check if first initials match
                    if parts1[0][0] == parts2[0][0]:
                        return 0.85
                return 0.7
            
            return 0.0
        
        duplicates = []
        seen_pairs = set()
        
        for i, fac1 in enumerate(faculty):
            for j, fac2 in enumerate(faculty):
                if i >= j:
                    continue
                
                pair_key = tuple(sorted([fac1.get("id", i), fac2.get("id", j)]))
                if pair_key in seen_pairs:
                    continue
                
                similarity = name_similarity(fac1.get("name", ""), fac2.get("name", ""))
                
                if similarity >= 0.7:
                    seen_pairs.add(pair_key)
                    duplicates.append({
                        "faculty1": {
                            "id": fac1.get("id"),
                            "name": fac1.get("name"),
                            "department": fac1.get("department"),
                            "rank": fac1.get("rank") or fac1.get("title")
                        },
                        "faculty2": {
                            "id": fac2.get("id"),
                            "name": fac2.get("name"),
                            "department": fac2.get("department"),
                            "rank": fac2.get("rank") or fac2.get("title")
                        },
                        "similarity": similarity,
                        "reason": "Same name" if similarity == 1.0 else 
                                 "Very similar name" if similarity >= 0.9 else
                                 "Same last name, similar first" if similarity >= 0.85 else
                                 "Same last name"
                    })
        
        # Sort by similarity (highest first)
        duplicates.sort(key=lambda x: x["similarity"], reverse=True)
        
        return duplicates[:50]  # Limit to top 50 matches
        
    except Exception as e:
        logger.error(f"Error detecting duplicates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Document Management Endpoints (Enhanced)
# ============================================================

@router.get("/documents/all")
async def get_all_documents():
    """Get all documents from all sources (manual + indexed)."""
    try:
        documents = []
        
        # 1. Load manual documents
        if os.path.exists(MANUAL_DOCS_FILE):
            with open(MANUAL_DOCS_FILE, "r", encoding="utf-8") as f:
                manual_docs = json.load(f)
                for doc in manual_docs:
                    doc["source"] = "manual"
                    doc["source_name"] = "Manual Entry"
                    documents.append(doc)
        
        # 2. Load indexed documents (from DSpace cache if exists)
        indexed_cache = os.path.join(DATA_DIR, "indexed_documents.json")
        if os.path.exists(indexed_cache):
            with open(indexed_cache, "r", encoding="utf-8") as f:
                indexed_docs = json.load(f)
                for doc in indexed_docs:
                    doc["source"] = "dspace"
                    doc["source_name"] = "ISU DSpace Repository"
                    documents.append(doc)
        
        return documents
    except Exception as e:
        logger.error(f"Error getting all documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/documents/stats")
async def get_documents_stats():
    """Get aggregated statistics for documents."""
    try:
        documents = []
        
        # Load all documents
        if os.path.exists(MANUAL_DOCS_FILE):
            with open(MANUAL_DOCS_FILE, "r", encoding="utf-8") as f:
                documents.extend(json.load(f))
        
        indexed_cache = os.path.join(DATA_DIR, "indexed_documents.json")
        if os.path.exists(indexed_cache):
            with open(indexed_cache, "r", encoding="utf-8") as f:
                documents.extend(json.load(f))
        
        # Calculate statistics
        stats = {
            "total_documents": len(documents),
            "by_type": {},
            "by_year": {},
            "by_source": {"manual": 0, "dspace": 0},
            "top_authors": {},
            "top_subjects": {},
            "by_department": {}
        }
        
        for doc in documents:
            # By Type
            doc_type = doc.get("type", "Unknown")
            stats["by_type"][doc_type] = stats["by_type"].get(doc_type, 0) + 1
            
            # By Year
            date_str = doc.get("date", "")
            year = date_str[:4] if len(date_str) >= 4 and date_str[:4].isdigit() else "Unknown"
            stats["by_year"][year] = stats["by_year"].get(year, 0) + 1
            
            # By Source
            source = doc.get("source", "manual")
            stats["by_source"][source] = stats["by_source"].get(source, 0) + 1
            
            # Top Authors
            authors = doc.get("authors", [])
            if isinstance(authors, str):
                authors = [authors]
            for author in authors[:3]:  # Limit to first 3 authors per doc
                if author:
                    stats["top_authors"][author] = stats["top_authors"].get(author, 0) + 1
            
            # Top Subjects
            subjects = doc.get("subjects", []) or doc.get("keywords", [])
            if isinstance(subjects, str):
                subjects = subjects.split(",")
            for subject in subjects[:5]:
                subj = subject.strip()
                if subj:
                    stats["top_subjects"][subj] = stats["top_subjects"].get(subj, 0) + 1
        
        # Sort and limit top items
        stats["top_authors"] = dict(sorted(stats["top_authors"].items(), key=lambda x: x[1], reverse=True)[:20])
        stats["top_subjects"] = dict(sorted(stats["top_subjects"].items(), key=lambda x: x[1], reverse=True)[:30])
        stats["by_year"] = dict(sorted(stats["by_year"].items(), key=lambda x: x[0] if x[0] != "Unknown" else "0000"))
        
        return stats
    except Exception as e:
        logger.error(f"Error getting document stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi.responses import StreamingResponse
import io
import csv

@router.get("/documents/export")
async def export_documents(format: str = "csv"):
    """Export documents in various formats."""
    try:
        documents = []
        
        if os.path.exists(MANUAL_DOCS_FILE):
            with open(MANUAL_DOCS_FILE, "r", encoding="utf-8") as f:
                docs = json.load(f)
                for doc in docs:
                    doc["source"] = "manual"
                documents.extend(docs)
        
        indexed_cache = os.path.join(DATA_DIR, "indexed_documents.json")
        if os.path.exists(indexed_cache):
            with open(indexed_cache, "r", encoding="utf-8") as f:
                docs = json.load(f)
                for doc in docs:
                    doc["source"] = "dspace"
                documents.extend(docs)
        
        if format == "json":
            return documents
        
        elif format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(["ID", "Title", "Authors", "Date", "Type", "Source", "URL", "Abstract", "Subjects"])
            
            for doc in documents:
                authors = ", ".join(doc.get("authors", [])) if isinstance(doc.get("authors"), list) else doc.get("authors", "")
                subjects = ", ".join(doc.get("subjects", [])) if isinstance(doc.get("subjects"), list) else doc.get("subjects", "")
                
                writer.writerow([
                    doc.get("id", doc.get("uuid", "")),
                    doc.get("title", ""),
                    authors,
                    doc.get("date", ""),
                    doc.get("type", ""),
                    doc.get("source", ""),
                    doc.get("url", ""),
                    doc.get("abstract", "")[:500] if doc.get("abstract") else "",
                    subjects
                ])
            
            output.seek(0)
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode('utf-8-sig')),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=documents_export.csv"}
            )
        
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Document Cache Management (GCP-Ready)
# ============================================================

INDEXED_DOCS_FILE = os.path.join(DATA_DIR, "indexed_documents.json")

@router.get("/documents/cache-stats")
async def get_cache_stats():
    """Get statistics about the document cache."""
    try:
        if not os.path.exists(INDEXED_DOCS_FILE):
            return {"total_cached": 0, "by_type": {}, "by_year": {}, "last_indexed": None}
        
        with open(INDEXED_DOCS_FILE, "r", encoding="utf-8") as f:
            docs = json.load(f)
        
        by_type = {}
        by_year = {}
        last_indexed = None
        
        for doc in docs:
            # By type
            doc_type = doc.get("type", "Unknown")
            by_type[doc_type] = by_type.get(doc_type, 0) + 1
            
            # By year
            year = doc.get("date", "")[:4] if doc.get("date") else "Unknown"
            by_year[year] = by_year.get(year, 0) + 1
            
            # Last indexed
            indexed_at = doc.get("cache_indexed_at")
            if indexed_at and (not last_indexed or indexed_at > last_indexed):
                last_indexed = indexed_at
        
        return {
            "total_cached": len(docs),
            "by_type": by_type,
            "by_year": dict(sorted(by_year.items())),
            "last_indexed": last_indexed
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

import httpx
from datetime import datetime

DSPACE_API_URL = os.getenv("DSPACE_BASE_URL", "https://dr.lib.iastate.edu") + "/server/api"

@router.post("/documents/index-now")
async def index_documents_now():
    """Trigger bulk indexing from DSpace using common research topics."""
    try:
        topics = [
            "computer science", "machine learning", "artificial intelligence",
            "data science", "software engineering", "bioinformatics",
            "robotics", "cybersecurity", "networking", "algorithms"
        ]
        
        existing_docs = []
        if os.path.exists(INDEXED_DOCS_FILE):
            with open(INDEXED_DOCS_FILE, "r", encoding="utf-8") as f:
                existing_docs = json.load(f)
        
        existing_uuids = {d.get("uuid") for d in existing_docs if d.get("uuid")}
        new_count = 0
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for topic in topics:
                try:
                    response = await client.get(
                        f"{DSPACE_API_URL}/discover/search/objects",
                        params={"query": topic, "dsoType": "item", "size": 50, "sort": "dc.date.accessioned,desc"}
                    )
                    if response.status_code != 200:
                        continue
                    
                    data = response.json()
                    objects = data.get("_embedded", {}).get("searchResult", {}).get("_embedded", {}).get("objects", [])
                    
                    for obj in objects:
                        if "_embedded" not in obj or "indexableObject" not in obj["_embedded"]:
                            continue
                        
                        item = obj["_embedded"]["indexableObject"]
                        uuid = item.get("uuid")
                        
                        if not uuid or uuid in existing_uuids:
                            continue
                        
                        metadata = item.get("metadata", {})
                        def get_values(field):
                            return [v.get("value", "") for v in metadata.get(field, []) if v.get("value")]
                        
                        doc = {
                            "uuid": uuid,
                            "title": get_values("dc.title")[0] if get_values("dc.title") else "",
                            "authors": get_values("dc.contributor.author"),
                            "advisors": get_values("dc.contributor.advisor"),
                            "abstract": get_values("dc.description.abstract")[0][:500] if get_values("dc.description.abstract") else "",
                            "date": get_values("dc.date.issued")[0] if get_values("dc.date.issued") else "",
                            "type": get_values("dc.type")[0] if get_values("dc.type") else "publication",
                            "subjects": get_values("dc.subject"),
                            "url": f"https://dr.lib.iastate.edu/items/{uuid}",
                            "source": "dspace",
                            "cache_indexed_at": datetime.now().isoformat(),
                            "indexed_via": topic
                        }
                        
                        existing_docs.append(doc)
                        existing_uuids.add(uuid)
                        new_count += 1
                        
                except Exception as e:
                    logger.error(f"Error indexing topic '{topic}': {e}")
                    continue
        
        # Save updated cache
        with open(INDEXED_DOCS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing_docs, f, indent=2)
        
        return {
            "message": f"Indexed {new_count} new documents",
            "total_cached": len(existing_docs),
            "topics_searched": topics
        }
    except Exception as e:
        logger.error(f"Error bulk indexing: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/documents/cache")
async def clear_cache():
    """Clear the document cache."""
    try:
        if os.path.exists(INDEXED_DOCS_FILE):
            with open(INDEXED_DOCS_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)
        return {"message": "Cache cleared"}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Faculty Mismatch Flagging System
# ============================================================

MISMATCHES_FILE = os.path.join(DATA_DIR, "flagged_mismatches.json")

class MismatchFlag(BaseModel):
    document_id: str
    document_title: str
    matched_faculty_id: str
    matched_faculty_name: str
    author_name_in_doc: str
    suggested_faculty_id: Optional[str] = None
    suggested_faculty_name: Optional[str] = None
    notes: Optional[str] = ""

@router.get("/mismatches")
async def get_mismatches():
    """Get all flagged mismatches pending review."""
    try:
        if not os.path.exists(MISMATCHES_FILE):
            return []
        with open(MISMATCHES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading mismatches: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/mismatches")
async def flag_mismatch(flag: MismatchFlag):
    """Flag a faculty mismatch for admin review."""
    try:
        mismatches = []
        if os.path.exists(MISMATCHES_FILE):
            with open(MISMATCHES_FILE, "r", encoding="utf-8") as f:
                mismatches = json.load(f)
        
        entry = flag.dict()
        entry["id"] = str(uuid.uuid4())
        entry["created_at"] = datetime.now().isoformat()
        entry["status"] = "pending"
        
        # Check for duplicate
        for m in mismatches:
            if m.get("document_id") == entry["document_id"] and m.get("matched_faculty_id") == entry["matched_faculty_id"]:
                return {"message": "Already flagged", "id": m.get("id")}
        
        mismatches.append(entry)
        
        with open(MISMATCHES_FILE, "w", encoding="utf-8") as f:
            json.dump(mismatches, f, indent=2)
        
        return {"message": "Mismatch flagged", "id": entry["id"]}
    except Exception as e:
        logger.error(f"Error flagging mismatch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class MismatchResolution(BaseModel):
    mismatch_id: str
    correct_faculty_id: Optional[str] = None
    action: str  # "correct", "ignore", "delete_match"

@router.post("/mismatches/resolve")
async def resolve_mismatch(resolution: MismatchResolution):
    """Resolve a flagged mismatch."""
    try:
        if not os.path.exists(MISMATCHES_FILE):
            raise HTTPException(status_code=404, detail="No mismatches found")
        
        with open(MISMATCHES_FILE, "r", encoding="utf-8") as f:
            mismatches = json.load(f)
        
        found = False
        for m in mismatches:
            if m.get("id") == resolution.mismatch_id:
                m["status"] = "resolved"
                m["resolved_at"] = datetime.now().isoformat()
                m["resolution_action"] = resolution.action
                if resolution.correct_faculty_id:
                    m["correct_faculty_id"] = resolution.correct_faculty_id
                found = True
                break
        
        if not found:
            raise HTTPException(status_code=404, detail="Mismatch not found")
        
        with open(MISMATCHES_FILE, "w", encoding="utf-8") as f:
            json.dump(mismatches, f, indent=2)
        
        return {"message": f"Mismatch resolved with action: {resolution.action}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving mismatch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/mismatches/{mismatch_id}")
async def delete_mismatch(mismatch_id: str):
    """Delete a flagged mismatch."""
    try:
        if not os.path.exists(MISMATCHES_FILE):
            raise HTTPException(status_code=404, detail="No mismatches found")
        
        with open(MISMATCHES_FILE, "r", encoding="utf-8") as f:
            mismatches = json.load(f)
        
        original_len = len(mismatches)
        mismatches = [m for m in mismatches if m.get("id") != mismatch_id]
        
        if len(mismatches) == original_len:
            raise HTTPException(status_code=404, detail="Mismatch not found")
        
        with open(MISMATCHES_FILE, "w", encoding="utf-8") as f:
            json.dump(mismatches, f, indent=2)
        
        return {"message": "Mismatch deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting mismatch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Topic Discovery System
# ============================================================

DISCOVERED_TOPICS_FILE = os.path.join(DATA_DIR, "topics_discovered.json")

@router.get("/topics/discovered")
async def get_discovered_topics():
    """Get all discovered topics from document analysis."""
    try:
        if not os.path.exists(DISCOVERED_TOPICS_FILE):
            return {"topics": [], "total_documents_analyzed": 0, "last_discovered": None}
        with open(DISCOVERED_TOPICS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading discovered topics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/topics/discover")
async def discover_topics():
    """Analyze all indexed documents and extract topics from subjects, keywords, and content."""
    try:
        documents = []
        
        # Load indexed documents
        if os.path.exists(INDEXED_DOCS_FILE):
            with open(INDEXED_DOCS_FILE, "r", encoding="utf-8") as f:
                documents.extend(json.load(f))
        
        # Load manual documents
        if os.path.exists(MANUAL_DOCS_FILE):
            with open(MANUAL_DOCS_FILE, "r", encoding="utf-8") as f:
                documents.extend(json.load(f))
        
        if not documents:
            return {"message": "No documents to analyze", "topics": []}
        
        # Research topic keywords to look for in titles/abstracts
        RESEARCH_KEYWORDS = [
            # AI & ML
            "machine learning", "deep learning", "neural network", "artificial intelligence",
            "reinforcement learning", "computer vision", "natural language processing",
            "convolutional neural", "recurrent neural", "transformer", "classification",
            "regression", "clustering", "prediction", "optimization", "generative",
            # Data Science
            "data mining", "big data", "analytics", "visualization", "statistics",
            "time series", "anomaly detection", "feature extraction", "dimensionality",
            # Security
            "security", "privacy", "cryptography", "encryption", "authentication",
            "malware", "intrusion detection", "vulnerability", "cyber",
            # Systems
            "distributed systems", "cloud computing", "parallel computing", "high performance",
            "networking", "internet of things", "iot", "embedded systems", "real-time",
            # Software Engineering
            "software engineering", "testing", "verification", "requirements", "design patterns",
            "agile", "devops", "continuous integration", "code analysis",
            # Robotics
            "robotics", "autonomous", "motion planning", "sensor", "control systems",
            "human-robot interaction", "swarm", "manipulation",
            # Theory
            "algorithm", "complexity", "graph theory", "optimization", "computational",
            "formal methods", "probabilistic", "stochastic",
            # Domain-specific
            "bioinformatics", "genomics", "medical imaging", "healthcare", "agriculture",
            "climate", "energy", "sustainability", "education", "social media",
            "wind turbine", "aerodynamics", "simulation", "virtual reality", "augmented reality",
            "cybersickness", "user experience", "human factors"
        ]
        
        # Extract topics from various fields
        topic_counts = {}
        topic_docs = {}  # topic -> list of document UUIDs
        
        for doc in documents:
            doc_id = doc.get("uuid") or doc.get("id") or doc.get("title", "")[:50]
            
            # Extract from subjects (primary source)
            subjects = doc.get("subjects", []) or []
            if isinstance(subjects, str):
                subjects = [s.strip() for s in subjects.split(",")]
            
            # Extract from keywords
            keywords = doc.get("keywords", []) or []
            if isinstance(keywords, str):
                keywords = [k.strip() for k in keywords.split(",")]
            
            # Extract from raw_metadata dc.subject
            raw_metadata = doc.get("raw_metadata", {}) or {}
            dc_subjects = raw_metadata.get("dc.subject", []) or []
            if isinstance(dc_subjects, str):
                dc_subjects = [dc_subjects]
            
            # NEW: Extract keywords from title and abstract
            title = (doc.get("title") or "").lower()
            abstract = (doc.get("abstract") or "").lower()
            content = title + " " + abstract
            
            # Find matching research keywords in content
            extracted_keywords = []
            for kw in RESEARCH_KEYWORDS:
                if kw in content:
                    extracted_keywords.append(kw.title())
            
            # Combine all topic sources
            all_topics = set()
            for topic_list in [subjects, keywords, dc_subjects, extracted_keywords]:
                for topic in topic_list:
                    if topic and len(topic.strip()) > 2:
                        normalized = topic.strip().title()
                        all_topics.add(normalized)

            
            # Count topics
            for topic in all_topics:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
                if topic not in topic_docs:
                    topic_docs[topic] = []
                topic_docs[topic].append(doc_id)
        
        # Sort by frequency and create structured output
        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
        
        # Create topic entries
        topics = []
        for topic, count in sorted_topics:
            if count >= 1:  # Include topics with at least 1 document
                topics.append({
                    "name": topic,
                    "count": count,
                    "documents": topic_docs.get(topic, [])[:10]  # First 10 doc IDs
                })
        
        # Group topics into categories (simple heuristic)
        def categorize_topic(topic_name):
            topic_lower = topic_name.lower()
            if any(kw in topic_lower for kw in ["machine learning", "deep learning", "neural", "ai", "artificial intelligence"]):
                return "AI & Machine Learning"
            elif any(kw in topic_lower for kw in ["computer vision", "image", "video", "recognition"]):
                return "Computer Vision"
            elif any(kw in topic_lower for kw in ["nlp", "language", "text", "speech"]):
                return "Natural Language Processing"
            elif any(kw in topic_lower for kw in ["data", "mining", "analytics", "big data"]):
                return "Data Science"
            elif any(kw in topic_lower for kw in ["security", "privacy", "crypto", "attack"]):
                return "Security & Privacy"
            elif any(kw in topic_lower for kw in ["robot", "autonomous", "control"]):
                return "Robotics"
            elif any(kw in topic_lower for kw in ["software", "testing", "engineering"]):
                return "Software Engineering"
            elif any(kw in topic_lower for kw in ["network", "distributed", "cloud", "system"]):
                return "Systems & Networks"
            elif any(kw in topic_lower for kw in ["bio", "genome", "protein", "medical", "health"]):
                return "Bioinformatics & Health"
            elif any(kw in topic_lower for kw in ["algorithm", "theory", "complexity"]):
                return "Theory & Algorithms"
            elif any(kw in topic_lower for kw in ["agriculture", "crop", "soil", "farm"]):
                return "Agriculture & Environment"
            else:
                return "Other Topics"
        
        # Group by category
        categories = {}
        for topic in topics:
            category = categorize_topic(topic["name"])
            if category not in categories:
                categories[category] = {"name": category, "topics": [], "total_docs": 0}
            categories[category]["topics"].append(topic)
            categories[category]["total_docs"] += topic["count"]
        
        # Sort categories by total documents
        sorted_categories = sorted(categories.values(), key=lambda x: x["total_docs"], reverse=True)
        
        result = {
            "total_documents_analyzed": len(documents),
            "total_topics_found": len(topics),
            "categories": sorted_categories,
            "top_topics": topics[:50],  # Top 50 topics overall
            "last_discovered": datetime.now().isoformat()
        }
        
        # Save discovered topics
        with open(DISCOVERED_TOPICS_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        
        return result
        
    except Exception as e:
        logger.error(f"Error discovering topics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Faculty Document Counts (for People Search)
# ============================================================

@router.get("/faculty/document-counts")
async def get_faculty_document_counts():
    """Get document counts for each faculty member by matching author names."""
    try:
        # Load faculty
        faculty_list = []
        if os.path.exists(FACULTY_FILE):
            with open(FACULTY_FILE, "r", encoding="utf-8") as f:
                faculty_list = json.load(f)
        
        if not faculty_list:
            return {"counts": {}, "total_faculty": 0}
        
        # Load indexed documents
        documents = []
        if os.path.exists(INDEXED_DOCS_FILE):
            with open(INDEXED_DOCS_FILE, "r", encoding="utf-8") as f:
                documents.extend(json.load(f))
        
        if os.path.exists(MANUAL_DOCS_FILE):
            with open(MANUAL_DOCS_FILE, "r", encoding="utf-8") as f:
                documents.extend(json.load(f))
        
        # Build faculty name lookup (normalize for matching)
        def normalize_name(name):
            if not name:
                return ""
            # Lowercase, remove extra spaces
            normalized = name.lower().strip()
            # Remove titles
            for title in ["dr.", "dr ", "prof.", "prof ", "professor "]:
                normalized = normalized.replace(title, "")
            return " ".join(normalized.split())
        
        # Create mapping of normalized names to faculty IDs
        faculty_names = {}
        for fac in faculty_list:
            name = fac.get("name", "")
            fac_id = fac.get("id")
            if name and fac_id:
                normalized = normalize_name(name)
                faculty_names[normalized] = fac_id
                # Also add last name only for partial matching
                parts = normalized.split()
                if len(parts) > 1:
                    faculty_names[parts[-1]] = fac_id  # Last name only
        
        # Count documents per faculty
        doc_counts = {}
        faculty_docs = {}  # faculty_id -> list of doc titles
        
        for doc in documents:
            authors = doc.get("authors", []) or []
            advisors = doc.get("advisors", []) or []
            all_people = authors + advisors
            
            for person in all_people:
                if not person:
                    continue
                normalized_person = normalize_name(person)
                
                # Try exact match first
                if normalized_person in faculty_names:
                    fac_id = faculty_names[normalized_person]
                    doc_counts[fac_id] = doc_counts.get(fac_id, 0) + 1
                    if fac_id not in faculty_docs:
                        faculty_docs[fac_id] = []
                    faculty_docs[fac_id].append(doc.get("title", "Untitled")[:80])
                else:
                    # Try matching by last name if person has multiple parts
                    person_parts = normalized_person.split()
                    if len(person_parts) > 1:
                        last_name = person_parts[-1]
                        # Check if last name + first initial matches any faculty
                        for fac_normalized, fac_id in faculty_names.items():
                            fac_parts = fac_normalized.split()
                            if len(fac_parts) > 1 and fac_parts[-1] == last_name:
                                # Last name matches, check first letter
                                if person_parts[0][0] == fac_parts[0][0]:
                                    doc_counts[fac_id] = doc_counts.get(fac_id, 0) + 1
                                    if fac_id not in faculty_docs:
                                        faculty_docs[fac_id] = []
                                    faculty_docs[fac_id].append(doc.get("title", "Untitled")[:80])
                                    break
        
        return {
            "counts": doc_counts,
            "sample_docs": {k: v[:5] for k, v in faculty_docs.items()},  # First 5 doc titles per faculty
            "total_faculty": len(faculty_list),
            "faculty_with_docs": len(doc_counts),
            "total_documents": len(documents)
        }
        
    except Exception as e:
        logger.error(f"Error getting faculty document counts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Vertex AI Search Endpoints
# ============================================================

@router.post("/vertex/search")
async def vertex_ai_search(
    query: str = Body(..., embed=True),
    limit: int = Body(10, embed=True),
    filters: Optional[Dict] = Body(None, embed=True)
):
    """
    Perform RAG-powered search using Vertex AI Search.
    Returns AI-generated summary with citations.
    """
    try:
        from services.vertex_ai_service import vertex_search_service
        result = await vertex_search_service.search(query, limit, filters)
        return result
    except ImportError:
        return {"error": "Vertex AI service not available", "answer": "", "sources": []}
    except Exception as e:
        logger.error(f"Vertex AI search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vertex/index-local")
async def index_local_documents():
    """
    Index all local documents (from indexed_documents.json) to Vertex AI Search.
    """
    try:
        from services.vertex_ai_service import vertex_search_service
        
        documents = []
        if os.path.exists(INDEXED_DOCS_FILE):
            with open(INDEXED_DOCS_FILE, "r", encoding="utf-8") as f:
                documents = json.load(f)
        
        if os.path.exists(MANUAL_DOCS_FILE):
            with open(MANUAL_DOCS_FILE, "r", encoding="utf-8") as f:
                documents.extend(json.load(f))
        
        if not documents:
            return {"message": "No documents to index", "indexed": 0}
        
        result = await vertex_search_service.index_documents_batch(documents)
        return {
            "message": f"Indexed {result['indexed']} documents to Vertex AI Search",
            **result
        }
        
    except ImportError:
        return {"error": "Vertex AI service not available"}
    except Exception as e:
        logger.error(f"Vertex AI indexing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/dspace")
async def sync_dspace_to_vertex():
    """
    Sync documents from DSpace to Vertex AI Search and Firestore.
    """
    try:
        from services.dspace_sync_service import dspace_sync_service
        
        result = await dspace_sync_service.full_sync(
            max_items=1000,
            include_pdfs=False  # Set to True to also download PDFs
        )
        
        return {
            "message": "DSpace sync completed",
            **result
        }
        
    except ImportError:
        return {"error": "DSpace sync service not available"}
    except Exception as e:
        logger.error(f"DSpace sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vertex/status")
async def get_vertex_status():
    """
    Get status of Vertex AI Search integration.
    """
    try:
        from services.vertex_ai_service import vertex_search_service
        
        return {
            "initialized": vertex_search_service.initialized,
            "project_id": vertex_search_service.project_id,
            "data_store_id": vertex_search_service.data_store_id,
            "engine_id": vertex_search_service.engine_id
        }
        
    except ImportError:
        return {"initialized": False, "error": "Vertex AI service not available"}
    except Exception as e:
        return {"initialized": False, "error": str(e)}

