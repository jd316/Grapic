# Supabase Setup Guide for Grapic

This guide walks you through setting up Supabase for Grapic's authentication and PostgreSQL database.

## Prerequisites

- A Supabase account (free tier works)
- Basic understanding of SQL

## Step 1: Create a Supabase Project

1. Go to [supabase.com](https://supabase.com)
2. Click "New Project"
3. Fill in:
   - **Name**: grapic (or your preferred name)
   - **Database Password**: Generate a strong password (save it!)
   - **Region**: Choose closest to your users
4. Wait for the project to be provisioned (1-2 minutes)

## Step 2: Run the Database Migration

1. In your Supabase project, go to **SQL Editor** in the left sidebar
2. Click **New Query**
3. Copy the contents of `backend/supabase/migrations/001_initial_schema.sql`
4. Paste into the SQL Editor
5. Click **Run** (or press `Ctrl+Enter`)

This will create:
- `events` table
- `photos` table
- `face_embeddings` table
- `user_profiles` table
- Row Level Security (RLS) policies
- Helper functions and triggers
- Indexes for performance

## Step 3: Configure Authentication Settings

1. In your Supabase project, go to **Authentication** → **Settings**
2. Under **Site URL**, add your frontend URL (e.g., `http://localhost:3000` for development)
3. Under **Redirect URLs**, add allowed redirect URLs:
   - `http://localhost:3000/**` (for development)
   - `https://your-frontend-domain.com/**` (for production)
4. Enable **Email Auth** if not already enabled
5. (Optional) Disable other auth providers (Phone, Magic Links, etc.) if not needed

## Step 4: Get Your API Keys

1. In your Supabase project, go to **Project Settings** → **API**
2. Copy the following values:
   - **Project URL** (looks like `https://xxxxxxxxxxxxx.supabase.co`)
   - **anon public** key (this is `SUPABASE_KEY`)
   - **service_role** key (this is `SUPABASE_SERVICE_KEY`)

**⚠️ IMPORTANT**: Never share or commit your `service_role` key! It bypasses Row Level Security.

## Step 5: Configure Environment Variables

Create a `.env` file in the project root (or copy `.env.example`):

```bash
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key-here
SUPABASE_SERVICE_KEY=your-service-role-key-here
```

## Step 6: Install Dependencies and Run

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The backend will now:
- Use Supabase for authentication
- Use PostgreSQL for data storage
- Enable multi-tenancy (each user has their own events)

## Step 7: Test the Setup

### Test Authentication

```bash
# Sign up a new user
curl -X POST http://localhost:8000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123","full_name":"Test User"}'

# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123"}'
```

### Test Event Creation (requires auth)

```bash
# Create an event (replace YOUR_ACCESS_TOKEN with the token from login)
curl -X POST http://localhost:8000/api/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{"name":"Wedding","description":"John & Jane Wedding","expires_in_days":30}'
```

## Row Level Security (RLS) Overview

The migration creates RLS policies to ensure:
- Users can only read/write their own events
- Photos and face embeddings are protected by the same ownership rules
- Service role key can bypass RLS for background operations

## Troubleshooting

### "Invalid or expired token" error

- Ensure you're using the `access_token` (not `refresh_token`) in the Authorization header
- Check that the token hasn't expired (default: 1 hour)
- Use `/api/auth/refresh` to get a new access token

### "Authentication required" error

- Ensure `SUPABASE_URL`, `SUPABASE_KEY`, and `SUPABASE_SERVICE_KEY` are set
- Check that you've run the migration
- Verify your Supabase project is active

### Database connection errors

- Check that your Supabase project isn't paused (free tier pauses after 1 week of inactivity)
- Verify the `SUPABASE_URL` is correct
- Check Supabase status page: [status.supabase.com](https://status.supabase.com/)

### Migration fails

- Ensure you're using a Supabase project with PostgreSQL (not another database)
- Check the SQL Editor for specific error messages
- Try running each section of the migration separately

## Switching Back to SQLite

To switch back to SQLite (no authentication, single-organizer mode):

1. Remove or comment out `SUPABASE_URL`, `SUPABASE_KEY`, and `SUPABASE_SERVICE_KEY` from `.env`
2. Restart the backend

The backend will automatically fall back to SQLite mode.

## Production Considerations

1. **Enable email confirmation**: In Supabase Auth settings, enable "Enable email confirmations"
2. **Set up custom SMTP**: Configure your own email provider for reliable password reset emails
3. **Configure CORS**: Set `GRAPIC_CORS_ORIGINS` to your frontend domain
4. **Use environment-specific configs**: Use different Supabase projects for dev/staging/prod
5. **Monitor usage**: Check Supabase dashboard for database size and API usage

## Additional Resources

- [Supabase Documentation](https://supabase.com/docs)
- [Supabase Python Client](https://github.com/supabase/supabase-py)
- [Row Level Security Guide](https://supabase.com/docs/guides/auth/row-level-security)
