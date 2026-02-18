-- Pgvector Migration for Optimized Face Similarity Search
-- Run this after 001_initial_schema.sql to enable vector similarity search

-- ============================================================================
-- EXTENSIONS
-- ============================================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- MIGRATE face_embeddings.table TO USE VECTOR TYPE
-- ============================================================================

-- Add new vector column (if not exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'face_embeddings' AND column_name = 'embedding_vector'
    ) THEN
        ALTER TABLE public.face_embeddings ADD COLUMN embedding_vector vector(128);
    END IF;
END $$;

-- Migrate existing JSONB data to vector type
-- Note: pgvector stores vectors as arrays, dimension is implicit
UPDATE public.face_embeddings
SET embedding_vector = embedding::vector
WHERE embedding_vector IS NULL AND embedding IS NOT NULL;

-- Drop old JSONB column after migration (safe to drop after verifying)
-- Uncomment the line below after verifying data migrated correctly
-- ALTER TABLE public.face_embeddings DROP COLUMN embedding;

-- For now, keep both columns for backward compatibility during migration
-- You can drop the old column later

-- ============================================================================
-- CREATE INDEX FOR COSINE SIMILARITY SEARCH
-- ============================================================================

-- Create index for cosine similarity (inner product)
-- Note: For cosine similarity with normalized vectors, we use ivfflat with inner_product
CREATE INDEX IF NOT EXISTS face_embeddings_embedding_vector_idx
ON public.face_embeddings
USING ivfflat (embedding_vector vector_cosine_ops)
WITH (lists = 100);  -- Adjust lists based on your data size (sqrt(num_rows))

-- ============================================================================
-- CREATE FUNCTION FOR VECTOR SIMILARITY SEARCH
-- ============================================================================

-- Function to find similar faces using vector similarity
CREATE OR REPLACE FUNCTION public.find_similar_faces(
    target_embedding vector(128),
    event_id_param UUID,
    threshold FLOAT DEFAULT 0.4
)
RETURNS TABLE (
    photo_id UUID,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        fe.photo_id,
        (1 - (fe.embedding_vector <=> target_embedding))::FLOAT as similarity  -- Cosine distance to similarity
    FROM public.face_embeddings fe
    WHERE fe.event_id = event_id_param
        AND fe.embedding_vector IS NOT NULL
        AND (1 - (fe.embedding_vector <=> target_embedding)) >= threshold
    ORDER BY fe.embedding_vector <=> target_embedding  -- Sort by distance (ascending)
    LIMIT 1000;  -- Reasonable limit to prevent excessive results
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute permission
GRANT EXECUTE ON FUNCTION public.find_similar_faces TO authenticated;
GRANT EXECUTE ON FUNCTION public.find_similar_faces TO service_role;

-- ============================================================================
-- CREATE FUNCTION TO UPDATE VECTOR FROM JSONB (for backward compatibility)
-- ============================================================================

CREATE OR REPLACE FUNCTION public.update_embedding_vector()
RETURNS TRIGGER AS $$
BEGIN
    -- Auto-populate embedding_vector from JSONB embedding if vector is null
    IF NEW.embedding_vector IS NULL AND NEW.embedding IS NOT NULL THEN
        NEW.embedding_vector := NEW.embedding::vector::vector(128);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update vector column
DROP TRIGGER IF EXISTS on_face_embeddings_insert_or_update ON public.face_embeddings;
CREATE TRIGGER on_face_embeddings_insert_or_update
    BEFORE INSERT OR UPDATE ON public.face_embeddings
    FOR EACH ROW
    EXECUTE FUNCTION public.update_embedding_vector();

-- ============================================================================
-- CREATE MATERIALIZED VIEW FOR EMBEDDING STATS
-- ============================================================================

-- Drop old view if exists
DROP MATERIALIZED VIEW IF EXISTS public.embedding_stats;

CREATE MATERIALIZED VIEW public.embedding_stats AS
SELECT
    e.id as event_id,
    e.name as event_name,
    COUNT(DISTINCT fe.photo_id) as photos_with_faces,
    COUNT(fe.id) as total_faces,
    AVG(array_length(ARRAY(SELECT jsonb_array_elements_text(fe.embedding)), 1)) as avg_embedding_length,
    MAX(fe.created_at) as last_processed_at
FROM public.events e
LEFT JOIN public.face_embeddings fe ON fe.event_id = e.id
GROUP BY e.id, e.name;

-- Create index on materialized view
CREATE UNIQUE INDEX IF NOT EXISTS embedding_stats_event_id_idx ON public.embedding_stats(event_id);

-- Function to refresh stats
CREATE OR REPLACE FUNCTION public.refresh_embedding_stats()
RETURNS VOID AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY public.embedding_stats;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT SELECT ON public.embedding_stats TO authenticated;
GRANT SELECT ON public.embedding_stats TO service_role;
GRANT EXECUTE ON FUNCTION public.refresh_embedding_stats TO service_role;

-- ============================================================================
-- COMMENTS FOR DOCUMENTATION
-- ============================================================================

COMMENT ON COLUMN public.face_embeddings.embedding_vector IS 'Vector representation of face (128d) using pgvector for similarity search';
COMMENT ON FUNCTION public.find_similar_faces IS 'Find similar faces using vector cosine similarity. Returns photos with similarity >= threshold.';
COMMENT ON INDEX face_embeddings_embedding_vector_idx IS 'IVFFlat index for fast approximate cosine similarity search';

-- ============================================================================
-- NOTES
-- ============================================================================
-- After running this migration:
--
-- 1. Verify data migration:
--    SELECT COUNT(*), COUNT(embedding_vector) FROM public.face_embeddings;
--
-- 2. Test vector search:
--    SELECT * FROM public.find_similar_faces(
--        '[0.1, 0.2, ...]'::vector(128),
--        'your-event-id'::UUID,
--        0.4
--    );
--
-- 3. If everything works, you can drop the old JSONB column:
--    ALTER TABLE public.face_embeddings DROP COLUMN embedding;
--
-- 4. To rebuild index with different parameters:
--    DROP INDEX face_embeddings_embedding_vector_idx;
--    CREATE INDEX face_embeddings_embedding_vector_idx
--    ON public.face_embeddings
--    USING ivfflat (embedding_vector vector_cosine_ops)
--    WITH (lists = 200);  -- Adjust based on data size
