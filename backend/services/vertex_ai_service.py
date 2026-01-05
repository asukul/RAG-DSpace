"""
Vertex AI Search Service for RAG-based search.

Uses Google Cloud Vertex AI Search for:
- Semantic document search
- RAG-powered answers with citations
- Automatic document indexing
"""

from google.cloud import discoveryengine_v1 as discoveryengine
from google.api_core.client_options import ClientOptions
from typing import Dict, List, Any, Optional
import logging
import os
import json

logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "isu-research-search")
LOCATION = os.environ.get("GCP_LOCATION", "global")
DATA_STORE_ID = os.environ.get("VERTEX_DATASTORE_ID", "isu-research")
ENGINE_ID = os.environ.get("VERTEX_ENGINE_ID", "isu-research-app")


class VertexAISearchService:
    """Service for RAG-powered search using Vertex AI Search."""
    
    def __init__(self):
        """Initialize Vertex AI Search client."""
        self.project_id = PROJECT_ID
        self.location = LOCATION
        self.data_store_id = DATA_STORE_ID
        self.engine_id = ENGINE_ID
        
        try:
            # Initialize clients
            client_options = ClientOptions(
                api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com" if LOCATION != "global" else None
            )
            
            self.search_client = discoveryengine.SearchServiceClient(client_options=client_options)
            self.document_client = discoveryengine.DocumentServiceClient(client_options=client_options)
            
            self.initialized = True
            logger.info(f"Vertex AI Search initialized for project: {PROJECT_ID}")
        except Exception as e:
            logger.warning(f"Vertex AI Search not initialized: {e}")
            self.initialized = False
    
    @property
    def serving_config(self) -> str:
        """Get the serving config path."""
        return f"projects/{self.project_id}/locations/{self.location}/collections/default_collection/engines/{self.engine_id}/servingConfigs/default_search"
    
    @property
    def data_store_path(self) -> str:
        """Get the data store path."""
        return f"projects/{self.project_id}/locations/{self.location}/collections/default_collection/dataStores/{self.data_store_id}"
    
    @property
    def branch_path(self) -> str:
        """Get the default branch path."""
        return f"{self.data_store_path}/branches/default_branch"
    
    async def search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform RAG-powered semantic search.
        
        Args:
            query: Natural language search query
            limit: Maximum number of results
            filters: Optional filters (author, year, topic)
            
        Returns:
            Dictionary with AI summary, citations, and results
        """
        if not self.initialized:
            return self._fallback_search(query)
        
        try:
            # Build search request with RAG
            request = discoveryengine.SearchRequest(
                serving_config=self.serving_config,
                query=query,
                page_size=limit,
                content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                    # Enable extractive answers
                    extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                        max_extractive_answer_count=3,
                        max_extractive_segment_count=5,
                    ),
                    # Enable AI summary (RAG)
                    summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
                        summary_result_count=5,
                        include_citations=True,
                        ignore_adversarial_query=True,
                        ignore_non_summary_seeking_query=False,
                        model_prompt_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelPromptSpec(
                            preamble="You are a research assistant for Iowa State University. Provide helpful, accurate answers about research papers and faculty. Always cite your sources."
                        ),
                        model_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelSpec(
                            version="gemini-1.5-flash-001/answer_gen/v1"
                        )
                    )
                ),
                # Query expansion for better results
                query_expansion_spec=discoveryengine.SearchRequest.QueryExpansionSpec(
                    condition=discoveryengine.SearchRequest.QueryExpansionSpec.Condition.AUTO
                ),
                # Spell correction
                spell_correction_spec=discoveryengine.SearchRequest.SpellCorrectionSpec(
                    mode=discoveryengine.SearchRequest.SpellCorrectionSpec.Mode.AUTO
                )
            )
            
            # Add filters if provided
            if filters:
                filter_parts = []
                if "author" in filters:
                    filter_parts.append(f'authors: ANY("{filters["author"]}")')
                if "year" in filters:
                    filter_parts.append(f'date >= "{filters["year"]}-01-01"')
                if "topic" in filters:
                    filter_parts.append(f'subjects: ANY("{filters["topic"]}")')
                if filter_parts:
                    request.filter = " AND ".join(filter_parts)
            
            # Execute search
            response = self.search_client.search(request)
            
            # Process results
            results = []
            for result in response.results:
                doc = result.document
                doc_data = {
                    "id": doc.id,
                    "title": doc.struct_data.get("title", "Untitled"),
                    "authors": doc.struct_data.get("authors", []),
                    "abstract": doc.struct_data.get("abstract", ""),
                    "date": doc.struct_data.get("date", ""),
                    "url": doc.struct_data.get("url", ""),
                    "type": doc.struct_data.get("type", ""),
                    "relevance_score": result.model_scores
                }
                
                # Add extractive answers if available
                if hasattr(result, 'chunk') and result.chunk:
                    doc_data["snippet"] = result.chunk.content
                
                results.append(doc_data)
            
            # Get AI summary
            summary = ""
            citations = []
            if hasattr(response, 'summary') and response.summary:
                summary = response.summary.summary_text
                if hasattr(response.summary, 'summary_with_metadata'):
                    citations = [
                        {
                            "title": ref.title,
                            "uri": ref.uri
                        }
                        for ref in response.summary.summary_with_metadata.references
                    ]
            
            return {
                "answer": summary or f"Found {len(results)} results for: {query}",
                "citations": citations,
                "sources": results,
                "query": query,
                "corrected_query": response.corrected_query if hasattr(response, 'corrected_query') else None
            }
            
        except Exception as e:
            logger.error(f"Vertex AI Search error: {e}")
            return self._fallback_search(query, str(e))
    
    async def index_document(self, doc: Dict[str, Any]) -> bool:
        """
        Index a document to Vertex AI Search.
        
        Args:
            doc: Document dictionary with uuid, title, authors, abstract, etc.
            
        Returns:
            True if successful
        """
        if not self.initialized:
            logger.warning("Cannot index: Vertex AI not initialized")
            return False
        
        try:
            document = discoveryengine.Document(
                id=doc.get("uuid", doc.get("id")),
                json_data=json.dumps({
                    "title": doc.get("title", ""),
                    "authors": doc.get("authors", []),
                    "advisors": doc.get("advisors", []),
                    "abstract": doc.get("abstract", ""),
                    "subjects": doc.get("subjects", []),
                    "date": doc.get("date", ""),
                    "type": doc.get("type", ""),
                    "url": doc.get("url", ""),
                    "department": doc.get("department", ""),
                    "college": doc.get("college", "")
                })
            )
            
            request = discoveryengine.CreateDocumentRequest(
                parent=self.branch_path,
                document=document,
                document_id=doc.get("uuid", doc.get("id"))
            )
            
            self.document_client.create_document(request=request)
            logger.info(f"Indexed document: {doc.get('title', 'Unknown')[:50]}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to index document: {e}")
            return False
    
    async def index_documents_batch(self, docs: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Index multiple documents in batch.
        
        Args:
            docs: List of document dictionaries
            
        Returns:
            Dictionary with success/failure counts
        """
        success = 0
        failed = 0
        
        for doc in docs:
            if await self.index_document(doc):
                success += 1
            else:
                failed += 1
        
        return {"indexed": success, "failed": failed, "total": len(docs)}
    
    async def suggest_queries(self, query: str) -> List[str]:
        """Generate suggested follow-up queries."""
        # Use autocomplete if available
        if not self.initialized:
            return [
                f"What are the latest advances in {query}?",
                f"Who are the leading researchers in {query}?",
                f"What datasets are commonly used for {query}?"
            ]
        
        try:
            # For now, return static suggestions
            # In future, could use Vertex AI Completion API
            return [
                f"What are recent publications about {query}?",
                f"Which faculty specialize in {query}?",
                f"What are related topics to {query}?"
            ]
        except Exception as e:
            logger.error(f"Suggestions error: {e}")
            return []
    
    def _fallback_search(self, query: str, error: str = None) -> Dict[str, Any]:
        """Return fallback response when Vertex AI is not available."""
        message = f"Vertex AI Search not available. "
        if error:
            message += f"Error: {error}"
        else:
            message += "Please configure GCP credentials and enable Vertex AI Search."
        
        return {
            "answer": message,
            "citations": [],
            "sources": [],
            "query": query,
            "error": True
        }


# Create singleton instance
vertex_search_service = VertexAISearchService()
