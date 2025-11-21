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
        """Read JSON data from Vercel Blob Storage - simplified direct approach"""
        try:
            if not self.token:
                print("Warning: BLOB_READ_WRITE_TOKEN not set, returning empty data")
                return {}
            
            headers = self._get_headers()
            
            # Try direct GET first - this is the most reliable method
            get_url = f"{self.base_url}/{key}"
            get_response = requests.get(get_url, headers=headers, timeout=10)
            
            if get_response.status_code == 200:
                try:
                    # Check if response contains JSON directly or a URL
                    content_type = get_response.headers.get('content-type', '')
                    
                    # Try to parse as JSON
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
                        # If not JSON, might be text content
                        return {}
                except Exception as e:
                    print(f"Error parsing response: {e}")
                    return {}
            elif get_response.status_code == 404:
                # Blob doesn't exist yet, return empty dict
                return {}
            else:
                print(f"Error reading blob {key}: HTTP {get_response.status_code}")
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
    
    def list_blobs(self, prefix: str = "") -> List[Dict[str, Any]]:
        """List all blobs with optional prefix"""
        try:
            if not self.token:
                return []
            
            headers = self._get_headers()
            list_url = f"{self.base_url}/list"
            params = {"prefix": prefix} if prefix else {}
            response = requests.get(list_url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                return result.get("blobs", [])
            return []
        except Exception as e:
            print(f"Error listing blobs: {e}")
            return []
    
    def purge_all_data(self):
        """Delete all application data blobs (cats, cat data, foods, but keep images)"""
        try:
            if not self.token:
                print("Warning: BLOB_READ_WRITE_TOKEN not set, cannot purge data")
                return
            
            # List all blobs
            all_blobs = self.list_blobs()
            
            # Delete data blobs (not images)
            deleted_count = 0
            for blob in all_blobs:
                pathname = blob.get("pathname", "")
                # Delete data files but keep cat_images
                if pathname and not pathname.startswith("cat_images/"):
                    if self.delete_blob(pathname):
                        deleted_count += 1
            
            print(f"Purged {deleted_count} data blobs")
            return deleted_count
        except Exception as e:
            print(f"Error purging data: {e}")
            import traceback
            traceback.print_exc()
            return 0

# For backward compatibility, use VercelBlobStorage as CloudStorageManager
CloudStorageManager = VercelBlobStorage

