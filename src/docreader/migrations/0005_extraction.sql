-- Feature 05 (branch 005): field extraction, minimal version
-- (specs/005-field-extraction/data-model.md). The stage `extraction` exists since 0001.
-- Results reference document with ON DELETE CASCADE and run with ON DELETE RESTRICT.

-- The result of one prototype field of one document: exactly six rows per extracted
-- document, replaced as a whole when the document is extracted again. No foreign key to
-- `clause`: `parse` rewrites a document's clauses with DELETE + INSERT, and readers check
-- `clause_key` against the parse themselves (data-model.md).
CREATE TABLE field_value (
    document_id         text      NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    field               text      NOT NULL CHECK (field IN (
                            'contract_number', 'customer_name_short', 'contractor_name_short',
                            'amount_without_vat', 'amount_with_vat', 'contract_end_date')),
    result              text      NOT NULL
                        CHECK (result IN ('found', 'not_found', 'rejected', 'failed')),
    value_text          text      NULL,
    value_normalized    text      NULL,
    quote               text      NULL,
    quote_start         integer   NULL,
    quote_end           integer   NULL,
    clause_key          text      NULL,
    page                integer   NULL,
    pages               integer[] NULL,
    reason              text      NULL,
    proposed_value      text      NULL,
    proposed_quote      text      NULL,
    proposed_clause     text      NULL,
    source_text_sha256  char(64)  NOT NULL CHECK (source_text_sha256 ~ '^[0-9a-f]{64}$'),
    run_id              bigint    NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    PRIMARY KEY (document_id, field),
    -- principle III: a found value always has its quote and its place
    CHECK (result <> 'found' OR (
        value_text IS NOT NULL AND value_normalized IS NOT NULL AND quote IS NOT NULL
        AND quote_start IS NOT NULL AND quote_end IS NOT NULL AND clause_key IS NOT NULL
        AND page IS NOT NULL AND pages IS NOT NULL AND reason IS NULL
        AND quote_start >= 0 AND quote_start < quote_end)),
    -- everything but a found value has no accepted value, quote or place
    CHECK (result = 'found' OR (
        value_text IS NULL AND value_normalized IS NULL AND quote IS NULL
        AND quote_start IS NULL AND quote_end IS NULL AND clause_key IS NULL
        AND page IS NULL AND pages IS NULL)),
    CHECK (result <> 'not_found' OR (
        reason IS NULL AND proposed_value IS NULL AND proposed_quote IS NULL
        AND proposed_clause IS NULL)),
    CHECK (result NOT IN ('rejected', 'failed') OR reason IS NOT NULL),
    CHECK (result <> 'failed' OR (
        proposed_value IS NULL AND proposed_quote IS NULL AND proposed_clause IS NULL))
);
