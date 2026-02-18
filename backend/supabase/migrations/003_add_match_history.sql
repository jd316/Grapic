-- Match History Migration
-- Track all selfie match attempts for analytics and false positive rate measurement

-- ============================================================================
-- CREATE match_history TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.match_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    photo_id UUID NOT NULL REFERENCES public.photos(id) ON DELETE CASCADE,
    similarity FLOAT NOT NULL,
    threshold_used FLOAT NOT NULL DEFAULT 0.4,
    match_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_feedback TEXT, -- 'correct', 'incorrect', 'not sure' (optional future feature)
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL, -- Track who searched
    metadata JSONB DEFAULT '{}' -- Additional data (face confidence, etc.)
);

-- ============================================================================
-- CREATE INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_match_history_event ON public.match_history(event_id);
CREATE INDEX IF NOT EXISTS idx_match_history_photo ON public.match_history(photo_id);
CREATE INDEX IF NOT EXISTS idx_match_history_user ON public.match_history(user_id);
CREATE INDEX IF NOT EXISTS idx_match_history_similarity ON public.match_history(similarity);
CREATE INDEX IF NOT EXISTS idx_match_history_timestamp ON public.match_history(match_timestamp DESC);

-- ============================================================================
-- CREATE FUNCTIONS FOR ANALYTICS
-- ============================================================================

-- Function to record a match
CREATE OR REPLACE FUNCTION public.record_match(
    evt_id UUID,
    pht_id UUID,
    sim FLOAT,
    threshold FLOAT DEFAULT 0.4,
    usr_id UUID DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO public.match_history (event_id, photo_id, similarity, threshold_used, user_id)
    VALUES (evt_id, pht_id, sim, threshold, usr_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get similarity distribution for an event
CREATE OR REPLACE FUNCTION public.get_similarity_distribution(evt_id UUID)
RETURNS TABLE (
    similarity_range TEXT,
    count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        CASE
            WHEN similarity >= 0.90 THEN '0.90-1.00'  -- Very high confidence
            WHEN similarity >= 0.70 THEN '0.70-0.89'  -- High confidence
            WHEN similarity >= 0.50 THEN '0.50-0.69'  -- Medium confidence
            WHEN similarity >= 0.40 THEN '0.40-0.49'  -- Low confidence (threshold)
            ELSE '0.00-0.39'  -- Below threshold
        END as similarity_range,
        COUNT(*) as count
    FROM public.match_history
    WHERE event_id = evt_id
    GROUP BY
        CASE
            WHEN similarity >= 0.90 THEN '0.90-1.00'
            WHEN similarity >= 0.70 THEN '0.70-0.89'
            WHEN similarity >= 0.50 THEN '0.50-0.69'
            WHEN similarity >= 0.40 THEN '0.40-0.49'
            ELSE '0.00-0.39'
        END
    ORDER BY MIN(similarity) DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get aggregate similarity statistics for an event
CREATE OR REPLACE FUNCTION public.get_similarity_stats(evt_id UUID)
RETURNS TABLE (
    avg_similarity FLOAT,
    median_similarity FLOAT,
    min_similarity FLOAT,
    max_similarity FLOAT,
    total_matches BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        AVG(similarity) as avg_similarity,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY similarity) as median_similarity,
        MIN(similarity) as min_similarity,
        MAX(similarity) as max_similarity,
        COUNT(*) as total_matches
    FROM public.match_history
    WHERE event_id = evt_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to estimate false positive rate
-- Note: This requires user_feedback data. Without feedback, we use low similarity matches as proxy.
CREATE OR REPLACE FUNCTION public.estimate_false_positive_rate(evt_id UUID, low_confidence_threshold FLOAT DEFAULT 0.50)
RETURNS TABLE (
    false_positive_estimate FLOAT,
    total_matches BIGINT,
    low_confidence_matches BIGINT
) AS $$
DECLARE
    total BIGINT;
    low_conf BIGINT;
BEGIN
    SELECT COUNT(*) INTO total
    FROM public.match_history
    WHERE event_id = evt_id;

    SELECT COUNT(*) INTO low_conf
    FROM public.match_history
    WHERE event_id = evt_id AND similarity < low_confidence_threshold;

    RETURN QUERY
    SELECT
        CASE
            WHEN total > 0 THEN ROUND((low_conf::FLOAT / total::FLOAT) * 100, 2)
            ELSE 0
        END as false_positive_estimate,
        total as total_matches,
        low_conf as low_confidence_matches;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- CREATE MATERIALIZED VIEW FOR MATCH ANALYTICS
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS public.match_analytics AS
SELECT
    e.id as event_id,
    e.name as event_name,
    COUNT(DISTINCT mh.user_id) as unique_searchers,
    COUNT(DISTINCT mh.photo_id) as photos_matched,
    COUNT(*) as total_match_attempts,
    AVG(mh.similarity) as avg_similarity,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY mh.similarity) as median_similarity,
    MIN(mh.similarity) as min_similarity,
    MAX(mh.similarity) as max_similarity,
    ROUND(AVG(CASE WHEN mh.similarity >= 0.90 THEN 1 ELSE 0 END) * 100, 1) as pct_very_high_confidence,
    ROUND(AVG(CASE WHEN mh.similarity >= 0.70 AND mh.similarity < 0.90 THEN 1 ELSE 0 END) * 100, 1) as pct_high_confidence,
    ROUND(AVG(CASE WHEN mh.similarity >= 0.50 AND mh.similarity < 0.70 THEN 1 ELSE 0 END) * 100, 1) as pct_medium_confidence,
    ROUND(AVG(CASE WHEN mh.similarity >= 0.40 AND mh.similarity < 0.50 THEN 1 ELSE 0 END) * 100, 1) as pct_low_confidence,
    ROUND(AVG(CASE WHEN mh.similarity < 0.40 THEN 1 ELSE 0 END) * 100, 1) as pct_below_threshold,
    MAX(mh.match_timestamp) as last_search_at
FROM public.events e
LEFT JOIN public.match_history mh ON mh.event_id = e.id
GROUP BY e.id, e.name;

CREATE UNIQUE INDEX IF NOT EXISTS match_analytics_event_id_idx ON public.match_analytics(event_id);
REFRESH MATERIALIZED VIEW CONCURRENTLY public.match_analytics;

-- Function to refresh match analytics
CREATE OR REPLACE FUNCTION public.refresh_match_analytics()
RETURNS VOID AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY public.match_analytics;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================

ALTER TABLE public.match_history ENABLE ROW LEVEL SECURITY;

-- Service role can insert (for recording matches)
CREATE POLICY "Service role can insert matches"
    ON public.match_history FOR INSERT
    WITH CHECK (jwt_claim_role() = 'service_role');

-- Users can read match history for their own events
CREATE POLICY "Users can view own event match history"
    ON public.match_history FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.events
            WHERE events.id = match_history.event_id
            AND events.user_id = auth.uid()
        )
    );

-- Service role full access
CREATE POLICY "Service role full access to match_history"
    ON public.match_history FOR ALL
    USING (jwt_claim_role() = 'service_role');

-- Grants for analytics view
GRANT SELECT ON public.match_analytics TO authenticated;
GRANT SELECT ON public.match_analytics TO service_role;

-- ============================================================================
-- GRANTS
-- ============================================================================

GRANT EXECUTE ON FUNCTION public.record_match TO service_role;
GRANT EXECUTE ON FUNCTION public.get_similarity_distribution TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_similarity_distribution TO service_role;
GRANT EXECUTE ON FUNCTION public.get_similarity_stats TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_similarity_stats TO service_role;
GRANT EXECUTE ON FUNCTION public.estimate_false_positive_rate TO authenticated;
GRANT EXECUTE ON FUNCTION public.estimate_false_positive_rate TO service_role;
GRANT EXECUTE ON FUNCTION public.refresh_match_analytics TO service_role;
