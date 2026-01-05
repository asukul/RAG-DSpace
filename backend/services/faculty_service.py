"""
Faculty Service for ISU CS Department.

Contains data for all 44 faculty members with search functionality.
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class FacultyMember:
    """Faculty member data model."""
    id: str
    name: str
    email: str
    rank: str
    title: Optional[str] = None
    photo_url: Optional[str] = None
    profile_url: str = ""
    research_areas: List[str] = field(default_factory=list)
    research_interests: List[str] = field(default_factory=list)
    
    def dict(self) -> Dict[str, Any]:
        return asdict(self)


# Research area constants
AREAS = {
    "AI_ML": "AI, ML, and Data Science",
    "BIOINFO": "Bioinformatics and Computational Biology",
    "HCI": "Human Computer Interaction",
    "ROBOTICS": "Robotics and Autonomous Systems",
    "SE_PL": "Software Engineering and Programming Languages",
    "SYSTEMS": "Systems and Networking",
    "THEORY": "Theoretical Foundations"
}


# Complete faculty database
FACULTY_DATABASE: List[FacultyMember] = [
    # ==================== PROFESSORS ====================
    FacultyMember(
        id="pavan-aduri",
        name="Pavan Aduri",
        email="pavan@iastate.edu",
        rank="Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/aduri_pavan.jpg",
        profile_url="https://www.cs.iastate.edu/people/pavan-aduri",
        research_areas=[AREAS["THEORY"]],
        research_interests=["Computational Complexity", "Algorithm Design", "Machine Learning Theory"]
    ),
    FacultyMember(
        id="samik-basu",
        name="Samik Basu",
        email="sbasu@iastate.edu",
        rank="Professor",
        title="Director of Graduate Education",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/basu_samik.jpg",
        profile_url="https://www.cs.iastate.edu/people/samik-basu",
        research_areas=[AREAS["SE_PL"], AREAS["THEORY"]],
        research_interests=["Formal Methods", "Software Verification", "Model Checking"]
    ),
    FacultyMember(
        id="myra-cohen",
        name="Myra Cohen",
        email="mcohen@iastate.edu",
        rank="Professor",
        title="Associate Chair for Research, Nguyen Endowed Chair",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/myra_cohen_0.jpg",
        profile_url="https://www.cs.iastate.edu/people/myra-cohen",
        research_areas=[AREAS["SE_PL"], AREAS["AI_ML"]],
        research_interests=["Software Testing", "Combinatorial Testing", "Search-Based SE"]
    ),
    FacultyMember(
        id="oliver-eulenstein",
        name="Oliver Eulenstein",
        email="oeulenst@iastate.edu",
        rank="Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/eulenstein_oliver.jpg",
        profile_url="https://www.cs.iastate.edu/people/oliver-eulenstein",
        research_areas=[AREAS["BIOINFO"], AREAS["THEORY"]],
        research_interests=["Phylogenetics", "Computational Biology", "Algorithms"]
    ),
    FacultyMember(
        id="xiaoqiu-huang",
        name="Xiaoqiu Huang",
        email="xqhuang@iastate.edu",
        rank="Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/Dr.-Huang.jpg",
        profile_url="https://www.cs.iastate.edu/people/xiaoqiu-huang",
        research_areas=[AREAS["BIOINFO"]],
        research_interests=["Sequence Alignment", "Genome Assembly", "Bioinformatics"]
    ),
    FacultyMember(
        id="yan-bin-jia",
        name="Yan-Bin Jia",
        email="jia@iastate.edu",
        rank="Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-12/jia2025.jpg",
        profile_url="https://www.cs.iastate.edu/people/yan-bin-jia",
        research_areas=[AREAS["ROBOTICS"]],
        research_interests=["Robotics", "Motion Planning", "Manipulation", "Haptics"]
    ),
    FacultyMember(
        id="robyn-lutz",
        name="Robyn Lutz",
        email="rlutz@iastate.edu",
        rank="Distinguished Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lutz_robbyn.jpg",
        profile_url="https://www.cs.iastate.edu/people/robyn-lutz",
        research_areas=[AREAS["SE_PL"]],
        research_interests=["Software Safety", "Requirements Engineering", "NASA Software"]
    ),
    FacultyMember(
        id="jack-lutz",
        name="Jack Lutz",
        email="lutz@iastate.edu",
        rank="Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lutz_jack.jpg",
        profile_url="https://www.cs.iastate.edu/people/jack-lutz",
        research_areas=[AREAS["THEORY"]],
        research_interests=["Computational Complexity", "Algorithmic Information Theory"]
    ),
    FacultyMember(
        id="sam-xin",
        name="Sam Xin",
        email="cxin@iastate.edu",
        rank="Professor",
        title="Department Chair, IEEE Fellow",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-08/thumbnail_Xin_photo_HR.jpg",
        profile_url="https://www.cs.iastate.edu/people/sam-xin",
        research_areas=[AREAS["SYSTEMS"], AREAS["AI_ML"]],
        research_interests=["Cybersecurity", "Machine Learning", "Network Security"]
    ),
    FacultyMember(
        id="wallapak-tavanapong",
        name="Wallapak Tavanapong",
        email="tavanapo@iastate.edu",
        rank="Professor",
        title="Kingland Systems Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/tavanapong_wallapak.jpg",
        profile_url="https://www.cs.iastate.edu/people/wallapak-tavanapong",
        research_areas=[AREAS["AI_ML"], AREAS["SYSTEMS"]],
        research_interests=["Medical AI", "Deep Learning", "Computer Vision", "Colonoscopy Analysis"]
    ),
    
    # ==================== ASSOCIATE PROFESSORS ====================
    FacultyMember(
        id="ying-cai",
        name="Ying Cai",
        email="yingcai@iastate.edu",
        rank="Associate Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/cai.jpg",
        profile_url="https://www.cs.iastate.edu/people/ying-cai",
        research_areas=[AREAS["SYSTEMS"]],
        research_interests=["Wireless Networks", "Mobile Computing", "Database Systems"]
    ),
    FacultyMember(
        id="soma-chaudhuri",
        name="Soma Chaudhuri",
        email="chaudhur@iastate.edu",
        rank="Associate Professor",
        title="Associate Chair for Education",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/chaudhuri_4.png",
        profile_url="https://www.cs.iastate.edu/people/soma-chaudhuri",
        research_areas=[AREAS["THEORY"]],
        research_interests=["Distributed Computing", "Fault Tolerance", "Algorithms"]
    ),
    FacultyMember(
        id="ali-jannesari",
        name="Ali Jannesari",
        email="jannesar@iastate.edu",
        rank="Associate Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/ali_janessari1.jpg",
        profile_url="https://www.cs.iastate.edu/people/ali-jannesari",
        research_areas=[AREAS["SYSTEMS"], AREAS["AI_ML"]],
        research_interests=["High Performance Computing", "ML Systems", "Parallelization"]
    ),
    FacultyMember(
        id="james-lathrop",
        name="James Lathrop",
        email="jil@iastate.edu",
        rank="Associate Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lathrop_jim.jpg",
        profile_url="https://www.cs.iastate.edu/people/james-lathrop",
        research_areas=[AREAS["THEORY"], AREAS["BIOINFO"]],
        research_interests=["Molecular Computing", "DNA Computing", "Self-Assembly"]
    ),
    FacultyMember(
        id="wei-le",
        name="Wei Le",
        email="weile@iastate.edu",
        rank="Associate Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-07/Capture%20One%20Catalog1631%202.jpg",
        profile_url="https://www.cs.iastate.edu/people/wei-le",
        research_areas=[AREAS["SE_PL"], AREAS["AI_ML"]],
        research_interests=["Program Analysis", "Software Testing", "ML for Code"]
    ),
    FacultyMember(
        id="qi-li",
        name="Qi Li",
        email="qli@iastate.edu",
        rank="Associate Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-06/Qi%20Li%202023.jpg",
        profile_url="https://www.cs.iastate.edu/people/qi-li",
        research_areas=[AREAS["SYSTEMS"], AREAS["AI_ML"]],
        research_interests=["Cybersecurity", "ML Security", "Privacy", "NLP Security"]
    ),
    FacultyMember(
        id="andrew-miner",
        name="Andrew Miner",
        email="asminer@iastate.edu",
        rank="Associate Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/Miner.png",
        profile_url="https://www.cs.iastate.edu/people/andrew-miner",
        research_areas=[AREAS["THEORY"], AREAS["SE_PL"]],
        research_interests=["Model Checking", "Petri Nets", "Formal Verification"]
    ),
    FacultyMember(
        id="gurpur-prabhu",
        name="Gurpur Prabhu",
        email="prabhu@iastate.edu",
        rank="Associate Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/prabhu_gurpur.jpg",
        profile_url="https://www.cs.iastate.edu/people/gurpur-prabhu",
        research_areas=[AREAS["THEORY"]],
        research_interests=["Computational Complexity", "Graph Theory"]
    ),
    FacultyMember(
        id="nok-wongpiromsarn",
        name="Tichakorn (Nok) Wongpiromsarn",
        email="nok@iastate.edu",
        rank="Associate Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/nok.jpeg",
        profile_url="https://www.cs.iastate.edu/people/tichakorn-nok-wongpiromsarn",
        research_areas=[AREAS["ROBOTICS"], AREAS["SE_PL"]],
        research_interests=["Formal Methods", "Autonomous Systems", "Motion Planning"]
    ),
    FacultyMember(
        id="wensheng-zhang",
        name="Wensheng Zhang",
        email="wzhang@iastate.edu",
        rank="Associate Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/zhang_wensheng.jpg",
        profile_url="https://www.cs.iastate.edu/people/wensheng-zhang",
        research_areas=[AREAS["SYSTEMS"], AREAS["AI_ML"]],
        research_interests=["Network Security", "Wireless Networks", "Video Analysis"]
    ),
    
    # ==================== ASSISTANT PROFESSORS ====================
    FacultyMember(
        id="hongyang-gao",
        name="Hongyang Gao",
        email="hygao@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/img_1814_0.jpg",
        profile_url="https://www.cs.iastate.edu/people/hongyang-gao",
        research_areas=[AREAS["AI_ML"]],
        research_interests=["Deep Learning", "Graph Neural Networks", "Neural ODEs"]
    ),
    FacultyMember(
        id="mengdi-huai",
        name="Mengdi Huai",
        email="mdhuai@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/mengdi_img.jpg",
        profile_url="https://www.cs.iastate.edu/people/mengdi-huai",
        research_areas=[AREAS["AI_ML"]],
        research_interests=["Trustworthy AI", "Fairness in ML", "Privacy-Preserving ML"]
    ),
    FacultyMember(
        id="regis-kopper",
        name="Regis Kopper",
        email="kopper@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-09/cs_faculty_23.jpg",
        profile_url="https://www.cs.iastate.edu/people/regis-kopper",
        research_areas=[AREAS["HCI"]],
        research_interests=["Virtual Reality", "Augmented Reality", "3D Interaction"]
    ),
    FacultyMember(
        id="yang-li",
        name="Yang Li",
        email="yangli1@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-06/bio_yang_li.jpg",
        profile_url="https://www.cs.iastate.edu/people/yang-li",
        research_areas=[AREAS["AI_ML"]],
        research_interests=["Machine Learning", "Optimization", "Deep Learning"]
    ),
    FacultyMember(
        id="liyi-li",
        name="Liyi Li",
        email="liyili2@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/liyi.jpg",
        profile_url="https://www.cs.iastate.edu/people/liyi-li",
        research_areas=[AREAS["SE_PL"]],
        research_interests=["Programming Languages", "Type Systems", "Formal Verification"]
    ),
    FacultyMember(
        id="chenglin-miao",
        name="Chenglin Miao",
        email="cmiao@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/cmiao.jpg",
        profile_url="https://www.cs.iastate.edu/people/chenglin-miao",
        research_areas=[AREAS["AI_ML"], AREAS["SYSTEMS"]],
        research_interests=["Mobile Computing", "IoT", "Smart Health"]
    ),
    FacultyMember(
        id="meisam-mohammady",
        name="Meisam Mohammady",
        email="meisam@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/dsc_0057_01.jpg",
        profile_url="https://www.cs.iastate.edu/people/meisam-mohammady",
        research_areas=[AREAS["SYSTEMS"]],
        research_interests=["Privacy", "Differential Privacy", "Data Protection"]
    ),
    FacultyMember(
        id="christopher-quinn",
        name="Christopher Quinn",
        email="cjquinn@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/chris_quinn.jpg",
        profile_url="https://www.cs.iastate.edu/people/christopher-quinn",
        research_areas=[AREAS["AI_ML"], AREAS["THEORY"]],
        research_interests=["Information Theory", "Causal Inference", "Bandits"]
    ),
    FacultyMember(
        id="amit-sikder",
        name="Amit Kumar Sikder",
        email="aksikder@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/amit_-_headshot.png",
        profile_url="https://www.cs.iastate.edu/people/amit-kumar-sikder",
        research_areas=[AREAS["SYSTEMS"]],
        research_interests=["IoT Security", "Smart Home Security", "CPS Security"]
    ),
    FacultyMember(
        id="clay-stevens",
        name="Clay Stevens",
        email="cdsteven@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/clay_stevens_scholar_0.jpg",
        profile_url="https://www.cs.iastate.edu/people/clay-stevens",
        research_areas=[AREAS["THEORY"]],
        research_interests=["Algorithmic Randomness", "Computability Theory"]
    ),
    FacultyMember(
        id="bowen-weng",
        name="Bowen Weng",
        email="bweng@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/bowenw_0.jpeg",
        profile_url="https://www.cs.iastate.edu/people/bowen-weng",
        research_areas=[AREAS["ROBOTICS"], AREAS["AI_ML"]],
        research_interests=["Reinforcement Learning", "Autonomous Vehicles", "Control"]
    ),
    FacultyMember(
        id="lin-yan",
        name="Lin Yan",
        email="linyan@iastate.edu",
        rank="Assistant Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lin.jpg",
        profile_url="https://www.cs.iastate.edu/people/lin-yan",
        research_areas=[AREAS["AI_ML"]],
        research_interests=["Data Visualization", "Visual Analytics", "Scientific Visualization"]
    ),
    
    # ==================== TEACHING FACULTY ====================
    FacultyMember(
        id="georgi-batinov",
        name="Georgi Batinov",
        email="batinov@iastate.edu",
        rank="Assistant Teaching Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/uncropped.jpg",
        profile_url="https://www.cs.iastate.edu/people/georgi-batinov",
        research_areas=[AREAS["HCI"]],
        research_interests=["CS Education", "HCI", "Software Engineering"]
    ),
    FacultyMember(
        id="susan-chang",
        name="Shu-Hui (Susan) Chang",
        email="shchang@iastate.edu",
        rank="Teaching Professor",
        title="Director of Distance Education",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/dr_chang_new_2.png",
        profile_url="https://www.cs.iastate.edu/people/shu-hui-susan-chang",
        research_areas=[],
        research_interests=["CS Education", "Distance Learning"]
    ),
    FacultyMember(
        id="matthew-holman",
        name="Matthew Holman",
        email="mjholman@iastate.edu",
        rank="Assistant Teaching Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/profilepicture2.jpg",
        profile_url="https://www.cs.iastate.edu/people/matthew-holman",
        research_areas=[],
        research_interests=["CS Education", "Programming"]
    ),
    FacultyMember(
        id="ashwin-joshy",
        name="Ashwin Kallingal Joshy",
        email="ashwinkj@iastate.edu",
        rank="Assistant Teaching Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-09/cs_faculty_18.jpg",
        profile_url="https://www.cs.iastate.edu/people/ashwin-kallingal-joshy",
        research_areas=[],
        research_interests=["CS Education", "Software Development"]
    ),
    FacultyMember(
        id="ambrose-laing",
        name="Ambrose Kofi Laing",
        email="alaing@iastate.edu",
        rank="Associate Teaching Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/laingportrait2a.jpg",
        profile_url="https://www.cs.iastate.edu/people/ambrose-kofi-laing",
        research_areas=[],
        research_interests=["CS Education"]
    ),
    FacultyMember(
        id="simanta-mitra",
        name="Simanta Mitra",
        email="smitra@iastate.edu",
        rank="Teaching Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/dsc_0069.jpg",
        profile_url="https://www.cs.iastate.edu/people/simanta-mitra",
        research_areas=[],
        research_interests=["CS Education", "Software Engineering"]
    ),
    FacultyMember(
        id="sarfaraz-mohammed",
        name="Sarfaraz Ahmed Mohammed",
        email="sarfaraz@iastate.edu",
        rank="Assistant Teaching Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-07/SarfarazAhmedMohammed.jpg",
        profile_url="https://www.cs.iastate.edu/people/sarfaraz-ahmed-mohammed",
        research_areas=[],
        research_interests=["CS Education"]
    ),
    FacultyMember(
        id="trent-muhr",
        name="Trent Muhr",
        email="muhr@iastate.edu",
        rank="Lecturer",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/screenshot_2024-08-15_at_4.10.02_pm.jpg",
        profile_url="https://www.cs.iastate.edu/people/trent-muhr",
        research_areas=[],
        research_interests=["CS Education"]
    ),
    FacultyMember(
        id="jeremy-sheaffer",
        name="Jeremy Sheaffer",
        email="sheaffer@iastate.edu",
        rank="Assistant Teaching Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/sheaffer_jeremy.jpg",
        profile_url="https://www.cs.iastate.edu/people/jeremy-sheaffer",
        research_areas=[],
        research_interests=["CS Education", "Programming"]
    ),
    FacultyMember(
        id="adisak-sukul",
        name="Adisak Sukul",
        email="adisak@iastate.edu",
        rank="Teaching Professor",
        title="Google Cloud Faculty Expert",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/sukul_adisak.jpg",
        profile_url="https://www.cs.iastate.edu/people/adisak-sukul",
        research_areas=[AREAS["AI_ML"]],
        research_interests=["Data Science", "Machine Learning", "Cloud Computing", "Applied AI"]
    ),
    FacultyMember(
        id="matthew-tancreti",
        name="Matthew Tancreti",
        email="tancreti@iastate.edu",
        rank="Associate Teaching Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/my_project_1.png",
        profile_url="https://www.cs.iastate.edu/people/matthew-tancreti",
        research_areas=[AREAS["SYSTEMS"]],
        research_interests=["Embedded Systems", "Operating Systems"]
    ),
    FacultyMember(
        id="wenting-xu",
        name="Wenting Xu",
        email="wentinxu@iastate.edu",
        rank="Assistant Teaching Professor",
        photo_url="https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/thumbnail_img_1943.jpg",
        profile_url="https://www.cs.iastate.edu/people/wenting-xu",
        research_areas=[],
        research_interests=["CS Education"]
    ),
]


class FacultyService:
    """Service for faculty data operations."""
    
    def __init__(self):
        self._faculty_map = {f.id: f for f in FACULTY_DATABASE}
        logger.info(f"Faculty service initialized with {len(FACULTY_DATABASE)} members")
    
    def get_all(self) -> List[FacultyMember]:
        """Get all faculty members."""
        return FACULTY_DATABASE
    
    def get_by_id(self, faculty_id: str) -> Optional[FacultyMember]:
        """Get faculty by ID (slug)."""
        return self._faculty_map.get(faculty_id)
    
    def search(self, query: str) -> List[FacultyMember]:
        """Search faculty by name or interests."""
        query_lower = query.lower()
        results = []
        
        for faculty in FACULTY_DATABASE:
            score = 0
            
            if query_lower in faculty.name.lower():
                score += 10
            
            for interest in faculty.research_interests:
                if query_lower in interest.lower():
                    score += 5
            
            for area in faculty.research_areas:
                if query_lower in area.lower():
                    score += 3
            
            if score > 0:
                results.append((score, faculty))
        
        results.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in results]
    
    def find_by_research_area(self, area: str) -> List[FacultyMember]:
        """Find faculty by research area or keyword."""
        area_lower = area.lower()
        results = []
        
        for faculty in FACULTY_DATABASE:
            for research_area in faculty.research_areas:
                if area_lower in research_area.lower():
                    results.append(faculty)
                    break
            else:
                for interest in faculty.research_interests:
                    if area_lower in interest.lower():
                        results.append(faculty)
                        break
        
        return results
    
    def get_research_areas(self) -> List[str]:
        """Get list of unique research areas."""
        areas = set()
        for faculty in FACULTY_DATABASE:
            areas.update(faculty.research_areas)
        return sorted(list(areas))


# Create singleton instance
faculty_service = FacultyService()
