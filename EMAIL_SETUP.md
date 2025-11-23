# Daily Email Setup Guide

This guide will help you set up the daily email pipeline to receive your cat's diet plan every morning at 7am.

## Prerequisites

1. A SendGrid account (free tier available: https://sendgrid.com)
2. Access to your Vercel project environment variables

## Step 1: Set up SendGrid

1. Sign up for a free SendGrid account at https://sendgrid.com
2. Verify your sender email address (or domain) in SendGrid
3. Create an API Key:
   - Go to Settings > API Keys
   - Click "Create API Key"
   - Give it a name (e.g., "Babbu Feeder Daily Email")
   - Select "Full Access" or "Mail Send" permissions
   - Copy the API key (you'll only see it once!)

## Step 2: Configure Vercel Environment Variables

Go to your Vercel project settings and add these environment variables:

### Required Variables:

1. **SENDGRID_API_KEY**
   - Value: Your SendGrid API key from Step 1
   - Example: `SG.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

2. **SENDGRID_FROM_EMAIL**
   - Value: The verified sender email address in SendGrid
   - Example: `noreply@yourdomain.com` or `your-email@gmail.com`
   - Note: Must be verified in SendGrid

3. **DAILY_EMAIL_RECIPIENT**
   - Value: Your email address where you want to receive the daily diet plan
   - Example: `your-email@gmail.com`

### Optional Variables:

4. **DAILY_EMAIL_CAT_ID** (optional)
   - Value: The cat ID to send diet plan for (defaults to 1 if not set)
   - Example: `1` (for Youtiao)

5. **CRON_SECRET** (optional, recommended)
   - Value: A secret token to protect the endpoint from unauthorized access
   - Example: `your-random-secret-token-here`
   - Generate a random string for security

## Step 3: Deploy to Vercel

After adding the environment variables, redeploy your application:

```bash
git push origin main
```

Or trigger a redeploy from the Vercel dashboard.

## Step 4: Verify the Setup

1. **Test the endpoint manually:**
   - Visit: `https://your-app.vercel.app/api/send-daily-email`
   - Or use curl:
     ```bash
     curl https://your-app.vercel.app/api/send-daily-email
     ```
   - You should receive an email within a few minutes

2. **Check Vercel Cron Jobs:**
   - Go to your Vercel project dashboard
   - Navigate to Settings > Cron Jobs
   - You should see a cron job scheduled for "0 7 * * *" (7am daily)

## How It Works

- **Vercel Cron Jobs** automatically calls `/api/send-daily-email` every day at 7am (UTC)
- The endpoint generates a formatted HTML email with:
  - Cat's name and daily target calories
  - Life stage information
  - Per-meal feeding plan with food types and grams
  - Organized by meal number
- The email is sent via SendGrid to your specified recipient

## Troubleshooting

### Email not received?
1. Check Vercel function logs for errors
2. Verify SendGrid API key is correct
3. Check that sender email is verified in SendGrid
4. Check spam/junk folder
5. Verify `DAILY_EMAIL_RECIPIENT` is set correctly

### Cron job not running?
1. Check Vercel Cron Jobs dashboard
2. Verify `vercel.json` has the cron configuration
3. Check Vercel function logs at 7am UTC

### Want to change the time?
Edit `vercel.json` and change the cron schedule:
- `"0 7 * * *"` = 7am UTC daily
- `"0 11 * * *"` = 11am UTC daily (7am EST)
- Use https://crontab.guru/ to create custom schedules

## Manual Testing

You can manually trigger the email by visiting:
```
https://your-app.vercel.app/api/send-daily-email
```

Or with authentication (if CRON_SECRET is set):
```
https://your-app.vercel.app/api/send-daily-email?token=Bearer YOUR_SECRET
```

