"""
Google Cloud Storage utility module for managing cat feeder data in buckets.
"""
import os
import json
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from google.cloud import storage
from google.cloud.exceptions import NotFound
import logging

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class CloudStorageManager:
    """Manages Google Cloud Storage operations for the cat feeder app."""
    
    def __init__(self, bucket_name: Optional[str] = None):
        """
        Initialize the Cloud Storage Manager.
        
        Args:
            bucket_name: Name of the GCS bucket. If None, reads from env var GCS_BUCKET_NAME.
        """
        # Get bucket name from environment variable or parameter
        self.bucket_name = bucket_name or os.getenv("GCS_BUCKET_NAME", "babbu-feeder-data")
        
        # Initialize the storage client
        # If GOOGLE_APPLICATION_CREDENTIALS is set, it will use that service account
        # Otherwise, it will use default credentials
        try:
            self.client = storage.Client()
            self.bucket = self.client.bucket(self.bucket_name)
        except Exception as e:
            logger.error(f"Failed to initialize Google Cloud Storage client: {e}")
            raise
    
    def _get_file_path(self, data_type: str, filename: Optional[str] = None) -> str:
        """
        Generate file path in bucket based on data type.
        
        Args:
            data_type: Type of data ('logs', 'foods', 'cat_profile')
            filename: Optional filename. If None, uses default for data type.
        
        Returns:
            Full path in bucket
        """
        if filename:
            return f"{data_type}/{filename}"
        
        # Default filenames
        defaults = {
            "logs": "logs.json",
            "foods": "foods.json",
            "cat_profile": "cat_profile.json"
        }
        return f"{data_type}/{defaults.get(data_type, 'data.json')}"
    
    def read_json(self, data_type: str, filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Read JSON data from bucket.
        
        Args:
            data_type: Type of data ('logs', 'foods', 'cat_profile')
            filename: Optional filename
        
        Returns:
            Dictionary containing the JSON data, or empty dict if file doesn't exist
        """
        file_path = self._get_file_path(data_type, filename)
        
        try:
            blob = self.bucket.blob(file_path)
            if not blob.exists():
                logger.info(f"File {file_path} does not exist, returning empty data")
                return {}
            
            content = blob.download_as_text()
            return json.loads(content)
        except NotFound:
            logger.info(f"File {file_path} not found in bucket")
            return {}
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            raise
    
    def write_json(self, data: Dict[str, Any], data_type: str, filename: Optional[str] = None) -> bool:
        """
        Write JSON data to bucket.
        
        Args:
            data: Dictionary to write as JSON
            data_type: Type of data ('logs', 'foods', 'cat_profile')
            filename: Optional filename
        
        Returns:
            True if successful
        """
        file_path = self._get_file_path(data_type, filename)
        
        try:
            blob = self.bucket.blob(file_path)
            json_content = json.dumps(data, indent=2, ensure_ascii=False)
            blob.upload_from_string(json_content, content_type='application/json')
            logger.info(f"Successfully wrote data to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error writing {file_path}: {e}")
            raise
    
    def delete_file(self, data_type: str, filename: Optional[str] = None) -> bool:
        """
        Delete a file from bucket.
        
        Args:
            data_type: Type of data ('logs', 'foods', 'cat_profile')
            filename: Optional filename
        
        Returns:
            True if successful
        """
        file_path = self._get_file_path(data_type, filename)
        
        try:
            blob = self.bucket.blob(file_path)
            if blob.exists():
                blob.delete()
                logger.info(f"Successfully deleted {file_path}")
                return True
            else:
                logger.info(f"File {file_path} does not exist")
                return False
        except Exception as e:
            logger.error(f"Error deleting {file_path}: {e}")
            raise

