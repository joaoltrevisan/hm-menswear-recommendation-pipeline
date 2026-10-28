-- All objects are owned by hm_owner. No source/customer data is bundled.
CREATE SCHEMA quality AUTHORIZATION hm_owner;
CREATE SCHEMA staging AUTHORIZATION hm_owner;
CREATE SCHEMA mart AUTHORIZATION hm_owner;
CREATE SCHEMA serving AUTHORIZATION hm_owner;
CREATE SCHEMA evaluation AUTHORIZATION hm_owner;

CREATE DOMAIN control.sha256 AS text CHECK (VALUE ~ '^[0-9a-f]{64}$');
CREATE DOMAIN control.article_id AS text COLLATE "C" CHECK (VALUE ~ '^[0-9]{10}$');
CREATE DOMAIN control.customer_id AS text COLLATE "C" CHECK (VALUE ~ '^[0-9a-f]{64}$');
CREATE DOMAIN control.file_role AS text CHECK (VALUE IN ('articles', 'customers', 'transactions'));

CREATE TABLE control.source_files (
    file_id uuid PRIMARY KEY,
    namespace text NOT NULL CHECK (length(btrim(namespace)) > 0),
    role control.file_role NOT NULL,
    sha256 control.sha256 NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    private_location text NOT NULL CHECK (length(btrim(private_location)) > 0),
    acquired_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (namespace, role, sha256), UNIQUE (file_id, role)
);
CREATE TABLE control.releases (
    release_id uuid PRIMARY KEY,
    manifest_sha256 control.sha256 NOT NULL UNIQUE,
    parser_version text NOT NULL CHECK (length(btrim(parser_version)) > 0),
    validation_version text NOT NULL CHECK (length(btrim(validation_version)) > 0),
    scope_version text NOT NULL CHECK (length(btrim(scope_version)) > 0),
    contract_version text NOT NULL CHECK (length(btrim(contract_version)) > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE control.release_files (
    release_id uuid NOT NULL REFERENCES control.releases,
    role control.file_role NOT NULL,
    file_id uuid NOT NULL,
    PRIMARY KEY (release_id, role), UNIQUE (release_id, file_id, role),
    FOREIGN KEY (file_id, role) REFERENCES control.source_files (file_id, role)
);
CREATE TABLE control.lineage (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    active_release_id uuid REFERENCES control.releases
);
INSERT INTO control.lineage(singleton) VALUES (true);

CREATE TABLE control.preparations (
    preparation_id uuid PRIMARY KEY,
    release_id uuid NOT NULL REFERENCES control.releases,
    status text NOT NULL CHECK (status IN ('preparing', 'complete', 'failed')),
    artifact_sha256 control.sha256,
    private_location text NOT NULL CHECK (length(btrim(private_location)) > 0),
    source_rows bigint CHECK (source_rows >= 0),
    rejected_rows bigint CHECK (rejected_rows >= 0),
    valid_out_of_scope_rows bigint CHECK (valid_out_of_scope_rows >= 0),
    valid_menswear_rows bigint CHECK (valid_menswear_rows >= 0),
    completed_at timestamptz,
    UNIQUE (preparation_id, release_id),
    CHECK (status <> 'complete' OR (
        artifact_sha256 IS NOT NULL AND completed_at IS NOT NULL
        AND source_rows IS NOT NULL AND rejected_rows IS NOT NULL
        AND valid_out_of_scope_rows IS NOT NULL AND valid_menswear_rows IS NOT NULL
        AND source_rows = rejected_rows + valid_out_of_scope_rows + valid_menswear_rows))
);
CREATE TABLE control.batches (
    batch_id uuid PRIMARY KEY,
    release_id uuid NOT NULL REFERENCES control.releases,
    preparation_id uuid NOT NULL,
    start_date date NOT NULL CHECK (isfinite(start_date)),
    end_date date NOT NULL CHECK (isfinite(end_date)),
    status text NOT NULL CHECK (status IN ('pending', 'completed')),
    accepted_rows bigint CHECK (accepted_rows >= 0),
    inserted_rows bigint CHECK (inserted_rows >= 0),
    reused_rows bigint CHECK (reused_rows >= 0),
    completed_at timestamptz,
    UNIQUE (release_id, start_date, end_date), UNIQUE (batch_id, release_id),
    FOREIGN KEY (preparation_id, release_id)
        REFERENCES control.preparations (preparation_id, release_id),
    CHECK (start_date < end_date),
    CHECK (status <> 'completed' OR (completed_at IS NOT NULL AND accepted_rows IS NOT NULL
        AND inserted_rows IS NOT NULL AND reused_rows IS NOT NULL
        AND accepted_rows = inserted_rows + reused_rows))
);
CREATE TABLE control.runs (
    run_id uuid PRIMARY KEY,
    release_id uuid NOT NULL REFERENCES control.releases,
    batch_id uuid,
    status text NOT NULL CHECK (status IN ('preparing', 'waiting_to_publish', 'publishing',
        'succeeded', 'noop', 'failed', 'interrupted')),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ended_at timestamptz,
    error_code text CHECK (error_code ~ '^[a-z][a-z0-9_]{0,79}$'),
    FOREIGN KEY (batch_id, release_id) REFERENCES control.batches (batch_id, release_id),
    CHECK ((status IN ('succeeded', 'noop', 'failed', 'interrupted')) = (ended_at IS NOT NULL)),
    CHECK (ended_at IS NULL OR ended_at >= started_at),
    CHECK (status NOT IN ('succeeded', 'noop') OR batch_id IS NOT NULL)
);
CREATE TABLE quality.rejections (
    preparation_id uuid NOT NULL REFERENCES control.preparations,
    role control.file_role NOT NULL,
    source_record_number bigint NOT NULL CHECK (source_record_number > 0),
    primary_reason text NOT NULL CHECK (primary_reason ~ '^[a-z][a-z0-9_]{0,79}$'),
    additional_reasons text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (preparation_id, role, source_record_number)
);

-- Staging may retain invalid tokens privately; these are not mart records.
CREATE TABLE staging.articles (
    preparation_id uuid NOT NULL REFERENCES control.preparations,
    source_record_number bigint NOT NULL CHECK (source_record_number > 0),
    article_id text,
    attributes jsonb NOT NULL CHECK (jsonb_typeof(attributes) = 'object'),
    PRIMARY KEY (preparation_id, source_record_number)
);
CREATE INDEX staging_article_lookup ON staging.articles (preparation_id, article_id);
CREATE TABLE staging.customers (
    preparation_id uuid NOT NULL REFERENCES control.preparations,
    source_record_number bigint NOT NULL CHECK (source_record_number > 0),
    customer_id text,
    attributes jsonb NOT NULL CHECK (jsonb_typeof(attributes) = 'object'),
    PRIMARY KEY (preparation_id, source_record_number)
);
CREATE INDEX staging_customer_lookup ON staging.customers (preparation_id, customer_id);
CREATE TABLE staging.purchase_records (
    preparation_id uuid NOT NULL REFERENCES control.preparations,
    source_record_number bigint NOT NULL CHECK (source_record_number > 0),
    purchase_date date,
    customer_id text,
    article_id text,
    price_source_units numeric,
    sales_channel_code text,
    disposition text NOT NULL CHECK (disposition IN ('rejected', 'out_of_scope', 'menswear')),
    PRIMARY KEY (preparation_id, source_record_number)
);
CREATE INDEX staging_purchase_window ON staging.purchase_records (preparation_id, purchase_date);
CREATE TABLE staging.customer_observations (
    preparation_id uuid NOT NULL REFERENCES control.preparations,
    customer_id control.customer_id NOT NULL,
    first_observed_date date NOT NULL CHECK (isfinite(first_observed_date)),
    source_record_number bigint NOT NULL CHECK (source_record_number > 0),
    PRIMARY KEY (preparation_id, customer_id)
);

CREATE TABLE mart.articles (
    release_id uuid NOT NULL REFERENCES control.releases,
    article_id control.article_id NOT NULL,
    source_record_number bigint NOT NULL CHECK (source_record_number > 0),
    product_code text, prod_name text, product_type_no text, product_type_name text,
    product_group_name text, graphical_appearance_no text, graphical_appearance_name text,
    colour_group_code text, colour_group_name text, perceived_colour_value_id text,
    perceived_colour_value_name text, perceived_colour_master_id text,
    perceived_colour_master_name text, department_no text, department_name text,
    index_code text, index_name text, index_group_no text,
    index_group_name text NOT NULL CHECK (index_group_name = 'Menswear'),
    section_no text, section_name text, garment_group_no text, garment_group_name text,
    detail_desc text,
    PRIMARY KEY (release_id, article_id), UNIQUE (release_id, source_record_number)
);
CREATE TABLE mart.customers (
    release_id uuid NOT NULL REFERENCES control.releases,
    customer_id control.customer_id NOT NULL,
    source_record_number bigint NOT NULL CHECK (source_record_number > 0),
    fn text CHECK (fn = '1.0'), active text CHECK (active = '1.0'),
    club_member_status text, fashion_news_frequency text,
    age integer CHECK (age >= 0),
    PRIMARY KEY (release_id, customer_id), UNIQUE (release_id, source_record_number)
);
CREATE TABLE mart.customer_observations (
    release_id uuid NOT NULL REFERENCES control.releases,
    customer_id control.customer_id NOT NULL,
    first_observed_date date NOT NULL CHECK (isfinite(first_observed_date)),
    transaction_file_id uuid NOT NULL,
    file_role control.file_role GENERATED ALWAYS AS ('transactions') STORED,
    source_record_number bigint NOT NULL CHECK (source_record_number > 0),
    first_batch_id uuid NOT NULL,
    PRIMARY KEY (release_id, customer_id),
    FOREIGN KEY (release_id, transaction_file_id, file_role)
        REFERENCES control.release_files (release_id, file_id, role),
    FOREIGN KEY (first_batch_id, release_id) REFERENCES control.batches (batch_id, release_id)
);
CREATE TABLE mart.purchase_events (
    transaction_file_id uuid NOT NULL,
    source_record_number bigint NOT NULL CHECK (source_record_number > 0),
    release_id uuid NOT NULL REFERENCES control.releases,
    file_role control.file_role GENERATED ALWAYS AS ('transactions') STORED,
    article_id control.article_id NOT NULL,
    customer_id control.customer_id NOT NULL,
    purchase_date date NOT NULL CHECK (isfinite(purchase_date)),
    price_source_units numeric NOT NULL CHECK (
        price_source_units >= 0 AND price_source_units < 'Infinity'::numeric),
    sales_channel_code text NOT NULL CHECK (sales_channel_code IN ('1', '2')),
    first_batch_id uuid NOT NULL,
    PRIMARY KEY (transaction_file_id, source_record_number),
    UNIQUE (transaction_file_id, source_record_number, release_id),
    FOREIGN KEY (release_id, transaction_file_id, file_role)
        REFERENCES control.release_files (release_id, file_id, role),
    FOREIGN KEY (release_id, article_id) REFERENCES mart.articles,
    FOREIGN KEY (release_id, customer_id) REFERENCES mart.customers,
    FOREIGN KEY (first_batch_id, release_id) REFERENCES control.batches (batch_id, release_id)
);
CREATE INDEX purchase_customer_date ON mart.purchase_events (release_id, customer_id, purchase_date);
CREATE INDEX purchase_date_article ON mart.purchase_events (release_id, purchase_date, article_id);
CREATE TABLE control.batch_records (
    batch_id uuid NOT NULL,
    release_id uuid NOT NULL,
    transaction_file_id uuid NOT NULL,
    source_record_number bigint NOT NULL,
    PRIMARY KEY (batch_id, transaction_file_id, source_record_number),
    FOREIGN KEY (batch_id, release_id) REFERENCES control.batches (batch_id, release_id),
    FOREIGN KEY (transaction_file_id, source_record_number, release_id)
        REFERENCES mart.purchase_events (transaction_file_id, source_record_number, release_id)
);

-- Structural model/serving tables only. No training/evaluation logic in Stage 2.
CREATE TABLE control.models (
    model_id control.sha256 PRIMARY KEY,
    release_id uuid NOT NULL REFERENCES control.releases,
    cutoff_date date NOT NULL CHECK (isfinite(cutoff_date)),
    family text NOT NULL CHECK (family IN ('popularity', 'repeat_history', 'item_item')),
    config_sha256 control.sha256 NOT NULL,
    input_snapshot_sha256 control.sha256 NOT NULL,
    dependency_lock_sha256 control.sha256 NOT NULL,
    code_commit text NOT NULL CHECK (code_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'),
    manifest jsonb NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
    private_location text NOT NULL CHECK (length(btrim(private_location)) > 0),
    status text NOT NULL CHECK (status IN ('building', 'complete', 'failed')),
    completed_at timestamptz,
    UNIQUE (model_id, release_id),
    CHECK (status <> 'complete' OR completed_at IS NOT NULL)
);
CREATE TABLE serving.recommendations (
    model_id control.sha256 NOT NULL,
    release_id uuid NOT NULL,
    customer_id control.customer_id NOT NULL,
    rank smallint NOT NULL CHECK (rank BETWEEN 1 AND 12),
    article_id control.article_id NOT NULL,
    score double precision NOT NULL CHECK (score >= 0 AND score < 'Infinity'::double precision),
    fallback_reason text CHECK (fallback_reason ~ '^[a-z][a-z0-9_]{0,79}$'),
    PRIMARY KEY (model_id, customer_id, rank), UNIQUE (model_id, customer_id, article_id),
    FOREIGN KEY (model_id, release_id) REFERENCES control.models (model_id, release_id),
    FOREIGN KEY (release_id, article_id) REFERENCES mart.articles,
    FOREIGN KEY (release_id, customer_id) REFERENCES mart.customer_observations
);
CREATE TABLE evaluation.test_sessions (
    test_session_id uuid PRIMARY KEY,
    protocol_sha256 control.sha256 NOT NULL UNIQUE,
    selected_model_id control.sha256 NOT NULL REFERENCES control.models,
    frozen_recipe_sha256 control.sha256 NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (test_session_id, protocol_sha256)
);
CREATE TABLE evaluation.runs (
    evaluation_id uuid PRIMARY KEY,
    model_id control.sha256 NOT NULL REFERENCES control.models,
    protocol_sha256 control.sha256 NOT NULL,
    config_sha256 control.sha256 NOT NULL,
    split text NOT NULL CHECK (split IN ('validation', 'test')),
    test_session_id uuid,
    FOREIGN KEY (test_session_id, protocol_sha256)
        REFERENCES evaluation.test_sessions (test_session_id, protocol_sha256),
    CHECK ((split = 'test') = (test_session_id IS NOT NULL)),
    cohort_counts jsonb NOT NULL CHECK (jsonb_typeof(cohort_counts) = 'object'),
    metrics jsonb NOT NULL CHECK (jsonb_typeof(metrics) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX one_test_result_per_model_protocol ON evaluation.runs(model_id, protocol_sha256)
    WHERE split = 'test';
