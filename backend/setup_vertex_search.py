#!/usr/bin/env python3
"""
Create Vertex AI Search Data Store and Search App
"""

from google.cloud import discoveryengine_v1 as discoveryengine
from google.api_core.exceptions import AlreadyExists, NotFound
import os

PROJECT_ID = "rag-dspace"
LOCATION = "global"  # Vertex AI Search only supports global location
DATA_STORE_ID = "isu-research"
SEARCH_APP_ID = "isu-research-app"

def create_data_store():
    """Create a Vertex AI Search data store for unstructured documents"""
    client = discoveryengine.DataStoreServiceClient()
    
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection"
    
    data_store = discoveryengine.DataStore(
        display_name="ISU Research Data Store",
        industry_vertical=discoveryengine.IndustryVertical.GENERIC,
        solution_types=[discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH],
        content_config=discoveryengine.DataStore.ContentConfig.CONTENT_REQUIRED,
    )
    
    try:
        operation = client.create_data_store(
            parent=parent,
            data_store=data_store,
            data_store_id=DATA_STORE_ID,
        )
        print(f"Creating data store... (operation: {operation.operation.name})")
        result = operation.result(timeout=300)  # Wait up to 5 minutes
        print(f"[OK] Data store created: {result.name}")
        return result
    except AlreadyExists:
        print(f"[OK] Data store '{DATA_STORE_ID}' already exists")
        # Get existing data store
        ds_name = f"{parent}/dataStores/{DATA_STORE_ID}"
        return client.get_data_store(name=ds_name)
    except Exception as e:
        print(f"[ERROR] Error creating data store: {e}")
        raise

def create_search_engine():
    """Create a search engine (app) linked to the data store"""
    client = discoveryengine.EngineServiceClient()
    
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection"
    
    engine = discoveryengine.Engine(
        display_name="ISU Research Search App",
        solution_type=discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH,
        search_engine_config=discoveryengine.Engine.SearchEngineConfig(
            search_tier=discoveryengine.SearchTier.SEARCH_TIER_STANDARD,
            search_add_ons=[discoveryengine.SearchAddOn.SEARCH_ADD_ON_LLM],
        ),
        data_store_ids=[DATA_STORE_ID],
    )
    
    try:
        operation = client.create_engine(
            parent=parent,
            engine=engine,
            engine_id=SEARCH_APP_ID,
        )
        print(f"Creating search engine... (operation: {operation.operation.name})")
        result = operation.result(timeout=300)
        print(f"[OK] Search engine created: {result.name}")
        return result
    except AlreadyExists:
        print(f"[OK] Search engine '{SEARCH_APP_ID}' already exists")
        engine_name = f"{parent}/engines/{SEARCH_APP_ID}"
        return client.get_engine(name=engine_name)
    except Exception as e:
        print(f"[ERROR] Error creating search engine: {e}")
        raise

def list_data_stores():
    """List existing data stores"""
    client = discoveryengine.DataStoreServiceClient()
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection"
    
    print(f"\nListing data stores in {parent}...")
    try:
        stores = list(client.list_data_stores(parent=parent))
        if stores:
            for store in stores:
                print(f"  - {store.name} ({store.display_name})")
        else:
            print("  No data stores found")
        return stores
    except Exception as e:
        print(f"[ERROR] Error listing data stores: {e}")
        return []

def main():
    print("=" * 60)
    print("Vertex AI Search Setup for ISU Research")
    print("=" * 60)
    print(f"Project: {PROJECT_ID}")
    print(f"Location: {LOCATION}")
    print()
    
    # List existing data stores first
    list_data_stores()
    
    print()
    print("Step 1: Creating Data Store...")
    data_store = create_data_store()
    
    print()
    print("Step 2: Creating Search Engine...")
    engine = create_search_engine()
    
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print(f"Data Store ID: {DATA_STORE_ID}")
    print(f"Search App ID: {SEARCH_APP_ID}")
    print()
    print("Next steps:")
    print("1. Index documents using the DSpace sync endpoint")
    print("2. Test search functionality via the API")

if __name__ == "__main__":
    main()
