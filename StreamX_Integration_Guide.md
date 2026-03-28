# 🚀 StreamX: End-to-End Integration Guide

This guide explains how to connect your **Autonomous Python Harvester Bot** to your **Vercel-hosted React Front-End**. 

To connect them, we use a modern 3-tier architecture:
`Python Harvester` ➔ `Cloud PostgreSQL Database (Supabase)` ➔ `React Front-End (Vercel)`

---

## Phase 1: Set Up the Cloud Database (Supabase)
Since your website runs in the cloud (Vercel), your database must also be in the cloud. We strongly recommend **[Supabase](https://supabase.com)** because it is free, provides a PostgreSQL database, and instantly generates a data API for your React app.

1. Go to [Supabase](https://supabase.com) and create a free account.
2. Click **New Project** and name it `stream-x-db`. Wait 2 minutes for the database to provision.
3. Once created, go to **Settings** > **Database** in the sidebar.
4. Scroll down to **Connection String** -> **URI**.
5. Copy the URI. It will look something like this:
   `postgresql://postgres.[YOUR-PROJECT-REF]:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:6543/postgres`

---

## Phase 2: Connect the Python Harvester
The harvester needs to know where to save the deep metadata it extracts from TMDB.

1. Open your StreamX Bot project folder.
2. Open `harvester/.env` and replace the local Database URL with your new Supabase Connection String.
   ```env
   # Inside harvester/.env
   DATABASE_URL="postgresql://postgres.[YOUR-PROJECT-REF]:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
   ```
3. Run the bot once to bootstrap the tables and populate the database!
   ```bash
   cd harvester
   python main.py
   ```
   *Note: Because we programmed `database.py` to be fully autonomous, it will log into Supabase, automatically create the `movies` table with all the correct Array columns, and safely push all extracted movies into the cloud!*

---

## Phase 3: Connect the React Front-End
Now, your cloud database is filling up with thousands of highly-enriched movie entries. It's time to display them on your Vercel site.

1. In Supabase, go to **Settings** > **API**. Copy the **Project URL** and the **anon `public` API Key**.
2. Open your React/Next.js front-end repository.
3. Add these to your front-end `.env.local` file:
   ```env
   NEXT_PUBLIC_SUPABASE_URL="https://[YOUR-PROJECT-REF].supabase.co"
   NEXT_PUBLIC_SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5..."
   ```
4. Install the Supabase Javascript client:
   ```bash
   npm install @supabase/supabase-js
   ```
5. Create a file called `lib/supabaseClient.js` (or `.ts`):
   ```javascript
   import { createClient } from '@supabase/supabase-js'

   const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
   const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

   export const supabase = createClient(supabaseUrl, supabaseAnonKey)
   ```

---

## Phase 4: Swap TMDB API for Your Own Database
Right now, your website fetches directly from TMDB.

**Old Code (Fetching from TMDB):**
```javascript
const response = await fetch(`https://api.themoviedb.org/3/movie/popular?api_key=...`)
const data = await response.json()
```

**New Code (Fetching from your Supabase Database):**
```javascript
import { supabase } from '../lib/supabaseClient'

// Fetch all popular movies directly from YOUR database
const { data: movies, error } = await supabase
  .from('movies')
  .select('*')
  .order('rating', { ascending: false })
  .limit(20);

// You now have access to rich metadata that TMDB doesn't normally serve in a list!
console.log(movies[0].cast_members) // ['Leonardo DiCaprio', 'Joseph Gordon-Levitt', ...]
console.log(movies[0].genres)       // ['Action', 'Sci-Fi']
```

---

## Final Step: Continuous Harvesting
To keep the database actively updated every 3 hours as configured in `config.py`, you must keep the Python bot running. 

- **Option A (Free):** Leave a terminal window open on your computer running `python main.py`.
- **Option B (Professional):** Deploy the `Stream-X-Bot` GitHub repository to a free/cheap cloud container service like **Render**, **Railway**, or a **DigitalOcean Droplet**. Because we included a `requirements.txt` and a `docker-compose.yml`, deploying to these services is a 1-click process. Once deployed, it will run the 24/7 autonomous loop forever.
