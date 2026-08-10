"""
Export all vectors from Pinecone index to JSON file.
Used to migrate 474k vectors from Pinecone → Qdrant.
"""

import os
import json
from dotenv import load_dotenv
from pinecone import Pinecone
from pathlib import Path

dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

INDEX_NAME = "food-index"
OUTPUT_FILE = "diagnostic/pinecone_export.json"

def export_vectors():
    """Export all vectors from Pinecone to JSON."""
    
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(INDEX_NAME)
    
    print(f"Connecting to Pinecone index: {INDEX_NAME}")
    
    # Get index stats
    stats = index.describe_index_stats()
    total_vectors = stats.total_vector_count
    
    print(f"Total vectors in index: {total_vectors:,}")
    print(f"Exporting to: {OUTPUT_FILE}\n")
    
    os.makedirs("diagnostic", exist_ok=True)
    
    exported_count = 0
    
    # List all vectors with pagination
    with open(OUTPUT_FILE, 'w') as f:
        f.write('[\n')
        
        # list() returns a paginated iterator
        for page_num, batch in enumerate(index.list(limit=100)):
            print(f"Processing batch {page_num + 1}...", end='\r')
            
            for record in batch:
                # record = {"id": "...", "values": [...], "metadata": {...}}
                # metadata might be a method or property — handle both
                # All fields might be callable methods
                record_id = record.id() if callable(record.id) else record.id
                values = record.values() if callable(record.values) else record.values
                
                metadata = {}
                if hasattr(record, 'metadata'):
                    try:
                        metadata = record.metadata() if callable(record.metadata) else record.metadata
                    except:
                        pass
                
                vector_data = {
                    "id": record_id,
                    "values": list(values),  # Convert to list
                    "metadata": metadata
                }
                
                # Write JSON object, comma-separated
                if exported_count > 0:
                    f.write(',\n')
                
                f.write(json.dumps(vector_data))
                exported_count += 1
        
        f.write('\n]')
    
    print(f"\n✅ Export complete!")
    print(f"Total vectors exported: {exported_count:,}")
    print(f"File: {OUTPUT_FILE}")
    print(f"File size: {os.path.getsize(OUTPUT_FILE) / (1024**2):.1f} MB")


if __name__ == "__main__":
    export_vectors()