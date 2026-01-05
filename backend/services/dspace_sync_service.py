"""
DSpace Sync Service for Vertex AI Search.

Syncs documents from DSpace to:
- Vertex AI Search (for RAG)
- Firestore (for fast metadata queries)
- Cloud Storage (for PDF backup)
"""

from google.cloud import firestore
from google.cloud import storage as gcs
import httpx
from typing import Dict, List, Any, Optional
import logging
import os
import json
from datetime import datetime

from services.vertex_ai_service import vertex_search_service

logger = logging.getLogger(__name__)

# Configuration
DSPACE_BASE_URL = os.environ.get("DSPACE_BASE_URL", "https://dr.lib.iastate.edu/server/api")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "isu-research-pdfs")
USE_FIRESTORE = os.environ.get("USE_FIRESTORE", "false").lower() == "true"
USE_GCS = os.environ.get("USE_GCS", "false").lower() == "true"


class DSpaceSyncService:
    """Service for syncing DSpace documents to GCP services."""
    
    def __init__(self):
        """Initialize sync service."""
        self.dspace_url = DSPACE_BASE_URL
        
        # Initialize Firestore if enabled
        self.firestore_client = None
        if USE_FIRESTORE:
            try:
                self.firestore_client = firestore.Client()
                logger.info("Firestore client initialized")
            except Exception as e:
                logger.warning(f"Firestore not available: {e}")
        
        # Initialize Cloud Storage if enabled
        self.storage_client = None
        if USE_GCS:
            try:
                self.storage_client = gcs.Client()
                self.bucket = self.storage_client.bucket(GCS_BUCKET)
                logger.info(f"Cloud Storage initialized: {GCS_BUCKET}")
            except Exception as e:
                logger.warning(f"Cloud Storage not available: {e}")
    
    async def fetch_dspace_items(
        self,
        collection_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Fetch items from DSpace API.
        
        Args:
            collection_id: Optional collection to filter by
            limit: Maximum items to fetch
            offset: Pagination offset
            
        Returns:
            List of document dictionaries
        """
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                if collection_id:
                    url = f"{self.dspace_url}/discover/search/objects"
                    params = {
                        "scope": collection_id,
                        "size": limit,
                        "page": offset // limit
                    }
                else:
                    url = f"{self.dspace_url}/core/items"
                    params = {"size": limit, "page": offset // limit}
                
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                # Parse items
                items = []
                embedded = data.get("_embedded", {})
                raw_items = embedded.get("items", embedded.get("searchResult", {}).get("_embedded", {}).get("objects", []))
                
                for item in raw_items:
                    # Handle search result wrapper
                    if "_embedded" in item and "indexableObject" in item["_embedded"]:
                        item = item["_embedded"]["indexableObject"]
                    
                    parsed = self._parse_dspace_item(item)
                    if parsed:
                        items.append(parsed)
                
                return items
                
        except Exception as e:
            logger.error(f"Error fetching DSpace items: {e}")
            return []
    
    def _parse_dspace_item(self, item: Dict) -> Optional[Dict[str, Any]]:
        """Parse a DSpace item into a standard format."""
        try:
            metadata = item.get("metadata", {})
            
            def get_meta(key: str) -> List[str]:
                values = metadata.get(key, [])
                if isinstance(values, list):
                    return [v.get("value", v) if isinstance(v, dict) else v for v in values]
                return [values] if values else []
            
            return {
                "uuid": item.get("uuid"),
                "title": get_meta("dc.title")[0] if get_meta("dc.title") else "Untitled",
                "authors": get_meta("dc.contributor.author"),
                "advisors": get_meta("dc.contributor.advisor"),
                "abstract": get_meta("dc.description.abstract")[0] if get_meta("dc.description.abstract") else "",
                "subjects": get_meta("dc.subject"),
                "date": get_meta("dc.date.issued")[0] if get_meta("dc.date.issued") else "",
                "type": get_meta("dc.type")[0] if get_meta("dc.type") else "",
                "url": f"https://dr.lib.iastate.edu/items/{item.get('uuid')}",
                "department": get_meta("dc.contributor.department")[0] if get_meta("dc.contributor.department") else "",
                "college": get_meta("dc.contributor.college")[0] if get_meta("dc.contributor.college") else ""
            }
        except Exception as e:
            logger.error(f"Error parsing DSpace item: {e}")
            return None
    
    async def sync_to_vertex_ai(self, docs: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Index documents to Vertex AI Search.
        
        Args:
            docs: List of document dictionaries
            
        Returns:
            Dictionary with success/failure counts
        """
        return await vertex_search_service.index_documents_batch(docs)
    
    async def sync_to_firestore(self, docs: List[Dict[str, Any]]) -> int:
        """
        Sync documents to Firestore.
        
        Args:
            docs: List of document dictionaries
            
        Returns:
            Number of documents synced
        """
        if not self.firestore_client:
            logger.warning("Firestore not available")
            return 0
        
        try:
            batch = self.firestore_client.batch()
            count = 0
            
            for doc in docs:
                doc_ref = self.firestore_client.collection("documents").document(doc["uuid"])
                batch.set(doc_ref, {
                    **doc,
                    "synced_at": datetime.utcnow().isoformat()
                })
                count += 1
                
                # Commit every 500 docs (Firestore batch limit)
                if count % 500 == 0:
                    batch.commit()
                    batch = self.firestore_client.batch()
            
            # Commit remaining
            if count % 500 != 0:
                batch.commit()
            
            logger.info(f"Synced {count} documents to Firestore")
            return count
            
        except Exception as e:
            logger.error(f"Firestore sync error: {e}")
            return 0
    
    async def download_pdf(self, doc: Dict[str, Any]) -> Optional[bytes]:
        """
        Download PDF file for a document.
        
        Args:
            doc: Document dictionary with uuid
            
        Returns:
            PDF bytes or None
        """
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Get bitstreams
                url = f"{self.dspace_url}/core/items/{doc['uuid']}/bitstreams"
                response = await client.get(url)
                response.raise_for_status()
                
                bitstreams = response.json().get("_embedded", {}).get("bitstreams", [])
                
                # Find PDF bitstream
                for bs in bitstreams:
                    if bs.get("name", "").lower().endswith(".pdf"):
                        bs_url = f"{self.dspace_url}/core/bitstreams/{bs['uuid']}/content"
                        pdf_response = await client.get(bs_url)
                        if pdf_response.status_code == 200:
                            return pdf_response.content
                
                return None
                
        except Exception as e:
            logger.error(f"Error downloading PDF: {e}")
            return None
    
    async def upload_pdf_to_gcs(self, doc_id: str, pdf_bytes: bytes) -> bool:
        """
        Upload PDF to Cloud Storage.
        
        Args:
            doc_id: Document UUID
            pdf_bytes: PDF file bytes
            
        Returns:
            True if successful
        """
        if not self.storage_client:
            return False
        
        try:
            blob = self.bucket.blob(f"pdfs/{doc_id}.pdf")
            blob.upload_from_string(pdf_bytes, content_type="application/pdf")
            logger.info(f"Uploaded PDF: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"GCS upload error: {e}")
            return False
    
    async def full_sync(
        self,
        collection_id: Optional[str] = None,
        max_items: int = 1000,
        include_pdfs: bool = False
    ) -> Dict[str, Any]:
        """
        Perform full sync from DSpace to all services.
        
        Args:
            collection_id: Optional collection to sync
            max_items: Maximum items to sync
            include_pdfs: Whether to download PDFs
            
        Returns:
            Sync summary
        """
        logger.info(f"Starting full sync (max: {max_items}, pdfs: {include_pdfs})")
        
        start_time = datetime.utcnow()
        stats = {
            "fetched": 0,
            "vertex_indexed": 0,
            "firestore_synced": 0,
            "pdfs_downloaded": 0,
            "errors": []
        }
        
        try:
            # Fetch all documents
            all_docs = []
            offset = 0
            while len(all_docs) < max_items:
                batch = await self.fetch_dspace_items(
                    collection_id=collection_id,
                    limit=100,
                    offset=offset
                )
                if not batch:
                    break
                all_docs.extend(batch)
                offset += 100
            
            all_docs = all_docs[:max_items]
            stats["fetched"] = len(all_docs)
            
            # Sync to Vertex AI
            vertex_result = await self.sync_to_vertex_ai(all_docs)
            stats["vertex_indexed"] = vertex_result.get("indexed", 0)
            
            # Sync to Firestore
            stats["firestore_synced"] = await self.sync_to_firestore(all_docs)
            
            # Download PDFs if requested
            if include_pdfs:
                for doc in all_docs[:50]:  # Limit PDF downloads
                    pdf = await self.download_pdf(doc)
                    if pdf:
                        if await self.upload_pdf_to_gcs(doc["uuid"], pdf):
                            stats["pdfs_downloaded"] += 1
            
            # Update sync status
            if self.firestore_client:
                self.firestore_client.collection("sync_status").document("latest").set({
                    "last_sync": datetime.utcnow().isoformat(),
                    "documents_synced": stats["fetched"],
                    "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
                })
            
            logger.info(f"Sync complete: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Full sync error: {e}")
            stats["errors"].append(str(e))
            return stats


# Create singleton instance
dspace_sync_service = DSpaceSyncService()
