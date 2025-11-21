import os
import json
import requests
from typing import Optional, Dict, Any, List

class VercelBlobStorage:
    """Storage manager using Vercel Blob Storage HTTP API"""
    
    def __init__(self):
        self.token = os.getenv("BLOB_READ_WRITE_TOKEN")
        # Vercel Blob API endpoint
        self.base_url = "https://blob.vercel-storage.com"
        
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        if not self.token:
            raise ValueError("BLOB_READ_WRITE_TOKEN environment variable is not set")
        return {
            "Authorization": f"Bearer {self.token}",
        }
    
    def read_json(self, key: str) -> Dict[str, Any]:
        """Read JSON data from Vercel Blob Storage - handles Vercel's blob naming with suffixes"""
        try:
            if not self.token:
                print("Warning: BLOB_READ_WRITE_TOKEN not set, returning empty data")
                return {}
            
            headers = self._get_headers()
            
            # First, try direct GET with exact key
            get_url = f"{self.base_url}/{key}"
            get_response = requests.get(get_url, headers=headers, timeout=10)
            
            if get_response.status_code == 200:
                try:
                    data = get_response.json()
                    # If it's a blob metadata response with a URL, fetch the actual content
                    if isinstance(data, dict) and 'url' in data and 'pathname' not in data:
                        blob_url = data['url']
                        content_response = requests.get(blob_url, timeout=10)
                        if content_response.status_code == 200:
                            return content_response.json()
                    # Otherwise return the JSON directly
                    return data
                except json.JSONDecodeError:
                    return {}
            
            # If direct GET failed, try listing blobs with prefix to find the actual blob name
            # Vercel adds suffixes like "data/cat_1-76udXzISNAw3ujt1sYxLI8g46URz0M"
            if get_response.status_code == 404:
                print(f"Blob {key} not found directly, trying prefix search...")
                # List blobs with the prefix
                blobs = self.list_blobs(prefix=key)
                if blobs:
                    print(f"Found {len(blobs)} blobs with prefix '{key}'")
                else:
                    print(f"No blobs returned for prefix '{key}'")
                    
                # Find exact match or closest match (blob name starting with key)
                matching_blob = None
                for blob in blobs:
                    pathname = blob.get("pathname", "")
                    # Debug
                    print(f"  -> candidate blob pathname: {pathname}")
                    # Check for exact match first
                    if pathname == key:
                        matching_blob = blob
                        print(f"Found exact match: {pathname}")
                        break
                    # Check if pathname starts with key followed by "-" (handles Vercel suffixes)
                    # e.g., "data/cat_1" matches "data/cat_1-76udXzISNAw3ujt1sYxLI8g46URz0M"
                    elif pathname.startswith(key + "-"):
                        matching_blob = blob
                        print(f"Found blob with suffix: {pathname}")
                        break
                    # Also check for directory-style (key + "/")
                    elif pathname.startswith(key + "/"):
                        matching_blob = blob
                        print(f"Found blob in subdirectory: {pathname}")
                        break
                    
                if matching_blob:
                    print(f"Matched blob metadata: {matching_blob}")
                    # Get the URL and fetch content
                    blob_url = matching_blob.get("url")
                    # Some responses include downloadUrl instead of url
                    if not blob_url:
                        blob_url = matching_blob.get("downloadUrl")
                    if blob_url:
                        try:
                            content_response = requests.get(blob_url, timeout=10)
                            if content_response.status_code == 200:
                                try:
                                    data = content_response.json()
                                    print(f"Successfully read JSON from blob {matching_blob.get('pathname')} via public URL")
                                    return data
                                except json.JSONDecodeError as e:
                                    print(f"Error parsing JSON from blob {blob_url}: {e}")
                                    print(f"Response text (first 500 chars): {content_response.text[:500]}")
                                    return {}
                            else:
                                print(f"Failed to fetch blob content from {blob_url}: HTTP {content_response.status_code}")
                                print(f"Response preview: {content_response.text[:200]}")
                        except Exception as fetch_err:
                            print(f"Error fetching blob content from {blob_url}: {fetch_err}")
                    else:
                        print(f"No URL found in blob metadata: {matching_blob}")
                else:
                    print(f"No blob found with prefix '{key}' (searched {len(blobs)} blobs)")
                    if blobs:
                        print(f"Available blobs: {[b.get('pathname') for b in blobs[:5]]}")
            
            # Blob doesn't exist
            return {}
                
        except requests.exceptions.RequestException as e:
            print(f"Network error reading from Vercel Blob: {e}")
            return {}
        except Exception as e:
            print(f"Error reading from Vercel Blob: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def write_json(self, data: Dict[str, Any], key: str):
        """Write JSON data to Vercel Blob Storage"""
        try:
            if not self.token:
                print("Warning: BLOB_READ_WRITE_TOKEN not set, cannot save data")
                return
            
            # Convert data to JSON string
            json_data = json.dumps(data, indent=2)
            
            # Use PUT to upload the blob
            # Format: PUT https://blob.vercel-storage.com/{pathname}
            put_url = f"{self.base_url}/{key}"
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
            
            response = requests.put(put_url, headers=headers, data=json_data.encode('utf-8'), timeout=10)
            
            if response.status_code in [200, 201]:
                result = response.json()
                print(f"Successfully saved {key} to Vercel Blob: {result.get('url', 'N/A')}")
            else:
                print(f"Error saving to Vercel Blob: HTTP {response.status_code}")
                print(f"Response: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"Network error writing to Vercel Blob: {e}")
        except Exception as e:
            print(f"Error writing to Vercel Blob: {e}")
            import traceback
            traceback.print_exc()
    
    def delete_blob(self, key: str) -> bool:
        """Delete a blob from Vercel Blob Storage"""
        try:
            if not self.token:
                print("Warning: BLOB_READ_WRITE_TOKEN not set, cannot delete blob")
                return False
            
            headers = self._get_headers()
            delete_url = f"{self.base_url}/{key}"
            response = requests.delete(delete_url, headers=headers, timeout=10)
            
            if response.status_code in [200, 204]:
                print(f"Successfully deleted blob: {key}")
                return True
            else:
                print(f"Error deleting blob {key}: HTTP {response.status_code}")
                return False
        except Exception as e:
            print(f"Error deleting blob: {e}")
            return False
    
    def list_blobs(self, prefix: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        """List blobs by sending GET requests with prefix parameters"""
        try:
            if not self.token:
                return []
            
            headers = self._get_headers()
            params = {"prefix": prefix, "limit": limit}
            response = requests.get(self.base_url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                blobs = result.get("blobs", [])
                if prefix:
                    print(f"list_blobs('{prefix}') -> {len(blobs)} blobs")
                return blobs
            else:
                print(f"list_blobs error HTTP {response.status_code}: {response.text[:200]}")
            return []
        except Exception as e:
            print(f"Error listing blobs: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def purge_all_data(self):
        """Delete all application data blobs (old root-level and new data/ directory, but keep images)"""
        try:
            if not self.token:
                print("Warning: BLOB_READ_WRITE_TOKEN not set, cannot purge data")
                return 0
            
            # List all blobs
            all_blobs = self.list_blobs()
            
            # Delete data blobs (not images)
            deleted_count = 0
            for blob in all_blobs:
                pathname = blob.get("pathname", "")
                if not pathname:
                    continue
                
                # Keep cat_images directory
                if pathname.startswith("cat_images/"):
                    continue
                
                # Delete old root-level data files (cats, cat_*, foods)
                # and new data/ directory files
                if (pathname.startswith("data/") or 
                    pathname == "cats" or 
                    pathname.startswith("cat_") or 
                    pathname == "foods" or
                    pathname.startswith("foods-") or
                    pathname.startswith("cats-") or
                    (pathname.startswith("cat_") and "-" in pathname)):
                    if self.delete_blob(pathname):
                        deleted_count += 1
                        print(f"Deleted: {pathname}")
            
            print(f"Purged {deleted_count} data blobs")
            return deleted_count
        except Exception as e:
            print(f"Error purging data: {e}")
            import traceback
            traceback.print_exc()
            return 0

# For backward compatibility, use VercelBlobStorage as CloudStorageManager
CloudStorageManager = VercelBlobStorage

