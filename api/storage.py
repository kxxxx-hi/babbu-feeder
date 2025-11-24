import os
import json
from typing import Optional, Dict, Any, List

class GCSStorage:
    """Storage manager using Google Cloud Storage"""
    
    def __init__(self):
        self.bucket_name = os.getenv("GCS_BUCKET_NAME")
        if not self.bucket_name:
            raise ValueError("GCS_BUCKET_NAME environment variable is not set")
        
        # Initialize GCS client
        try:
            from google.cloud import storage
            from google.oauth2 import service_account
            
            # Get service account JSON from environment variable
            service_account_json_str = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
            if not service_account_json_str:
                raise ValueError("GCP_SERVICE_ACCOUNT_JSON environment variable is not set")
            
            # Parse the JSON string
            try:
                service_account_info = json.loads(service_account_json_str)
            except json.JSONDecodeError:
                # If it's already a dict (shouldn't happen but handle it)
                if isinstance(service_account_json_str, dict):
                    service_account_info = service_account_json_str
                else:
                    raise ValueError("GCP_SERVICE_ACCOUNT_JSON is not valid JSON")
            
            # Create credentials from service account info
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info
            )
            
            # Initialize storage client
            self.client = storage.Client(credentials=credentials, project=service_account_info.get("project_id"))
            self.bucket = self.client.bucket(self.bucket_name)
            
            print(f"GCS Storage initialized successfully with bucket: {self.bucket_name}")
        except ImportError:
            raise ImportError("google-cloud-storage library not installed. Install with: pip install google-cloud-storage")
        except Exception as e:
            print(f"Error initializing GCS Storage: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def read_json(self, key: str, force_refresh: bool = False) -> Dict[str, Any]:
        """Read JSON data from Google Cloud Storage
        
        Args:
            key: The blob key/path in GCS
            force_refresh: If True, reloads the blob metadata before reading (helps with eventual consistency)
        """
        try:
            blob = self.bucket.blob(key)
            
            # Force refresh blob metadata to get latest version
            if force_refresh:
                try:
                    blob.reload()
                except:
                    pass  # If reload fails, continue anyway
            
            if not blob.exists():
                print(f"Blob {key} does not exist in GCS")
                return {}
            
            # Download and parse JSON
            content = blob.download_as_text()
            try:
                data = json.loads(content)
                print(f"Successfully read JSON from GCS: {key}")
                return data
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON from GCS blob {key}: {e}")
                return {}
                
        except Exception as e:
            print(f"Error reading from GCS: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def write_json(self, data: Dict[str, Any], key: str) -> bool:
        """Write JSON data to Google Cloud Storage. Returns True if successful, False otherwise."""
        try:
            # Convert data to JSON string
            json_data = json.dumps(data, indent=2)
            
            # Upload to GCS
            blob = self.bucket.blob(key)
            blob.upload_from_string(json_data, content_type='application/json')
            
            print(f"Successfully saved {key} to GCS bucket {self.bucket_name}")
            return True
        except Exception as e:
            print(f"Error writing to GCS: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def delete_blob(self, key: str) -> bool:
        """Delete a blob from Google Cloud Storage"""
        try:
            blob = self.bucket.blob(key)
            if blob.exists():
                blob.delete()
                print(f"Successfully deleted blob from GCS: {key}")
                return True
            else:
                print(f"Blob {key} does not exist in GCS")
                return False
        except Exception as e:
            print(f"Error deleting blob from GCS: {e}")
            return False
    
    def list_blobs(self, prefix: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        """List blobs in GCS with optional prefix"""
        try:
            blobs = self.bucket.list_blobs(prefix=prefix, max_results=limit)
            result = []
            for blob in blobs:
                result.append({
                    "pathname": blob.name,
                    "size": blob.size,
                    "updated": blob.updated.isoformat() if blob.updated else None,
                    "url": blob.public_url if blob.public_url else None
                })
            return result
        except Exception as e:
            print(f"Error listing blobs from GCS: {e}")
            return []
    
    def purge_all_data(self):
        """Delete all application data blobs (but keep images)"""
        try:
            # List all blobs with data/ prefix
            data_blobs = self.bucket.list_blobs(prefix="data/")
            
            deleted_count = 0
            for blob in data_blobs:
                # Keep cat_images directory
                if blob.name.startswith("data/cat_images/"):
                    continue
                
                # Delete data files
                blob.delete()
                deleted_count += 1
                print(f"Deleted: {blob.name}")
            
            # Also check for old root-level files (for migration cleanup)
            old_prefixes = ["cats", "cat_", "foods"]
            for prefix in old_prefixes:
                blobs = self.bucket.list_blobs(prefix=prefix)
                for blob in blobs:
                    if not blob.name.startswith("data/"):
                        blob.delete()
                        deleted_count += 1
                        print(f"Deleted old format: {blob.name}")
            
            print(f"Purged {deleted_count} data blobs from GCS")
            return deleted_count
        except Exception as e:
            print(f"Error purging data from GCS: {e}")
            import traceback
            traceback.print_exc()
            return 0

# Use GCSStorage as CloudStorageManager
CloudStorageManager = GCSStorage
