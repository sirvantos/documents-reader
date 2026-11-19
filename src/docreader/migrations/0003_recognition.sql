-- Feature 13 (branch 003): scan page recognition (specs/003-scan-recognition/data-model.md).
-- Results reference page with ON DELETE CASCADE and run with ON DELETE RESTRICT.

-- New stage `recognition`, first in pipeline order; must match docreader.stages.Stage.
ALTER TABLE stage_status DROP CONSTRAINT stage_status_stage_check;
ALTER TABLE stage_status ADD CONSTRAINT stage_status_stage_check
    CHECK (stage IN ('recognition', 'reading', 'structure', 'extraction', 'checks', 'indexing'));
INSERT INTO stage_status (document_id, stage) SELECT id, 'recognition' FROM document;

-- One recognised scan page; one row per page, replaced on re-recognition (FR-008, FR-012).
CREATE TABLE page_recognition (
    document_id          text        NOT NULL,
    page_number          integer     NOT NULL,
    engine               text        NOT NULL CHECK (btrim(engine) <> ''),
    engine_version       text        NOT NULL CHECK (btrim(engine_version) <> ''),
    dpi                  smallint    NOT NULL CHECK (dpi BETWEEN 72 AND 1200),
    turn                 smallint    NOT NULL CHECK (turn IN (0, 90, 180, 270)),
    orientation_unknown  boolean     NOT NULL DEFAULT false,
    lines                jsonb       NOT NULL CHECK (jsonb_typeof(lines) = 'array'),
    quality              real        NULL CHECK (quality BETWEEN 0 AND 1),
    ink_share            real        NULL CHECK (ink_share BETWEEN 0 AND 1),
    result_sha256        char(64)    NOT NULL CHECK (result_sha256 ~ '^[0-9a-f]{64}$'),
    seconds              real        NOT NULL CHECK (seconds >= 0),
    error                text        NULL CHECK (error IS NULL OR btrim(error) <> ''),
    run_id               bigint      NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    recognized_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, page_number),
    FOREIGN KEY (document_id, page_number)
        REFERENCES page (document_id, page_number) ON DELETE CASCADE,
    CHECK (error IS NULL OR (jsonb_array_length(lines) = 0 AND quality IS NULL))
);

-- Where the lines of a read page come from (research R-7); old rows are PDF text.
ALTER TABLE page_text
    ADD COLUMN source text NOT NULL DEFAULT 'pdf' CHECK (source IN ('pdf', 'recognized'));

-- Two new page flags (research R-8).
ALTER TABLE page_flag DROP CONSTRAINT page_flag_code_check;
ALTER TABLE page_flag ADD CONSTRAINT page_flag_code_check
    CHECK (code IN ('scan_unread', 'ocr_text', 'unreadable', 'maybe_not_russian', 'empty',
                    'reading_order_unknown', 'low_recognition_quality', 'scan_no_text'));
