-- No default grant to future tables: each migration must explicitly grant its minimum needs.
REVOKE ALL ON SCHEMA control, quality, staging, mart, serving, evaluation FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA control, quality, staging, mart, serving, evaluation FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA control FROM PUBLIC;
REVOKE ALL ON DOMAIN control.sha256, control.article_id, control.customer_id,
    control.file_role FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE hm_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE hm_owner REVOKE USAGE ON TYPES FROM PUBLIC;
GRANT USAGE ON DOMAIN control.sha256, control.article_id, control.customer_id,
    control.file_role TO hm_loader, hm_model, hm_reader;
GRANT USAGE ON SCHEMA control, quality, staging, mart TO hm_loader;
GRANT SELECT, INSERT ON control.source_files, control.releases, control.release_files,
    control.preparations, control.batches, control.runs, control.batch_records,
    mart.articles, mart.customers, mart.purchase_events, mart.customer_observations TO hm_loader;
GRANT SELECT ON control.lineage TO hm_loader;
GRANT UPDATE(active_release_id) ON control.lineage TO hm_loader;
GRANT UPDATE(status, artifact_sha256, source_rows, rejected_rows, valid_out_of_scope_rows,
    valid_menswear_rows, completed_at) ON control.preparations TO hm_loader;
GRANT UPDATE(status, accepted_rows, inserted_rows, reused_rows, completed_at)
    ON control.batches TO hm_loader;
GRANT UPDATE(batch_id, status, ended_at, error_code) ON control.runs TO hm_loader;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA staging, quality TO hm_loader;

GRANT USAGE ON SCHEMA control, mart, serving, evaluation TO hm_model;
GRANT SELECT ON control.releases, control.release_files, control.lineage,
    control.preparations, control.batches, control.batch_records TO hm_model;
GRANT SELECT(release_id, article_id, index_group_name) ON mart.articles TO hm_model;
GRANT SELECT(transaction_file_id, source_record_number, release_id, article_id, customer_id,
    purchase_date) ON mart.purchase_events TO hm_model;
GRANT SELECT(release_id, customer_id, first_observed_date) ON mart.customer_observations TO hm_model;
GRANT SELECT, INSERT ON control.models, serving.recommendations,
    evaluation.test_sessions, evaluation.runs TO hm_model;
GRANT UPDATE(status, completed_at) ON control.models TO hm_model;

GRANT USAGE ON SCHEMA control, mart, serving TO hm_reader;
GRANT SELECT ON mart.articles, serving.recommendations TO hm_reader;
GRANT SELECT(model_id, cutoff_date, family, status) ON control.models TO hm_reader;
