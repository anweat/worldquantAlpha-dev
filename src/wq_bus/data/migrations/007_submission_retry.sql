-- 007: submission_queue retry tracking (dead-letter on max_retries).
ALTER TABLE submission_queue ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE submission_queue ADD COLUMN last_error  TEXT;
-- status taxonomy (extended): pending | submitting | submitted | failed
--                             | retry_pending  (transient failure, will retry)
--                             | dead_letter    (max_retries exceeded — stop retrying)
