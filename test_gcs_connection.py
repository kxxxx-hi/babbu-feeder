#!/usr/bin/env python3
"""Test Google Cloud Storage connection and bucket setup."""
import os
from dotenv import load_dotenv
from google.cloud import storage

# Load environment variables
load_dotenv()

try:
    client = storage.Client()
    bucket_name = os.getenv('GCS_BUCKET_NAME', 'babbu-feeder-data')
    print(f"Attempting to access bucket: {bucket_name}")
    print(f"Project ID: {client.project}")
    
    bucket = client.bucket(bucket_name)
    
    # Check if bucket exists
    if bucket.exists():
        print(f"✅ SUCCESS: Bucket '{bucket_name}' exists and is accessible!")
        print(f"   Location: {bucket.location}")
        print(f"   Storage class: {bucket.storage_class}")
    else:
        print(f"⚠️  Bucket '{bucket_name}' does not exist yet.")
        print(f"   Creating bucket...")
        try:
            bucket.create(location='us-central1')  # You can change location
            print(f"✅ Bucket '{bucket_name}' created successfully!")
        except Exception as create_error:
            print(f"❌ Failed to create bucket: {create_error}")
            print(f"   Please create it manually in Google Cloud Console:")
            print(f"   https://console.cloud.google.com/storage/browser")
            
except Exception as e:
    print(f"❌ Error connecting to Google Cloud Storage:")
    print(f"   {type(e).__name__}: {e}")
    print(f"\nTroubleshooting:")
    print(f"   1. Check that GOOGLE_APPLICATION_CREDENTIALS is set correctly")
    print(f"   2. Verify the service account has Storage Admin permissions")
    print(f"   3. Ensure the bucket name is correct")

