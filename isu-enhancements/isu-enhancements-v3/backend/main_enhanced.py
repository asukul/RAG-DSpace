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

# ==========================================================
# Data Models
# ==========================================================

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=50)

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

FACULTY_DATA = [
    # Professors
    {"id": "pavan-aduri", "name": "Pavan Aduri", "email": "pavan@iastate.edu", "rank": "Professor", "title": None, "group": "Theory", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/aduri_pavan.jpg", "profile_url": "https://www.cs.iastate.edu/people/pavan-aduri", "research_areas": ["Theoretical Foundations"], "research_interests": ["Computational Complexity", "Algorithm Design"], "courses_taught": ["COM S 311", "COM S 531"], "is_teaching_faculty": False},
    {"id": "samik-basu", "name": "Samik Basu", "email": "sbasu@iastate.edu", "rank": "Professor", "title": "Director of Graduate Education", "group": "Software Engineering", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/basu_samik.jpg", "profile_url": "https://www.cs.iastate.edu/people/samik-basu", "research_areas": ["Software Engineering", "Theory"], "research_interests": ["Formal Methods", "Software Verification"], "courses_taught": ["COM S 512", "COM S 342"], "is_teaching_faculty": False},
    {"id": "myra-cohen", "name": "Myra Cohen", "email": "mcohen@iastate.edu", "rank": "Professor", "title": "Nguyen Chair", "group": "Software Engineering", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/myra_cohen_0.jpg", "profile_url": "https://www.cs.iastate.edu/people/myra-cohen", "research_areas": ["Software Engineering", "AI and Machine Learning"], "research_interests": ["Software Testing", "Combinatorial Testing", "Search-Based SE"], "courses_taught": ["COM S 417", "COM S 512"], "is_teaching_faculty": False},
    {"id": "oliver-eulenstein", "name": "Oliver Eulenstein", "email": "oeulenst@iastate.edu", "rank": "Professor", "title": None, "group": "Bioinformatics", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/eulenstein_oliver.jpg", "profile_url": "https://www.cs.iastate.edu/people/oliver-eulenstein", "research_areas": ["Bioinformatics", "Theory"], "research_interests": ["Phylogenetics", "Computational Biology"], "courses_taught": ["COM S 435", "COM S 311"], "is_teaching_faculty": False},
    {"id": "xiaoqiu-huang", "name": "Xiaoqiu Huang", "email": "xqhuang@iastate.edu", "rank": "Professor", "title": None, "group": "Bioinformatics", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/Dr.-Huang.jpg", "profile_url": "https://www.cs.iastate.edu/people/xiaoqiu-huang", "research_areas": ["Bioinformatics"], "research_interests": ["Sequence Alignment", "Genome Assembly"], "courses_taught": ["COM S 435"], "is_teaching_faculty": False},
    {"id": "yan-bin-jia", "name": "Yan-Bin Jia", "email": "jia@iastate.edu", "rank": "Professor", "title": None, "group": "Robotics", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-12/jia2025.jpg", "profile_url": "https://www.cs.iastate.edu/people/yan-bin-jia", "research_areas": ["Robotics"], "research_interests": ["Robotics", "Motion Planning", "Manipulation"], "courses_taught": [], "is_teaching_faculty": False},
    {"id": "robyn-lutz", "name": "Robyn Lutz", "email": "rlutz@iastate.edu", "rank": "Distinguished Professor", "title": None, "group": "Software Engineering", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lutz_robbyn.jpg", "profile_url": "https://www.cs.iastate.edu/people/robyn-lutz", "research_areas": ["Software Engineering"], "research_interests": ["Software Safety", "Requirements Engineering"], "courses_taught": ["COM S 409", "COM S 512"], "is_teaching_faculty": False},
    {"id": "jack-lutz", "name": "Jack Lutz", "email": "lutz@iastate.edu", "rank": "Professor", "title": None, "group": "Theory", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lutz_jack.jpg", "profile_url": "https://www.cs.iastate.edu/people/jack-lutz", "research_areas": ["Theory"], "research_interests": ["Computational Complexity", "Algorithmic Information Theory"], "courses_taught": ["COM S 331", "COM S 531"], "is_teaching_faculty": False},
    {"id": "sam-xin", "name": "Chunsheng (Sam) Xin", "email": "cxin@iastate.edu", "rank": "Professor", "title": "Department Chair", "group": "Systems and Networking", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-08/thumbnail_Xin_photo_HR.jpg", "profile_url": "https://www.cs.iastate.edu/people/sam-xin", "research_areas": ["Systems and Networking", "AI and Machine Learning"], "research_interests": ["Cybersecurity", "Machine Learning", "Network Security"], "courses_taught": [], "is_teaching_faculty": False},
    {"id": "wallapak-tavanapong", "name": "Wallapak Tavanapong", "email": "tavanapo@iastate.edu", "rank": "Professor", "title": "Kingland Professor", "group": "AI and Machine Learning", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/tavanapong_wallapak.jpg", "profile_url": "https://www.cs.iastate.edu/people/wallapak-tavanapong", "research_areas": ["AI and Machine Learning", "Systems and Networking"], "research_interests": ["Medical AI", "Deep Learning", "Computer Vision"], "courses_taught": ["COM S 363", "COM S 461", "COM S 577"], "is_teaching_faculty": False},
    
    # Associate Professors
    {"id": "ying-cai", "name": "Ying Cai", "email": "yingcai@iastate.edu", "rank": "Associate Professor", "title": None, "group": "Systems and Networking", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/cai.jpg", "profile_url": "https://www.cs.iastate.edu/people/ying-cai", "research_areas": ["Systems and Networking"], "research_interests": ["Wireless Networks", "Mobile Computing"], "courses_taught": ["COM S 486", "COM S 487"], "is_teaching_faculty": False},
    {"id": "soma-chaudhuri", "name": "Soma Chaudhuri", "email": "chaudhur@iastate.edu", "rank": "Associate Professor", "title": "Associate Chair", "group": "Theory", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/chaudhuri_4.png", "profile_url": "https://www.cs.iastate.edu/people/soma-chaudhuri", "research_areas": ["Theory"], "research_interests": ["Distributed Computing", "Fault Tolerance"], "courses_taught": ["COM S 311", "COM S 511"], "is_teaching_faculty": False},
    {"id": "ali-jannesari", "name": "Ali Jannesari", "email": "jannesar@iastate.edu", "rank": "Associate Professor", "title": None, "group": "Systems and Networking", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/ali_janessari1.jpg", "profile_url": "https://www.cs.iastate.edu/people/ali-jannesari", "research_areas": ["Systems and Networking", "AI and Machine Learning"], "research_interests": ["High Performance Computing", "ML Systems"], "courses_taught": ["COM S 425", "COM S 583"], "is_teaching_faculty": False},
    {"id": "james-lathrop", "name": "James Lathrop", "email": "jil@iastate.edu", "rank": "Associate Professor", "title": None, "group": "Theory", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lathrop_jim.jpg", "profile_url": "https://www.cs.iastate.edu/people/james-lathrop", "research_areas": ["Theory", "Bioinformatics"], "research_interests": ["Molecular Computing", "DNA Computing"], "courses_taught": ["COM S 331"], "is_teaching_faculty": False},
    {"id": "wei-le", "name": "Wei Le", "email": "weile@iastate.edu", "rank": "Associate Professor", "title": None, "group": "Software Engineering", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-07/Capture%20One%20Catalog1631%202.jpg", "profile_url": "https://www.cs.iastate.edu/people/wei-le", "research_areas": ["Software Engineering", "AI and Machine Learning"], "research_interests": ["Program Analysis", "Software Testing", "ML for Code"], "courses_taught": ["COM S 342", "COM S 440"], "is_teaching_faculty": False},
    {"id": "qi-li", "name": "Qi Li", "email": "qli@iastate.edu", "rank": "Associate Professor", "title": None, "group": "Security", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-06/Qi%20Li%202023.jpg", "profile_url": "https://www.cs.iastate.edu/people/qi-li", "research_areas": ["Systems and Networking", "AI and Machine Learning"], "research_interests": ["Cybersecurity", "ML Security", "NLP Security"], "courses_taught": ["COM S 481", "COM S 577"], "is_teaching_faculty": False},
    {"id": "andrew-miner", "name": "Andrew Miner", "email": "asminer@iastate.edu", "rank": "Associate Professor", "title": None, "group": "Software Engineering", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/Miner.png", "profile_url": "https://www.cs.iastate.edu/people/andrew-miner", "research_areas": ["Theory", "Software Engineering"], "research_interests": ["Model Checking", "Petri Nets"], "courses_taught": ["COM S 512"], "is_teaching_faculty": False},
    {"id": "nok-wongpiromsarn", "name": "Tichakorn (Nok) Wongpiromsarn", "email": "nok@iastate.edu", "rank": "Associate Professor", "title": None, "group": "Robotics", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/nok.jpeg", "profile_url": "https://www.cs.iastate.edu/people/tichakorn-nok-wongpiromsarn", "research_areas": ["Robotics", "Software Engineering"], "research_interests": ["Formal Methods", "Autonomous Systems"], "courses_taught": ["COM S 512"], "is_teaching_faculty": False},
    {"id": "wensheng-zhang", "name": "Wensheng Zhang", "email": "wzhang@iastate.edu", "rank": "Associate Professor", "title": None, "group": "Systems and Networking", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/zhang_wensheng.jpg", "profile_url": "https://www.cs.iastate.edu/people/wensheng-zhang", "research_areas": ["Systems and Networking", "AI and Machine Learning"], "research_interests": ["Network Security", "Video Analysis"], "courses_taught": ["COM S 486"], "is_teaching_faculty": False},
    
    # Assistant Professors
    {"id": "hongyang-gao", "name": "Hongyang Gao", "email": "hygao@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "AI and Machine Learning", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/img_1814_0.jpg", "profile_url": "https://www.cs.iastate.edu/people/hongyang-gao", "research_areas": ["AI and Machine Learning"], "research_interests": ["Deep Learning", "Graph Neural Networks"], "courses_taught": ["COM S 474", "COM S 573", "COM S 579"], "is_teaching_faculty": False},
    {"id": "mengdi-huai", "name": "Mengdi Huai", "email": "mdhuai@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "AI and Machine Learning", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/mengdi_img.jpg", "profile_url": "https://www.cs.iastate.edu/people/mengdi-huai", "research_areas": ["AI and Machine Learning"], "research_interests": ["Trustworthy AI", "Fairness in ML"], "courses_taught": ["COM S 472", "COM S 573"], "is_teaching_faculty": False},
    {"id": "regis-kopper", "name": "Regis Kopper", "email": "kopper@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "Human-Computer Interaction", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-09/cs_faculty_23.jpg", "profile_url": "https://www.cs.iastate.edu/people/regis-kopper", "research_areas": ["Human-Computer Interaction"], "research_interests": ["Virtual Reality", "Augmented Reality"], "courses_taught": ["COM S 336"], "is_teaching_faculty": False},
    {"id": "yang-li", "name": "Yang Li", "email": "yangli1@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "AI and Machine Learning", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-06/bio_yang_li.jpg", "profile_url": "https://www.cs.iastate.edu/people/yang-li", "research_areas": ["AI and Machine Learning"], "research_interests": ["Machine Learning", "Optimization"], "courses_taught": ["COM S 474"], "is_teaching_faculty": False},
    {"id": "liyi-li", "name": "Liyi Li", "email": "liyili2@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "Software Engineering", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/liyi.jpg", "profile_url": "https://www.cs.iastate.edu/people/liyi-li", "research_areas": ["Software Engineering"], "research_interests": ["Programming Languages", "Type Systems"], "courses_taught": ["COM S 342"], "is_teaching_faculty": False},
    {"id": "chenglin-miao", "name": "Chenglin Miao", "email": "cmiao@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "AI and Machine Learning", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/cmiao.jpg", "profile_url": "https://www.cs.iastate.edu/people/chenglin-miao", "research_areas": ["AI and Machine Learning", "Systems and Networking"], "research_interests": ["Mobile Computing", "IoT", "Smart Health"], "courses_taught": [], "is_teaching_faculty": False},
    {"id": "meisam-mohammady", "name": "Meisam Mohammady", "email": "meisam@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "Security", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/dsc_0057_01.jpg", "profile_url": "https://www.cs.iastate.edu/people/meisam-mohammady", "research_areas": ["Systems and Networking"], "research_interests": ["Privacy", "Differential Privacy"], "courses_taught": ["COM S 481"], "is_teaching_faculty": False},
    {"id": "christopher-quinn", "name": "Christopher Quinn", "email": "cjquinn@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "AI and Machine Learning", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/chris_quinn.jpg", "profile_url": "https://www.cs.iastate.edu/people/christopher-quinn", "research_areas": ["AI and Machine Learning", "Theory"], "research_interests": ["Information Theory", "Causal Inference"], "courses_taught": [], "is_teaching_faculty": False},
    {"id": "amit-sikder", "name": "Amit Kumar Sikder", "email": "aksikder@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "Security", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/amit_-_headshot.png", "profile_url": "https://www.cs.iastate.edu/people/amit-kumar-sikder", "research_areas": ["Systems and Networking"], "research_interests": ["IoT Security", "Smart Home Security"], "courses_taught": ["COM S 481"], "is_teaching_faculty": False},
    {"id": "clay-stevens", "name": "Clay Stevens", "email": "cdsteven@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "Theory", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/clay_stevens_scholar_0.jpg", "profile_url": "https://www.cs.iastate.edu/people/clay-stevens", "research_areas": ["Theory"], "research_interests": ["Algorithmic Randomness", "Computability Theory"], "courses_taught": ["COM S 331", "COM S 531"], "is_teaching_faculty": False},
    {"id": "bowen-weng", "name": "Bowen Weng", "email": "bweng@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "Robotics", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/bowenw_0.jpeg", "profile_url": "https://www.cs.iastate.edu/people/bowen-weng", "research_areas": ["Robotics", "AI and Machine Learning"], "research_interests": ["Reinforcement Learning", "Autonomous Vehicles"], "courses_taught": ["COM S 472", "COM S 572"], "is_teaching_faculty": False},
    {"id": "lin-yan", "name": "Lin Yan", "email": "linyan@iastate.edu", "rank": "Assistant Professor", "title": None, "group": "AI and Machine Learning", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lin.jpg", "profile_url": "https://www.cs.iastate.edu/people/lin-yan", "research_areas": ["AI and Machine Learning"], "research_interests": ["Data Visualization", "Visual Analytics"], "courses_taught": ["COM S 336"], "is_teaching_faculty": False},
    
    # Teaching Faculty
    {"id": "georgi-batinov", "name": "Georgi Batinov", "email": "batinov@iastate.edu", "rank": "Assistant Teaching Professor", "title": None, "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/uncropped.jpg", "profile_url": "https://www.cs.iastate.edu/people/georgi-batinov", "research_areas": ["Human-Computer Interaction"], "research_interests": ["CS Education", "HCI"], "courses_taught": ["COM S 319", "COM S 336"], "is_teaching_faculty": True},
    {"id": "susan-chang", "name": "Shu-Hui (Susan) Chang", "email": "shchang@iastate.edu", "rank": "Teaching Professor", "title": "Director of Distance Education", "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/dr_chang_new_2.png", "profile_url": "https://www.cs.iastate.edu/people/shu-hui-susan-chang", "research_areas": [], "research_interests": ["CS Education", "Distance Learning"], "courses_taught": ["COM S 227", "COM S 228", "COM S 252"], "is_teaching_faculty": True},
    {"id": "matthew-holman", "name": "Matthew Holman", "email": "mjholman@iastate.edu", "rank": "Assistant Teaching Professor", "title": None, "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/profilepicture2.jpg", "profile_url": "https://www.cs.iastate.edu/people/matthew-holman", "research_areas": [], "research_interests": ["CS Education"], "courses_taught": ["COM S 127", "COM S 227"], "is_teaching_faculty": True},
    {"id": "ashwin-joshy", "name": "Ashwin Kallingal Joshy", "email": "ashwinkj@iastate.edu", "rank": "Assistant Teaching Professor", "title": None, "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-09/cs_faculty_18.jpg", "profile_url": "https://www.cs.iastate.edu/people/ashwin-kallingal-joshy", "research_areas": [], "research_interests": ["CS Education"], "courses_taught": ["COM S 227", "COM S 228"], "is_teaching_faculty": True},
    {"id": "ambrose-laing", "name": "Ambrose Kofi Laing", "email": "alaing@iastate.edu", "rank": "Associate Teaching Professor", "title": None, "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/laingportrait2a.jpg", "profile_url": "https://www.cs.iastate.edu/people/ambrose-kofi-laing", "research_areas": [], "research_interests": ["CS Education"], "courses_taught": ["COM S 227", "COM S 230"], "is_teaching_faculty": True},
    {"id": "simanta-mitra", "name": "Simanta Mitra", "email": "smitra@iastate.edu", "rank": "Teaching Professor", "title": None, "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/dsc_0069.jpg", "profile_url": "https://www.cs.iastate.edu/people/simanta-mitra", "research_areas": [], "research_interests": ["CS Education", "Software Engineering"], "courses_taught": ["COM S 309", "COM S 319", "COM S 362", "COM S 402"], "is_teaching_faculty": True},
    {"id": "sarfaraz-mohammed", "name": "Sarfaraz Ahmed Mohammed", "email": "sarfaraz@iastate.edu", "rank": "Assistant Teaching Professor", "title": None, "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-07/SarfarazAhmedMohammed.jpg", "profile_url": "https://www.cs.iastate.edu/people/sarfaraz-ahmed-mohammed", "research_areas": [], "research_interests": ["CS Education", "Database Systems"], "courses_taught": ["COM S 363"], "is_teaching_faculty": True},
    {"id": "trent-muhr", "name": "Trent Muhr", "email": "muhr@iastate.edu", "rank": "Lecturer", "title": None, "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/screenshot_2024-08-15_at_4.10.02_pm.jpg", "profile_url": "https://www.cs.iastate.edu/people/trent-muhr", "research_areas": [], "research_interests": ["CS Education"], "courses_taught": ["COM S 127"], "is_teaching_faculty": True},
    {"id": "jeremy-sheaffer", "name": "Jeremy Sheaffer", "email": "sheaffer@iastate.edu", "rank": "Assistant Teaching Professor", "title": None, "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/sheaffer_jeremy.jpg", "profile_url": "https://www.cs.iastate.edu/people/jeremy-sheaffer", "research_areas": [], "research_interests": ["CS Education", "Systems"], "courses_taught": ["COM S 127", "COM S 227", "COM S 327"], "is_teaching_faculty": True},
    {"id": "adisak-sukul", "name": "Adisak Sukul", "email": "adisak@iastate.edu", "rank": "Teaching Professor", "title": "Google Cloud Expert", "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/sukul_adisak.jpg", "profile_url": "https://www.cs.iastate.edu/people/adisak-sukul", "research_areas": ["AI and Machine Learning"], "research_interests": ["Data Science", "Machine Learning", "Cloud Computing", "Deep Learning"], "courses_taught": ["COM S 227", "COM S 228", "COM S 309", "COM S 319", "COM S 363", "COM S 474", "COM S 579"], "is_teaching_faculty": True},
    {"id": "matthew-tancreti", "name": "Matthew Tancreti", "email": "tancreti@iastate.edu", "rank": "Associate Teaching Professor", "title": None, "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/my_project_1.png", "profile_url": "https://www.cs.iastate.edu/people/matthew-tancreti", "research_areas": ["Systems and Networking"], "research_interests": ["Embedded Systems", "Operating Systems"], "courses_taught": ["COM S 321", "COM S 352"], "is_teaching_faculty": True},
    {"id": "wenting-xu", "name": "Wenting Xu", "email": "wentinxu@iastate.edu", "rank": "Assistant Teaching Professor", "title": None, "group": "Teaching", "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/thumbnail_img_1943.jpg", "profile_url": "https://www.cs.iastate.edu/people/wenting-xu", "research_areas": [], "research_interests": ["CS Education"], "courses_taught": ["COM S 227", "COM S 228"], "is_teaching_faculty": True},
]

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

rag_service = GeminiRAGService()

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
    rag_result, sources = await asyncio.gather(rag_task, dspace_task)
    
    # Find related faculty
    q = request.query.lower()
    related = [f for f in FACULTY_DATA if any(q in i.lower() for i in f.get("research_interests", []))][:3]
    
    return {
        "query": request.query,
        "answer": rag_result.get("answer", ""),
        "sources": sources,
        "files_searched": rag_result.get("files_searched", 0),
        "search_mode": rag_result.get("mode", "unknown"),
        "related_faculty": related,
        "suggested_queries": [f"Latest {request.query} research", f"{request.query} applications", f"{request.query} at ISU"],
        "total_results": len(sources)
    }

@app.get("/api/faculty")
async def list_faculty(search: Optional[str] = None, group: Optional[str] = None, teaching_only: bool = False, research_only: bool = False):
    results = FACULTY_DATA
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
