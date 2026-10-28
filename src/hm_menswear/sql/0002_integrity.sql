-- These guards enforce structural publication contracts, not loader/model algorithms.
CREATE FUNCTION control.deny_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN RAISE EXCEPTION 'immutable_record' USING ERRCODE = '23514'; END $$;
DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['control.source_files', 'control.releases',
        'control.release_files', 'mart.articles', 'mart.customers',
        'mart.customer_observations', 'mart.purchase_events', 'control.batch_records',
        'evaluation.test_sessions', 'evaluation.runs'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON %s '
            'FOR EACH ROW EXECUTE FUNCTION control.deny_mutation()', target);
    END LOOP;
END $$;

CREATE FUNCTION control.require_complete_release() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE target uuid; role_count integer; namespace_count integer;
BEGIN
    target := NEW.release_id;
    SELECT count(*), count(DISTINCT f.namespace) INTO role_count, namespace_count
    FROM control.release_files r JOIN control.source_files f ON f.file_id = r.file_id
    WHERE r.release_id = target;
    IF role_count <> 3 OR namespace_count <> 1 THEN
        RAISE EXCEPTION 'release_requires_three_roles_one_namespace' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_release AFTER INSERT ON control.releases
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION control.require_complete_release();
CREATE CONSTRAINT TRIGGER complete_release_files AFTER INSERT ON control.release_files
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION control.require_complete_release();

CREATE FUNCTION control.pin_lineage() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'DELETE' OR NEW.singleton IS DISTINCT FROM OLD.singleton
       OR (OLD.active_release_id IS NOT NULL
           AND NEW.active_release_id IS DISTINCT FROM OLD.active_release_id) THEN
        RAISE EXCEPTION 'active_lineage_is_pinned' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER pin_lineage BEFORE UPDATE OR DELETE ON control.lineage
    FOR EACH ROW EXECUTE FUNCTION control.pin_lineage();

CREATE FUNCTION control.protect_terminal() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF OLD.status IN ('complete', 'completed', 'succeeded', 'noop', 'failed', 'interrupted') THEN
        RAISE EXCEPTION 'terminal_record_is_immutable' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER terminal_preparation BEFORE UPDATE OR DELETE ON control.preparations
    FOR EACH ROW EXECUTE FUNCTION control.protect_terminal();
CREATE TRIGGER terminal_batch BEFORE UPDATE OR DELETE ON control.batches
    FOR EACH ROW EXECUTE FUNCTION control.protect_terminal();
CREATE TRIGGER terminal_run BEFORE UPDATE OR DELETE ON control.runs
    FOR EACH ROW EXECUTE FUNCTION control.protect_terminal();
CREATE TRIGGER terminal_model BEFORE UPDATE OR DELETE ON control.models
    FOR EACH ROW EXECUTE FUNCTION control.protect_terminal();

CREATE FUNCTION control.guard_staging() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE target uuid;
BEGIN
    target := CASE WHEN TG_OP = 'DELETE' THEN OLD.preparation_id ELSE NEW.preparation_id END;
    PERFORM 1 FROM control.preparations WHERE preparation_id = target
        AND status = 'preparing' FOR SHARE;
    IF NOT FOUND OR (TG_OP = 'UPDATE' AND NEW.preparation_id <> OLD.preparation_id) THEN
        RAISE EXCEPTION 'preparation_not_writable' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['staging.articles', 'staging.customers',
        'staging.purchase_records', 'staging.customer_observations', 'quality.rejections'] LOOP
        EXECUTE format('CREATE TRIGGER preparation_writable BEFORE INSERT OR UPDATE OR DELETE '
            'ON %s FOR EACH ROW EXECUTE FUNCTION control.guard_staging()', target);
    END LOOP;
END $$;

CREATE FUNCTION control.require_active_release() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    PERFORM 1 FROM control.lineage WHERE singleton AND active_release_id = NEW.release_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'release_not_active' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['control.preparations', 'control.batches', 'mart.articles',
        'mart.customers', 'mart.customer_observations', 'mart.purchase_events', 'control.models'] LOOP
        EXECUTE format('CREATE TRIGGER active_release BEFORE INSERT ON %s '
            'FOR EACH ROW EXECUTE FUNCTION control.require_active_release()', target);
    END LOOP;
END $$;

CREATE FUNCTION control.guard_batch_input() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    PERFORM 1 FROM control.preparations WHERE preparation_id = NEW.preparation_id
        AND release_id = NEW.release_id AND status = 'complete' FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'complete_preparation_required' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER complete_input BEFORE INSERT OR UPDATE ON control.batches
    FOR EACH ROW EXECUTE FUNCTION control.guard_batch_input();

CREATE FUNCTION control.guard_fact_batch() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE event_date date;
BEGIN
    IF TG_TABLE_NAME = 'purchase_events' THEN
        event_date := NEW.purchase_date;
    ELSE
        event_date := NEW.first_observed_date;
    END IF;
    PERFORM 1 FROM control.batches WHERE batch_id = NEW.first_batch_id
        AND release_id = NEW.release_id AND status = 'pending'
        AND start_date <= event_date AND event_date < end_date FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'pending_batch_with_matching_window_required' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER fact_batch BEFORE INSERT ON mart.purchase_events
    FOR EACH ROW EXECUTE FUNCTION control.guard_fact_batch();
CREATE TRIGGER observation_batch BEFORE INSERT ON mart.customer_observations
    FOR EACH ROW EXECUTE FUNCTION control.guard_fact_batch();

CREATE FUNCTION control.require_published_batch() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    PERFORM 1 FROM control.batches WHERE batch_id = NEW.first_batch_id AND status = 'completed';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'facts_require_completed_batch_at_commit' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER published_fact AFTER INSERT ON mart.purchase_events
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION control.require_published_batch();
CREATE CONSTRAINT TRIGGER published_observation AFTER INSERT ON mart.customer_observations
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION control.require_published_batch();

CREATE FUNCTION control.guard_membership() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    PERFORM 1 FROM control.batches b JOIN mart.purchase_events p
        ON p.transaction_file_id = NEW.transaction_file_id
        AND p.source_record_number = NEW.source_record_number
        AND p.release_id = b.release_id
    WHERE b.batch_id = NEW.batch_id AND b.release_id = NEW.release_id AND b.status = 'pending'
        AND b.start_date <= p.purchase_date AND p.purchase_date < b.end_date FOR SHARE OF b;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'membership_requires_pending_matching_batch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER membership_batch BEFORE INSERT ON control.batch_records
    FOR EACH ROW EXECUTE FUNCTION control.guard_membership();

CREATE FUNCTION control.reconcile_completed_batch() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE members bigint; inserted bigint;
BEGIN
    IF NEW.status = 'completed' THEN
        SELECT count(*) INTO members FROM control.batch_records WHERE batch_id = NEW.batch_id;
        SELECT count(*) INTO inserted FROM mart.purchase_events WHERE first_batch_id = NEW.batch_id;
        IF members <> NEW.accepted_rows OR inserted <> NEW.inserted_rows
           OR EXISTS (SELECT 1 FROM mart.purchase_events p WHERE p.first_batch_id = NEW.batch_id
               AND NOT EXISTS (SELECT 1 FROM control.batch_records m WHERE m.batch_id = NEW.batch_id
                   AND m.transaction_file_id = p.transaction_file_id
                   AND m.source_record_number = p.source_record_number)) THEN
            RAISE EXCEPTION 'batch_reconciliation_failed' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER reconcile_batch AFTER INSERT OR UPDATE ON control.batches
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION control.reconcile_completed_batch();

CREATE FUNCTION control.guard_successful_run() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.status IN ('succeeded', 'noop') AND NOT EXISTS (
        SELECT 1 FROM control.batches WHERE batch_id = NEW.batch_id AND status = 'completed') THEN
        RAISE EXCEPTION 'successful_run_requires_completed_batch' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER successful_run AFTER INSERT OR UPDATE ON control.runs
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION control.guard_successful_run();

CREATE FUNCTION control.guard_recommendation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE cutoff date;
BEGIN
    SELECT cutoff_date INTO cutoff FROM control.models
        WHERE model_id = NEW.model_id AND release_id = NEW.release_id AND status = 'complete';
    IF cutoff IS NULL OR NOT EXISTS (SELECT 1 FROM mart.purchase_events
        WHERE release_id = NEW.release_id AND article_id = NEW.article_id AND purchase_date <= cutoff)
        OR NOT EXISTS (SELECT 1 FROM mart.customer_observations
            WHERE release_id = NEW.release_id AND customer_id = NEW.customer_id
                AND first_observed_date <= cutoff) THEN
        RAISE EXCEPTION 'complete_model_past_item_and_known_customer_required' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER recommendation_eligible BEFORE INSERT ON serving.recommendations
    FOR EACH ROW EXECUTE FUNCTION control.guard_recommendation();
