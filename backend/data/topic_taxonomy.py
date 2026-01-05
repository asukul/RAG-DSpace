"""
Topic Taxonomy for CS Research Areas.

Hierarchical structure of research topics with paper counts.
"""

from typing import Dict, List, Optional, Any


# Complete topic taxonomy tree
TOPIC_TREE: Dict[str, Any] = {
    "id": "cs-ai",
    "name": "Computer Science & AI",
    "icon": "💻",
    "papers": 2000,
    "children": [
        {
            "id": "ai-ml",
            "name": "AI & Machine Learning",
            "icon": "🧠",
            "papers": 450,
            "faculty": ["W. Tavanapong", "H. Gao", "M. Huai", "A. Sukul"],
            "children": [
                {
                    "id": "deep-learning",
                    "name": "Deep Learning",
                    "icon": "🔮",
                    "papers": 156,
                    "faculty": ["H. Gao", "W. Tavanapong"],
                    "children": [
                        {"id": "cnn", "name": "Convolutional Neural Networks", "icon": "🖼️", "papers": 45},
                        {"id": "rnn", "name": "Recurrent Neural Networks", "icon": "🔄", "papers": 28},
                        {"id": "transformers", "name": "Transformers & Attention", "icon": "🎯", "papers": 38},
                        {"id": "gnn", "name": "Graph Neural Networks", "icon": "🕸️", "papers": 32, "faculty": ["H. Gao"]},
                        {"id": "generative", "name": "Generative Models", "icon": "🎨", "papers": 25}
                    ]
                },
                {
                    "id": "ml-theory",
                    "name": "Machine Learning Theory",
                    "icon": "📐",
                    "papers": 89,
                    "children": [
                        {"id": "optimization", "name": "Optimization", "icon": "📈", "papers": 34},
                        {"id": "statistical", "name": "Statistical Learning", "icon": "📊", "papers": 28},
                        {"id": "rl", "name": "Reinforcement Learning", "icon": "🎮", "papers": 27, "faculty": ["B. Weng"]}
                    ]
                },
                {
                    "id": "trustworthy-ai",
                    "name": "Trustworthy AI",
                    "icon": "🛡️",
                    "papers": 67,
                    "faculty": ["M. Huai"],
                    "children": [
                        {"id": "fairness", "name": "Fairness in ML", "icon": "⚖️", "papers": 23},
                        {"id": "explainability", "name": "Explainability", "icon": "🔍", "papers": 22},
                        {"id": "privacy-ml", "name": "Privacy in ML", "icon": "🔒", "papers": 22}
                    ]
                },
                {
                    "id": "applied-ml",
                    "name": "Applied Machine Learning",
                    "icon": "⚙️",
                    "papers": 138,
                    "children": [
                        {"id": "medical-ai", "name": "Medical AI", "icon": "🏥", "papers": 52, "faculty": ["W. Tavanapong"]},
                        {"id": "iot-ml", "name": "IoT & Smart Systems", "icon": "📡", "papers": 34, "faculty": ["C. Miao"]},
                        {"id": "scientific-ml", "name": "Scientific Computing", "icon": "🔬", "papers": 28},
                        {"id": "time-series", "name": "Time Series", "icon": "📉", "papers": 24}
                    ]
                }
            ]
        },
        {
            "id": "cv",
            "name": "Computer Vision",
            "icon": "👁️",
            "papers": 189,
            "children": [
                {"id": "image-class", "name": "Image Classification", "icon": "🏷️", "papers": 45},
                {"id": "object-detect", "name": "Object Detection", "icon": "🎯", "papers": 38},
                {"id": "segmentation", "name": "Segmentation", "icon": "✂️", "papers": 32},
                {"id": "video-analysis", "name": "Video Analysis", "icon": "🎬", "papers": 42, "faculty": ["W. Tavanapong", "W. Zhang"]},
                {"id": "3d-vision", "name": "3D Vision", "icon": "📦", "papers": 32}
            ]
        },
        {
            "id": "nlp",
            "name": "Natural Language Processing",
            "icon": "💬",
            "papers": 167,
            "children": [
                {"id": "text-class", "name": "Text Classification", "icon": "📝", "papers": 38},
                {"id": "ner", "name": "Named Entity Recognition", "icon": "🏷️", "papers": 24},
                {"id": "qa", "name": "Question Answering", "icon": "❓", "papers": 32},
                {"id": "summarization", "name": "Summarization", "icon": "📋", "papers": 28},
                {"id": "llm", "name": "Large Language Models", "icon": "🤖", "papers": 45}
            ]
        },
        {
            "id": "robotics",
            "name": "Robotics & Autonomous Systems",
            "icon": "🤖",
            "papers": 145,
            "faculty": ["Y. Jia", "N. Wongpiromsarn", "B. Weng"],
            "children": [
                {"id": "motion-planning", "name": "Motion Planning", "icon": "🛤️", "papers": 38, "faculty": ["Y. Jia"]},
                {"id": "manipulation", "name": "Manipulation", "icon": "🦾", "papers": 32, "faculty": ["Y. Jia"]},
                {"id": "autonomous-vehicles", "name": "Autonomous Vehicles", "icon": "🚗", "papers": 42, "faculty": ["N. Wongpiromsarn", "B. Weng"]},
                {"id": "swarm", "name": "Swarm Robotics", "icon": "🐝", "papers": 18},
                {"id": "human-robot", "name": "Human-Robot Interaction", "icon": "🤝", "papers": 15}
            ]
        },
        {
            "id": "security",
            "name": "Security & Privacy",
            "icon": "🔒",
            "papers": 178,
            "faculty": ["S. Xin", "Q. Li", "A. Sikder"],
            "children": [
                {"id": "network-sec", "name": "Network Security", "icon": "🌐", "papers": 45, "faculty": ["S. Xin", "Q. Li"]},
                {"id": "ml-security", "name": "ML Security", "icon": "🛡️", "papers": 38, "faculty": ["Q. Li"]},
                {"id": "iot-security", "name": "IoT Security", "icon": "📡", "papers": 35, "faculty": ["A. Sikder"]},
                {"id": "crypto", "name": "Cryptography", "icon": "🔐", "papers": 28},
                {"id": "privacy", "name": "Privacy", "icon": "👤", "papers": 32, "faculty": ["M. Mohammady"]}
            ]
        },
        {
            "id": "systems",
            "name": "Systems & Networking",
            "icon": "🖥️",
            "papers": 234,
            "children": [
                {"id": "distributed", "name": "Distributed Systems", "icon": "🌍", "papers": 56},
                {"id": "cloud", "name": "Cloud Computing", "icon": "☁️", "papers": 48},
                {"id": "hpc", "name": "High-Performance Computing", "icon": "⚡", "papers": 42, "faculty": ["A. Jannesari"]},
                {"id": "networks", "name": "Computer Networks", "icon": "🔗", "papers": 45},
                {"id": "mobile", "name": "Mobile Computing", "icon": "📱", "papers": 43, "faculty": ["Y. Cai", "C. Miao"]}
            ]
        },
        {
            "id": "se",
            "name": "Software Engineering",
            "icon": "🛠️",
            "papers": 198,
            "faculty": ["M. Cohen", "R. Lutz", "W. Le"],
            "children": [
                {"id": "testing", "name": "Software Testing", "icon": "🧪", "papers": 52, "faculty": ["M. Cohen"]},
                {"id": "verification", "name": "Formal Verification", "icon": "✅", "papers": 38, "faculty": ["S. Basu", "A. Miner"]},
                {"id": "program-analysis", "name": "Program Analysis", "icon": "🔍", "papers": 35, "faculty": ["W. Le"]},
                {"id": "safety", "name": "Safety-Critical Systems", "icon": "⚠️", "papers": 28, "faculty": ["R. Lutz"]},
                {"id": "se-ai", "name": "AI for SE", "icon": "🤖", "papers": 45, "faculty": ["W. Le"]}
            ]
        },
        {
            "id": "theory",
            "name": "Theory & Foundations",
            "icon": "📚",
            "papers": 156,
            "faculty": ["P. Aduri", "J. Lutz", "S. Chaudhuri"],
            "children": [
                {"id": "complexity", "name": "Computational Complexity", "icon": "🧩", "papers": 42, "faculty": ["P. Aduri", "J. Lutz"]},
                {"id": "algorithms", "name": "Algorithm Design", "icon": "📊", "papers": 38},
                {"id": "info-theory", "name": "Information Theory", "icon": "📡", "papers": 28, "faculty": ["C. Quinn"]},
                {"id": "randomness", "name": "Algorithmic Randomness", "icon": "🎲", "papers": 24, "faculty": ["J. Lutz", "C. Stevens"]},
                {"id": "molecular", "name": "Molecular Computing", "icon": "🧬", "papers": 24, "faculty": ["J. Lathrop"]}
            ]
        },
        {
            "id": "data-science",
            "name": "Data Science & Analytics",
            "icon": "📈",
            "papers": 178,
            "faculty": ["A. Sukul", "L. Yan"],
            "children": [
                {"id": "data-mining", "name": "Data Mining", "icon": "⛏️", "papers": 45},
                {"id": "visualization", "name": "Data Visualization", "icon": "📊", "papers": 38, "faculty": ["L. Yan"]},
                {"id": "big-data", "name": "Big Data Processing", "icon": "💾", "papers": 42},
                {"id": "analytics", "name": "Predictive Analytics", "icon": "🔮", "papers": 28},
                {"id": "databases", "name": "Database Systems", "icon": "🗄️", "papers": 25}
            ]
        },
        {
            "id": "hci",
            "name": "Human-Computer Interaction",
            "icon": "👆",
            "papers": 89,
            "faculty": ["R. Kopper", "G. Batinov"],
            "children": [
                {"id": "vr-ar", "name": "VR/AR", "icon": "🥽", "papers": 35, "faculty": ["R. Kopper"]},
                {"id": "viz-hci", "name": "Interactive Visualization", "icon": "🖼️", "papers": 28},
                {"id": "accessibility", "name": "Accessibility", "icon": "♿", "papers": 15},
                {"id": "ux", "name": "User Experience", "icon": "😊", "papers": 11}
            ]
        }
    ]
}


def _build_index(node: Dict, parent_path: str = "") -> Dict[str, Dict]:
    """Build flat index of topics for fast lookup."""
    index = {}
    
    path = f"{parent_path}/{node['id']}" if parent_path else node['id']
    index[node['id']] = {**node, 'path': path}
    
    for child in node.get('children', []):
        index.update(_build_index(child, path))
    
    return index


# Build index at module load
_TOPIC_INDEX = _build_index(TOPIC_TREE)


def get_topic_by_id(topic_id: str) -> Optional[Dict]:
    """Get topic by ID."""
    return _TOPIC_INDEX.get(topic_id)


def search_topics(query: str) -> List[Dict]:
    """Search topics by name."""
    query_lower = query.lower()
    results = []
    
    for topic_id, topic in _TOPIC_INDEX.items():
        if query_lower in topic['name'].lower():
            results.append({
                'id': topic['id'],
                'name': topic['name'],
                'icon': topic['icon'],
                'papers': topic['papers'],
                'path': topic['path']
            })
    
    return sorted(results, key=lambda x: x['papers'], reverse=True)


def get_all_topics_flat() -> List[Dict]:
    """Get all topics as flat list."""
    return [
        {
            'id': t['id'],
            'name': t['name'],
            'icon': t['icon'],
            'papers': t['papers']
        }
        for t in _TOPIC_INDEX.values()
    ]
