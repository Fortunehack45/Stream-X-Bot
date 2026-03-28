# 🚀 StreamX Harvester — Cloud Deployment Guide

To ensure 24/7 autonomous operation without relying on your local machine, follow these steps to deploy the harvester to the cloud (Railway or Render).

## 1. Sync Code to GitHub
Ensure the latest code from `C:\Users\ALEX\Desktop\StreamX Bot` is pushed to your repository:
```bash
git add .
git commit -m "feat: cloud-ready stable release"
git push origin main
```

## 2. Recommended Platform: [Railway](https://railway.app/)
Railway is the easiest platform for Python background workers.

1. **Login**: Connect your GitHub account to Railway.
2. **New Project**: Select "Deploy from GitHub repo" and choose `Stream-X-Bot`.
3. **Variables**: Add the following Environment Variables (copy from your `.env`):
   - `TMDB_API_KEY`: `[Your Key]`
   - `DB_HOST`: `aws-1-eu-west-2.pooler.supabase.com`
   - `DB_PORT`: `5432`
   - `DB_NAME`: `postgres`
   - `DB_USER`: `postgres.[project-ref]`
   - `DB_PASSWORD`: `[Your Password]`
   - `SCRAPE_INTERVAL_HOURS`: `3`
4. **Deploy**: Railway will automatically detect the `Procfile` and start the `worker` process.

## 3. Alternative: [Render](https://render.com/)
Render allows you to host this as a **Web Service** (ideal for the free tier).

1. **New**: Create a "Web Service".
2. **Repository**: Select `Stream-X-Bot`.
3. **Runtime**: Select `Python`.
4. **Build Command**: `pip install -r requirements.txt`.
5. **Start Command**: `python harvester/main.py`.
6. **Variables**: Add the same environment variables as listed above.
   - *Note: Render will automatically provide the `PORT` variable, and the bot will bind to it for health checks.*

## 🏁 Verification
Once deployed, check the "Logs" tab on Railway/Render. You should see:
- `Health-check server listening on port [PORT] (Render mode active).`
- `Bootstrapping database schema…`
- `Schema is ready.`
- `Bot ready. Target: ... | Schedule: every 3 hour(s).`

The bot is now 100% autonomous and cloud-synced!
