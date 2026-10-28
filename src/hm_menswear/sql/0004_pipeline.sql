-- Track preparation attempts with the same durable lifecycle/ownership protocol as loads.
ALTER TABLE control.runs ADD COLUMN operation text NOT NULL DEFAULT 'load'
    CHECK (operation IN ('prepare', 'load'));
ALTER TABLE control.runs ADD COLUMN preparation_id uuid;
ALTER TABLE control.runs ADD FOREIGN KEY (preparation_id, release_id)
    REFERENCES control.preparations(preparation_id, release_id);
ALTER TABLE control.runs DROP CONSTRAINT runs_status_check;
ALTER TABLE control.runs ADD CONSTRAINT runs_status_check CHECK (status IN (
    'preparing','prepared','waiting_to_publish','publishing','succeeded','noop','failed','interrupted'));
ALTER TABLE control.runs DROP CONSTRAINT runs_check;
ALTER TABLE control.runs ADD CONSTRAINT runs_terminal_time CHECK (
    (status IN ('prepared','succeeded','noop','failed','interrupted')) = (ended_at IS NOT NULL));
ALTER TABLE control.runs ADD CONSTRAINT runs_operation_status CHECK (
    (operation='load' AND status <> 'prepared') OR
    (operation='prepare' AND preparation_id IS NOT NULL
        AND status IN ('preparing','prepared','failed','interrupted')));
ALTER TABLE control.preparations ADD COLUMN started_at timestamptz NOT NULL DEFAULT clock_timestamp();
ALTER TABLE control.preparations ADD COLUMN error_code text
    CHECK (error_code ~ '^[a-z][a-z0-9_]{0,79}$');
GRANT UPDATE(error_code) ON control.preparations TO hm_loader;

CREATE OR REPLACE FUNCTION control.protect_terminal() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF OLD.status IN ('complete','completed','prepared','succeeded','noop','failed','interrupted') THEN
        RAISE EXCEPTION 'terminal_record_is_immutable' USING ERRCODE='23514';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE FUNCTION control.guard_prepared_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF NEW.status='prepared' AND NOT EXISTS (SELECT 1 FROM control.preparations
        WHERE preparation_id=NEW.preparation_id AND release_id=NEW.release_id AND status='complete') THEN
        RAISE EXCEPTION 'prepared_run_requires_complete_preparation' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION control.guard_prepared_run() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER prepared_run AFTER INSERT OR UPDATE ON control.runs
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION control.guard_prepared_run();
CREATE INDEX purchase_first_batch ON mart.purchase_events(first_batch_id);
CREATE INDEX batch_membership_fact ON control.batch_records(transaction_file_id,source_record_number);
CREATE INDEX observation_first_date ON mart.customer_observations(release_id,first_observed_date);
CREATE INDEX staging_observation_window ON staging.customer_observations(preparation_id,first_observed_date);
CREATE INDEX complete_preparations ON control.preparations(release_id) WHERE status='complete';
CREATE INDEX runs_preparation ON control.runs(preparation_id);
