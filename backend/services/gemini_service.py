"""
Gemini AI Service for semantic search.

Uses Google Gemini (via Vertex AI) for:
- Understanding natural language queries
- Generating answers from document context
- Suggesting related queries
"""

import os
from typing import Dict, List, Any, Optional
import logging
import json
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger(__name__)

GCP_PROJECT = os.getenv("GCP_PROJECT", "rag-dspace")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
GEMINI_GEN_MODEL = os.getenv("GEMINI_GEN_MODEL", "gemini-2.5-flash")


class GeminiSearchService:
    """Service for AI-powered search using Gemini via Vertex AI."""

    def __init__(self):
        """Initialize the google-genai Vertex client."""
        self.model_name = GEMINI_GEN_MODEL
        self.client = None
        try:
            from google import genai as google_genai
            self.client = google_genai.Client(
                vertexai=True,
                project=GCP_PROJECT,
                location=GCP_LOCATION,
            )
            self.initialized = True
            logger.info(
                f"Gemini (Vertex) service initialized: project={GCP_PROJECT}, "
                f"location={GCP_LOCATION}, model={self.model_name}"
            )
        except ImportError:
            self.initialized = False
            logger.warning("google-genai not installed")
        except Exception as e:
            self.initialized = False
            logger.warning(f"Gemini Vertex client init failed: {e}")
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform semantic search and generate answer.
        
        Args:
            query: Natural language search query
            limit: Maximum number of results
            filters: Optional filters (author, year, topic)
            
        Returns:
            Dictionary with answer and sources
        """
        if not self.initialized:
            return self._mock_search(query)
        
        try:
            # Build context for the search
            context = self._build_search_context(query, filters)
            
            # Generate response with Gemini
            prompt = f"""You are a research assistant for Iowa State University's Computer Science department.
            
Based on the following search query and context, provide a helpful answer about the research.

Query: {query}

Context: {context}

Instructions:
1. Provide a clear, informative answer based on available research
2. Mention specific papers, authors, or methods when relevant
3. If the query is about a specific topic, explain the key concepts
4. Keep the answer concise but comprehensive (2-3 paragraphs)
5. If you don't have enough information, say so honestly

Answer:"""

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=prompt,
            )
            answer = response.text if response.text else "Unable to generate answer."
            
            # Get mock sources for now (in production, these come from Gemini File Search)
            sources = self._get_mock_sources(query, filters)
            
            return {
                "answer": answer,
                "sources": sources[:limit],
                "query": query
            }
            
        except Exception as e:
            logger.error(f"Gemini search error: {e}")
            return self._mock_search(query)
    
    async def suggest_queries(self, query: str) -> List[str]:
        """Generate suggested follow-up queries."""
        if not self.initialized:
            return self._mock_suggestions(query)
        
        try:
            prompt = f"""Based on this research query: "{query}"

Generate 3 related follow-up questions that a researcher might want to ask.
Return only the questions, one per line, no numbering or bullets."""

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=prompt,
            )
            suggestions = (response.text or "").strip().split('\n')
            return [s.strip() for s in suggestions if s.strip()][:3]
            
        except Exception as e:
            logger.error(f"Suggestions error: {e}")
            return self._mock_suggestions(query)
    
    def _build_search_context(self, query: str, filters: Optional[Dict] = None) -> str:
        """Build context string for the search."""
        context_parts = [
            "Iowa State University Computer Science Department Research Repository",
            f"Focus areas: AI, Machine Learning, Computer Vision, NLP, Robotics, Security, Systems",
        ]
        
        if filters:
            if "author" in filters:
                context_parts.append(f"Author filter: {filters['author']}")
            if "topic" in filters:
                context_parts.append(f"Topic filter: {filters['topic']}")
            if "year" in filters:
                context_parts.append(f"Year filter: {filters['year']}")
        
        return "\n".join(context_parts)
    
    def _get_mock_sources(self, query: str, filters: Optional[Dict] = None) -> List[Dict]:
        """Get mock sources for demo purposes."""
        # These would come from Gemini File Search or DSpace in production
        mock_sources = [
            {
                "title": "Deep Learning Framework for Medical Image Analysis",
                "authors": ["Wallapak Tavanapong", "Lei Qi", "Johnny Wong"],
                "year": 2023,
                "type": "article",
                "url": "https://dr.lib.iastate.edu/entities/publication/example1",
                "snippet": "We present a comprehensive deep learning framework for automated medical image analysis, focusing on colonoscopy video processing..."
            },
            {
                "title": "Graph Neural Networks for Molecular Property Prediction",
                "authors": ["Hongyang Gao", "Zhaoning Yu"],
                "year": 2024,
                "type": "article",
                "url": "https://dr.lib.iastate.edu/entities/publication/example2",
                "snippet": "This paper introduces novel graph neural network architectures for predicting molecular properties with improved accuracy..."
            },
            {
                "title": "Trustworthy AI: Fairness and Explainability in ML Systems",
                "authors": ["Mengdi Huai", "Student A"],
                "year": 2024,
                "type": "thesis",
                "url": "https://dr.lib.iastate.edu/entities/publication/example3",
                "snippet": "This dissertation explores methods for ensuring fairness and explainability in machine learning systems deployed in high-stakes applications..."
            },
            {
                "title": "Autonomous Vehicle Perception using Multi-Modal Sensor Fusion",
                "authors": ["Bowen Weng", "Student B"],
                "year": 2023,
                "type": "thesis",
                "url": "https://dr.lib.iastate.edu/entities/publication/example4",
                "snippet": "We propose a novel approach to autonomous vehicle perception that combines LiDAR, camera, and radar data using attention-based fusion..."
            },
            {
                "title": "Software Testing for Configurable Systems",
                "authors": ["Myra Cohen", "Student C"],
                "year": 2023,
                "type": "article",
                "url": "https://dr.lib.iastate.edu/entities/publication/example5",
                "snippet": "This paper presents combinatorial interaction testing techniques for highly configurable software systems..."
            }
        ]
        
        # Filter by author if specified
        if filters and "author" in filters:
            author = filters["author"].lower()
            mock_sources = [s for s in mock_sources if any(author in a.lower() for a in s["authors"])]
        
        return mock_sources
    
    def _mock_search(self, query: str) -> Dict[str, Any]:
        """Return mock results when Gemini (Vertex) is not available."""
        return {
            "answer": (
                f"This is a demo response for: '{query}'. To get AI-powered answers, "
                "ensure Application Default Credentials are configured and the "
                "Vertex AI API is enabled in your GCP project."
            ),
            "sources": self._get_mock_sources(query),
            "query": query
        }
    
    def _mock_suggestions(self, query: str) -> List[str]:
        """Return mock suggestions."""
        base_suggestions = [
            f"What are the latest advances in {query}?",
            f"Who are the leading researchers in {query}?",
            f"What datasets are commonly used for {query}?"
        ]
        return base_suggestions


# Create singleton instance
gemini_service = GeminiSearchService()
