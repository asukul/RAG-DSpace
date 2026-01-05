"""
ISU Research Search - FastAPI Backend
Final version with Gemini Files RAG Integration
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

# Gemini SDK
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================================
# Configuration
# ==========================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DSPACE_BASE_URL = os.getenv("DSPACE_BASE_URL", "https://dr.lib.iastate.edu")
DSPACE_API_URL = f"{DSPACE_BASE_URL}/server/api"

# Initialize Gemini
if GEMINI_AVAILABLE and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("Gemini configured successfully")

# ==========================================================
# FastAPI App
# ==========================================================

app = FastAPI(
    title="ISU Research Search API",
    description="AI-powered RAG search for Iowa State's DSpace repository",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# Models
# ==========================================================

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)

# ==========================================================
# Gemini RAG Service
# ==========================================================

class GeminiRAGService:
    """RAG search using Gemini Files API."""
    
    def __init__(self):
        self.model_name = "gemini-2.0-flash-exp"
        self.files_cache = None
        self.cache_time = None
    
    def _get_uploaded_files(self):
        """Get list of uploaded files (with caching)."""
        if not GENAI_AVAILABLE:
            return []
        
        try:
            # Cache for 5 minutes
            now = datetime.now()
            if self.files_cache and self.cache_time:
                if (now - self.cache_time).seconds < 300:
                    return self.files_cache
            
            self.files_cache = list(genai.list_files())
            self.cache_time = now
            logger.info(f"Loaded {len(self.files_cache)} files from Gemini")
            return self.files_cache
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return []
    
    async def search(self, query: str) -> Dict[str, Any]:
        """Perform RAG search using indexed documents."""
        
        if not GENAI_AVAILABLE or not GEMINI_API_KEY:
            return {
                "answer": f"Gemini not configured. Query: {query}",
                "sources": [],
                "files_searched": 0
            }
        
        try:
            files = self._get_uploaded_files()
            
            if not files:
                return {
                    "answer": "No documents indexed. Please run the ingestion pipeline first.",
                    "sources": [],
                    "files_searched": 0
                }
            
            logger.info(f"RAG search: '{query}' across {len(files)} files")
            
            model = genai.GenerativeModel(self.model_name)
            
            prompt = f"""You are a research assistant for Iowa State University's Computer Science department repository.

Based on the uploaded research documents, please answer this question:

QUESTION: {query}

INSTRUCTIONS:
1. Search through all uploaded documents for relevant information
2. Provide a comprehensive, accurate answer based ONLY on the documents
3. Cite specific papers by title and authors when possible
4. Format citations like: (Author, Year) or "According to [Paper Title]..."
5. If information isn't found in the documents, say so honestly
6. Keep the answer focused and informative (2-4 paragraphs)
7. At the end, list the most relevant papers you referenced

ANSWER:"""

            response = model.generate_content([*files, prompt])
            
            answer = response.text if response.text else "Unable to generate answer."
            
            # Extract potential sources from the answer (basic extraction)
            sources = self._extract_sources_from_answer(answer)
            
            return {
                "answer": answer,
                "sources": sources,
                "files_searched": len(files)
            }
            
        except Exception as e:
            logger.error(f"RAG search error: {e}")
            return {
                "answer": f"Search error: {str(e)}",
                "sources": [],
                "files_searched": 0
            }
    
    def _extract_sources_from_answer(self, answer: str) -> List[Dict]:
        """Extract cited sources from the answer."""
        # This is a simple extraction - in production you'd parse more carefully
        sources = []
        
        # Look for common citation patterns
        import re
        
        # Pattern: (Author, Year) or (Author et al., Year)
        citations = re.findall(r'\(([A-Z][a-z]+(?:\s+et\s+al\.)?),?\s*(\d{4})\)', answer)
        
        for author, year in citations[:5]:  # Limit to 5
            sources.append({
                "authors": [author],
                "year": year,
                "type": "citation"
            })
        
        return sources
    
    async def suggest_queries(self, query: str) -> List[str]:
        """Generate related query suggestions."""
        if not GENAI_AVAILABLE or not GEMINI_API_KEY:
            return [
                f"Latest research on {query}",
                f"Applications of {query}",
                f"{query} at Iowa State"
            ]
        
        try:
            model = genai.GenerativeModel(self.model_name)
            
            prompt = f"""Based on this research query: "{query}"

Generate 3 related follow-up questions a researcher might ask.
Return ONLY the questions, one per line, no numbering."""

            response = model.generate_content(prompt)
            suggestions = response.text.strip().split('\n')
            return [s.strip() for s in suggestions if s.strip()][:3]
            
        except Exception as e:
            logger.error(f"Suggestions error: {e}")
            return [f"More about {query}", f"Applications of {query}"]


# Initialize RAG service
rag_service = GeminiRAGService()

# ==========================================================
# DSpace Service
# ==========================================================

class DSpaceService:
    """Service for DSpace API."""
    
    def __init__(self):
        self.api_url = DSPACE_API_URL
        self.timeout = httpx.Timeout(30.0)
    
    async def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Search DSpace repository."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                url = f"{self.api_url}/discover/search/objects"
                params = {
                    "query": query,
                    "dsoType": "item",
                    "size": limit,
                    "sort": "score,desc"
                }
                
                response = await client.get(url, params=params)
                
                if response.status_code != 200:
                    return []
                
                data = response.json()
                
                items = []
                embedded = data.get("_embedded", {})
                search_result = embedded.get("searchResult", {})
                objects = search_result.get("_embedded", {}).get("objects", [])
                
                for obj in objects:
                    if "_embedded" in obj and "indexableObject" in obj["_embedded"]:
                        item = obj["_embedded"]["indexableObject"]
                        parsed = self._parse_item(item)
                        if parsed:
                            items.append(parsed)
                
                return items
                
        except Exception as e:
            logger.error(f"DSpace search error: {e}")
            return []
    
    def _parse_item(self, item: Dict) -> Optional[Dict]:
        """Parse DSpace item."""
        try:
            metadata = item.get("metadata", {})
            
            def get_values(field: str) -> List[str]:
                values = metadata.get(field, [])
                return [v.get("value", "") for v in values if v.get("value")]
            
            def get_first(field: str) -> str:
                values = get_values(field)
                return values[0] if values else ""
            
            title = get_first("dc.title")
            if not title:
                return None
            
            return {
                "uuid": item.get("uuid", ""),
                "title": title,
                "authors": get_values("dc.contributor.author"),
                "abstract": get_first("dc.description.abstract")[:300] + "..." if get_first("dc.description.abstract") else "",
                "date": get_first("dc.date.issued"),
                "type": get_first("dc.type") or "publication",
                "url": f"{DSPACE_BASE_URL}/items/{item.get('uuid', '')}"
            }
        except:
            return None


dspace_service = DSpaceService()

# ==========================================================
# Faculty Data
# ==========================================================

FACULTY_DATA = [
    {"id": "wallapak-tavanapong", "name": "Wallapak Tavanapong", "email": "tavanapo@iastate.edu", "rank": "Professor", "title": "Kingland Professor", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/tavanapong_wallapak.jpg", "profile_url": "https://www.cs.iastate.edu/people/wallapak-tavanapong", "research_areas": ["AI and Machine Learning"], "research_interests": ["Medical AI", "Deep Learning", "Computer Vision"]},
    {"id": "hongyang-gao", "name": "Hongyang Gao", "email": "hygao@iastate.edu", "rank": "Assistant Professor", "title": None, "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/img_1814_0.jpg", "profile_url": "https://www.cs.iastate.edu/people/hongyang-gao", "research_areas": ["AI and Machine Learning"], "research_interests": ["Deep Learning", "Graph Neural Networks"]},
    {"id": "myra-cohen", "name": "Myra Cohen", "email": "mcohen@iastate.edu", "rank": "Professor", "title": "Nguyen Chair", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/myra_cohen_0.jpg", "profile_url": "https://www.cs.iastate.edu/people/myra-cohen", "research_areas": ["Software Engineering"], "research_interests": ["Software Testing", "Search-Based SE"]},
    {"id": "adisak-sukul", "name": "Adisak Sukul", "email": "adisak@iastate.edu", "rank": "Teaching Professor", "title": "Google Cloud Expert", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/sukul_adisak.jpg", "profile_url": "https://www.cs.iastate.edu/people/adisak-sukul", "research_areas": ["AI and Machine Learning"], "research_interests": ["Data Science", "Machine Learning", "Cloud Computing"]},
    {"id": "mengdi-huai", "name": "Mengdi Huai", "email": "mdhuai@iastate.edu", "rank": "Assistant Professor", "title": None, "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/mengdi_img.jpg", "profile_url": "https://www.cs.iastate.edu/people/mengdi-huai", "research_areas": ["AI and Machine Learning"], "research_interests": ["Trustworthy AI", "Fairness in ML"]},
    {"id": "qi-li", "name": "Qi Li", "email": "qli@iastate.edu", "rank": "Associate Professor", "title": None, "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-06/Qi%20Li%202023.jpg", "profile_url": "https://www.cs.iastate.edu/people/qi-li", "research_areas": ["Security"], "research_interests": ["Cybersecurity", "ML Security"]},
    {"id": "wei-le", "name": "Wei Le", "email": "weile@iastate.edu", "rank": "Associate Professor", "title": None, "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-07/Capture%20One%20Catalog1631%202.jpg", "profile_url": "https://www.cs.iastate.edu/people/wei-le", "research_areas": ["Software Engineering"], "research_interests": ["Program Analysis", "ML for Code"]},
    {"id": "bowen-weng", "name": "Bowen Weng", "email": "bweng@iastate.edu", "rank": "Assistant Professor", "title": None, "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/bowenw_0.jpeg", "profile_url": "https://www.cs.iastate.edu/people/bowen-weng", "research_areas": ["Robotics", "AI and Machine Learning"], "research_interests": ["Reinforcement Learning", "Autonomous Vehicles"]},
]

# ==========================================================
# API Endpoints
# ==========================================================

@app.get("/")
async def root():
    """Root endpoint."""
    files_count = len(rag_service._get_uploaded_files()) if GENAI_AVAILABLE else 0
    return {
        "name": "ISU Research Search API",
        "version": "3.0.0 - RAG Enabled",
        "status": "running",
        "gemini_configured": bool(GEMINI_API_KEY),
        "indexed_documents": files_count,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health")
async def health():
    """Health check."""
    files_count = len(rag_service._get_uploaded_files()) if GENAI_AVAILABLE else 0
    return {
        "status": "healthy",
        "gemini": bool(GEMINI_API_KEY),
        "indexed_files": files_count,
        "dspace_url": DSPACE_BASE_URL
    }


@app.post("/api/search")
async def search(request: SearchRequest):
    """RAG-powered search endpoint."""
    logger.info(f"Search request: {request.query}")
    
    # Run RAG search and DSpace search in parallel
    rag_task = rag_service.search(request.query)
    dspace_task = dspace_service.search(request.query, limit=request.limit)
    suggestions_task = rag_service.suggest_queries(request.query)
    
    rag_result, dspace_results, suggestions = await asyncio.gather(
        rag_task, dspace_task, suggestions_task
    )
    
    # Find related faculty
    query_lower = request.query.lower()
    related_faculty = [
        f for f in FACULTY_DATA
        if any(query_lower in interest.lower() for interest in f.get("research_interests", []))
    ][:3]
    
    return {
        "query": request.query,
        "answer": rag_result.get("answer", ""),
        "sources": dspace_results,  # Real DSpace results
        "rag_sources": rag_result.get("sources", []),
        "files_searched": rag_result.get("files_searched", 0),
        "related_faculty": related_faculty,
        "suggested_queries": suggestions,
        "total_results": len(dspace_results)
    }


@app.get("/api/faculty")
async def list_faculty(search: Optional[str] = None):
    """List faculty."""
    if search:
        search_lower = search.lower()
        return [
            f for f in FACULTY_DATA
            if search_lower in f["name"].lower()
            or any(search_lower in i.lower() for i in f.get("research_interests", []))
        ]
    return FACULTY_DATA


@app.get("/api/faculty/{faculty_id}")
async def get_faculty(faculty_id: str):
    """Get faculty by ID."""
    for f in FACULTY_DATA:
        if f["id"] == faculty_id:
            return f
    raise HTTPException(status_code=404, detail="Faculty not found")


@app.get("/api/stats")
async def get_stats():
    """Get system statistics."""
    files_count = len(rag_service._get_uploaded_files()) if GENAI_AVAILABLE else 0
    return {
        "indexed_documents": files_count,
        "faculty_count": len(FACULTY_DATA),
        "gemini_enabled": bool(GEMINI_API_KEY),
        "dspace_url": DSPACE_BASE_URL
    }


@app.on_event("startup")
async def startup():
    files_count = 0
    if GENAI_AVAILABLE and GEMINI_API_KEY:
        files_count = len(rag_service._get_uploaded_files())
    
    logger.info("=" * 60)
    logger.info("ISU Research Search API v3.0 - RAG Enabled")
    logger.info(f"Gemini configured: {bool(GEMINI_API_KEY)}")
    logger.info(f"Indexed documents: {files_count}")
    logger.info(f"DSpace URL: {DSPACE_BASE_URL}")
    logger.info("=" * 60)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
