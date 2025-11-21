import os
import json
import requests
from typing import Optional, Dict, Any

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
        """Read JSON data from Vercel Blob Storage"""
        try:
            if not self.token:
                print("Warning: BLOB_READ_WRITE_TOKEN not set, returning empty data")
                return {}
            
            headers = self._get_headers()
            
            # First, try to list blobs with the prefix to find the exact match
            list_url = f"{self.base_url}/list"
            params = {"prefix": key}
            
            try:
                list_response = requests.get(list_url, headers=headers, params=params, timeout=10)
                
                if list_response.status_code == 200:
                    result = list_response.json()
                    blobs = result.get("blobs", [])
                    print(f"Found {len(blobs)} blobs with prefix '{key}'")
                    
                    # Find exact match first
                    matching_blob = None
                    for blob in blobs:
                        pathname = blob.get("pathname", "")
                        if pathname == key:
                            matching_blob = blob
                            print(f"Found exact match: {pathname}")
                            break
                    
                    # If no exact match, try prefix match
                    if not matching_blob and blobs:
                        matching_blob = blobs[0]
                        print(f"Using first blob with prefix: {matching_blob.get('pathname')}")
                    
                    if matching_blob:
                        # Get the URL and fetch content
                        blob_url = matching_blob.get("url")
                        if blob_url:
                            print(f"Fetching content from: {blob_url}")
                            # Public URLs don't need auth, but try with auth header just in case
                            content_response = requests.get(blob_url, timeout=10)
                            if content_response.status_code == 200:
                                try:
                                    data = content_response.json()
                                    print(f"Successfully read JSON from blob")
                                    return data
                                except json.JSONDecodeError as e:
                                    print(f"Error: Response from {blob_url} is not valid JSON: {e}")
                                    print(f"Response text (first 200 chars): {content_response.text[:200]}")
                                    return {}
                            else:
                                print(f"Error fetching blob content: HTTP {content_response.status_code}")
                else:
                    print(f"List API returned HTTP {list_response.status_code}: {list_response.text}")
            except Exception as e:
                print(f"Error in list operation: {e}")
            
            # If listing didn't work, try direct GET with the key as pathname
            print(f"Trying direct GET for key: {key}")
            get_url = f"{self.base_url}/{key}"
            get_response = requests.get(get_url, headers=headers, timeout=10)
            
            if get_response.status_code == 200:
                try:
                    # Check if response is JSON or if it's a redirect to the actual blob URL
                    content_type = get_response.headers.get('content-type', '')
                    if 'application/json' in content_type:
                        data = get_response.json()
                        print(f"Successfully read JSON via direct GET")
                        return data
                    else:
                        # Might be a redirect or the actual content
                        try:
                            data = get_response.json()
                            return data
                        except:
                            # If not JSON, might be the blob URL in the response
                            result = get_response.json() if get_response.text else {}
                            if 'url' in result:
                                # Follow the URL
                                blob_url = result['url']
                                content_response = requests.get(blob_url, timeout=10)
                                if content_response.status_code == 200:
                                    return content_response.json()
                            return {}
                except json.JSONDecodeError as e:
                    print(f"Error: Response from {get_url} is not valid JSON: {e}")
                    print(f"Response text (first 200 chars): {get_response.text[:200]}")
                    return {}
            elif get_response.status_code == 404:
                # Blob doesn't exist yet, return empty dict
                print(f"Blob {key} not found (404), returning empty data")
                return {}
            else:
                print(f"Error reading blob {key}: HTTP {get_response.status_code}")
                print(f"Response: {get_response.text[:200]}")
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

# For backward compatibility, use VercelBlobStorage as CloudStorageManager
CloudStorageManager = VercelBlobStorage

