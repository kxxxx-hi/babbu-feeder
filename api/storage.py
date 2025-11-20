"""
Vercel Blob Storage utility module for managing cat feeder data.
"""
import os
import json
import logging
from typing import Dict, Any, Optional, List

import requests
from dotenv import load_dotenv

load_dotenv()

BLOB_WRITE_TOKEN = os.getenv("VERCEL_BLOB_WRITE_TOKEN") or os.getenv("BLOB_READ_WRITE_TOKEN")
BLOB_BUCKET = os.getenv("VERCEL_BLOB_BUCKET", "babbu-feeder-blob")
BLOB_BASE_URL = os.getenv("VERCEL_BLOB_BASE_URL", "https://blob.vercel-storage.com")
VERCEL_API_BASE_URL = os.getenv("VERCEL_API_BASE_URL", "https://api.vercel.com")
VERCEL_TEAM_ID = os.getenv("VERCEL_TEAM_ID")

# Legacy path prefixes to scan when a canonical blob is missing.
LEGACY_JSON_PREFIXES: Dict[str, str] = {
    "cat_profile/cat_profile.json": "cat_profile",
}

logger = logging.getLogger(__name__)


class BlobStorageManager:
    """Manages Vercel Blob Storage operations for the cat feeder app."""

    def __init__(self):
        if not BLOB_WRITE_TOKEN:
            raise RuntimeError("VERCEL_BLOB_WRITE_TOKEN is not configured")
        self.base_url = BLOB_BASE_URL.rstrip("/")
        self.bucket = BLOB_BUCKET.strip("/")
        self.token = BLOB_WRITE_TOKEN
        self.api_base_url = VERCEL_API_BASE_URL.rstrip("/")
        self.team_id = VERCEL_TEAM_ID

    def _url(self, path: str) -> str:
        normalized = path.lstrip("/")
        return f"{self.base_url}/{self.bucket}/{normalized}"

    def _headers(
        self,
        content_type: Optional[str] = None,
        *,
        disable_suffix: bool = False,
        slug: Optional[str] = None,
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {"Authorization": f"Bearer {self.token}"}
        if content_type:
            headers["Content-Type"] = content_type
        if disable_suffix:
            headers["x-vercel-add-random-suffix"] = "0"
        if slug:
            headers["x-vercel-blob-slug"] = slug.lstrip("/")
        return headers

    def _api_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Authorization": f"Bearer {self.token}"}
        if self.team_id:
            headers["x-vercel-team-id"] = self.team_id
        return headers

    def _api_url(self, path: str) -> str:
        return f"{self.api_base_url}{path}"

    def _list_blobs(self, prefix: str) -> List[Dict[str, Any]]:
        """
        List blobs under a given prefix using the Vercel management API.
        """
        params = {
            "prefix": f"{self.bucket}/{prefix.lstrip('/')}",
            "limit": "100",
        }
        resp = requests.get(self._api_url("/v2/blob/list"), headers=self._api_headers(), params=params)
        resp.raise_for_status()
        payload = resp.json()
        blobs: List[Dict[str, Any]] = payload.get("blobs", [])
        for blob in blobs:
            rel = blob.get("pathname") or blob.get("name")
            if rel and rel.startswith(f"{self.bucket}/"):
                rel = rel[len(self.bucket) + 1 :]
            blob["relative_path"] = rel
        return blobs

    def _maybe_recover_legacy_json(self, path: str) -> Optional[Dict[str, Any]]:
        """
        Attempt to find and migrate legacy blobs that were created before
        deterministic filenames were enforced.
        """
        canonical = path.lstrip("/")
        legacy_prefix = LEGACY_JSON_PREFIXES.get(canonical)
        if not legacy_prefix:
            return None
        try:
            blobs = self._list_blobs(legacy_prefix)
        except Exception as exc:
            logger.debug("Unable to list legacy blobs for %s: %s", path, exc)
            return None

        base_name = os.path.splitext(os.path.basename(canonical))[0]
        candidates = []
        for blob in blobs:
            rel_path = blob.get("relative_path")
            if not rel_path or not rel_path.endswith(".json"):
                continue
            if rel_path == canonical:
                continue
            if not rel_path.startswith(legacy_prefix):
                continue
            if base_name not in rel_path:
                continue
            candidates.append(blob)

        if not candidates:
            return None

        def _sort_key(item: Dict[str, Any]):
            return item.get("uploadedAt") or item.get("createdAt") or ""

        candidates.sort(key=_sort_key, reverse=True)
        chosen = candidates[0]
        rel_path = chosen.get("relative_path")
        if not rel_path:
            return None

        logger.info("Recovering legacy blob %s into %s", rel_path, canonical)
        resp = requests.get(self._url(rel_path), headers=self._headers())
        if resp.status_code != 200 or not resp.content:
            logger.warning("Failed to download legacy blob %s (status %s)", rel_path, resp.status_code)
            return None

        try:
            data = resp.json()
        except ValueError:
            logger.warning("Legacy blob %s did not contain valid JSON", rel_path)
            return None

        try:
            self.write_json(path, data)
        except Exception as exc:
            logger.warning("Failed to rewrite legacy blob %s into %s: %s", rel_path, canonical, exc)
        return data

    def read_json(self, path: str) -> Dict[str, Any]:
        url = self._url(path)
        try:
            resp = requests.get(url, headers=self._headers())
            if resp.status_code == 404:
                recovered = self._maybe_recover_legacy_json(path)
                if recovered is not None:
                    return recovered
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
                headers=self._headers("application/json", disable_suffix=True, slug=path),
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
                headers=self._headers(content_type, disable_suffix=True, slug=path),
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

