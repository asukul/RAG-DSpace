"""
Build a fresh COURSES list using the current 4-digit ISU CS catalog.
Outputs a Python source snippet ready to paste into main.py.
"""

# Source: scraped from cs.iastate.edu/courses (April 2026)
# Format: (number, title)
RAW = [
    ("COMS 1010", "Orientation"),
    ("COMS 1030", "Computer Literacy and Applications"),
    ("COMS 1040", "Brief Introduction to Computer Programming for Non-Majors"),
    ("COMS 1060", "Introduction to Web Programming"),
    ("COMS 1130", "Introduction to Spreadsheets and Databases"),
    ("COMS 1270", "Introduction to Programming for Problem Solving"),
    ("COMS 2030", "Careers in Computer Science"),
    ("COMS 2070", "Fundamentals of Computer Programming"),
    ("COMS 2270", "Object-Oriented Programming"),
    ("COMS 2280", "Introduction to Data Structures"),
    ("COMS 2300", "Discrete Computational Structures"),
    ("COMS 2520", "Linux Operating System Essentials"),
    ("COMS 3090", "Software Development Practices"),
    ("COMS 3110", "Introduction to the Design and Analysis of Algorithms"),
    ("COMS 3190", "Construction of User Interfaces"),
    ("COMS 3210", "Introduction to Computer Architecture and Machine-Level Programming"),
    ("COMS 3260", "C for Programmers"),
    ("COMS 3270", "Advanced Programming Techniques"),
    ("COMS 3310", "Theory of Computing"),
    ("COMS 3360", "Introduction to Computer Graphics"),
    ("COMS 3420", "Principles of Programming Languages"),
    ("COMS 3520", "Introduction to Operating Systems"),
    ("COMS 3620", "Object-Oriented Analysis and Design"),
    ("COMS 3630", "Introduction to Database Management Systems"),
    ("COMS 4020", "Computer Science Senior Project"),
    ("COMS 4070", "Applied Formal Methods"),
    ("COMS 4090", "Software Requirements Engineering"),
    ("COMS 4100", "Distributed Development of Software"),
    ("COMS 4120", "Formal Methods in Software Engineering"),
    ("COMS 4130", "Foundations and Applications of Program Analysis"),
    ("COMS 4140", "Gerontechnology in Smart Home Environments"),
    ("COMS 4150", "Software System Safety"),
    ("COMS 4170", "Software Testing"),
    ("COMS 4180", "Introduction to Computational Geometry"),
    ("COMS 4190X", "Trustworthy Healthcare Software"),
    ("COMS 4210", "Logic for Mathematics and Computer Science"),
    ("COMS 4240", "Introduction to High Performance Computing"),
    ("COMS 4250", "High Performance Computing for Scientific and Engineering Applications"),
    ("COMS 4300", "Concurrent Programming"),
    ("COMS 4330", "Molecular Programming of Nanoscale Devices and Processes"),
    ("COMS 4340", "Quantum Information and Complexity"),
    ("COMS 4350", "Algorithms for Large Data Sets: Theory and Practice"),
    ("COMS 4370", "Computer Game and Media Programming"),
    ("COMS 4400", "Principles and Practice of Compiling"),
    ("COMS 4410", "Programming Languages"),
    ("COMS 4530", "Privacy Preserving Algorithms and Data Security"),
    ("COMS 4540", "Distributed Systems"),
    ("COMS 4550", "Simulation: Algorithms and Implementation"),
    ("COMS 4590X", "Security and Privacy in Cloud Computing"),
    ("COMS 4610", "Principles and Internals of Database Systems"),
    ("COMS 4720", "Principles of Artificial Intelligence"),
    ("COMS 4740", "Introduction to Machine Learning"),
    ("COMS 4760", "Motion Strategy Algorithms and Applications"),
    ("COMS 4770", "Foundations of Robotics and Computer Vision"),
    ("COMS 4870", "Introduction to Network Programming and Cloud Computing"),
    ("COMS 4880", "Computer Networks"),
    ("COMS 5010X", "Computational Methods I"),
    ("COMS 5040X", "Computational Methods II"),
    ("COMS 5070", "Applied Formal Methods"),
    ("COMS 5090", "Software Requirements Engineering"),
    ("COMS 5100", "Distributed Development of Software"),
    ("COMS 5110", "Design and Analysis of Algorithms"),
    ("COMS 5120", "Formal Methods in Software Engineering"),
    ("COMS 5130", "Foundations and Applications of Program Analysis"),
    ("COMS 5140", "Gerontechnology in Smart Home Environments"),
    ("COMS 5150", "Software System Safety"),
    ("COMS 5180", "Introduction to Computational Geometry"),
    ("COMS 5190X", "Trustworthy Healthcare Software"),
    ("COMS 5270X", "Concurrent Systems"),
    ("COMS 5310", "Theory of Computation"),
    ("COMS 5330", "Computational Models of Nanoscale Self-Assembly"),
    ("COMS 5340", "Quantum Information and Complexity"),
    ("COMS 5350", "Algorithms for Large Data Sets: Theory and Practice"),
    ("COMS 5400", "Principles and Practice of Compiling"),
    ("COMS 5410", "Programming Languages"),
    ("COMS 5510", "Computational Techniques for Genome Assembly and Analysis"),
    ("COMS 5520", "Principles of Operating Systems"),
    ("COMS 5530", "Privacy-Preserving Algorithms and Data Security"),
    ("COMS 5540", "Distributed Systems"),
    ("COMS 5550", "Simulation: Algorithms and Implementation"),
    ("COMS 5590", "Security and Privacy in Cloud Computing"),
    ("COMS 5610", "Database Design, Management, and Research"),
    ("COMS 5670", "Bioinformatics Algorithms"),
    ("COMS 5690", "Structural Bioinformatics"),
    ("COMS 5720", "Principles of Artificial Intelligence"),
    ("COMS 5730", "Machine Learning"),
    ("COMS 5740", "Introduction to Machine Learning"),
    ("COMS 5760", "Motion Planning for Robotics and Autonomous Systems"),
    ("COMS 5770", "Foundations of Robotics and Computer Vision"),
    ("COMS 5780X", "Optimization for Machine Learning"),
    ("COMS 5790", "Natural Language Processing"),
    ("COMS 5860", "Computer Network Architectures"),
    ("COMS 5870", "Network Programming, Applications, and Research Issues"),
    ("COMS 5880", "Computer Networks"),
    ("COMS 6120", "Distributed Algorithms"),
    ("COMS 6330", "Advanced Topics in Computational Randomness"),
    ("COMS 6650A", "Advanced Topics in Software Engineering"),
    ("COMS 6720", "Advanced Topics in Artificial Intelligence"),
    ("COMS 6730", "Advanced Topics in Machine Learning"),
    # AI program — appears in faculty.courses_taught but not in the CS catalog
    ("AI 2010X", "Introduction to Artificial Intelligence"),
]

# Topic classification by keyword on title
TOPIC_RULES = [
    (("artificial intelligence", "machine learning", "ml ", "deep learning", "natural language", "nlp"), "AI and Machine Learning"),
    (("robot", "vision", "motion plan", "autonomous"), "Computer Vision"),
    (("graphics", "game", "media programming"), "Graphics and Games"),
    (("operating system", "network", "distributed", "concurrent", "cloud", "high performance"), "Systems and Networking"),
    (("database", "data set", "data structures", "data security"), "Data Science"),
    (("software", "programming language", "compiling", "compiler", "testing", "requirements", "formal method", "program analysis"), "Software Engineering"),
    (("security", "privacy", "cryptography"), "Security"),
    (("theory of comput", "algorithm", "logic", "computational geometry", "discrete computational", "quantum"), "Theory"),
    (("bioinformatics", "genome", "structural"), "Bioinformatics"),
    (("user interface", "human-computer", "hci"), "Human-Computer Interaction"),
    (("nanoscale", "molecular"), "Theory"),
    (("orientation", "career", "literacy", "spreadsheets", "fundamentals", "introduction to programming", "web programming", "linux", "non-majors"), "Fundamentals"),
    (("c for programmers", "advanced programming"), "Software Engineering"),
    (("gerontechnology", "healthcare"), "Software Engineering"),
]


def classify_topic(title: str) -> list:
    t = title.lower()
    matches = []
    for keywords, topic in TOPIC_RULES:
        if any(k in t for k in keywords):
            matches.append(topic)
    return list(dict.fromkeys(matches)) or ["Computer Science"]


def level_from_number(num: str) -> str:
    # Extract first digit of the numeric part
    digits = "".join(c for c in num if c.isdigit())
    if not digits:
        return "Other"
    first = digits[0]
    return {
        "1": "Introductory",
        "2": "Sophomore",
        "3": "Junior",
        "4": "Senior",
        "5": "Graduate",
        "6": "Advanced Graduate",
    }.get(first, "Other")


def build():
    out = []
    seen = set()
    for number, title in RAW:
        if number in seen:
            continue
        seen.add(number)
        out.append({
            "number": number,
            "name": title,
            "level": level_from_number(number),
            "credits": "3",  # default; the catalog page didn't reliably surface credits
            "topics": classify_topic(title),
        })
    return out


if __name__ == "__main__":
    import json
    courses = build()
    print(f"# {len(courses)} courses")
    print("COURSES = [")
    for c in courses:
        topics_str = json.dumps(c["topics"])
        print(f'    {{"number": "{c["number"]}", "name": "{c["name"]}", "level": "{c["level"]}", "credits": "{c["credits"]}", "topics": {topics_str}}},')
    print("]")
