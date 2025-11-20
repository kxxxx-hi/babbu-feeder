# Grant Service Account Access to Bucket

The service account needs permission to access the bucket. Here's how to grant it:

## Quick Steps

1. **Go to the bucket in Google Cloud Console:**
   https://console.cloud.google.com/storage/browser/babbu-feeder-bucket?project=babbu-feeder

2. **Click on the bucket name** (`babbu-feeder-bucket`)

3. **Click on the "Permissions" tab** (at the top)

4. **Click "Grant Access"** button

5. **In the "New principals" field, enter:**
   ```
   babbu-feeder-service-account@babbu-feeder.iam.gserviceaccount.com
   ```

6. **Select the role:**
   - **Storage Object Admin** (recommended - can read/write objects)
   - OR **Storage Admin** (full access to bucket and objects)

7. **Click "Save"**

## Alternative: Grant at Project Level

If you want to grant permissions at the project level (affects all buckets):

1. Go to: https://console.cloud.google.com/iam-admin/iam?project=babbu-feeder

2. Find: `babbu-feeder-service-account@babbu-feeder.iam.gserviceaccount.com`

3. Click the edit icon (pencil) next to it

4. Click "Add Another Role"

5. Select: **Storage Object Admin** or **Storage Admin**

6. Click "Save"

## Test After Granting Permissions

After granting permissions, run:

```bash
python3 test_gcs_connection.py
```

You should see:
```
✅ SUCCESS: Bucket 'babbu-feeder-bucket' exists and is accessible!
```

