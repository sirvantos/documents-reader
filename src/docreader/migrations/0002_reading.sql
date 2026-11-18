-- Feature 03 (branch 002): PDF text reading (specs/002-pdf-text-reading/data-model.md).
-- Feature 01 tables are not changed: stage 'reading' already exists in stage_status.
-- Results reference document/page with ON DELETE CASCADE and run with ON DELETE RESTRICT.

-- One read page: lines in reading order with their boxes (FR-001, FR-002).
CREATE TABLE page_text (
    document_id  text     NOT NULL,
    page_number  integer  NOT NULL,
    rotation     smallint NOT NULL CHECK (rotation IN (0, 90, 180, 270)),
    width        real     NOT NULL CHECK (width > 0),
    height       real     NOT NULL CHECK (height > 0),
    lines        jsonb    NOT NULL CHECK (jsonb_typeof(lines) = 'array'),
    has_table    boolean  NOT NULL,
    run_id       bigint   NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    PRIMARY KEY (document_id, page_number),
    FOREIGN KEY (document_id, page_number)
        REFERENCES page (document_id, page_number) ON DELETE CASCADE
);

-- Page quality flags (FR-006); a separate table so the report counts them with GROUP BY.
CREATE TABLE page_flag (
    document_id  text    NOT NULL,
    page_number  integer NOT NULL,
    code         text    NOT NULL
                 CHECK (code IN ('scan_unread', 'ocr_text', 'unreadable',
                                 'maybe_not_russian', 'empty', 'reading_order_unknown')),
    reason       text    NOT NULL CHECK (btrim(reason) <> ''),
    PRIMARY KEY (document_id, page_number, code),
    FOREIGN KEY (document_id, page_number)
        REFERENCES page_text (document_id, page_number) ON DELETE CASCADE
);

-- Clean text of the whole document (FR-003); text_sha256 detects a changed text (FR-012).
CREATE TABLE document_text (
    document_id  text     PRIMARY KEY REFERENCES document (id) ON DELETE CASCADE,
    text         text     NOT NULL,
    text_sha256  char(64) NOT NULL CHECK (text_sha256 ~ '^[0-9a-f]{64}$'),
    read_pages   integer  NOT NULL CHECK (read_pages >= 0),
    run_id       bigint   NOT NULL REFERENCES run (id) ON DELETE RESTRICT
);

-- Map from a range [start, end_) of document_text.text to a line of page_text.lines.
CREATE TABLE text_span (
    document_id  text    NOT NULL REFERENCES document_text (document_id) ON DELETE CASCADE,
    start        integer NOT NULL CHECK (start >= 0),
    end_         integer NOT NULL,
    page_number  integer NOT NULL,
    line_index   integer NOT NULL CHECK (line_index >= 0),
    PRIMARY KEY (document_id, start),
    CHECK (end_ > start)
);
CREATE INDEX text_span_document_end_idx ON text_span (document_id, end_);
