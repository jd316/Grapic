-- Grapic Supabase Database Schema
-- Run this in your Supabase project's SQL Editor

-- ============================================================================
-- EXTENSIONS
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- TABLES
-- ============================================================================

-- Events table
CREATE TABLE IF NOT EXISTS public.events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    access_code TEXT UNIQUE NOT NULL,
    organizer_code TEXT UNIQUE NOT NULL,
    photo_count INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    attendee_count INTEGER DEFAULT 0
);

-- Photos table
CREATE TABLE IF NOT EXISTS public.photos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    face_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending', -- pending, done, error
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    processing_time_ms INTEGER
);

-- Face embeddings table
CREATE TABLE IF NOT EXISTS public.face_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    photo_id UUID NOT NULL REFERENCES public.photos(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    embedding JSONB NOT NULL, -- Store as JSONB array
    face_location JSONB NOT NULL, -- [x, y, w, h] as JSONB
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- User profiles (extends auth.users)
CREATE TABLE IF NOT EXISTS public.user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT,
    avatar_url TEXT,
    subscription_tier TEXT DEFAULT 'free', -- free, pro, enterprise
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Photos indexes
CREATE INDEX IF NOT EXISTS idx_photos_event ON public.photos(event_id);
CREATE INDEX IF NOT EXISTS idx_photos_status ON public.photos(status);
CREATE INDEX IF NOT EXISTS idx_photos_uploaded_at ON public.photos(uploaded_at DESC);

-- Face embeddings indexes
CREATE INDEX IF NOT EXISTS idx_faces_event ON public.face_embeddings(event_id);
CREATE INDEX IF NOT EXISTS idx_faces_photo ON public.face_embeddings(photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_embedding ON public.face_embeddings USING GIN (embedding);

-- Events indexes
CREATE INDEX IF NOT EXISTS idx_events_access ON public.events(access_code);
CREATE INDEX IF NOT EXISTS idx_events_organizer ON public.events(organizer_code);
CREATE INDEX IF NOT EXISTS idx_events_user ON public.events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_created ON public.events(created_at DESC);

-- User profiles indexes
CREATE INDEX IF NOT EXISTS idx_user_profiles_subscription ON public.user_profiles(subscription_tier);

-- ============================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================================================

-- Enable RLS on all tables
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.photos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.face_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;

-- Events policies
-- Users can read their own events
CREATE POLICY "Users can view own events"
    ON public.events FOR SELECT
    USING (auth.uid() = user_id);

-- Users can insert their own events
CREATE POLICY "Users can create own events"
    ON public.events FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users can update their own events
CREATE POLICY "Users can update own events"
    ON public.events FOR UPDATE
    USING (auth.uid() = user_id);

-- Users can delete their own events
CREATE POLICY "Users can delete own events"
    ON public.events FOR DELETE
    USING (auth.uid() = user_id);

-- Service role can do anything (for background operations)
CREATE POLICY "Service role full access to events"
    ON public.events FOR ALL
    USING (jwt_claim_role() = 'service_role');

-- Photos policies (cascade from events)
CREATE POLICY "Users can view photos of own events"
    ON public.photos FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.events
            WHERE events.id = photos.event_id
            AND events.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert photos to own events"
    ON public.photos FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.events
            WHERE events.id = photos.event_id
            AND events.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can update photos of own events"
    ON public.photos FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.events
            WHERE events.id = photos.event_id
            AND events.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can delete photos of own events"
    ON public.photos FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM public.events
            WHERE events.id = photos.event_id
            AND events.user_id = auth.uid()
        )
    );

CREATE POLICY "Service role full access to photos"
    ON public.photos FOR ALL
    USING (jwt_claim_role() = 'service_role');

-- Face embeddings policies (cascade from photos)
CREATE POLICY "Users can view face embeddings of own events"
    ON public.face_embeddings FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.photos
            JOIN public.events ON events.id = photos.event_id
            WHERE photos.id = face_embeddings.photo_id
            AND events.user_id = auth.uid()
        )
    );

CREATE POLICY "Service role full access to face embeddings"
    ON public.face_embeddings FOR ALL
    USING (jwt_claim_role() = 'service_role');

-- User profiles policies
CREATE POLICY "Users can view own profile"
    ON public.user_profiles FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "Users can update own profile"
    ON public.user_profiles FOR UPDATE
    USING (auth.uid() = id);

CREATE POLICY "Users can insert own profile"
    ON public.user_profiles FOR INSERT
    WITH CHECK (auth.uid() = id);

-- ============================================================================
-- FUNCTIONS AND TRIGGERS
-- ============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for user_profiles
CREATE TRIGGER update_user_profiles_updated_at
    BEFORE UPDATE ON public.user_profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at();

-- Function to auto-create user profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.user_profiles (id, full_name)
    VALUES (NEW.id, NEW.raw_user_meta_data->>'full_name')
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to create profile on user signup
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

-- Function to increment event photo count
CREATE OR REPLACE FUNCTION public.increment_event_photo_count(event_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE public.events
    SET photo_count = photo_count + 1
    WHERE id = event_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to increment event processed count
CREATE OR REPLACE FUNCTION public.increment_event_processed_count(event_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE public.events
    SET processed_count = processed_count + 1
    WHERE id = event_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- VIEWS FOR ANALYTICS
-- ============================================================================

-- View for event stats
CREATE OR REPLACE VIEW public.event_stats AS
SELECT
    e.id,
    e.name,
    e.user_id,
    e.photo_count,
    e.processed_count,
    e.attendee_count,
    COUNT(DISTINCT p.id) FILTER (WHERE p.status = 'pending') as pending_count,
    COUNT(DISTINCT p.id) FILTER (WHERE p.status = 'error') as error_count,
    AVG(p.processing_time_ms) FILTER (WHERE p.status = 'done' AND p.processing_time_ms IS NOT NULL) as avg_processing_ms,
    CASE
        WHEN e.photo_count > 0 THEN ROUND((e.attendee_count::FLOAT / e.photo_count) * 100, 1)
        ELSE 0
    END as engagement_pct
FROM public.events e
LEFT JOIN public.photos p ON p.event_id = e.id
GROUP BY e.id, e.name, e.user_id, e.photo_count, e.processed_count, e.attendee_count;

-- ============================================================================
-- GRANTS
-- ============================================================================

-- Grant access to authenticated users
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO authenticated;

-- Grant access to service role
GRANT USAGE ON SCHEMA public TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;
