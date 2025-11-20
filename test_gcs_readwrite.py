#!/usr/bin/env python3
"""Test Google Cloud Storage read/write operations."""
import os
import json
from dotenv import load_dotenv
from google.cloud import storage

# Load environment variables
load_dotenv()

try:
    client = storage.Client()
    bucket_name = os.getenv('GCS_BUCKET_NAME', 'babbu-feeder-bucket')
    bucket = client.bucket(bucket_name)
    
    print(f"Testing read/write operations on bucket: {bucket_name}\n")
    
    # Test 1: Write a test file
    print("1. Testing write operation...")
    test_data = {
        "test": True,
        "message": "This is a test file",
        "timestamp": "2024-01-01T00:00:00Z"
    }
    blob = bucket.blob("test/test.json")
    blob.upload_from_string(json.dumps(test_data, indent=2), content_type='application/json')
    print("   ✅ Successfully wrote test file")
    
    # Test 2: Read the test file
    print("2. Testing read operation...")
    content = blob.download_as_text()
    read_data = json.loads(content)
    print(f"   ✅ Successfully read test file: {read_data['message']}")
    
    # Test 3: Test the storage structure (logs, foods, cat_profile)
    print("3. Testing storage structure...")
    
    # Initialize empty data structures
    logs_data = {"weights": []}
    foods_data = {"foods": []}
    profile_data = {"profile": {}}
    
    # Write logs
    logs_blob = bucket.blob("logs/logs.json")
    logs_blob.upload_from_string(json.dumps(logs_data, indent=2), content_type='application/json')
    print("   ✅ Created logs/logs.json")
    
    # Write foods
    foods_blob = bucket.blob("foods/foods.json")
    foods_blob.upload_from_string(json.dumps(foods_data, indent=2), content_type='application/json')
    print("   ✅ Created foods/foods.json")
    
    # Write profile
    profile_blob = bucket.blob("cat_profile/cat_profile.json")
    profile_blob.upload_from_string(json.dumps(profile_data, indent=2), content_type='application/json')
    print("   ✅ Created cat_profile/cat_profile.json")
    
    # Test 4: Read back the data
    print("4. Testing read back...")
    logs_content = logs_blob.download_as_text()
    logs_read = json.loads(logs_content)
    print(f"   ✅ Successfully read logs: {len(logs_read.get('weights', []))} entries")
    
    # Clean up test file
    print("\n5. Cleaning up test file...")
    test_blob = bucket.blob("test/test.json")
    if test_blob.exists():
        test_blob.delete()
        print("   ✅ Test file deleted")
    
    print("\n" + "="*50)
    print("✅ ALL TESTS PASSED!")
    print("="*50)
    print("\nYour bucket is ready to use with the babbu-feeder app!")
    print(f"Bucket: {bucket_name}")
    print("Data structure initialized:")
    print("  - logs/logs.json")
    print("  - foods/foods.json")
    print("  - cat_profile/cat_profile.json")
    
except Exception as e:
    print(f"❌ Error during read/write test:")
    print(f"   {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

