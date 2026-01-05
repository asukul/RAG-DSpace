"""
DSpace Service for accessing ISU's repository.

Provides methods to:
- Search documents
- Get item details
- List collections
- Count publications by author
"""

import httpx
from typing import Dict, List, Any, Optional
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger(__name__)


class DSpaceService:
    """Service for interacting with DSpace REST API."""
    
    def __init__(self):
        """Initialize DSpace client."""
        self.base_url = settings.dspace_base_url
        self.api_url = settings.dspace_api_url
        self.timeout = httpx.Timeout(30.0)
        logger.info(f"DSpace service initialized for {self.base_url}")
    
    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make GET request to DSpace API."""
        url = f"{self.api_url}/{endpoint}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def search(
        self,
        query: str,
        limit: int = 20,
        page: int = 0,
        dso_type: str = "item"
    ) -> List[Dict]:
        """
        Search DSpace repository.
        
        Args:
            query: Search query string
            limit: Maximum results per page
            page: Page number (0-indexed)
            dso_type: Object type (item, collection, community)
            
        Returns:
            List of search results
        """
        try:
            params = {
                "query": query,
                "dsoType": dso_type,
                "page": page,
                "size": limit,
                "sort": "dc.date.accessioned,desc"
            }
            
            data = await self._get("discover/search/objects", params)
            
            # Extract items from response
            embedded = data.get("_embedded", {})
            search_result = embedded.get("searchResult", {})
            results_embedded = search_result.get("_embedded", {})
            objects = results_embedded.get("objects", [])
            
            items = []
            for obj in objects:
                if "_embedded" in obj and "indexableObject" in obj["_embedded"]:
                    item = obj["_embedded"]["indexableObject"]
                    items.append(self._parse_item(item))
            
            return items
            
        except Exception as e:
            logger.error(f"DSpace search error: {e}")
            return []
    
    async def search_by_author(self, author_name: str, limit: int = 20) -> List[Dict]:
        """Search for publications by author name."""
        # Try different name formats
        queries = [
            f'dc.contributor.author:"{author_name}"',
            f'dc.contributor.author:"{self._format_name_last_first(author_name)}"',
        ]
        
        results = []
        for query in queries:
            items = await self.search(query, limit=limit)
            results.extend(items)
        
        # Deduplicate by UUID
        seen = set()
        unique_results = []
        for item in results:
            if item["uuid"] not in seen:
                seen.add(item["uuid"])
                unique_results.append(item)
        
        return unique_results[:limit]
    
    async def search_by_subject(self, subject: str, limit: int = 20) -> List[Dict]:
        """Search for publications by subject/topic."""
        query = f'dc.subject:"{subject}" OR dc.title:"{subject}"'
        return await self.search(query, limit=limit)
    
    async def count_by_author(self, author_name: str) -> int:
        """Count publications by author."""
        try:
            items = await self.search_by_author(author_name, limit=100)
            return len(items)
        except Exception as e:
            logger.error(f"Count error: {e}")
            return 0
    
    async def get_item(self, uuid: str) -> Optional[Dict]:
        """Get item details by UUID."""
        try:
            data = await self._get(f"core/items/{uuid}")
            return self._parse_item(data)
        except Exception as e:
            logger.error(f"Get item error: {e}")
            return None
    
    async def get_collections(self) -> List[Dict]:
        """Get list of collections."""
        try:
            data = await self._get("core/collections", {"size": 100})
            embedded = data.get("_embedded", {})
            collections = embedded.get("collections", [])
            
            return [
                {
                    "uuid": c.get("uuid"),
                    "name": c.get("name"),
                    "handle": c.get("handle"),
                    "item_count": c.get("archivedItemsCount", 0)
                }
                for c in collections
            ]
        except Exception as e:
            logger.error(f"Collections error: {e}")
            return []
    
    async def get_suggestions(self, prefix: str) -> List[str]:
        """Get search suggestions based on prefix."""
        try:
            # Search for titles starting with prefix
            items = await self.search(f"dc.title:{prefix}*", limit=5)
            titles = [item.get("title", "") for item in items if item.get("title")]
            return titles[:5]
        except Exception as e:
            logger.error(f"Suggestions error: {e}")
            return []
    
    def _parse_item(self, data: Dict) -> Dict:
        """Parse DSpace item response into comprehensive format with all metadata."""
        metadata = data.get("metadata", {})
        
        # Extract metadata fields
        def get_values(field: str) -> List[str]:
            values = metadata.get(field, [])
            return [v.get("value", "") for v in values if v.get("value")]
        
        def get_first(field: str) -> str:
            values = get_values(field)
            return values[0] if values else ""
        
        # Capture ALL dc.* metadata fields into raw_metadata
        raw_metadata = {}
        for key, values in metadata.items():
            raw_metadata[key] = [v.get("value", "") for v in values if v.get("value")]
        
        uuid = data.get("uuid", "")
        
        return {
            "uuid": uuid,
            "handle": data.get("handle", ""),
            "title": get_first("dc.title"),
            "authors": get_values("dc.contributor.author"),
            "advisors": get_values("dc.contributor.advisor") + get_values("dc.contributor.majorProfessor"),
            "contributors": get_values("dc.contributor"),
            "abstract": get_first("dc.description.abstract"),
            "date": get_first("dc.date.issued"),
            "type": get_first("dc.type"),
            "subjects": get_values("dc.subject"),
            "publisher": get_first("dc.publisher"),
            "language": get_first("dc.language.iso"),
            "rights": get_first("dc.rights"),
            "identifier_doi": get_first("dc.identifier.doi"),
            "identifier_uri": get_first("dc.identifier.uri"),
            "format": get_first("dc.format.mimetype"),
            "degree_name": get_first("thesis.degree.name"),
            "degree_level": get_first("thesis.degree.level"),
            "degree_discipline": get_first("thesis.degree.discipline"),
            "raw_metadata": raw_metadata,  # ALL DC elements for "See More"
            "url": f"{self.base_url}/items/{uuid}",
            "dspace_url": f"{self.base_url}/items/{uuid}"
        }

    
    def _format_name_last_first(self, name: str) -> str:
        """Convert 'First Last' to 'Last, First'."""
        parts = name.strip().split()
        if len(parts) >= 2:
            return f"{parts[-1]}, {' '.join(parts[:-1])}"
        return name


# Create singleton instance
dspace_service = DSpaceService()
