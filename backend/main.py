"""
ISU Research Search - Enhanced Backend
With Courses, Full Faculty Data, and Document Type Grouping
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import httpx
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import Admin Service
from admin_service import router as admin_router

# ==========================================================
# Configuration
# ==========================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DSPACE_BASE_URL = os.getenv("DSPACE_BASE_URL", "https://dr.lib.iastate.edu")
DSPACE_API_URL = f"{DSPACE_BASE_URL}/server/api"

# Gemini SDK
GENAI_AVAILABLE = False
genai = None

try:
    import google.generativeai as genai_module
    genai = genai_module
    GENAI_AVAILABLE = True
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        logger.info("Gemini SDK configured successfully")
except ImportError:
    logger.warning("google-generativeai not installed")
except Exception as e:
    logger.error(f"Gemini error: {e}")

# ==========================================================
# FastAPI App
# ==========================================================

app = FastAPI(
    title="ISU Research Search API",
    description="Enhanced API with Courses, Faculty, and RAG Search",
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)

# ==========================================================
# Data Models
# ==========================================================

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)

# ==========================================================
# Course Data
# ==========================================================

COURSES = [
    {"number": "COM S 101", "name": "Orientation to Computer Science", "level": "Introductory", "credits": "1", "topics": ["Fundamentals"]},
    {"number": "COM S 107", "name": "Introduction to Web Development", "level": "Introductory", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COM S 127", "name": "Introduction to Computer Programming", "level": "Introductory", "credits": "3", "topics": ["Fundamentals"]},
    {"number": "COM S 203", "name": "Computer Architecture", "level": "Sophomore", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COM S 227", "name": "Object-oriented Programming", "level": "Sophomore", "credits": "4", "topics": ["Software Engineering"]},
    {"number": "COM S 228", "name": "Introduction to Data Structures", "level": "Sophomore", "credits": "3", "topics": ["Fundamentals"]},
    {"number": "COM S 230", "name": "Discrete Computational Structures", "level": "Sophomore", "credits": "3", "topics": ["Theory"]},
    {"number": "COM S 252", "name": "Linux Operating System Essentials", "level": "Sophomore", "credits": "1", "topics": ["Systems and Networking"]},
    {"number": "COM S 309", "name": "Software Development Practices", "level": "Junior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COM S 311", "name": "Design and Analysis of Algorithms", "level": "Junior", "credits": "3", "topics": ["Theory"]},
    {"number": "COM S 319", "name": "Software Construction and User Interfaces", "level": "Junior", "credits": "3", "topics": ["Software Engineering", "Human-Computer Interaction"]},
    {"number": "COM S 321", "name": "Computer Architecture and Machine-Level Programming", "level": "Junior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COM S 327", "name": "Advanced Programming Techniques", "level": "Junior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COM S 331", "name": "Theory of Computing", "level": "Junior", "credits": "3", "topics": ["Theory"]},
    {"number": "COM S 336", "name": "Introduction to Computer Graphics", "level": "Junior", "credits": "3", "topics": ["Computer Vision"]},
    {"number": "COM S 342", "name": "Principles of Programming Languages", "level": "Junior", "credits": "3", "topics": ["Programming Languages"]},
    {"number": "COM S 352", "name": "Introduction to Operating Systems", "level": "Junior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COM S 362", "name": "Object-Oriented Analysis and Design", "level": "Junior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COM S 363", "name": "Introduction to Database Management Systems", "level": "Junior", "credits": "3", "topics": ["Systems and Networking", "Data Science"]},
    {"number": "COM S 402", "name": "Computer Science Senior Project", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COM S 409", "name": "Software Requirements Engineering", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COM S 417", "name": "Software Testing", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COM S 421", "name": "Logic for Mathematics and Computer Science", "level": "Senior", "credits": "3", "topics": ["Theory"]},
    {"number": "COM S 425", "name": "Introduction to High Performance Computing", "level": "Senior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COM S 430", "name": "Information Retrieval", "level": "Senior", "credits": "3", "topics": ["Data Science", "AI and Machine Learning"]},
    {"number": "COM S 435", "name": "Algorithms in Computational Biology", "level": "Senior", "credits": "3", "topics": ["Bioinformatics"]},
    {"number": "COM S 440", "name": "Principles and Practice of Compiling", "level": "Senior", "credits": "3", "topics": ["Programming Languages"]},
    {"number": "COM S 461", "name": "Principles and Internals of Database Systems", "level": "Senior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COM S 472", "name": "Principles of Artificial Intelligence", "level": "Senior", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COM S 474", "name": "Introduction to Machine Learning", "level": "Senior", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COM S 481", "name": "Computer Security", "level": "Senior", "credits": "3", "topics": ["Security"]},
    {"number": "COM S 486", "name": "Fundamental Concepts in Computer Networking", "level": "Senior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COM S 511", "name": "Design and Analysis of Algorithms", "level": "Graduate", "credits": "3", "topics": ["Theory"]},
    {"number": "COM S 512", "name": "Formal Methods in Software Engineering", "level": "Graduate", "credits": "3", "topics": ["Software Engineering", "Theory"]},
    {"number": "COM S 531", "name": "Theory of Computation", "level": "Graduate", "credits": "3", "topics": ["Theory"]},
    {"number": "COM S 572", "name": "Principles of Artificial Intelligence", "level": "Graduate", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COM S 573", "name": "Machine Learning", "level": "Graduate", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COM S 577", "name": "Computer Vision", "level": "Graduate", "credits": "3", "topics": ["Computer Vision"]},
    {"number": "COM S 579", "name": "Introduction to Deep Learning", "level": "Graduate", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COM S 583", "name": "Reconfigurable Computing", "level": "Graduate", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COM S 587", "name": "Software Architecture", "level": "Graduate", "credits": "3", "topics": ["Software Engineering"]},
]

# ==========================================================
# Faculty Data (Complete)
# ==========================================================

# Load Faculty Data
import json
import os
from verified_faculty_data import VERIFIED_FACULTY_DATA

# Define Data Paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

FACULTY_FILE = os.path.join(DATA_DIR, "faculty.json")
MANUAL_DOCS_FILE = os.path.join(DATA_DIR, "manual_documents.json")

def load_or_seed_faculty_data():
    """
    Loads faculty data from faculty.json. 
    If not exists, seeds it from Verified + LAS Scraped data.
    """
    if os.path.exists(FACULTY_FILE):
        try:
            with open(FACULTY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"Loaded {len(data)} faculty from faculty.json")
            return data
        except Exception as e:
            logger.error(f"Error loading faculty.json: {e}")
            # Fallback to reseeding if corrupt
            pass

    logger.info("Seeding faculty.json from source files...")
    
    # 1. Load Scraped LAS Data
    las_faculty = []
    las_data_path = os.path.join(DATA_DIR, "las_faculty.json")
    
    if os.path.exists(las_data_path):
        try:
            with open(las_data_path, "r", encoding="utf-8") as f:
                las_faculty = json.load(f)
            logger.info(f"Loaded {len(las_faculty)} faculty from las_faculty.json")
        except Exception as e:
            logger.error(f"Error loading las_faculty.json: {e}")

    # 2. Merge with Verified Data (Verified takes precedence)
    verified_map = {f['id']: f for f in VERIFIED_FACULTY_DATA}
    verified_names = {f['name'].lower(): f['id'] for f in VERIFIED_FACULTY_DATA}
    
    final_faculty_list = list(VERIFIED_FACULTY_DATA)
    
    # 3. Add Scraped Faculty not in Verified List
    for person in las_faculty:
        if person['id'] in verified_map:
            continue
        if person['name'].lower() in verified_names:
            continue
        
        # Defaults
        if "courses_taught" not in person:
            person["courses_taught"] = []
        if "is_teaching_faculty" not in person:
            person["is_teaching_faculty"] = False
        if "department" not in person:
            person["department"] = "Unknown Department"
        if "college" not in person:
            person["college"] = "College of Liberal Arts and Sciences"
            
        final_faculty_list.append(person)

    # 4. Save to faculty.json
    try:
        with open(FACULTY_FILE, "w", encoding="utf-8") as f:
            json.dump(final_faculty_list, f, indent=2)
        logger.info(f"Seeded faculty.json with {len(final_faculty_list)} entries")
    except Exception as e:
        logger.error(f"Error saving faculty.json: {e}")
        
    return final_faculty_list

FACULTY_DATA = load_or_seed_faculty_data()
logger.info(f"Total Faculty Compiled: {len(FACULTY_DATA)}")

# ==========================================================
# RAG Service
# ==========================================================

class GeminiRAGService:
    def __init__(self):
        self.model_name = "gemini-2.0-flash-exp"
        self.files_cache = None
        self.cache_time = None
    
    def _get_files(self):
        if not GENAI_AVAILABLE or not genai:
            return []
        try:
            now = datetime.now()
            if self.files_cache and self.cache_time:
                if (now - self.cache_time).seconds < 300:
                    return self.files_cache
            self.files_cache = list(genai.list_files())
            self.cache_time = now
            return self.files_cache
        except:
            return []
    
    async def search(self, query: str) -> Dict:
        if not GENAI_AVAILABLE or not GEMINI_API_KEY or not genai:
            return await self._api_search(query)
        
        try:
            files = self._get_files()
            if not files:
                return await self._api_search(query)
            
            model = genai.GenerativeModel(self.model_name)
            prompt = f"""You are a research assistant for Iowa State University's Computer Science department.
Answer this question based on the uploaded research documents:

QUESTION: {query}

Provide a comprehensive answer. Cite papers by title/author when relevant. If not found, say so."""

            response = model.generate_content([*files, prompt])
            return {"answer": response.text or "", "files_searched": len(files), "mode": "rag"}
        except Exception as e:
            logger.error(f"RAG error: {e}")
            return await self._api_search(query)
    
    async def _api_search(self, query: str) -> Dict:
        if not GEMINI_API_KEY:
            return {"answer": f"Configure GEMINI_API_KEY. Query: {query}", "files_searched": 0, "mode": "demo"}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",
                    params={"key": GEMINI_API_KEY},
                    json={"contents": [{"parts": [{"text": f"Answer about computer science research: {query}"}]}]}
                )
                if response.status_code == 200:
                    data = response.json()
                    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    return {"answer": text, "files_searched": 0, "mode": "api"}
        except:
            pass
        return {"answer": f"Search: {query}", "files_searched": 0, "mode": "fallback"}

    async def _find_relevant_faculty_gemini(self, query: str, faculty_list: List[Dict]) -> List[Dict]:
        """Use Gemini to find the most relevant faculty for a query."""
        if not GENAI_AVAILABLE or not GEMINI_API_KEY or not genai:
            return []
        
        try:
            # Prepare faculty summary
            faculty_summary = []
            for f in faculty_list:
                info = f"{f['name']} ({f.get('group', 'Unknown')}) - Interests: {', '.join(f.get('research_interests', []))}"
                faculty_summary.append(f"{f['id']}: {info}")
            
            prompt = f"""You are a helpful research assistant.
IDENTIFY RELEVANT EXPERTS.
Query: "{query}"

List of Faculty:
{chr(10).join(faculty_summary[:50])}  # Limit context size if needed

Task: Return a JSON array of the IDs of the top 3-5 most relevant faculty members for the query.
Example: ["yan-bin-jia", "bowen-weng"]
Return ONLY the JSON array.
"""
            model = genai.GenerativeModel("gemini-2.0-flash-exp")
            response = await model.generate_content_async(prompt)
            
            import json
            text = response.text.replace("```json", "").replace("```", "").strip()
            relevant_ids = json.loads(text)
            
            # Filter faculty list
            results = [f for f in faculty_list if f["id"] in relevant_ids]
            return results
        except Exception as e:
            logger.error(f"Gemini matching error: {e}")
            return []

rag_service = GeminiRAGService()

async def find_relevant_faculty(query: str, faculty_list: List[Dict]) -> List[Dict]:
    """Find relevant faculty using Gemini or fallback to keywords."""
    # 1. Try Gemini
    gemini_results = await rag_service._find_relevant_faculty_gemini(query, faculty_list)
    if gemini_results:
        return gemini_results
    
    # 2. Fallback: weighted keyword matching
    q = query.lower()
    scored = []
    
    terms = q.split()
    
    for f in faculty_list:
        score = 0
        text = (
            f['name'] + " " + 
            " ".join(f.get('research_interests', [])) + " " + 
            f.get('group', '') + " " + 
            f.get('department', '')
        ).lower()
        
        if q in text:
            score += 10
            
        for term in terms:
            if len(term) > 3 and term in text:
                score += 2
        
        if score > 0:
            scored.append((score, f))
            
    # Sort by score desc
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[:5]]

# ==========================================================
# DSpace Service
# ==========================================================

class DSpaceService:
    def __init__(self):
        self.api_url = DSPACE_API_URL
        self.timeout = httpx.Timeout(30.0)
    
    async def search(self, query: str, limit: int = 20) -> List[Dict]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.api_url}/discover/search/objects",
                    params={"query": query, "dsoType": "item", "size": limit, "sort": "score,desc"}
                )
                if response.status_code != 200:
                    return []
                
                data = response.json()
                items = []
                for obj in data.get("_embedded", {}).get("searchResult", {}).get("_embedded", {}).get("objects", []):
                    if "_embedded" in obj and "indexableObject" in obj["_embedded"]:
                        item = self._parse(obj["_embedded"]["indexableObject"])
                        if item:
                            items.append(item)
                return items
        except:
            return []
    
    def _parse(self, item: Dict) -> Optional[Dict]:
        try:
            metadata = item.get("metadata", {})
            def get(f): 
                v = metadata.get(f, [])
                return [x.get("value", "") for x in v if x.get("value")]
            
            title = get("dc.title")
            if not title:
                return None
            
            abstract = get("dc.description.abstract")
            return {
                "uuid": item.get("uuid", ""),
                "title": title[0],
                "authors": get("dc.contributor.author"),
                "advisors": get("dc.contributor.advisor") + get("dc.contributor.majorProfessor"),
                "contributors": get("dc.contributor"),
                "abstract": abstract[0][:300] + "..." if abstract else "",
                "date": get("dc.date.issued")[0] if get("dc.date.issued") else "",
                "type": get("dc.type")[0] if get("dc.type") else "publication",
                "url": f"{DSPACE_BASE_URL}/items/{item.get('uuid', '')}"
            }
        except:
            return None

dspace_service = DSpaceService()

# ==========================================================
# API Endpoints
# ==========================================================

@app.get("/")
async def root():
    return {"name": "ISU Research Search API", "version": "4.0.0", "status": "running"}

@app.get("/health")
async def health():
    return {"status": "healthy", "gemini": bool(GEMINI_API_KEY), "indexed_files": len(rag_service._get_files())}

@app.post("/api/search")
async def search(request: SearchRequest):
    rag_task = rag_service.search(request.query)
    dspace_task = dspace_service.search(request.query, limit=request.limit)
    rag_result, dspace_sources = await asyncio.gather(rag_task, dspace_task)
    
    # 0. Load Manual Documents
    manual_sources = []
    try:
        if os.path.exists(MANUAL_DOCS_FILE):
             with open(MANUAL_DOCS_FILE, "r", encoding="utf-8") as f:
                 all_manual = json.load(f)
                 # Simple filtering for manual docs
                 q_lower = request.query.lower()
                 for doc in all_manual:
                     text = (doc.get("title", "") + " " + doc.get("abstract", "")).lower()
                     if q_lower in text: # Basic substring match
                         manual_sources.append(doc)
    except Exception as e:
        logger.error(f"Error loading manual docs: {e}")

    sources = manual_sources + dspace_sources # Manual docs first
    
    # 1. Semantic/Keyword Search for Related Faculty (General Recommendation)
    semantic_related = await find_relevant_faculty(request.query, FACULTY_DATA)
    
    # 2. Extract "Found Experts" directly from the search results (Ordered by appearance)
    found_faculty = []
    found_ids = set()
    
    for source in sources:
        # Collect people from this paper
        people = (source.get("authors", []) or []) + (source.get("advisors", []) or []) + (source.get("contributors", []) or [])
        
        for person_name in people:
            p_lower = person_name.lower()
            
            for f in FACULTY_DATA:
                if f['id'] in found_ids:
                    continue
                
                f_name = f['name'].lower()
                f_last = f_name.split()[-1]
                
                # Strict matching logic (similar to frontend regex \b)
                # Check 1: Full Name match with word boundaries
                is_match = False
                if f_name in p_lower:
                     idx = p_lower.find(f_name)
                     if (idx == 0 or not p_lower[idx-1].isalpha()) and \
                        (idx + len(f_name) == len(p_lower) or not p_lower[idx + len(f_name)].isalpha()):
                            is_match = True

                # Check 2: Last Name match (only if full name didn't match)
                if not is_match and f_last in p_lower:
                     idx = p_lower.find(f_last)
                     if (idx == 0 or not p_lower[idx-1].isalpha()) and \
                        (idx + len(f_last) == len(p_lower) or not p_lower[idx + len(f_last)].isalpha()):
                            is_match = True
                
                if is_match:
                    found_faculty.append(f)
                    found_ids.add(f['id'])
    
    # 3. Filter Semantic Results to remove anyone already found in the papers
    # This creates the distinct "Related Experts" list (similar topics but not in these papers)
    related_faculty = [f for f in semantic_related if f['id'] not in found_ids]

    # 4. Auto-cache DSpace results for future analytics
    if dspace_sources:
        try:
            INDEXED_DOCS_FILE = os.path.join(DATA_DIR, "indexed_documents.json")
            existing_docs = []
            if os.path.exists(INDEXED_DOCS_FILE):
                with open(INDEXED_DOCS_FILE, "r", encoding="utf-8") as f:
                    existing_docs = json.load(f)
            
            existing_uuids = {d.get("uuid") for d in existing_docs if d.get("uuid")}
            new_count = 0
            
            for doc in dspace_sources:
                if doc.get("uuid") and doc.get("uuid") not in existing_uuids:
                    doc["cache_indexed_at"] = datetime.now().isoformat()
                    doc["source"] = "dspace"
                    existing_docs.append(doc)
                    existing_uuids.add(doc["uuid"])
                    new_count += 1
            
            if new_count > 0:
                with open(INDEXED_DOCS_FILE, "w", encoding="utf-8") as f:
                    json.dump(existing_docs, f, indent=2)
                logger.info(f"Cached {new_count} new DSpace documents (total: {len(existing_docs)})")
        except Exception as e:
            logger.error(f"Error caching DSpace docs: {e}")

    return {
        "query": request.query,
        "answer": rag_result.get("answer", ""),
        "sources": sources,
        "files_searched": rag_result.get("files_searched", 0),
        "search_mode": rag_result.get("mode", "unknown"),
        "found_faculty": found_faculty,      # Experts explicitly in the results
        "related_faculty": related_faculty,  # Experts relevant by topic
        "suggested_queries": [f"Latest {request.query} research", f"{request.query} applications", f"{request.query} at ISU"],
        "total_results": len(sources)
    }

@app.get("/api/faculty")
async def list_faculty(search: Optional[str] = None, group: Optional[str] = None, teaching_only: bool = False, research_only: bool = False):
    # Dynamically load from file to reflect any admin changes
    try:
        with open(FACULTY_FILE, "r", encoding="utf-8") as f:
            results = json.load(f)
    except Exception as e:
        logger.error(f"Error loading faculty for API: {e}")
        results = []
        
    if teaching_only:
        results = [f for f in results if f.get("is_teaching_faculty")]
    if research_only:
        results = [f for f in results if not f.get("is_teaching_faculty")]
    if group:
        results = [f for f in results if f.get("group", "").lower() == group.lower()]
    if search:
        s = search.lower()
        results = [f for f in results if s in f["name"].lower() or any(s in i.lower() for i in f.get("research_interests", []))]
    return results

@app.get("/api/faculty/{faculty_id}")
async def get_faculty(faculty_id: str):
    for f in FACULTY_DATA:
        if f["id"] == faculty_id:
            return f
    raise HTTPException(status_code=404, detail="Faculty not found")

@app.get("/api/courses")
async def list_courses(level: Optional[str] = None, topic: Optional[str] = None):
    results = COURSES
    if level:
        results = [c for c in results if c.get("level", "").lower() == level.lower()]
    if topic:
        results = [c for c in results if any(topic.lower() in t.lower() for t in c.get("topics", []))]
    return {"courses": results, "total": len(results)}

@app.get("/api/courses/{course_number}")
async def get_course(course_number: str):
    for c in COURSES:
        if c["number"].replace(" ", "").lower() == course_number.replace(" ", "").lower():
            # Find instructors
            instructors = [f for f in FACULTY_DATA if c["number"] in f.get("courses_taught", [])]
            return {**c, "instructors": instructors}
    raise HTTPException(status_code=404, detail="Course not found")

@app.get("/api/stats")
async def get_stats():
    return {
        "indexed_documents": len(rag_service._get_files()),
        "faculty_count": len(FACULTY_DATA),
        "teaching_faculty": len([f for f in FACULTY_DATA if f.get("is_teaching_faculty")]),
        "research_faculty": len([f for f in FACULTY_DATA if not f.get("is_teaching_faculty")]),
        "courses_count": len(COURSES),
        "gemini_enabled": bool(GEMINI_API_KEY)
    }

@app.get("/api/groups")
async def get_groups():
    groups = {}
    for f in FACULTY_DATA:
        g = f.get("group", "Other")
        if g not in groups:
            groups[g] = 0
        groups[g] += 1
    return {"groups": [{"name": k, "count": v} for k, v in sorted(groups.items())]}

@app.on_event("startup")
async def startup():
    logger.info("=" * 60)
    logger.info("ISU Research Search API v4.0 - Enhanced")
    logger.info(f"Gemini: {'✓' if GEMINI_API_KEY else '✗'}")
    logger.info(f"Faculty: {len(FACULTY_DATA)} | Courses: {len(COURSES)}")
    logger.info("=" * 60)
