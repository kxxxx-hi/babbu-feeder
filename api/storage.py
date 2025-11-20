"""
Vercel Blob Storage utility module for managing cat feeder data.
"""
import os
import json
import logging
from typing import Dict, Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

BLOB_WRITE_TOKEN = os.getenv("VERCEL_BLOB_WRITE_TOKEN")
BLOB_BUCKET = os.getenv("VERCEL_BLOB_BUCKET", "babbu-feeder-blob")
BLOB_BASE_URL = os.getenv("VERCEL_BLOB_BASE_URL", "https://blob.vercel-storage.com")

logger = logging.getLogger(__name__)


class BlobStorageManager:
    """Manages Vercel Blob Storage operations for the cat feeder app."""

    def __init__(self):
        if not BLOB_WRITE_TOKEN:
            raise RuntimeError("VERCEL_BLOB_WRITE_TOKEN is not configured")
        self.base_url = BLOB_BASE_URL.rstrip("/")
        self.bucket = BLOB_BUCKET.strip("/")
        self.token = BLOB_WRITE_TOKEN

    def _url(self, path: str) -> str:
        normalized = path.lstrip("/")
        return f"{self.base_url}/{self.bucket}/{normalized}"

    def _headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def read_json(self, path: str) -> Dict[str, Any]:
        url = self._url(path)
        try:
            resp = requests.get(url, headers=self._headers())
            if resp.status_code == 404:
                logger.info("Blob %s not found, returning empty data", path)
                return {}
            resp.raise_for_status()
            if not resp.content:
                return {}
            return resp.json()
        except Exception as exc:
            logger.error("Error reading blob %s: %s", path, exc)
            raise

    def write_json(self, path: str, data: Dict[str, Any], access: str = "private") -> None:
        url = self._url(path)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            resp = requests.put(
                url,
                params={"access": access},
                headers=self._headers("application/json"),
                data=payload,
            )
            resp.raise_for_status()
            logger.info("Successfully wrote blob %s", path)
        except Exception as exc:
            logger.error("Error writing blob %s: %s", path, exc)
            raise

    def delete(self, path: str) -> None:
        url = self._url(path)
        try:
            resp = requests.delete(url, headers=self._headers())
            if resp.status_code in (200, 204, 404):
                logger.info("Deleted blob %s (status %s)", path, resp.status_code)
                return
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Error deleting blob %s: %s", path, exc)
            raise

    def upload_image(self, image_data: bytes, filename: str, content_type: str = "image/jpeg") -> str:
        path = f"images/{filename}"
        url = self._url(path)
        try:
            resp = requests.put(
                url,
                params={"access": "public"},
                headers=self._headers(content_type),
                data=image_data,
            )
            resp.raise_for_status()
            logger.info("Uploaded image blob %s", path)
            return url
        except Exception as exc:
            logger.error("Error uploading image %s: %s", path, exc)
            raise

    def get_image_url(self, filename: str) -> Optional[str]:
        return self._url(f"images/{filename}")

