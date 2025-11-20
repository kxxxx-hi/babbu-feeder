# Google Cloud Storage Setup - Status

## ✅ Completed Steps

1. **Service Account Key Saved**
   - File: `service-account-key.json`
   - Service Account: `babbu-feeder-service-account@babbu-feeder.iam.gserviceaccount.com`
   - Project: `babbu-feeder`

2. **Environment Variables Configured**
   - File: `.env`
   - Bucket Name: `babbu-feeder-data`
   - Credentials Path: Set correctly

3. **Dependencies Installed**
   - `google-cloud-storage` ✅
   - `python-dotenv` ✅

4. **Connection Tested**
   - ✅ Successfully connected to Google Cloud
   - ✅ Service account credentials are valid
   - ⚠️  Bucket needs to be created (or permissions granted)

## 🔧 Next Steps

### Option 1: Create Bucket Manually (Recommended)

1. Go to [Google Cloud Console - Storage](https://console.cloud.google.com/storage/browser?project=babbu-feeder)
2. Click **"Create Bucket"**
3. Enter bucket name: `babbu-feeder-data`
4. Choose location (e.g., `us-central1`)
5. Choose storage class (e.g., `Standard`)
6. Click **"Create"**

### Option 2: Grant Bucket Creation Permission

If you want the service account to create buckets automatically:

1. Go to [IAM & Admin](https://console.cloud.google.com/iam-admin/iam?project=babbu-feeder)
2. Find the service account: `babbu-feeder-service-account@babbu-feeder.iam.gserviceaccount.com`
3. Click the edit icon (pencil)
4. Add role: **Storage Admin** (if not already added)
5. Save

Then run the test script again:
```bash
python3 test_gcs_connection.py
```

## 🧪 Test the Setup

After creating the bucket, test the connection:

```bash
python3 test_gcs_connection.py
```

You should see:
```
✅ SUCCESS: Bucket 'babbu-feeder-data' exists and is accessible!
```

## 🚀 Run the Application

Once the bucket is created, you can run the Flask app:

```bash
# Install all dependencies
pip install -r requirements.txt

# Run the app
flask --app api.index run --debug
```

Or if using uvicorn:
```bash
uvicorn api.index:app --reload --port 8000
```

Visit `http://localhost:5000` (or your port) to use the app!

## 📁 Data Structure

Once you start using the app, data will be stored in the bucket as:

```
babbu-feeder-data/
├── logs/
│   └── logs.json          # Weight logs
├── foods/
│   └── foods.json         # Food items
└── cat_profile/
    └── cat_profile.json   # Cat profile and diet plan
```

## 🔒 Security Notes

- ✅ `service-account-key.json` is in `.gitignore` (won't be committed)
- ✅ `.env` is in `.gitignore` (won't be committed)
- ⚠️  **Never commit these files to git!**
- ⚠️  Keep the service account key secure

## 🐛 Troubleshooting

### "Bucket does not exist"
- Create the bucket manually in Google Cloud Console
- Or grant Storage Admin role to the service account

### "Permission denied"
- Ensure the service account has **Storage Admin** or **Storage Object Admin** role
- Check IAM permissions in Google Cloud Console

### "Invalid credentials"
- Verify `GOOGLE_APPLICATION_CREDENTIALS` path in `.env` is correct
- Check that `service-account-key.json` file exists and is valid JSON

