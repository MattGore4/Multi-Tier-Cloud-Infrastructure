import os
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import List
from opensearchpy import OpenSearch, RequestsHttpConnection

app = FastAPI()

#Load in the OpenSearch credentials for environment variables
OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST")
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER")
OPENSEARCH_PASS = os.environ.get("OPENSEARCH_PASS")
DOCS_INDEX = os.environ.get("DOCS_INDEX", "acme-docs")

# Initialize OpenSearch Client connection
opensearch_client = OpenSearch(
    hosts=[{'host': OPENSEARCH_HOST, 'port': 443}],
    http_auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)

#Upon app server startup this ensures the OpenSearch document index actually exists, and if not creates it
@app.on_event("startup")
async def startup_event():
    # Safely look to see if the index is missing
    if not opensearch_client.indices.exists(index=DOCS_INDEX):
        print(f"Index {DOCS_INDEX} not found. Automatically initializing...")
        # Create the index automatically so your web app never throws a 404
        opensearch_client.indices.create(index=DOCS_INDEX, body={
            "settings": {
                "index": {
                    "number_of_shards": 1,
                    "number_of_replicas": 1
                }
            }
        })

#Defining the shape of FastAPI data
class SearchResult(BaseModel):
    id: str
    title: str
    category: str
    snippet: str

class SearchResponse(BaseModel):
    results: List[SearchResult]

class FullDocumentResponse(BaseModel):
    id: str
    title: str
    category: str
    content: str

# Endpoint to return search results based on a query
@app.get("/api/search", response_model=SearchResponse)
async def search_documents(q: str = Query(..., description="User search query")):
    search_body = {
        "query": {
            #Takes the user search term and looks for it across the document title, category, and content
            "multi_match": {
                "query": q,
                #Implements weighted search, where a match on the title is ranked the highest
                "fields": ["title^3", "category^2", "content"]
            }
        }
    }
    try:
        response = opensearch_client.search(body=search_body, index=DOCS_INDEX)
        #Takes the OpenSearch output and returns a formatted list to the frontend
        formatted_results = []
        for hit in response['hits']['hits']:
            source = hit['_source']
            formatted_results.append(
                SearchResult(
                    id=hit['_id'],
                    title=source.get('title', 'Unknown'),
                    category=source.get('category', 'General'),
                    snippet=source.get('content', '')[:160] + "..."
                )
            )
        return SearchResponse(results=formatted_results)
    except Exception as e:
        print(f"Database error during search: {e}")
        raise HTTPException(status_code=500, detail="Error querying the knowledge base")

# Endpoint for viewing a selected documents content
@app.get("/api/documents/{doc_id}", response_model=FullDocumentResponse)
#Searches for the exact document ID in OpenSearch
async def get_document_by_id(doc_id: str):
    #If found the document is properly formatted for the frontend
    try:
        response = opensearch_client.get(index=DOCS_INDEX, id=doc_id)
        source = response['_source']
        return FullDocumentResponse(
            id=response['_id'],
            title=source.get('title'),
            category=source.get('category'),
            content=source.get('content')
        )
    except Exception as e:
        print(f"Database error retrieving ID {doc_id}: {e}")
        raise HTTPException(status_code=404, detail="Document not found")
