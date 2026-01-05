
import asyncio
import os
# Mock keys for testing if environment not set, though main.py handles it.
os.environ["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")

from main import find_relevant_faculty, FACULTY_DATA

async def test():
    print(f"Total Faculty: {len(FACULTY_DATA)}")
    
    queries = [
        "Robotics and computer vision",
        "Software testing and verification",
        "Deep learning",
        "Bioinformatics",
        "Network security"
    ]

    for q in queries:
        print(f"\nQuery: {q}")
        results = await find_relevant_faculty(q, FACULTY_DATA)
        print("Matches:")
        for r in results:
            print(f"  - {r['name']} ({r.get('rank', 'N/A')}) - {r.get('group', 'N/A')}")

if __name__ == "__main__":
    asyncio.run(test())
