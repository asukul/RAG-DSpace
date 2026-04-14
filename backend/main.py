"""
ISU Research Search - Enhanced Backend
With Courses, Full Faculty Data, and Document Type Grouping
"""

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import os
import time
import httpx
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import Admin Service
from admin_service import router as admin_router
from services.embedding_service import embedding_service
from services.collaboration_service import collaboration_service
from services.topic_service import topic_service
from services.qdrant_rag_service import qdrant_rag_service
from services.auth_service import get_auth_service, _public_user
from services.dspace_local_service import get_dspace_local_service
from services.kg_service import get_kg_service
from services.openalex_cache_service import get_openalex_cache_service
from services.paper_reconcile_service import get_paper_reconcile_service

# ==========================================================
# Configuration
# ==========================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")  # legacy, unused for Vertex path
DSPACE_BASE_URL = os.getenv("DSPACE_BASE_URL", "https://dr.lib.iastate.edu")
DSPACE_API_URL = f"{DSPACE_BASE_URL}/server/api"
GCP_PROJECT = os.getenv("GCP_PROJECT", "rag-dspace")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
GEMINI_GEN_MODEL = os.getenv("GEMINI_GEN_MODEL", "gemini-2.5-flash")

# Vertex AI via google-genai SDK
GENAI_AVAILABLE = False
genai_client = None

try:
    from google import genai as google_genai
    genai_client = google_genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
    )
    GENAI_AVAILABLE = True
    logger.info(
        f"google-genai Vertex client initialized (project={GCP_PROJECT}, location={GCP_LOCATION})"
    )
    embedding_service.configure(vertex_client=genai_client)
except ImportError:
    logger.warning("google-genai not installed")
except Exception as e:
    logger.error(f"google-genai Vertex init error: {e}")
    # Still let embedding_service pick up Ollama/vertex envs on its own
    try:
        embedding_service.configure()
    except Exception:
        pass

# ==========================================================
# FastAPI App
# ==========================================================

app = FastAPI(
    title="ISU Research Search API",
    description="Semantic search with embeddings, courses, faculty, and RAG",
    version="5.0.0",
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


class GoogleLoginRequest(BaseModel):
    credential: str = Field(..., description="Google ID token (JWT) from GIS button")


class SetRoleRequest(BaseModel):
    email: str
    role: str  # 'user' | 'admin'


class ItemConflictResolveRequest(BaseModel):
    item_uuid: str = Field(..., description="UUID of the item to resolve")
    department: str = Field(..., description="Chosen department for this item")


class FacultyConflictResolveRequest(BaseModel):
    faculty_id: str = Field(..., description="Faculty slug id")
    primary_department: str = Field(..., description="Chosen primary department")
    action: str = Field(..., description="'keep_all' | 'merge' | 'remove_affiliation'")
    remove_affiliations: List[str] = Field(
        default_factory=list,
        description="Affiliations to remove (only used when action='remove_affiliation')",
    )


# ----------------------------------------------------------
# Auth dependency helpers
# ----------------------------------------------------------

def get_current_user_optional(
    authorization: Optional[str] = Header(default=None),
) -> Optional[Dict[str, Any]]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        return get_auth_service().get_user_from_token(token)
    except Exception:
        return None


def require_user(
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user

# ==========================================================
# Course Data
# ==========================================================

COURSES = [
    {"number": "COMS 1010", "name": "Orientation", "level": "Introductory", "credits": "3", "topics": ["Fundamentals"]},
    {"number": "COMS 1030", "name": "Computer Literacy and Applications", "level": "Introductory", "credits": "3", "topics": ["Fundamentals"]},
    {"number": "COMS 1040", "name": "Brief Introduction to Computer Programming for Non-Majors", "level": "Introductory", "credits": "3", "topics": ["Fundamentals"]},
    {"number": "COMS 1060", "name": "Introduction to Web Programming", "level": "Introductory", "credits": "3", "topics": ["Fundamentals"]},
    {"number": "COMS 1130", "name": "Introduction to Spreadsheets and Databases", "level": "Introductory", "credits": "3", "topics": ["Data Science", "Fundamentals"]},
    {"number": "COMS 1270", "name": "Introduction to Programming for Problem Solving", "level": "Introductory", "credits": "3", "topics": ["Fundamentals"]},
    {"number": "COMS 2030", "name": "Careers in Computer Science", "level": "Sophomore", "credits": "3", "topics": ["Fundamentals"]},
    {"number": "COMS 2070", "name": "Fundamentals of Computer Programming", "level": "Sophomore", "credits": "3", "topics": ["Fundamentals"]},
    {"number": "COMS 2270", "name": "Object-Oriented Programming", "level": "Sophomore", "credits": "3", "topics": ["Computer Science"]},
    {"number": "COMS 2280", "name": "Introduction to Data Structures", "level": "Sophomore", "credits": "3", "topics": ["Data Science"]},
    {"number": "COMS 2300", "name": "Discrete Computational Structures", "level": "Sophomore", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 2520", "name": "Linux Operating System Essentials", "level": "Sophomore", "credits": "3", "topics": ["Systems and Networking", "Fundamentals"]},
    {"number": "COMS 3090", "name": "Software Development Practices", "level": "Junior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 3110", "name": "Introduction to the Design and Analysis of Algorithms", "level": "Junior", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 3190", "name": "Construction of User Interfaces", "level": "Junior", "credits": "3", "topics": ["Human-Computer Interaction"]},
    {"number": "COMS 3210", "name": "Introduction to Computer Architecture and Machine-Level Programming", "level": "Junior", "credits": "3", "topics": ["Computer Science"]},
    {"number": "COMS 3260", "name": "C for Programmers", "level": "Junior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 3270", "name": "Advanced Programming Techniques", "level": "Junior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 3310", "name": "Theory of Computing", "level": "Junior", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 3360", "name": "Introduction to Computer Graphics", "level": "Junior", "credits": "3", "topics": ["Graphics and Games"]},
    {"number": "COMS 3420", "name": "Principles of Programming Languages", "level": "Junior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 3520", "name": "Introduction to Operating Systems", "level": "Junior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 3620", "name": "Object-Oriented Analysis and Design", "level": "Junior", "credits": "3", "topics": ["Computer Science"]},
    {"number": "COMS 3630", "name": "Introduction to Database Management Systems", "level": "Junior", "credits": "3", "topics": ["Data Science"]},
    {"number": "COMS 4020", "name": "Computer Science Senior Project", "level": "Senior", "credits": "3", "topics": ["Computer Science"]},
    {"number": "COMS 4070", "name": "Applied Formal Methods", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 4090", "name": "Software Requirements Engineering", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 4100", "name": "Distributed Development of Software", "level": "Senior", "credits": "3", "topics": ["Systems and Networking", "Software Engineering"]},
    {"number": "COMS 4120", "name": "Formal Methods in Software Engineering", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 4130", "name": "Foundations and Applications of Program Analysis", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 4140", "name": "Gerontechnology in Smart Home Environments", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 4150", "name": "Software System Safety", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 4170", "name": "Software Testing", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 4180", "name": "Introduction to Computational Geometry", "level": "Senior", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 4190X", "name": "Trustworthy Healthcare Software", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 4210", "name": "Logic for Mathematics and Computer Science", "level": "Senior", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 4240", "name": "Introduction to High Performance Computing", "level": "Senior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 4250", "name": "High Performance Computing for Scientific and Engineering Applications", "level": "Senior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 4300", "name": "Concurrent Programming", "level": "Senior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 4330", "name": "Molecular Programming of Nanoscale Devices and Processes", "level": "Senior", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 4340", "name": "Quantum Information and Complexity", "level": "Senior", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 4350", "name": "Algorithms for Large Data Sets: Theory and Practice", "level": "Senior", "credits": "3", "topics": ["Data Science", "Theory"]},
    {"number": "COMS 4370", "name": "Computer Game and Media Programming", "level": "Senior", "credits": "3", "topics": ["Graphics and Games"]},
    {"number": "COMS 4400", "name": "Principles and Practice of Compiling", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 4410", "name": "Programming Languages", "level": "Senior", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 4530", "name": "Privacy Preserving Algorithms and Data Security", "level": "Senior", "credits": "3", "topics": ["Data Science", "Security", "Theory"]},
    {"number": "COMS 4540", "name": "Distributed Systems", "level": "Senior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 4550", "name": "Simulation: Algorithms and Implementation", "level": "Senior", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 4590X", "name": "Security and Privacy in Cloud Computing", "level": "Senior", "credits": "3", "topics": ["Systems and Networking", "Security"]},
    {"number": "COMS 4610", "name": "Principles and Internals of Database Systems", "level": "Senior", "credits": "3", "topics": ["Data Science"]},
    {"number": "COMS 4720", "name": "Principles of Artificial Intelligence", "level": "Senior", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COMS 4740", "name": "Introduction to Machine Learning", "level": "Senior", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COMS 4760", "name": "Motion Strategy Algorithms and Applications", "level": "Senior", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 4770", "name": "Foundations of Robotics and Computer Vision", "level": "Senior", "credits": "3", "topics": ["Computer Vision"]},
    {"number": "COMS 4870", "name": "Introduction to Network Programming and Cloud Computing", "level": "Senior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 4880", "name": "Computer Networks", "level": "Senior", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 5010X", "name": "Computational Methods I", "level": "Graduate", "credits": "3", "topics": ["Computer Science"]},
    {"number": "COMS 5040X", "name": "Computational Methods II", "level": "Graduate", "credits": "3", "topics": ["Computer Science"]},
    {"number": "COMS 5070", "name": "Applied Formal Methods", "level": "Graduate", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 5090", "name": "Software Requirements Engineering", "level": "Graduate", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 5100", "name": "Distributed Development of Software", "level": "Graduate", "credits": "3", "topics": ["Systems and Networking", "Software Engineering"]},
    {"number": "COMS 5110", "name": "Design and Analysis of Algorithms", "level": "Graduate", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 5120", "name": "Formal Methods in Software Engineering", "level": "Graduate", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 5130", "name": "Foundations and Applications of Program Analysis", "level": "Graduate", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 5140", "name": "Gerontechnology in Smart Home Environments", "level": "Graduate", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 5150", "name": "Software System Safety", "level": "Graduate", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 5180", "name": "Introduction to Computational Geometry", "level": "Graduate", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 5190X", "name": "Trustworthy Healthcare Software", "level": "Graduate", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 5270X", "name": "Concurrent Systems", "level": "Graduate", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 5310", "name": "Theory of Computation", "level": "Graduate", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 5330", "name": "Computational Models of Nanoscale Self-Assembly", "level": "Graduate", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 5340", "name": "Quantum Information and Complexity", "level": "Graduate", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 5350", "name": "Algorithms for Large Data Sets: Theory and Practice", "level": "Graduate", "credits": "3", "topics": ["Data Science", "Theory"]},
    {"number": "COMS 5400", "name": "Principles and Practice of Compiling", "level": "Graduate", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 5410", "name": "Programming Languages", "level": "Graduate", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 5510", "name": "Computational Techniques for Genome Assembly and Analysis", "level": "Graduate", "credits": "3", "topics": ["Bioinformatics"]},
    {"number": "COMS 5520", "name": "Principles of Operating Systems", "level": "Graduate", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 5530", "name": "Privacy-Preserving Algorithms and Data Security", "level": "Graduate", "credits": "3", "topics": ["Data Science", "Security", "Theory"]},
    {"number": "COMS 5540", "name": "Distributed Systems", "level": "Graduate", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 5550", "name": "Simulation: Algorithms and Implementation", "level": "Graduate", "credits": "3", "topics": ["Theory"]},
    {"number": "COMS 5590", "name": "Security and Privacy in Cloud Computing", "level": "Graduate", "credits": "3", "topics": ["Systems and Networking", "Security"]},
    {"number": "COMS 5610", "name": "Database Design, Management, and Research", "level": "Graduate", "credits": "3", "topics": ["Data Science"]},
    {"number": "COMS 5670", "name": "Bioinformatics Algorithms", "level": "Graduate", "credits": "3", "topics": ["Theory", "Bioinformatics"]},
    {"number": "COMS 5690", "name": "Structural Bioinformatics", "level": "Graduate", "credits": "3", "topics": ["Bioinformatics"]},
    {"number": "COMS 5720", "name": "Principles of Artificial Intelligence", "level": "Graduate", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COMS 5730", "name": "Machine Learning", "level": "Graduate", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COMS 5740", "name": "Introduction to Machine Learning", "level": "Graduate", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COMS 5760", "name": "Motion Planning for Robotics and Autonomous Systems", "level": "Graduate", "credits": "3", "topics": ["Computer Vision"]},
    {"number": "COMS 5770", "name": "Foundations of Robotics and Computer Vision", "level": "Graduate", "credits": "3", "topics": ["Computer Vision"]},
    {"number": "COMS 5780X", "name": "Optimization for Machine Learning", "level": "Graduate", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COMS 5790", "name": "Natural Language Processing", "level": "Graduate", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COMS 5860", "name": "Computer Network Architectures", "level": "Graduate", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 5870", "name": "Network Programming, Applications, and Research Issues", "level": "Graduate", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 5880", "name": "Computer Networks", "level": "Graduate", "credits": "3", "topics": ["Systems and Networking"]},
    {"number": "COMS 6120", "name": "Distributed Algorithms", "level": "Advanced Graduate", "credits": "3", "topics": ["Systems and Networking", "Theory"]},
    {"number": "COMS 6330", "name": "Advanced Topics in Computational Randomness", "level": "Advanced Graduate", "credits": "3", "topics": ["Computer Science"]},
    {"number": "COMS 6650A", "name": "Advanced Topics in Software Engineering", "level": "Advanced Graduate", "credits": "3", "topics": ["Software Engineering"]},
    {"number": "COMS 6720", "name": "Advanced Topics in Artificial Intelligence", "level": "Advanced Graduate", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "COMS 6730", "name": "Advanced Topics in Machine Learning", "level": "Advanced Graduate", "credits": "3", "topics": ["AI and Machine Learning"]},
    {"number": "AI 2010X", "name": "Introduction to Artificial Intelligence", "level": "Sophomore", "credits": "3", "topics": ["AI and Machine Learning"]},
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
    If not exists, seeds it from Verified + LAS + CoE Scraped data.
    """
    if os.path.exists(FACULTY_FILE):
        try:
            with open(FACULTY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Only use cached data if it has a reasonable number of entries
            if len(data) >= 100:
                logger.info(f"Loaded {len(data)} faculty from faculty.json")
                return data
            else:
                logger.info(f"faculty.json has only {len(data)} entries, reseeding...")
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
    
    # 2. Load Scraped CoE Data
    coe_faculty = []
    coe_data_path = os.path.join(DATA_DIR, "coe_faculty.json")
    
    if os.path.exists(coe_data_path):
        try:
            with open(coe_data_path, "r", encoding="utf-8") as f:
                coe_faculty = json.load(f)
            logger.info(f"Loaded {len(coe_faculty)} faculty from coe_faculty.json")
        except Exception as e:
            logger.error(f"Error loading coe_faculty.json: {e}")

    # 3. Load Scraped Ivy Business Data
    ivy_faculty = []
    ivy_data_path = os.path.join(DATA_DIR, "ivy_faculty.json")
    
    if os.path.exists(ivy_data_path):
        try:
            with open(ivy_data_path, "r", encoding="utf-8") as f:
                ivy_faculty = json.load(f)
            logger.info(f"Loaded {len(ivy_faculty)} faculty from ivy_faculty.json")
        except Exception as e:
            logger.error(f"Error loading ivy_faculty.json: {e}")

    # 4. Merge with Verified Data (Verified takes precedence)
    verified_map = {f['id']: f for f in VERIFIED_FACULTY_DATA}
    verified_names = {f['name'].lower(): f['id'] for f in VERIFIED_FACULTY_DATA}
    
    final_faculty_list = list(VERIFIED_FACULTY_DATA)
    added_ids = set(verified_map.keys())
    added_names = set(verified_names.keys())
    
    # 4. Add Scraped LAS Faculty not in Verified List
    for person in las_faculty:
        if person['id'] in added_ids:
            continue
        if person['name'].lower() in added_names:
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
        added_ids.add(person['id'])
        added_names.add(person['name'].lower())
    
    # 5. Add Scraped CoE Faculty not already added
    for person in coe_faculty:
        if person.get('id') in added_ids:
            continue
        if person['name'].lower() in added_names:
            continue
        
        # Defaults
        if "courses_taught" not in person:
            person["courses_taught"] = []
        if "is_teaching_faculty" not in person:
            person["is_teaching_faculty"] = False
        if "department" not in person:
            person["department"] = "Unknown Department"
        if "college" not in person:
            person["college"] = "College of Engineering"
            
        final_faculty_list.append(person)
        added_ids.add(person.get('id', ''))
        added_names.add(person['name'].lower())

    # 7. Add Scraped Ivy Business Faculty not already added
    for person in ivy_faculty:
        if person.get('id') in added_ids:
            continue
        if person['name'].lower() in added_names:
            continue
        
        # Defaults
        if "courses_taught" not in person:
            person["courses_taught"] = []
        if "is_teaching_faculty" not in person:
            person["is_teaching_faculty"] = False
        if "department" not in person:
            person["department"] = "Unknown Department"
        if "college" not in person:
            person["college"] = "Ivy College of Business"
            
        final_faculty_list.append(person)
        added_ids.add(person.get('id', ''))
        added_names.add(person['name'].lower())

    # 8. Load and Add CALS Faculty
    cals_faculty = []
    cals_data_path = os.path.join(DATA_DIR, "cals_faculty.json")
    
    if os.path.exists(cals_data_path):
        try:
            with open(cals_data_path, "r", encoding="utf-8") as f:
                cals_faculty = json.load(f)
            logger.info(f"Loaded {len(cals_faculty)} faculty from cals_faculty.json")
        except Exception as e:
            logger.error(f"Error loading cals_faculty.json: {e}")

    for person in cals_faculty:
        if person.get('id') in added_ids:
            continue
        if person['name'].lower() in added_names:
            continue
        
        # Defaults
        if "courses_taught" not in person:
            person["courses_taught"] = []
        if "is_teaching_faculty" not in person:
            person["is_teaching_faculty"] = False
        if "department" not in person:
            person["department"] = "Unknown Department"
        if "college" not in person:
            person["college"] = "College of Agriculture and Life Sciences"
            
        final_faculty_list.append(person)
        added_ids.add(person.get('id', ''))
        added_names.add(person['name'].lower())

    # 9. Load and Add Design Faculty
    design_faculty = []
    design_data_path = os.path.join(DATA_DIR, "design_faculty.json")
    
    if os.path.exists(design_data_path):
        try:
            with open(design_data_path, "r", encoding="utf-8") as f:
                design_faculty = json.load(f)
            logger.info(f"Loaded {len(design_faculty)} faculty from design_faculty.json")
        except Exception as e:
            logger.error(f"Error loading design_faculty.json: {e}")

    for person in design_faculty:
        if person.get('id') in added_ids:
            continue
        if person['name'].lower() in added_names:
            continue
        
        # Defaults
        if "courses_taught" not in person:
            person["courses_taught"] = []
        if "is_teaching_faculty" not in person:
            person["is_teaching_faculty"] = False
        if "department" not in person:
            person["department"] = "Unknown Department"
        if "college" not in person:
            person["college"] = "College of Design"
            
        final_faculty_list.append(person)
        added_ids.add(person.get('id', ''))
        added_names.add(person['name'].lower())

    # 10. Save to faculty.json
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
# Legacy GeminiRAGService (Files API path) was removed.
# All RAG flows go through services.qdrant_rag_service.qdrant_rag_service,
# which retrieves from the dspace_chunks Qdrant collection (39k vectors,
# Vertex text-embedding-005, 768d) and generates with Gemini 2.5 Flash on Vertex.

async def find_relevant_faculty(query: str, faculty_list: List[Dict]) -> List[Dict]:
    """Find relevant faculty using semantic embeddings, with keyword fallback."""
    # 1. Try semantic embedding search (fast, no generation call)
    semantic_results = embedding_service.search(query, top_k=8, threshold=0.3)
    if semantic_results:
        return [
            {**faculty, "_similarity": score}
            for faculty, score in semantic_results
        ]

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

    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[:8]]

# ==========================================================
# DSpace Service
# ==========================================================

class DSpaceService:
    def __init__(self):
        self.api_url = DSPACE_API_URL
        # Tight timeout — DSpace fan-out is best-effort; if it's slow we
        # fall back to the Qdrant-only result rather than blocking the user.
        self.timeout = httpx.Timeout(8.0, connect=4.0)
    
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
    return {"name": "ISU Research Search API", "version": "5.0.0", "status": "running"}

@app.get("/health")
async def health():
    qdrant_count = 0
    qdrant_collection_name = os.environ.get("QDRANT_COLLECTION", "dspace_chunks")
    try:
        if qdrant_rag_service.initialized and qdrant_rag_service._client is not None:
            info = qdrant_rag_service._client.get_collection(qdrant_collection_name)
            qdrant_count = info.points_count or 0
    except Exception:
        pass
    return {
        "status": "healthy",
        "gemini": GENAI_AVAILABLE and genai_client is not None,
        "qdrant_collection": qdrant_collection_name,
        "qdrant_chunks": qdrant_count,
        "rag_ready": qdrant_rag_service.initialized,
    }

def _person_name_matches(faculty_name: str, person_text: str) -> bool:
    """
    Strict full-name match used for "Found Experts" extraction.

    A faculty member matches a person string only if BOTH first name and last
    name appear in the person string (handles "First Last" and "Last, First").
    A bare last-name match is intentionally NOT enough — that pulls in every
    researcher who shares a common surname (Li, Mitra, Qi, ...).
    """
    if not faculty_name or not person_text:
        return False
    p = person_text.lower()
    parts = [w for w in faculty_name.lower().replace(",", " ").split() if w]
    if not parts:
        return False

    first = parts[0]
    last = parts[-1]
    full = " ".join(parts)

    if full in p:
        return True
    # "Sukul, Adisak" / "Last First" — both names present and last appears as a token
    def _word_present(word: str) -> bool:
        idx = p.find(word)
        if idx == -1:
            return False
        before_ok = idx == 0 or not p[idx - 1].isalpha()
        after_ok = idx + len(word) == len(p) or not p[idx + len(word)].isalpha()
        return before_ok and after_ok

    return _word_present(first) and _word_present(last)


def _enrich_citations_with_advisors(citations, dspace_sources):
    """
    Qdrant payloads only carry the `authors` field, but `dc.contributor.majorProfessor`
    holds the academic advisor for theses/dissertations. Look up each citation's
    UUID in the live DSpace results and merge in advisors + contributors so the
    frontend can render "Authors and Advisors" correctly.
    """
    by_uuid = {s.get("uuid"): s for s in (dspace_sources or []) if s.get("uuid")}
    enriched = []
    for c in citations or []:
        c2 = dict(c)
        ds = by_uuid.get(c.get("uuid"))
        if ds:
            advisors = ds.get("advisors") or []
            contributors = ds.get("contributors") or []
            if advisors:
                c2["advisors"] = advisors
            if contributors:
                c2["contributors"] = contributors
            # Replace authors with the well-formed DSpace list when available
            if ds.get("authors"):
                c2["authors_list"] = ds["authors"]
        enriched.append(c2)
    return enriched


@app.post("/api/search")
async def search(
    request: SearchRequest,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    started = time.time()
    rag_task = qdrant_rag_service.search(request.query)
    dspace_task = dspace_service.search(request.query, limit=request.limit)
    rag_result, dspace_sources = await asyncio.gather(rag_task, dspace_task)

    # Local DSpace metadata index — adds papers the live API misses
    # (the live discover endpoint caps at 50; our local index has 82k items).
    try:
        local_results = get_dspace_local_service().search(
            request.query, limit=max(request.limit, 30)
        )
        if local_results:
            existing_uuids = {s.get("uuid") for s in dspace_sources if s.get("uuid")}
            for r in local_results:
                if r.get("uuid") and r["uuid"] not in existing_uuids:
                    dspace_sources.append(r)
                    existing_uuids.add(r["uuid"])
    except Exception as e:
        logger.error(f"local DSpace search failed: {e}")

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

    # Enrich citations with advisor info from DSpace (Qdrant payload doesn't carry it)
    citations = _enrich_citations_with_advisors(
        rag_result.get("citations", []), dspace_sources
    )
    retrieved_chunks = _enrich_citations_with_advisors(
        rag_result.get("retrieved_chunks", []), dspace_sources
    )

    # 1. Semantic/Keyword Search for Related Faculty (General Recommendation)
    semantic_related = await find_relevant_faculty(request.query, FACULTY_DATA)

    # 2. Extract "Found Experts" directly from the search results (ordered by appearance).
    # Two sources of author info:
    #   (a) `sources` — DSpace REST keyword search results, with dc.contributor.author
    #       + advisors + contributors populated from the live DSpace API.
    #   (b) `retrieved_chunks` — Qdrant RAG results, with `authors` populated from
    #       the chunk payload. Needed because the RAG chunks may point at papers
    #       that don't surface in the DSpace keyword search (e.g., papers whose
    #       title doesn't contain the query terms but whose chunk content does).
    found_faculty = []
    found_ids = set()

    retrieved_chunks_list = rag_result.get("retrieved_chunks", []) or []

    for paper_source in list(sources) + list(retrieved_chunks_list):
        people = (
            (paper_source.get("authors", []) or [])
            + (paper_source.get("advisors", []) or [])
            + (paper_source.get("contributors", []) or [])
        )

        for person_name in people:
            for f in FACULTY_DATA:
                if f['id'] in found_ids:
                    continue
                if _person_name_matches(f['name'], person_name):
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

    duration_ms = int((time.time() - started) * 1000)

    # Log search activity (best-effort)
    try:
        get_auth_service().log_search(
            user_id=(current_user or {}).get("id"),
            query=request.query,
            mode=rag_result.get("mode"),
            duration_ms=duration_ms,
            result_count=len(sources),
        )
    except Exception as e:
        logger.error(f"search log failed: {e}")

    return {
        "query": request.query,
        "answer": rag_result.get("answer", ""),
        "citations": citations,                                # Qdrant chunks enriched with advisors
        "retrieved_chunks": retrieved_chunks,
        "sources": sources,                                    # Legacy DSpace + manual sources (kept for backwards compat)
        "files_searched": rag_result.get("files_searched", 0),
        "search_mode": rag_result.get("mode", "unknown"),
        "found_faculty": found_faculty,      # Experts explicitly in the results
        "related_faculty": related_faculty,  # Experts relevant by topic
        "suggested_queries": [f"Latest {request.query} research", f"{request.query} applications", f"{request.query} at ISU"],
        "total_results": len(sources),
        "duration_ms": duration_ms,
    }


@app.post("/api/search/stream")
async def search_stream(
    request: SearchRequest,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    """
    Streaming version of /api/search.

    Wire format: Server-Sent Events. Each event is a JSON line prefixed
    with `data:` and terminated by a blank line. Event types:
      - meta:  one event with citations + sources + faculty (everything except the answer)
      - token: zero-or-more events with incremental text chunks of the answer
      - done:  final event with timing + total result counts

    The frontend can render results immediately on `meta`, then "type in"
    the AI answer character by character as `token` events arrive.
    """
    started = time.time()
    user_id = (current_user or {}).get("id")

    async def event_stream():
        # Phase 1: parallel retrieval (Qdrant chunks + DSpace live API)
        rag_meta_task = qdrant_rag_service.search_meta_only(request.query)
        dspace_task = dspace_service.search(request.query, limit=request.limit)
        rag_meta, dspace_sources = await asyncio.gather(rag_meta_task, dspace_task)

        # Local DSpace metadata index — supplements live API results
        try:
            local_results = get_dspace_local_service().search(
                request.query, limit=max(request.limit, 30)
            )
            if local_results:
                existing_uuids = {s.get("uuid") for s in dspace_sources if s.get("uuid")}
                for r in local_results:
                    if r.get("uuid") and r["uuid"] not in existing_uuids:
                        dspace_sources.append(r)
                        existing_uuids.add(r["uuid"])
        except Exception as e:
            logger.error(f"local DSpace search (stream) failed: {e}")

        sources = dspace_sources

        citations = _enrich_citations_with_advisors(
            rag_meta.get("citations", []), dspace_sources
        )
        retrieved_chunks = _enrich_citations_with_advisors(
            rag_meta.get("retrieved_chunks", []), dspace_sources
        )

        # Faculty extraction (same logic as /api/search)
        semantic_related = await find_relevant_faculty(request.query, FACULTY_DATA)
        found_faculty = []
        found_ids = set()
        for source in sources:
            people = (
                (source.get("authors", []) or [])
                + (source.get("advisors", []) or [])
                + (source.get("contributors", []) or [])
            )
            for person_name in people:
                for f in FACULTY_DATA:
                    if f['id'] in found_ids:
                        continue
                    if _person_name_matches(f['name'], person_name):
                        found_faculty.append(f)
                        found_ids.add(f['id'])
        related_faculty = [f for f in semantic_related if f['id'] not in found_ids]

        meta_payload = {
            "query": request.query,
            "citations": citations,
            "retrieved_chunks": retrieved_chunks,
            "sources": sources,
            "files_searched": rag_meta.get("files_searched", 0),
            "search_mode": rag_meta.get("mode", "unknown"),
            "found_faculty": found_faculty,
            "related_faculty": related_faculty,
            "total_results": len(sources),
        }

        meta_elapsed_ms = int((time.time() - started) * 1000)
        meta_payload["meta_duration_ms"] = meta_elapsed_ms

        # Send the meta event
        yield f"event: meta\ndata: {json.dumps(meta_payload, ensure_ascii=False)}\n\n"

        # Phase 2: stream the LLM answer
        raw_chunks = rag_meta.get("_raw_chunks") or []
        if not raw_chunks:
            answer_text = "No relevant passages were found in the indexed corpus."
            yield f"event: token\ndata: {json.dumps({'text': answer_text})}\n\n"
        else:
            from services.qdrant_rag_service import _build_context as _bc
            context = _bc(raw_chunks)
            answer_text = ""
            # Run the blocking generator in a thread to avoid blocking the loop.
            # We collect chunks via a queue.
            import queue, threading
            q: "queue.Queue[Optional[str]]" = queue.Queue()

            def producer():
                try:
                    for piece in qdrant_rag_service._generate_stream(request.query, context):
                        q.put(piece)
                finally:
                    q.put(None)

            t = threading.Thread(target=producer, daemon=True)
            t.start()
            while True:
                piece = await asyncio.to_thread(q.get)
                if piece is None:
                    break
                answer_text += piece
                yield f"event: token\ndata: {json.dumps({'text': piece}, ensure_ascii=False)}\n\n"

        total_ms = int((time.time() - started) * 1000)
        # Log the search activity
        try:
            get_auth_service().log_search(
                user_id=user_id,
                query=request.query,
                mode=rag_meta.get("mode"),
                duration_ms=total_ms,
                result_count=len(sources),
            )
        except Exception as e:
            logger.error(f"stream search log failed: {e}")

        done = {
            "answer_chars": len(answer_text),
            "duration_ms": total_ms,
        }
        yield f"event: done\ndata: {json.dumps(done)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx hint to flush immediately
        },
    )


# Need json in scope for the streaming endpoint above
import json as _json_module  # noqa  (json already imported at top)


# ----------------------------------------------------------
# Authentication endpoints
# ----------------------------------------------------------

@app.post("/api/auth/google")
async def auth_google(req: GoogleLoginRequest):
    try:
        result = get_auth_service().login_with_google(req.credential)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"google login failed: {e}")
        raise HTTPException(status_code=500, detail="Login failure")
    return result


@app.get("/api/auth/me")
async def auth_me(
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    if user is None:
        return {"authenticated": False}
    return {"authenticated": True, "user": _public_user(user)}


@app.post("/api/auth/logout")
async def auth_logout():
    # Stateless JWT — client just discards the token. Endpoint exists so the
    # frontend has a clean call to make and so we can extend with token blocklist later.
    return {"ok": True}


# ----------------------------------------------------------
# Admin endpoints (gated by require_admin)
# ----------------------------------------------------------

@app.get("/api/admin/system")
async def admin_system(_: Dict[str, Any] = Depends(require_admin)):
    qdrant_count = 0
    qdrant_collection_name = os.environ.get("QDRANT_COLLECTION", "dspace_chunks")
    try:
        if qdrant_rag_service.initialized and qdrant_rag_service._client is not None:
            info = qdrant_rag_service._client.get_collection(qdrant_collection_name)
            qdrant_count = info.points_count or 0
    except Exception:
        pass
    try:
        dspace_local_stats = get_dspace_local_service().stats()
    except Exception:
        dspace_local_stats = {"ready": False, "items": 0}
    return {
        "backend": {
            "version": app.version,
            "gemini_ready": GENAI_AVAILABLE and genai_client is not None,
            "rag_ready": qdrant_rag_service.initialized,
            "embedding_backend": embedding_service.backend,
            "embedding_count": len(embedding_service.faculty_embeddings),
        },
        "qdrant": {
            "collection": os.environ.get("QDRANT_COLLECTION", "dspace_chunks"),
            "points": qdrant_count,
        },
        "dspace_local": dspace_local_stats,
        "data": {
            "faculty_total": len(FACULTY_DATA),
            "courses_total": len(COURSES),
        },
        "auth": get_auth_service().stats(),
    }


@app.get("/api/admin/users")
async def admin_users(
    limit: int = Query(default=200, ge=1, le=1000),
    _: Dict[str, Any] = Depends(require_admin),
):
    return {"users": get_auth_service().list_users(limit=limit)}


@app.get("/api/admin/searches")
async def admin_searches(
    limit: int = Query(default=100, ge=1, le=500),
    _: Dict[str, Any] = Depends(require_admin),
):
    return {"searches": get_auth_service().list_recent_searches(limit=limit)}


@app.get("/api/admin/users/{user_id}/searches")
async def admin_user_searches(
    user_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    _: Dict[str, Any] = Depends(require_admin),
):
    return {"searches": get_auth_service().list_user_searches(user_id, limit=limit)}


@app.post("/api/admin/users/role")
async def admin_set_role(
    req: SetRoleRequest,
    _: Dict[str, Any] = Depends(require_admin),
):
    ok = get_auth_service().set_role(req.email, req.role)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


# ----------------------------------------------------------
# Department conflict resolution endpoints (admin-only)
# ----------------------------------------------------------

CONFLICTS_FILE = os.path.join(DATA_DIR, "department_conflicts.json")
DSPACE_INDEX_DB = os.path.join(DATA_DIR, "dspace", "dspace_index.db")


def _load_conflicts() -> Dict[str, Any]:
    """Load department_conflicts.json from disk."""
    if not os.path.exists(CONFLICTS_FILE):
        raise HTTPException(status_code=404, detail="department_conflicts.json not found")
    with open(CONFLICTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_conflicts(data: Dict[str, Any]) -> None:
    """Atomically save department_conflicts.json back to disk."""
    tmp_path = CONFLICTS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, CONFLICTS_FILE)


@app.get("/api/admin/conflicts")
async def admin_get_conflicts(
    _: Dict[str, Any] = Depends(require_admin),
):
    """Return the full department conflicts data."""
    return _load_conflicts()


@app.post("/api/admin/conflicts/item/resolve")
async def admin_resolve_item_conflict(
    req: ItemConflictResolveRequest,
    _: Dict[str, Any] = Depends(require_admin),
):
    """
    Resolve a single item department conflict.
    Sets status='resolved' and resolution=chosen department in the JSON.
    Also updates dspace_index.db if available.
    """
    data = _load_conflicts()

    # Find the matching item conflict
    found = False
    for item in data.get("item_conflicts", []):
        if item["item_uuid"] == req.item_uuid:
            item["status"] = "resolved"
            item["resolution"] = req.department
            item["current_department"] = req.department
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"Item conflict not found: {req.item_uuid}")

    _save_conflicts(data)

    # Update dspace_index.db if it exists
    db_updated = False
    if os.path.exists(DSPACE_INDEX_DB):
        try:
            import sqlite3
            conn = sqlite3.connect(DSPACE_INDEX_DB)
            conn.execute(
                "UPDATE items SET department = ? WHERE uuid = ?",
                (req.department, req.item_uuid),
            )
            conn.commit()
            conn.close()
            db_updated = True
        except Exception as e:
            logger.error(f"Failed to update dspace_index.db for {req.item_uuid}: {e}")

    return {"ok": True, "item_uuid": req.item_uuid, "department": req.department, "db_updated": db_updated}


@app.post("/api/admin/conflicts/faculty/resolve")
async def admin_resolve_faculty_conflict(
    req: FacultyConflictResolveRequest,
    _: Dict[str, Any] = Depends(require_admin),
):
    """
    Resolve a faculty department conflict.
    Updates department_conflicts.json and faculty.json.
    """
    if req.action not in ("keep_all", "merge", "remove_affiliation"):
        raise HTTPException(status_code=400, detail=f"Invalid action: {req.action}")

    data = _load_conflicts()

    # Find the matching faculty conflict
    found = False
    for fac in data.get("faculty_conflicts", []):
        if fac["faculty_id"] == req.faculty_id:
            fac["status"] = "resolved"
            fac["resolution"] = {
                "action": req.action,
                "primary_department": req.primary_department,
                "removed_affiliations": req.remove_affiliations,
            }
            fac["primary_department"] = req.primary_department
            if req.action == "remove_affiliation" and req.remove_affiliations:
                fac["affiliations"] = [
                    a for a in fac.get("affiliations", [])
                    if a not in req.remove_affiliations
                ]
                fac["all_departments"] = [
                    d for d in fac.get("all_departments", [])
                    if d not in req.remove_affiliations
                ]
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"Faculty conflict not found: {req.faculty_id}")

    _save_conflicts(data)

    # Update faculty.json
    faculty_updated = False
    if os.path.exists(FACULTY_FILE):
        try:
            with open(FACULTY_FILE, "r", encoding="utf-8") as f:
                faculty_list = json.load(f)

            for fac in faculty_list:
                if fac.get("id") == req.faculty_id:
                    fac["department"] = req.primary_department
                    if req.action == "remove_affiliation" and req.remove_affiliations:
                        fac["affiliations"] = [
                            a for a in fac.get("affiliations", [])
                            if a not in req.remove_affiliations
                        ]
                    faculty_updated = True
                    break

            if faculty_updated:
                tmp_path = FACULTY_FILE + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(faculty_list, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, FACULTY_FILE)
        except Exception as e:
            logger.error(f"Failed to update faculty.json for {req.faculty_id}: {e}")

    return {
        "ok": True,
        "faculty_id": req.faculty_id,
        "action": req.action,
        "primary_department": req.primary_department,
        "faculty_json_updated": faculty_updated,
    }


@app.post("/api/admin/conflicts/item/bulk-resolve")
async def admin_bulk_resolve_item_conflicts(
    _: Dict[str, Any] = Depends(require_admin),
):
    """
    Bulk-resolve all pending item conflicts using their current_department
    as the resolution. Items with an empty current_department are skipped.
    """
    data = _load_conflicts()

    resolved_count = 0
    skipped_count = 0
    db_updates = []

    for item in data.get("item_conflicts", []):
        if item["status"] != "pending":
            continue
        dept = item.get("current_department", "").strip()
        if not dept:
            skipped_count += 1
            continue
        item["status"] = "resolved"
        item["resolution"] = dept
        db_updates.append((dept, item["item_uuid"]))
        resolved_count += 1

    _save_conflicts(data)

    # Bulk update dspace_index.db
    db_updated = 0
    if db_updates and os.path.exists(DSPACE_INDEX_DB):
        try:
            import sqlite3
            conn = sqlite3.connect(DSPACE_INDEX_DB)
            conn.executemany(
                "UPDATE items SET department = ? WHERE uuid = ?",
                db_updates,
            )
            conn.commit()
            conn.close()
            db_updated = len(db_updates)
        except Exception as e:
            logger.error(f"Failed to bulk-update dspace_index.db: {e}")

    return {
        "ok": True,
        "resolved": resolved_count,
        "skipped_no_department": skipped_count,
        "db_rows_updated": db_updated,
    }


# ----------------------------------------------------------
# Knowledge Graph endpoints
# ----------------------------------------------------------

@app.get("/api/kg/stats")
async def kg_stats():
    return get_kg_service().stats()


@app.get("/api/kg/entity/{entity_id:path}")
async def kg_entity(entity_id: str):
    ent = get_kg_service().get_entity(entity_id)
    if not ent:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}")
    return ent


@app.get("/api/kg/search")
async def kg_search(
    q: str = Query(..., min_length=1, max_length=120),
    types: Optional[str] = None,  # comma-separated, e.g. "paper,author,faculty"
    limit: int = Query(default=20, ge=1, le=100),
):
    type_list = [t.strip() for t in (types or "").split(",") if t.strip()] or None
    results = get_kg_service().search(q, types=type_list, limit=limit)
    return {"q": q, "types": type_list, "results": results}


@app.get("/api/kg/graph")
async def kg_graph(
    root_id: str = Query(..., min_length=3),
    depth: int = Query(default=2, ge=1, le=3),
    max_nodes: int = Query(default=200, ge=10, le=500),
):
    return get_kg_service().graph_around(root_id, depth=depth, max_nodes=max_nodes)


@app.get("/api/kg/author/{author_id:path}/papers")
async def kg_author_papers(author_id: str, limit: int = Query(default=50, ge=1, le=200)):
    return {
        "author_id": author_id,
        "papers": get_kg_service().papers_by_author(author_id, limit=limit),
    }


@app.get("/api/kg/paper/{paper_id:path}/authors")
async def kg_paper_authors(paper_id: str):
    return {
        "paper_id": paper_id,
        "authors": get_kg_service().authors_of_paper(paper_id),
    }


# ----------------------------------------------------------
# OpenAlex on-demand cache endpoints (Phase 5)
# ----------------------------------------------------------

@app.get("/api/kg/openalex/work/{work_id}")
async def kg_openalex_work(work_id: str):
    """Lazy-fetch a single OpenAlex work, cached for 7 days."""
    work = get_openalex_cache_service().get_work(work_id)
    if not work:
        raise HTTPException(status_code=404, detail=f"OpenAlex work not found: {work_id}")
    return work


@app.get("/api/kg/openalex/author/{author_id}")
async def kg_openalex_author(author_id: str):
    a = get_openalex_cache_service().get_author(author_id)
    if not a:
        raise HTTPException(status_code=404, detail=f"OpenAlex author not found: {author_id}")
    return a


@app.get("/api/kg/openalex/author/{author_id}/works")
async def kg_openalex_author_works(
    author_id: str, limit: int = Query(default=25, ge=1, le=100)
):
    return {
        "author_id": author_id,
        "works": get_openalex_cache_service().works_by_author(author_id, limit=limit),
    }


@app.get("/api/kg/openalex/work/{work_id}/cited_by")
async def kg_openalex_cited_by(
    work_id: str, limit: int = Query(default=25, ge=1, le=100)
):
    return {
        "work_id": work_id,
        "works": get_openalex_cache_service().cited_by_of(work_id, limit=limit),
    }


@app.get("/api/kg/openalex/work/{work_id}/cites")
async def kg_openalex_cites(work_id: str):
    return {
        "work_id": work_id,
        "cites": get_openalex_cache_service().cites_of(work_id),
    }


@app.get("/api/kg/openalex/cache/stats")
async def kg_openalex_cache_stats():
    return get_openalex_cache_service().stats()


# ----------------------------------------------------------
# Paper reconciliation endpoints (Phase 3)
# ----------------------------------------------------------

class PaperOverrideRequest(BaseModel):
    action: str = Field(..., description="'edit_field' | 'add' | 'delete' | 'claim_authorship'")
    field: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    rationale: Optional[str] = None


@app.get("/api/papers/stats")
async def papers_stats():
    return get_paper_reconcile_service().stats()


@app.get("/api/papers/{canonical_id:path}")
async def get_paper(canonical_id: str):
    paper = get_paper_reconcile_service().get_paper(canonical_id)
    if not paper:
        raise HTTPException(status_code=404, detail=f"paper not found: {canonical_id}")
    return paper


@app.post("/api/papers/{canonical_id:path}/edit")
async def edit_paper(
    canonical_id: str,
    req: PaperOverrideRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """
    Submit an edit override for a paper. Logged-in users can edit any paper
    they're listed as an author on (TODO: enforce). Admins can edit anything.
    Returns the new override id.
    """
    svc = get_paper_reconcile_service()
    if not svc.get_paper(canonical_id):
        raise HTTPException(status_code=404, detail="paper not found")
    if req.action not in ("edit_field", "add", "delete", "claim_authorship"):
        raise HTTPException(status_code=400, detail=f"invalid action: {req.action}")
    if req.action == "edit_field" and not req.field:
        raise HTTPException(status_code=400, detail="edit_field requires a field name")
    override_id = svc.add_override(
        canonical_id=canonical_id,
        user_id=int(user["id"]),
        action=req.action,
        field=req.field,
        payload=req.payload,
        rationale=req.rationale,
    )
    return {"override_id": override_id, "ok": True}


@app.delete("/api/papers/override/{override_id}")
async def delete_paper_override(
    override_id: int,
    user: Dict[str, Any] = Depends(require_admin),
):
    """Admin-only soft-delete of an override row."""
    ok = get_paper_reconcile_service().soft_delete_override(override_id)
    if not ok:
        raise HTTPException(status_code=404, detail="override not found or already deleted")
    return {"ok": True}


@app.get("/api/suggest")
async def suggest(
    q: str = Query(..., min_length=1, max_length=80),
    limit: int = Query(default=6, ge=1, le=15),
):
    """
    Lightweight typeahead for the main search box.

    Returns four buckets:
      - faculty   : in-memory prefix match against FACULTY_DATA
      - papers    : SQLite FTS5 prefix match against item titles
      - authors   : SQLite distinct author names containing the prefix
      - departments: distinct department names containing the prefix

    Designed to come back in <50ms total. Anonymous (no auth required).
    """
    q_clean = (q or "").strip()
    if len(q_clean) < 2:
        return {"q": q_clean, "faculty": [], "papers": [], "authors": [], "departments": []}

    q_lower = q_clean.lower()

    # 1. Faculty: cheap in-memory prefix scan over the loaded FACULTY_DATA
    faculty_hits = []
    seen_ids = set()
    for f in FACULTY_DATA:
        name = (f.get("name") or "").lower()
        # Match by full name OR last name OR any name token starting with prefix
        if (
            name.startswith(q_lower)
            or any(tok.startswith(q_lower) for tok in name.split())
            or q_lower in name
        ):
            fid = f.get("id")
            if fid in seen_ids:
                continue
            seen_ids.add(fid)
            faculty_hits.append({
                "id": fid,
                "name": f.get("name"),
                "department": f.get("department"),
                "rank": f.get("rank") or f.get("title"),
                "photo_url": f.get("photo_url"),
            })
            if len(faculty_hits) >= limit:
                break

    # 2. Papers: title-prefix FTS5 against the local DSpace index
    papers_hits = []
    try:
        papers_hits = get_dspace_local_service().suggest_titles(q_clean, limit=limit)
    except Exception as e:
        logger.debug(f"suggest titles err: {e}")

    # 3. Authors: distinct author names containing the prefix
    authors_hits = []
    try:
        authors_hits = get_dspace_local_service().suggest_authors(q_clean, limit=limit)
    except Exception as e:
        logger.debug(f"suggest authors err: {e}")

    # 4. Departments: dedup over FACULTY_DATA, then prefix-filter
    dept_hits = []
    seen_depts = set()
    for f in FACULTY_DATA:
        d = f.get("department") or ""
        if not d or d in seen_depts:
            continue
        if q_lower in d.lower():
            seen_depts.add(d)
            dept_hits.append({"name": d, "college": f.get("college")})
            if len(dept_hits) >= limit:
                break

    return {
        "q": q_clean,
        "faculty": faculty_hits,
        "papers": papers_hits,
        "authors": authors_hits,
        "departments": dept_hits,
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

@app.get("/api/faculty/semantic-match")
async def semantic_match_faculty(q: str = Query(..., min_length=1, max_length=500), top_k: int = Query(default=8, ge=1, le=20)):
    """Find faculty semantically related to a query using embeddings."""
    results = embedding_service.search(q, top_k=top_k, threshold=0.25)
    return {
        "query": q,
        "matches": [
            {**faculty, "_similarity": score}
            for faculty, score in results
        ],
        "total": len(results),
        "method": "semantic" if results else "none"
    }

@app.get("/api/faculty/{faculty_id}")
async def get_faculty(faculty_id: str):
    for f in FACULTY_DATA:
        if f["id"] == faculty_id:
            return f
    raise HTTPException(status_code=404, detail="Faculty not found")


@app.get("/api/faculty/{faculty_id}/publications")
async def get_faculty_publications(
    faculty_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    include_openalex: bool = Query(default=True),
):
    """
    Merged publication list for a faculty member.

    Sources:
      - DSpace local index (matches by author name)
      - OpenAlex (if the faculty has an openalex_id from faculty_openalex_match.json)

    Records are deduped by normalized title (case-insensitive, whitespace-stripped),
    with DSpace winning if a paper appears in both. Each result has a `canonical_id`
    that opens the PaperDetailModal in the frontend.
    """
    # 1. Look up the faculty record
    faculty = None
    for f in FACULTY_DATA:
        if f["id"] == faculty_id:
            faculty = f
            break
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty not found")

    name = faculty.get("name") or ""

    # 2. DSpace publications (by author-name match)
    dspace_papers: List[Dict[str, Any]] = []
    try:
        dspace_papers = get_dspace_local_service().papers_by_author(name, limit=limit)
    except Exception as e:
        logger.warning(f"papers_by_author DSpace error: {e}")

    # 3. OpenAlex publications (if matched)
    openalex_papers: List[Dict[str, Any]] = []
    openalex_id: Optional[str] = None
    if include_openalex:
        try:
            kg = get_kg_service()
            match = (kg.openalex_matches or {}).get(faculty_id)
            if match and match.get("openalex_id"):
                openalex_id = match["openalex_id"]
                works = get_openalex_cache_service().works_by_author(openalex_id, limit=limit)
                openalex_papers = works or []
        except Exception as e:
            logger.warning(f"openalex works_by_author error: {e}")

    # 4. Merge + dedupe by normalized title
    # Lower-case, replace any non-alphanumeric run with a single space, collapse.
    # This catches OpenAlex's U+2010 HYPHEN vs DSpace's ASCII '-' and similar gotchas.
    import re as _re
    _NORM_PUNCT = _re.compile(r"[^a-z0-9]+")
    def _norm_title(t: str) -> str:
        return _NORM_PUNCT.sub(" ", (t or "").lower()).strip()

    merged: Dict[str, Dict[str, Any]] = {}

    # DSpace first — preferred when there's a tie because we have a canonical_id
    for p in dspace_papers:
        title = p.get("title") or ""
        key = _norm_title(title)
        if not key:
            continue
        merged[key] = {
            "title": title,
            "year": str(p.get("year") or "")[:4],
            "type": p.get("type") or "",
            "authors": p.get("authors") or [],
            "abstract": p.get("abstract") or "",
            "url": p.get("url"),
            "doi": None,
            "cited_by_count": None,
            "source": "dspace",
            "canonical_id": f"paper:dspace:{p['uuid']}" if p.get("uuid") else None,
            "uuid": p.get("uuid"),
        }

    for w in openalex_papers:
        title = w.get("title") or ""
        key = _norm_title(title)
        if not key:
            continue
        existing = merged.get(key)
        if existing:
            # Enrich the DSpace record with OpenAlex citation info if not set
            if existing.get("cited_by_count") is None and w.get("cited_by_count") is not None:
                existing["cited_by_count"] = w.get("cited_by_count")
            if not existing.get("doi") and w.get("doi"):
                existing["doi"] = w.get("doi")
            if not existing.get("openalex_id") and w.get("id"):
                existing["openalex_id"] = w.get("id")
            existing["source"] = "both"
            continue
        merged[key] = {
            "title": title,
            "year": str(w.get("publication_year") or ""),
            "type": w.get("type") or "",
            "authors": [a.get("name") for a in (w.get("authors") or []) if a.get("name")],
            "abstract": "",
            "url": None,
            "doi": w.get("doi"),
            "cited_by_count": w.get("cited_by_count"),
            "source": "openalex",
            "canonical_id": f"paper:openalex:{w['id']}" if w.get("id") else None,
            "openalex_id": w.get("id"),
        }

    # 5. Sort by year desc (unknown years go last), then by title
    def _year_key(rec: Dict[str, Any]) -> Tuple[int, str]:
        y = rec.get("year") or ""
        try:
            return (-(int(y[:4])) if y[:4].isdigit() else 1, rec.get("title", ""))
        except Exception:
            return (1, rec.get("title", ""))

    publications = sorted(merged.values(), key=_year_key)
    return {
        "faculty_id": faculty_id,
        "faculty_name": name,
        "openalex_id": openalex_id,
        "counts": {
            "total":   len(publications),
            "dspace":  sum(1 for p in publications if p["source"] in ("dspace", "both")),
            "openalex": sum(1 for p in publications if p["source"] in ("openalex", "both")),
            "merged":  sum(1 for p in publications if p["source"] == "both"),
        },
        "publications": publications,
    }


@app.get("/api/courses")
async def list_courses(level: Optional[str] = None, topic: Optional[str] = None):
    results = COURSES
    if level:
        results = [c for c in results if c.get("level", "").lower() == level.lower()]
    if topic:
        results = [c for c in results if any(topic.lower() in t.lower() for t in c.get("topics", []))]
    return {"courses": results, "total": len(results)}

@app.get("/api/courses/search")
async def search_courses(q: str = Query(..., min_length=1), limit: int = Query(default=20, ge=1, le=100)):
    """
    Free-text search across course number, name, topic, level, and instructor name.
    Each match contributes to a score; results sorted desc.
    """
    terms = [t.strip().lower() for t in q.split() if t.strip()]
    if not terms:
        return {"query": q, "courses": [], "total": 0}

    def _norm_course(s: str) -> str:
        return (s or "").replace(" ", "").lower()

    scored = []
    for c in COURSES:
        score = 0
        number = c["number"].lower()
        number_compact = _norm_course(c["number"])
        name = c["name"].lower()
        topics_text = " ".join(c.get("topics", [])).lower()
        level = (c.get("level") or "").lower()
        instructors = [
            f for f in FACULTY_DATA
            if any(_norm_course(ct) == number_compact for ct in f.get("courses_taught", []))
        ]
        instructor_text = " ".join(f.get("name", "") for f in instructors).lower()

        for t in terms:
            if t in number_compact or t in number:
                score += 5
            if t in name:
                score += 3
            if t in topics_text:
                score += 4
            if t in level:
                score += 1
            if t in instructor_text:
                score += 3

        if score > 0:
            scored.append({
                **c,
                "instructors": [
                    {"id": f.get("id"), "name": f.get("name"), "department": f.get("department")}
                    for f in instructors
                ],
                "score": score,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return {"query": q, "courses": scored[:limit], "total": len(scored)}


@app.get("/api/courses/{course_number}")
async def get_course(course_number: str):
    target = course_number.replace(" ", "").lower()
    for c in COURSES:
        if c["number"].replace(" ", "").lower() == target:
            instructors = [
                f for f in FACULTY_DATA
                if any(ct.replace(" ", "").lower() == target for ct in f.get("courses_taught", []))
            ]
            return {**c, "instructors": instructors}
    raise HTTPException(status_code=404, detail="Course not found")

@app.get("/api/stats")
async def get_stats():
    qdrant_count = 0
    try:
        if qdrant_rag_service.initialized and qdrant_rag_service._client is not None:
            info = qdrant_rag_service._client.get_collection("dspace_chunks")
            qdrant_count = info.points_count or 0
    except Exception:
        pass
    return {
        "indexed_documents": qdrant_count,  # Qdrant chunk count
        "faculty_count": len(FACULTY_DATA),
        "teaching_faculty": len([f for f in FACULTY_DATA if f.get("is_teaching_faculty")]),
        "research_faculty": len([f for f in FACULTY_DATA if not f.get("is_teaching_faculty")]),
        "courses_count": len(COURSES),
        "gemini_enabled": GENAI_AVAILABLE and genai_client is not None,
        "rag_ready": qdrant_rag_service.initialized,
    }

@app.get("/api/topics")
async def list_topics():
    if not topic_service.initialized:
        topic_service.build()
    return {"topics": topic_service.list_topics()}


@app.get("/api/topics/stats")
async def topic_stats():
    if not topic_service.initialized:
        topic_service.build()
    return topic_service.stats()


@app.get("/api/topics/{topic_id}")
async def get_topic(topic_id: int):
    if not topic_service.initialized:
        topic_service.build()
    return topic_service.topic_documents(topic_id)


@app.get("/api/collaboration/stats")
async def collaboration_stats():
    if not collaboration_service.initialized:
        collaboration_service.build()
    return collaboration_service.stats()


@app.get("/api/collaboration/graph")
async def collaboration_graph(
    researcher: Optional[str] = None,
    max_nodes: int = Query(default=75, ge=1, le=500),
    min_weight: int = Query(default=1, ge=1),
):
    if not collaboration_service.initialized:
        collaboration_service.build()
    return collaboration_service.graph(
        researcher=researcher, max_nodes=max_nodes, min_weight=min_weight
    )


@app.get("/api/collaboration/coauthors")
async def collaboration_coauthors(researcher: str, top_k: int = Query(default=20, ge=1, le=100)):
    if not collaboration_service.initialized:
        collaboration_service.build()
    return collaboration_service.coauthors_of(researcher, top_k=top_k)


@app.get("/api/collaboration/students")
async def collaboration_students(advisor: str):
    if not collaboration_service.initialized:
        collaboration_service.build()
    return collaboration_service.students_of(advisor)


@app.get("/api/collaboration/advisors")
async def collaboration_advisors(student: str):
    if not collaboration_service.initialized:
        collaboration_service.build()
    return collaboration_service.advisors_of(student)


@app.get("/api/groups")
async def get_groups():
    groups = {}
    for f in FACULTY_DATA:
        g = f.get("group", "Other")
        if g not in groups:
            groups[g] = 0
        groups[g] += 1
    return {"groups": [{"name": k, "count": v} for k, v in sorted(groups.items())]}

def _get_priority_faculty(faculty_data: List[Dict]) -> List[Dict]:
    """
    Return verified CS faculty for embedding (free-tier Gemini quota friendly).
    The verified set (~42 faculty) covers the primary CS research demo. Other
    faculty fall back to keyword matching until the index is expanded.
    """
    try:
        from verified_faculty_data import VERIFIED_FACULTY_DATA
        verified_ids = {f["id"] for f in VERIFIED_FACULTY_DATA}
    except Exception:
        verified_ids = set()

    selected = [f for f in faculty_data if f["id"] in verified_ids]
    if not selected:
        # Fallback: take all CS dept faculty if no verified list available
        selected = [
            f for f in faculty_data
            if "computer science" in (f.get("department") or "").lower()
        ]
    return selected


@app.on_event("startup")
async def startup():
    logger.info("=" * 60)
    logger.info("ISU Research Search API v5.0 - Semantic Search")
    logger.info(f"Gemini: {'OK' if GEMINI_API_KEY else 'X'}")
    logger.info(f"Faculty: {len(FACULTY_DATA)} | Courses: {len(COURSES)}")
    logger.info("=" * 60)
    # Initialize auth service (creates SQLite + bootstraps admin row)
    try:
        get_auth_service()
    except Exception as e:
        logger.error(f"Auth service init failed: {e}")
    # Choose embedding scope based on backend:
    # - Ollama: no quota, embed all faculty
    # - Vertex: ~1500 RPM quota — fine for ~3400 faculty (~2-3 min one-time)
    # - Legacy Gemini Developer API: tight free-tier quota — restrict to verified CS
    if embedding_service.backend in ("ollama", "vertex"):
        embed_set = FACULTY_DATA
        logger.info(f"Embedding scope: all {len(FACULTY_DATA)} faculty ({embedding_service.backend} backend)")
    else:
        embed_set = _get_priority_faculty(FACULTY_DATA)
        logger.info(f"Embedding scope: {len(embed_set)} priority faculty (legacy Gemini free tier)")
    # Build in a background thread so the server starts serving immediately.
    import threading
    def _build():
        try:
            embedding_service.build_index(embed_set)
            logger.info(f"Semantic index ready: {len(embedding_service.faculty_embeddings)} faculty embedded")
        except Exception as e:
            logger.error(f"Embedding index build failed: {e}")
    threading.Thread(target=_build, daemon=True).start()

    # Build collaboration graph (cheap — under 1s for 163 docs)
    try:
        collaboration_service.build()
    except Exception as e:
        logger.error(f"Collaboration graph build failed: {e}")

    # Build topic clusters in background (re-uses cached doc embeddings if present)
    def _build_topics():
        try:
            topic_service.build()
        except Exception as e:
            logger.error(f"Topic cluster build failed: {e}")
    threading.Thread(target=_build_topics, daemon=True).start()

    # Configure Qdrant RAG service (Vertex Gemini + Qdrant retrieval)
    try:
        qdrant_rag_service.configure(gen_client=genai_client)
    except Exception as e:
        logger.error(f"QdrantRAGService configure failed: {e}")
