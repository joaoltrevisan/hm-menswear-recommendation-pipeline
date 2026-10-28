-- A source release has one immutable final-test reservation, even if protocol text changes.
ALTER TABLE evaluation.test_sessions
    ADD COLUMN release_id uuid NOT NULL REFERENCES control.releases,
    ADD COLUMN recipe jsonb NOT NULL CHECK (jsonb_typeof(recipe) = 'object'),
    ADD COLUMN allowed_models jsonb NOT NULL CHECK (jsonb_typeof(allowed_models) = 'array'),
    ADD CONSTRAINT one_reserved_test_per_release UNIQUE (release_id);
