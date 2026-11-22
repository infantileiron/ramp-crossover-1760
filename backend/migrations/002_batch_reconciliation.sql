-- 采集批次对账：批次、对账台账、运行与发布的批次归属
CREATE TABLE IF NOT EXISTS collection_batch (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    route_code text NOT NULL REFERENCES field_route(code),
    label text NOT NULL,
    source text NOT NULL,
    created_by text NOT NULL REFERENCES app_user(username),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (route_code, label)
);
CREATE TABLE IF NOT EXISTS collection_entry (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id integer NOT NULL REFERENCES collection_batch(id),
    route_code text NOT NULL,
    code text NOT NULL,
    sequence text NOT NULL CHECK (sequence IN ('AB', 'BA')),
    period1 numeric(7,2) CHECK (period1 IS NULL OR (period1 > 0 AND period1 <= 900)),
    period2 numeric(7,2) CHECK (period2 IS NULL OR (period2 > 0 AND period2 <= 900)),
    kind text NOT NULL CHECK (kind IN ('register', 'supplement', 'modify', 'reupload')),
    prev_sequence text CHECK (prev_sequence IS NULL OR prev_sequence IN ('AB', 'BA')),
    prev_period1 numeric(7,2),
    prev_period2 numeric(7,2),
    prev_entry_id bigint,
    status text NOT NULL CHECK (status IN ('passed', 'missing', 'duplicate', 'sequence_conflict', 'conflict')),
    actor text NOT NULL REFERENCES app_user(username),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (period1 IS NOT NULL OR period2 IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS collection_entry_ledger_idx ON collection_entry (route_code, code, id);
ALTER TABLE field_pair ADD COLUMN IF NOT EXISTS batch_id integer REFERENCES collection_batch(id);
ALTER TABLE field_pair ADD COLUMN IF NOT EXISTS entry_id bigint REFERENCES collection_entry(id);
ALTER TABLE report ADD COLUMN IF NOT EXISTS batch_id integer REFERENCES collection_batch(id);
ALTER TABLE report ADD COLUMN IF NOT EXISTS batch_choice text CHECK (batch_choice IN ('original', 'latest_complete'));
ALTER TABLE report ADD COLUMN IF NOT EXISTS adopted_report_id integer REFERENCES report(id);
-- 既有台账回填：每条路线补一个「初始台账」批次，并为每行登记对账条目
DO $$
DECLARE
    r RECORD;
    b integer;
    u text;
BEGIN
    FOR r IN SELECT DISTINCT route_code FROM field_pair WHERE batch_id IS NULL LOOP
        SELECT username INTO u FROM app_user WHERE role='analyst' ORDER BY username LIMIT 1;
        IF u IS NULL THEN
            SELECT username INTO u FROM app_user ORDER BY username LIMIT 1;
        END IF;
        IF u IS NULL THEN
            CONTINUE;
        END IF;
        INSERT INTO collection_batch (route_code, label, source, created_by)
        VALUES (r.route_code, '初始台账', '既有台账迁移', u)
        ON CONFLICT (route_code, label) DO NOTHING
        RETURNING id INTO b;
        IF b IS NULL THEN
            SELECT id INTO b FROM collection_batch WHERE route_code=r.route_code AND label='初始台账';
        END IF;
        INSERT INTO collection_entry (batch_id, route_code, code, sequence, period1, period2, kind, status, actor)
        SELECT b, route_code, code, sequence, period1, period2, 'register',
               CASE WHEN period1 IS NOT NULL AND period2 IS NOT NULL THEN 'passed' ELSE 'missing' END, u
        FROM field_pair
        WHERE route_code=r.route_code AND batch_id IS NULL
        ORDER BY code;
        UPDATE field_pair AS fp
        SET batch_id=b, entry_id=ce.id
        FROM collection_entry AS ce
        WHERE ce.batch_id=b AND ce.route_code=fp.route_code AND ce.code=fp.code AND fp.batch_id IS NULL;
    END LOOP;
END $$;
