"""
ISU Computer Science Faculty - VERIFIED Teaching Assignments
Source: Official ISU CS Course Pages (cs.iastate.edu/courses) - Spring 2025

This data was verified by checking each course page on the ISU CS website.
"""

# Verified Course Instructors from ISU CS Website (as of Spring 2025)
VERIFIED_COURSE_INSTRUCTORS = {
    # Introductory Courses
    "COMS 1130": ["Adisak Sukul", "Ambrose Laing", "Wenting Xu"],  # Intro to Spreadsheets/Databases
    "COMS 1270": ["Matthew Holman"],  # Intro to Programming
    
    # Sophomore Core
    "COMS 2270": ["Ambrose Laing", "Matthew Tancreti", "Matthew Holman"],  # OOP (Java)
    "COMS 2280": ["Ashwin Kallingal Joshy", "Georgi Batinov", "Trent Muhr"],  # Data Structures
    "COMS 2300": ["Soma Chaudhuri", "Ashwin Kallingal Joshy"],  # Discrete Structures
    
    # Junior Core
    "COMS 3090": ["Abraham Aldaco", "Simanta Mitra"],  # Software Development Practices
    "COMS 3110": ["Tichakorn Wongpiromsarn", "Trent Muhr"],  # Algorithms
    "COMS 3210": ["Jeremy Sheaffer"],  # Computer Architecture
    "COMS 3260": ["Georgi Batinov"],  # C for Programmers
    "COMS 3270": ["Trent Muhr", "Jeremy Sheaffer"],  # Advanced Programming (C/C++)
    "COMS 3310": ["Gianfranco Ciardo"],  # Theory of Computing
    "COMS 3360": ["Jeremy Sheaffer"],  # Computer Graphics
    "COMS 3420": ["Liyi Li"],  # Programming Languages
    "COMS 3520": ["Wensheng Zhang"],  # Operating Systems
    "COMS 3620": ["Georgi Batinov"],  # OO Analysis and Design
    "COMS 3630": ["Ying Cai", "Georgi Batinov"],  # Database Management Systems
    
    # Senior Electives
    "COMS 4020": ["Simanta Mitra"],  # Senior Project
    "COMS 4170": ["Myra Cohen"],  # Software Testing
    "COMS 4720": ["Bowen Weng"],  # Artificial Intelligence (Yan-Bin Jia coordinator)
    "COMS 4740": ["Hongyang Gao", "Regis Kopper"],  # Intro to Machine Learning
    "COMS 4770": ["Yan-Bin Jia"],  # Foundations of Robotics and Computer Vision
    
    # Graduate Courses
    "COMS 5110": [],  # Design and Analysis of Algorithms (Graduate)
    "COMS 5720": [],  # Principles of AI (Graduate)
    "COMS 5730": ["Mengdi Huai"],  # Machine Learning (Graduate)
}


# Complete Faculty Database with VERIFIED courses_taught
VERIFIED_FACULTY_DATA = [
    # ============================================================
    # PROFESSORS
    # ============================================================
    {
        "id": "pavan-aduri",
        "name": "Pavan Aduri",
        "email": "pavan@iastate.edu",
        "rank": "Professor",
        "title": None,
        "group": "Theory",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/aduri_pavan.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/pavan-aduri",
        "research_areas": ["Theoretical Foundations"],
        "research_interests": ["Computational Complexity", "Algorithm Design", "Randomness in Computation"],
        "courses_taught": [],  # Research-focused, primarily graduate advising
        "is_teaching_faculty": False
    },
    {
        "id": "samik-basu",
        "name": "Samik Basu",
        "email": "sbasu@iastate.edu",
        "rank": "Professor",
        "title": "Director of Graduate Education",
        "group": "Software Engineering",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/basu_samik.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/samik-basu",
        "research_areas": ["Software Engineering", "Theory"],
        "research_interests": ["Formal Methods", "Software Verification", "Model Checking"],
        "courses_taught": [],  # Research-focused
        "is_teaching_faculty": False
    },
    {
        "id": "myra-cohen",
        "name": "Myra Cohen",
        "email": "mcohen@iastate.edu",
        "rank": "Professor",
        "title": "Nguyen Chair",
        "group": "Software Engineering",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/myra_cohen_0.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/myra-cohen",
        "research_areas": ["Software Engineering", "AI and Machine Learning"],
        "research_interests": ["Software Testing", "Combinatorial Testing", "Search-Based SE"],
        "courses_taught": ["COMS 4170"],  # Software Testing - VERIFIED
        "is_teaching_faculty": False
    },
    {
        "id": "oliver-eulenstein",
        "name": "Oliver Eulenstein",
        "email": "oeulenst@iastate.edu",
        "rank": "Professor",
        "title": None,
        "group": "Bioinformatics",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/eulenstein_oliver.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/oliver-eulenstein",
        "research_areas": ["Bioinformatics", "Theory"],
        "research_interests": ["Phylogenetics", "Computational Biology", "Algorithm Design"],
        "courses_taught": [],  # Has taught COMS 3110 historically
        "is_teaching_faculty": False
    },
    {
        "id": "xiaoqiu-huang",
        "name": "Xiaoqiu Huang",
        "email": "xqhuang@iastate.edu",
        "rank": "Professor",
        "title": None,
        "group": "Bioinformatics",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/Dr.-Huang.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/xiaoqiu-huang",
        "research_areas": ["Bioinformatics"],
        "research_interests": ["Sequence Alignment", "Genome Assembly", "Protein Structure"],
        "courses_taught": [],  # Research-focused
        "is_teaching_faculty": False
    },
    {
        "id": "yan-bin-jia",
        "name": "Yan-Bin Jia",
        "email": "jia@iastate.edu",
        "rank": "Professor",
        "title": None,
        "group": "Robotics",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-12/jia2025.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/yan-bin-jia",
        "research_areas": ["Robotics"],
        "research_interests": ["Robotics", "Motion Planning", "Manipulation", "Haptics"],
        "courses_taught": ["COMS 4770"],  # Foundations of Robotics - VERIFIED
        "is_teaching_faculty": False
    },
    {
        "id": "robyn-lutz",
        "name": "Robyn Lutz",
        "email": "rlutz@iastate.edu",
        "rank": "Distinguished Professor",
        "title": None,
        "group": "Software Engineering",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lutz_robbyn.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/robyn-lutz",
        "research_areas": ["Software Engineering"],
        "research_interests": ["Software Safety", "Requirements Engineering", "Fault Trees"],
        "courses_taught": [],  # Research-focused
        "is_teaching_faculty": False
    },
    {
        "id": "jack-lutz",
        "name": "Jack Lutz",
        "email": "lutz@iastate.edu",
        "rank": "Professor",
        "title": None,
        "group": "Theory",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lutz_jack.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/jack-lutz",
        "research_areas": ["Theory"],
        "research_interests": ["Computational Complexity", "Algorithmic Information Theory", "Dimension"],
        "courses_taught": [],  # Research-focused
        "is_teaching_faculty": False
    },
    {
        "id": "sam-xin",
        "name": "Chunsheng (Sam) Xin",
        "email": "cxin@iastate.edu",
        "rank": "Professor",
        "title": "Department Chair, IEEE Fellow",
        "group": "Systems and Networking",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-08/thumbnail_Xin_photo_HR.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/sam-xin",
        "research_areas": ["Systems and Networking", "AI and Machine Learning"],
        "research_interests": ["Cybersecurity", "Machine Learning", "Network Security"],
        "courses_taught": [],  # Administrative/Research focus
        "is_teaching_faculty": False
    },
    {
        "id": "wallapak-tavanapong",
        "name": "Wallapak Tavanapong",
        "email": "tavanapo@iastate.edu",
        "rank": "Professor",
        "title": "Kingland Professor",
        "group": "AI and Machine Learning",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/tavanapong_wallapak.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/wallapak-tavanapong",
        "research_areas": ["AI and Machine Learning", "Systems and Networking"],
        "research_interests": ["Medical AI", "Deep Learning", "Computer Vision", "Colonoscopy Analysis"],
        "courses_taught": [],  # Research-focused, D4 traineeship
        "is_teaching_faculty": False
    },
    
    # ============================================================
    # ASSOCIATE PROFESSORS
    # ============================================================
    {
        "id": "ying-cai",
        "name": "Ying Cai",
        "email": "yingcai@iastate.edu",
        "rank": "Associate Professor",
        "title": None,
        "group": "Systems and Networking",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/cai.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/ying-cai",
        "research_areas": ["Systems and Networking"],
        "research_interests": ["Wireless Networks", "Mobile Computing", "Location Privacy"],
        "courses_taught": ["COMS 3630"],  # Database - VERIFIED
        "is_teaching_faculty": False
    },
    {
        "id": "soma-chaudhuri",
        "name": "Soma Chaudhuri",
        "email": "chaudhur@iastate.edu",
        "rank": "Associate Professor",
        "title": "Associate Chair",
        "group": "Theory",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/chaudhuri_4.png",
        "profile_url": "https://www.cs.iastate.edu/people/soma-chaudhuri",
        "research_areas": ["Theory"],
        "research_interests": ["Distributed Computing", "Fault Tolerance", "Algorithms"],
        "courses_taught": ["COMS 2300"],  # Discrete Structures - VERIFIED
        "is_teaching_faculty": False
    },
    {
        "id": "ali-jannesari",
        "name": "Ali Jannesari",
        "email": "jannesar@iastate.edu",
        "rank": "Associate Professor",
        "title": None,
        "group": "Systems and Networking",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/ali_janessari1.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/ali-jannesari",
        "research_areas": ["Systems and Networking", "AI and Machine Learning"],
        "research_interests": ["High Performance Computing", "ML Systems", "Parallel Computing"],
        "courses_taught": ["COMS 3190"],  # Software Construction - from SWAPP lab page
        "is_teaching_faculty": False
    },
    {
        "id": "james-lathrop",
        "name": "James Lathrop",
        "email": "jil@iastate.edu",
        "rank": "Associate Professor",
        "title": None,
        "group": "Theory",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lathrop_jim.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/james-lathrop",
        "research_areas": ["Theory", "Bioinformatics"],
        "research_interests": ["Molecular Computing", "DNA Computing", "Self-Assembly"],
        "courses_taught": [],  # Research-focused
        "is_teaching_faculty": False
    },
    {
        "id": "wei-le",
        "name": "Wei Le",
        "email": "weile@iastate.edu",
        "rank": "Associate Professor",
        "title": None,
        "group": "Software Engineering",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-07/Capture%20One%20Catalog1631%202.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/wei-le",
        "research_areas": ["Software Engineering", "AI and Machine Learning"],
        "research_interests": ["Program Analysis", "Software Testing", "ML for Code"],
        "courses_taught": [],  # Research-focused
        "is_teaching_faculty": False
    },
    {
        "id": "qi-li",
        "name": "Qi Li",
        "email": "qli@iastate.edu",
        "rank": "Associate Professor",
        "title": None,
        "group": "Security",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-06/Qi%20Li%202023.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/qi-li",
        "research_areas": ["Systems and Networking", "AI and Machine Learning"],
        "research_interests": ["Cybersecurity", "ML Security", "NLP Security"],
        "courses_taught": [],  # Research-focused
        "is_teaching_faculty": False
    },
    {
        "id": "andrew-miner",
        "name": "Andrew Miner",
        "email": "asminer@iastate.edu",
        "rank": "Associate Professor",
        "title": None,
        "group": "Software Engineering",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/Miner.png",
        "profile_url": "https://www.cs.iastate.edu/people/andrew-miner",
        "research_areas": ["Theory", "Software Engineering"],
        "research_interests": ["Model Checking", "Petri Nets", "Decision Diagrams"],
        "courses_taught": [],  # Research-focused
        "is_teaching_faculty": False
    },
    {
        "id": "nok-wongpiromsarn",
        "name": "Tichakorn (Nok) Wongpiromsarn",
        "email": "nok@iastate.edu",
        "rank": "Associate Professor",
        "title": None,
        "group": "Robotics",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/nok.jpeg",
        "profile_url": "https://www.cs.iastate.edu/people/tichakorn-nok-wongpiromsarn",
        "research_areas": ["Robotics", "Software Engineering"],
        "research_interests": ["Formal Methods", "Autonomous Systems", "Motion Planning"],
        "courses_taught": ["COMS 3110"],  # Algorithms - VERIFIED
        "is_teaching_faculty": False
    },
    {
        "id": "wensheng-zhang",
        "name": "Wensheng Zhang",
        "email": "wzhang@iastate.edu",
        "rank": "Associate Professor",
        "title": None,
        "group": "Systems and Networking",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/zhang_wensheng.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/wensheng-zhang",
        "research_areas": ["Systems and Networking", "AI and Machine Learning"],
        "research_interests": ["Network Security", "Video Analysis", "Wireless Security"],
        "courses_taught": ["COMS 3520"],  # Operating Systems - VERIFIED
        "is_teaching_faculty": False
    },
    
    # ============================================================
    # ASSISTANT PROFESSORS
    # ============================================================
    {
        "id": "hongyang-gao",
        "name": "Hongyang Gao",
        "email": "hygao@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "AI and Machine Learning",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/img_1814_0.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/hongyang-gao",
        "research_areas": ["AI and Machine Learning"],
        "research_interests": ["Deep Learning", "Graph Neural Networks", "Neural ODEs"],
        "courses_taught": ["COMS 4740"],  # Intro to ML - VERIFIED
        "is_teaching_faculty": False
    },
    {
        "id": "mengdi-huai",
        "name": "Mengdi Huai",
        "email": "mdhuai@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "AI and Machine Learning",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/mengdi_img.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/mengdi-huai",
        "research_areas": ["AI and Machine Learning"],
        "research_interests": ["Trustworthy AI", "Fairness in ML", "Privacy-Preserving ML"],
        "courses_taught": ["COMS 5730"],  # ML Graduate - VERIFIED
        "is_teaching_faculty": False
    },
    {
        "id": "regis-kopper",
        "name": "Regis Kopper",
        "email": "kopper@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "Human-Computer Interaction",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-09/cs_faculty_23.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/regis-kopper",
        "research_areas": ["Human-Computer Interaction"],
        "research_interests": ["Virtual Reality", "Augmented Reality", "3D Interaction"],
        "courses_taught": ["COMS 4740"],  # Intro to ML - VERIFIED (shares with Gao)
        "is_teaching_faculty": False
    },
    {
        "id": "yang-li",
        "name": "Yang Li",
        "email": "yangli1@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "AI and Machine Learning",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-06/bio_yang_li.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/yang-li",
        "research_areas": ["AI and Machine Learning"],
        "research_interests": ["Machine Learning", "Optimization", "Reinforcement Learning"],
        "courses_taught": [],  # Research-focused
        "is_teaching_faculty": False
    },
    {
        "id": "liyi-li",
        "name": "Liyi Li",
        "email": "liyili2@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "Software Engineering",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/liyi.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/liyi-li",
        "research_areas": ["Software Engineering"],
        "research_interests": ["Programming Languages", "Type Systems", "Formal Methods"],
        "courses_taught": ["COMS 3420"],  # Programming Languages - VERIFIED
        "is_teaching_faculty": False
    },
    {
        "id": "chenglin-miao",
        "name": "Chenglin Miao",
        "email": "cmiao@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "AI and Machine Learning",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/cmiao.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/chenglin-miao",
        "research_areas": ["AI and Machine Learning", "Systems and Networking"],
        "research_interests": ["Mobile Computing", "IoT", "Smart Health"],
        "courses_taught": [],
        "is_teaching_faculty": False
    },
    {
        "id": "meisam-mohammady",
        "name": "Meisam Mohammady",
        "email": "meisam@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "Security",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/dsc_0057_01.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/meisam-mohammady",
        "research_areas": ["Systems and Networking"],
        "research_interests": ["Privacy", "Differential Privacy", "Data Protection"],
        "courses_taught": [],
        "is_teaching_faculty": False
    },
    {
        "id": "christopher-quinn",
        "name": "Christopher Quinn",
        "email": "cjquinn@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "AI and Machine Learning",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/chris_quinn.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/christopher-quinn",
        "research_areas": ["AI and Machine Learning", "Theory"],
        "research_interests": ["Information Theory", "Causal Inference", "Statistical Learning"],
        "courses_taught": [],
        "is_teaching_faculty": False
    },
    {
        "id": "amit-sikder",
        "name": "Amit Kumar Sikder",
        "email": "aksikder@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "Security",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/amit_-_headshot.png",
        "profile_url": "https://www.cs.iastate.edu/people/amit-kumar-sikder",
        "research_areas": ["Systems and Networking"],
        "research_interests": ["IoT Security", "Smart Home Security", "CPS Security"],
        "courses_taught": [],
        "is_teaching_faculty": False
    },
    {
        "id": "clay-stevens",
        "name": "Clay Stevens",
        "email": "cdsteven@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "Theory",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/clay_stevens_scholar_0.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/clay-stevens",
        "research_areas": ["Theory"],
        "research_interests": ["Algorithmic Randomness", "Computability Theory", "Dimension"],
        "courses_taught": [],
        "is_teaching_faculty": False
    },
    {
        "id": "bowen-weng",
        "name": "Bowen Weng",
        "email": "bweng@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "Robotics",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/bowenw_0.jpeg",
        "profile_url": "https://www.cs.iastate.edu/people/bowen-weng",
        "research_areas": ["Robotics", "AI and Machine Learning"],
        "research_interests": ["Reinforcement Learning", "Autonomous Vehicles", "Motion Planning"],
        "courses_taught": ["COMS 4720"],  # Principles of AI - VERIFIED
        "is_teaching_faculty": False
    },
    {
        "id": "lin-yan",
        "name": "Lin Yan",
        "email": "linyan@iastate.edu",
        "rank": "Assistant Professor",
        "title": None,
        "group": "AI and Machine Learning",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lin.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/lin-yan",
        "research_areas": ["AI and Machine Learning"],
        "research_interests": ["Data Visualization", "Visual Analytics", "Topological Data Analysis"],
        "courses_taught": [],
        "is_teaching_faculty": False
    },
    
    # ============================================================
    # TEACHING FACULTY
    # ============================================================
    {
        "id": "georgi-batinov",
        "name": "Georgi Batinov",
        "email": "batinov@iastate.edu",
        "rank": "Assistant Teaching Professor",
        "title": None,
        "group": "Teaching",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/uncropped.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/georgi-batinov",
        "research_areas": ["Human-Computer Interaction"],
        "research_interests": ["CS Education", "HCI", "User Experience"],
        "courses_taught": ["COMS 2280", "COMS 3260", "COMS 3620", "COMS 3630"],  # VERIFIED
        "is_teaching_faculty": True
    },
    {
        "id": "soma-chaudhuri",
        "name": "Soma Chaudhuri",
        "email": "chaudhur@iastate.edu",
        "rank": "Associate Professor",
        "title": "Associate Chair",
        "group": "Theory",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/chaudhuri_4.png",
        "profile_url": "https://www.cs.iastate.edu/people/soma-chaudhuri",
        "research_areas": ["Theory"],
        "research_interests": ["Distributed Computing", "Fault Tolerance"],
        "courses_taught": ["COMS 2300"],  # VERIFIED
        "is_teaching_faculty": False
    },
    {
        "id": "matthew-holman",
        "name": "Matthew Holman",
        "email": "mjholman@iastate.edu",
        "rank": "Assistant Teaching Professor",
        "title": None,
        "group": "Teaching",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/profilepicture2.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/matthew-holman",
        "research_areas": [],
        "research_interests": ["CS Education", "Introductory Programming"],
        "courses_taught": ["COMS 1270", "COMS 2270"],  # VERIFIED
        "is_teaching_faculty": True
    },
    {
        "id": "ashwin-joshy",
        "name": "Ashwin Kallingal Joshy",
        "email": "ashwinkj@iastate.edu",
        "rank": "Assistant Teaching Professor",
        "title": None,
        "group": "Teaching",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-09/cs_faculty_18.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/ashwin-kallingal-joshy",
        "research_areas": [],
        "research_interests": ["CS Education", "Programming"],
        "courses_taught": ["COMS 2280", "COMS 2300"],  # VERIFIED
        "is_teaching_faculty": True
    },
    {
        "id": "ambrose-laing",
        "name": "Ambrose Kofi Laing",
        "email": "alaing@iastate.edu",
        "rank": "Associate Teaching Professor",
        "title": None,
        "group": "Teaching",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/laingportrait2a.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/ambrose-kofi-laing",
        "research_areas": [],
        "research_interests": ["CS Education", "Programming Pedagogy"],
        "courses_taught": ["COMS 1130", "COMS 2270"],  # VERIFIED
        "is_teaching_faculty": True
    },
    {
        "id": "simanta-mitra",
        "name": "Simanta Mitra",
        "email": "smitra@iastate.edu",
        "rank": "Teaching Professor",
        "title": None,
        "group": "Teaching",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/dsc_0069.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/simanta-mitra",
        "research_areas": [],
        "research_interests": ["CS Education", "Software Engineering", "Agile Development"],
        "courses_taught": ["COMS 3090", "COMS 4020"],  # VERIFIED
        "is_teaching_faculty": True
    },
    {
        "id": "trent-muhr",
        "name": "Trent Muhr",
        "email": "muhr@iastate.edu",
        "rank": "Lecturer",
        "title": None,
        "group": "Teaching",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/screenshot_2024-08-15_at_4.10.02_pm.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/trent-muhr",
        "research_areas": [],
        "research_interests": ["CS Education"],
        "courses_taught": ["COMS 2280", "COMS 3110", "COMS 3270"],  # VERIFIED
        "is_teaching_faculty": True
    },
    {
        "id": "jeremy-sheaffer",
        "name": "Jeremy Sheaffer",
        "email": "sheaffer@iastate.edu",
        "rank": "Assistant Teaching Professor",
        "title": None,
        "group": "Teaching",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/sheaffer_jeremy.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/jeremy-sheaffer",
        "research_areas": [],
        "research_interests": ["CS Education", "Systems Programming", "Computer Graphics"],
        "courses_taught": ["COMS 3210", "COMS 3270", "COMS 3360"],  # VERIFIED
        "is_teaching_faculty": True
    },
    {
        "id": "adisak-sukul",
        "name": "Adisak Sukul",
        "email": "adisak@iastate.edu",
        "rank": "Teaching Professor",
        "title": "Google Cloud Faculty Expert",
        "group": "Teaching",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/sukul_adisak.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/adisak-sukul",
        "research_areas": ["AI and Machine Learning"],
        "research_interests": ["Data Science", "Machine Learning", "Cloud Computing", "Deep Learning"],
        "courses_taught": ["COMS 1130", "AI 2010X"],  # VERIFIED - Spreadsheets/DB and Applied AI
        "is_teaching_faculty": True
    },
    {
        "id": "matthew-tancreti",
        "name": "Matthew Tancreti",
        "email": "tancreti@iastate.edu",
        "rank": "Associate Teaching Professor",
        "title": None,
        "group": "Teaching",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/my_project_1.png",
        "profile_url": "https://www.cs.iastate.edu/people/matthew-tancreti",
        "research_areas": ["Systems and Networking"],
        "research_interests": ["Embedded Systems", "Operating Systems", "Systems Programming"],
        "courses_taught": ["COMS 2270"],  # VERIFIED - OOP
        "is_teaching_faculty": True
    },
    {
        "id": "wenting-xu",
        "name": "Wenting Xu",
        "email": "wentinxu@iastate.edu",
        "rank": "Assistant Teaching Professor",
        "title": None,
        "group": "Teaching",
        "photo_url": "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/thumbnail_img_1943.jpg",
        "profile_url": "https://www.cs.iastate.edu/people/wenting-xu",
        "research_areas": [],
        "research_interests": ["CS Education", "Programming"],
        "courses_taught": ["COMS 1130"],  # VERIFIED - Spreadsheets/DB
        "is_teaching_faculty": True
    },
]


if __name__ == "__main__":
    import json
    
    print("Verified Faculty Teaching Assignments (Spring 2025)")
    print("=" * 60)
    
    for faculty in VERIFIED_FACULTY_DATA:
        if faculty["courses_taught"]:
            print(f"{faculty['name']}: {', '.join(faculty['courses_taught'])}")
    
    # Export to JSON
    with open("verified_faculty.json", "w") as f:
        json.dump(VERIFIED_FACULTY_DATA, f, indent=2)
    
    print(f"\nExported {len(VERIFIED_FACULTY_DATA)} faculty members")
