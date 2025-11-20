# Google Cloud Storage Setup for Babbu Feeder

## Step 1: Create Google Cloud Storage Bucket

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to **Storage** > **Buckets**
3. Click **Create Bucket**
4. Enter a unique bucket name (e.g., `babbu-feeder-data`)
5. Choose location and storage class
6. Click **Create**

## Step 2: Create Service Account

1. Go to **IAM & Admin** > **Service Accounts**
2. Click **Create Service Account**
3. Name it (e.g., `babbu-feeder-service`)
4. Grant role: **Storage Admin** (or **Storage Object Admin** for more restricted access)
5. Click **Done**

## Step 3: Generate Service Account Key

1. Click on the created service account
2. Go to **Keys** tab
3. Click **Add Key** > **Create new key**
4. Select **JSON** format
5. Download the key file (e.g., `babbu-feeder-key.json`)
6. **IMPORTANT**: Store this file securely and never commit it to git

## Step 4: Configure Environment Variables

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env`:
   ```env
   GCS_BUCKET_NAME=your-bucket-name-here
   GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/babbu-feeder-key.json
   ```

   **For local development**, use absolute path:
   ```env
   GOOGLE_APPLICATION_CREDENTIALS=/Users/yourname/path/to/babbu-feeder-key.json
   ```

   **For Google Cloud deployment** (Cloud Run, App Engine), you can leave `GOOGLE_APPLICATION_CREDENTIALS` unset to use default credentials.

## Step 5: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 6: Test the Setup

Start the server:
```bash
# For local development
flask --app api.index run --debug

# Or with uvicorn if using ASGI
uvicorn api.index:app --reload --port 8000
```

Visit `http://localhost:5000` (or your port) and test:
- Adding a cat profile
- Adding weight logs
- Adding foods
- Setting up a diet plan

## Data Structure in Bucket

After using the app, your bucket will have this structure:

```
your-bucket-name/
├── logs/
│   └── logs.json          # Weight logs (dt, weight_kg)
├── foods/
│   └── foods.json         # Food items (id, name, unit, kcal_per_unit, grams_per_cup)
└── cat_profile/
    └── cat_profile.json   # Cat profile (name, anchor_date, anchor_age_weeks, meals_per_day, life_stage_override, diet)
```

## Migration from SQLite

If you have existing SQLite data, you can migrate it by:
1. Exporting data from SQLite
2. Converting to JSON format
3. Uploading to GCS using the storage manager

## Troubleshooting

### Error: "Google Cloud Storage not configured"

**Solution**: 
- Check that `.env` file exists and has correct values
- Verify `GCS_BUCKET_NAME` is set
- Ensure `GOOGLE_APPLICATION_CREDENTIALS` points to a valid JSON file

### Error: "Failed to initialize Google Cloud Storage client"

**Solution**:
- Verify the service account key file is valid
- Check that the service account has the correct permissions
- Ensure the bucket name is correct

### Error: "Bucket not found"

**Solution**:
- Verify `GCS_BUCKET_NAME` matches your bucket name exactly
- Check that the bucket exists in your Google Cloud project
- Ensure the service account has access to the bucket

## Security Best Practices

1. ✅ Never commit `.env` or service account keys to git
2. ✅ Use environment variables for sensitive data
3. ✅ Rotate service account keys regularly
4. ✅ Use least privilege principle (Storage Object Admin instead of Storage Admin if possible)
5. ✅ Enable bucket versioning for data recovery
6. ✅ Use Google Cloud Secret Manager for production deployments

