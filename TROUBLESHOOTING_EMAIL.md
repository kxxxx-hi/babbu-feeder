# Email Troubleshooting Guide

## Quick Checks

### 1. Check Cron Status
Visit: `https://babbu-feeder.vercel.app/api/cron-status`

This will show:
- Environment variables status
- Recipient emails
- Cat ID
- Configuration status

### 2. Check Vercel Cron Job Logs
1. Go to Vercel Dashboard → Your Project
2. Click "Functions" tab
3. Click "Cron Jobs" section
4. Find `/api/send-daily-email`
5. Check execution logs for the time it should have run

### 3. Test Email Manually
Visit: `https://babbu-feeder.vercel.app/api/test-email?to=y.kexin@icloud.com&cat_id=1`

This will send a test email immediately to verify:
- SendGrid API key is working
- Email configuration is correct
- Email can be delivered

### 4. Check Environment Variables in Vercel
Go to Vercel Dashboard → Settings → Environment Variables

Required variables:
- `SENDGRID_API_KEY` - Your SendGrid API key
- `SENDGRID_FROM_EMAIL` - Verified sender email in SendGrid
- `DAILY_EMAIL_RECIPIENT` - Comma-separated recipient emails
- `DAILY_EMAIL_CAT_ID` - Cat ID (default: 1)

### 5. Verify Cron Schedule
Current schedule in `vercel.json`:
- `"0 23 * * *"` = 11 PM UTC = 7 AM Singapore Time (UTC+8)

To change the schedule:
1. Edit `vercel.json`
2. Update the `schedule` field in cron configuration
3. Push to GitHub
4. Vercel will automatically update the cron job

### 6. Check SendGrid Activity
1. Log into SendGrid dashboard
2. Go to "Activity" section
3. Check if emails were attempted to be sent
4. Look for any errors or bounces

### 7. Common Issues

**Issue: Cron job not running**
- Check Vercel cron job limit (free tier: 2 cron jobs max)
- Verify the schedule syntax is correct
- Check if deployment succeeded

**Issue: Email sent but not received**
- Check spam/junk folder
- Verify recipient email is correct
- Check SendGrid activity logs
- Verify sender email is verified in SendGrid

**Issue: "No diet plan found" error**
- Make sure a diet plan is saved for the cat
- Check `DAILY_EMAIL_CAT_ID` matches the cat with a diet plan

**Issue: Environment variables not set**
- Variables must be set in Vercel dashboard
- Redeploy after adding environment variables
- Check `/api/cron-status` to verify variables are loaded

### 8. Manual Trigger (for testing)
You can manually trigger the cron endpoint:
```
curl -X POST https://babbu-feeder.vercel.app/api/send-daily-email \
  -H "Authorization: Bearer YOUR_CRON_SECRET" \
  -H "x-vercel-cron: 1"
```

Or if `CRON_SECRET` is not set, Vercel cron jobs will automatically include the `x-vercel-cron: 1` header.

