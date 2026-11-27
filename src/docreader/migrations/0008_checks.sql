-- Feature 06 (branch 010): rule checks, field statuses and analyst decisions
-- (specs/010-rule-checks/data-model.md). field_value and gold_field are not changed:
-- the checks of a document are replaced as a whole by each `check`, a decision keeps the
-- system value it was taken on, and every row follows its document (ON DELETE CASCADE).

-- The outcome of every rule on every field of a checked document.
CREATE TABLE field_check (
    document_id  text    NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    field        text    NOT NULL CHECK (field IN (
                     'contract_number', 'customer_name_short', 'contractor_name_short',
                     'amount_without_vat', 'amount_with_vat', 'contract_end_date')),
    rule         text    NOT NULL CHECK (rule <> ''),
    outcome      text    NOT NULL CHECK (outcome IN ('passed', 'violated', 'not_applied')),
    reason       text    NULL CHECK (reason IS NULL OR reason <> ''),
    run_id       bigint  NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    PRIMARY KEY (document_id, field, rule)
);

-- The status of a field and what it was computed from (research R-6, R-7).
CREATE TABLE field_status (
    document_id        text      NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    field              text      NOT NULL CHECK (field IN (
                           'contract_number', 'customer_name_short', 'contractor_name_short',
                           'amount_without_vat', 'amount_with_vat', 'contract_end_date')),
    status             text      NOT NULL
                       CHECK (status IN ('accepted', 'needs_review', 'rejected', 'not_found')),
    reasons            text[]    NOT NULL DEFAULT '{}',
    flags              text[]    NOT NULL DEFAULT '{}',
    extraction_run_id  bigint    NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    checks_version     text      NOT NULL CHECK (checks_version <> ''),
    settings_sha256    char(64)  NOT NULL CHECK (settings_sha256 ~ '^[0-9a-f]{64}$'),
    run_id             bigint    NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    PRIMARY KEY (document_id, field)
);

-- The analyst's decision on a field, never written over the system value (FR-008).
CREATE TABLE field_decision (
    document_id        text         NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    field              text         NOT NULL CHECK (field IN (
                           'contract_number', 'customer_name_short', 'contractor_name_short',
                           'amount_without_vat', 'amount_with_vat', 'contract_end_date')),
    kind               text         NOT NULL CHECK (kind IN ('confirm', 'correct', 'absent')),
    value_text         text         NULL,
    value_normalized   text         NULL,
    clause_key         text         NULL,
    system_result      text         NOT NULL
                       CHECK (system_result IN ('found', 'not_found', 'rejected', 'failed')),
    system_normalized  text         NULL,
    answers_sha256     char(64)     NOT NULL CHECK (answers_sha256 ~ '^[0-9a-f]{64}$'),
    decided_at         timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, field),
    -- a correction carries its value; the other decisions carry none
    CHECK ((kind = 'correct') = (value_text IS NOT NULL AND value_normalized IS NOT NULL)),
    CHECK (kind = 'correct' OR (value_text IS NULL AND value_normalized IS NULL
                                AND clause_key IS NULL))
);

-- The usefulness report is a record of the results table (research R-10).
ALTER TABLE eval_result DROP CONSTRAINT eval_result_stage_check;
ALTER TABLE eval_result ADD CONSTRAINT eval_result_stage_check CHECK (stage IN (
    'fields', 'rules', 'search_plain', 'search_rerank', 'gold_blind', 'checks'));

ALTER TABLE eval_case DROP CONSTRAINT eval_case_outcome_check;
ALTER TABLE eval_case ADD CONSTRAINT eval_case_outcome_check CHECK (outcome IN (
    'correct', 'wrong', 'missed', 'invented', 'unlabeled', 'no_result', 'manual',
    'same', 'differs', 'blind_only', 'reviewed_only',
    'queued_wrong', 'queued_right', 'accepted_wrong', 'accepted_right'));
