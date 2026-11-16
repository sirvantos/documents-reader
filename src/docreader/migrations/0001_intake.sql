-- Feature 001: document intake and registry (specs/001-document-intake/data-model.md).
-- Applied by `docreader migrate`; schema_migrations is created by the runner (db.py).

-- Processing runs (FR-012). Never deleted, also not when documents are removed.
CREATE TABLE run (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stage           text        NOT NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz NULL,
    code_version    text        NOT NULL,
    model           text        NULL,
    prompt_version  text        NULL,
    settings        jsonb       NOT NULL,
    label           text        NULL
);

-- Document ID counter (research R-3): a single row that only grows,
-- so an ID is never reused, not even after the last document is removed.
CREATE TABLE document_counter (
    singleton  boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    last_seq   integer NOT NULL DEFAULT 0 CHECK (last_seq >= 0)
);
INSERT INTO document_counter (singleton, last_seq) VALUES (true, 0);

-- One contract (FR-003…FR-006).
CREATE TABLE document (
    id                  text        PRIMARY KEY CHECK (id ~ '^D-[0-9]{4,}$'),
    seq                 integer     NOT NULL UNIQUE,
    sha256              char(64)    NOT NULL UNIQUE CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    original_name       text        NOT NULL,
    source_path         text        NOT NULL,
    copy_path           text        NOT NULL,
    size_bytes          bigint      NOT NULL CHECK (size_bytes > 0),
    page_count          integer     NOT NULL CHECK (page_count > 0),
    added_at            timestamptz NOT NULL DEFAULT now(),
    note                text        NULL,
    -- Reserved; the CHECK is lifted by the feature that starts filling it.
    parent_document_id  text        NULL
                        REFERENCES document (id) ON DELETE SET NULL
                        CHECK (parent_document_id IS NULL),
    intake_run_id       bigint      NOT NULL REFERENCES run (id) ON DELETE RESTRICT
);
CREATE INDEX document_original_name_lower_idx ON document (lower(original_name));

-- Pages and their kind (FR-007); metrics are stored so `reclassify` needs no file access.
CREATE TABLE page (
    document_id           text    NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    page_number           integer NOT NULL CHECK (page_number >= 1),
    kind                  text    NOT NULL CHECK (kind IN ('text', 'scan', 'scan_with_text')),
    char_count            integer NOT NULL CHECK (char_count >= 0),
    image_coverage        real    NOT NULL CHECK (image_coverage >= 0 AND image_coverage <= 1),
    invisible_text_share  real    NULL
                          CHECK (invisible_text_share >= 0 AND invisible_text_share <= 1),
    kind_run_id           bigint  NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    PRIMARY KEY (document_id, page_number)
);

-- State of each document processing stage (FR-008).
-- The stage list must match docreader.db.STAGES.
CREATE TABLE stage_status (
    document_id  text        NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    stage        text        NOT NULL
                 CHECK (stage IN ('reading', 'structure', 'extraction', 'checks', 'indexing')),
    state        text        NOT NULL DEFAULT 'pending'
                 CHECK (state IN ('pending', 'done', 'needs_review', 'failed')),
    reason       text        NULL,
    run_id       bigint      NULL REFERENCES run (id) ON DELETE RESTRICT,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, stage),
    CONSTRAINT stage_status_reason_required
        CHECK (state IN ('pending', 'done') OR (reason IS NOT NULL AND btrim(reason) <> ''))
);

-- Deletion journal (FR-011). No FK: the document no longer exists.
CREATE TABLE deletion_log (
    id             bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id    text        NOT NULL,
    original_name  text        NOT NULL,
    sha256         char(64)    NOT NULL,
    deleted_at     timestamptz NOT NULL DEFAULT now()
);
