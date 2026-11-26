-- Feature 02 (branch 009): the gold set and the results table
-- (specs/009-evaluation-set/data-model.md). No pipeline stage is added: the comparison
-- only reads the results of the stages. The gold follows its document (ON DELETE
-- CASCADE); the results table does not reference documents: it is the history of
-- measurements and stays whole (FR-014).

-- Every load of a file into the gold set or the questions.
CREATE TABLE gold_load (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          text        NOT NULL CHECK (kind IN ('review', 'template', 'blind', 'questions')),
    file_name     text        NOT NULL CHECK (file_name <> ''),
    file_sha256   char(64)    NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    gold_sha256   char(64)    NOT NULL CHECK (gold_sha256 ~ '^[0-9a-f]{64}$'),
    counts        jsonb       NOT NULL
);

-- One row per marked pair «document, field»; an unmarked pair has no row.
CREATE TABLE gold_field (
    document_id        text    NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    field              text    NOT NULL CHECK (field <> ''),
    state              text    NOT NULL CHECK (state IN ('value', 'absent')),
    values_text        text[]  NOT NULL,
    values_normalized  text[]  NOT NULL,
    path               text    NOT NULL CHECK (path IN (
                           'agree', 'confirmed', 'chosen', 'typed', 'absent_marked', 'template')),
    -- the normalized feature 05 value shown on the card when the analyst answered
    system_normalized  text    NULL,
    clause_key         text    NULL CHECK (clause_key <> ''),
    load_id            bigint  NOT NULL REFERENCES gold_load (id) ON DELETE RESTRICT,
    PRIMARY KEY (document_id, field),
    CHECK ((state = 'absent') = (cardinality(values_text) = 0)),
    CHECK (cardinality(values_text) = cardinality(values_normalized))
);

-- The documents of the blind control and their blind values (not part of the gold).
CREATE TABLE blind_pick (
    document_id  text        PRIMARY KEY REFERENCES document (id) ON DELETE CASCADE,
    picked_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE gold_blind (
    document_id        text    NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    field              text    NOT NULL CHECK (field <> ''),
    state              text    NOT NULL CHECK (state IN ('value', 'absent')),
    values_text        text[]  NOT NULL,
    values_normalized  text[]  NOT NULL,
    load_id            bigint  NOT NULL REFERENCES gold_load (id) ON DELETE RESTRICT,
    PRIMARY KEY (document_id, field),
    CHECK ((state = 'absent') = (cardinality(values_text) = 0)),
    CHECK (cardinality(values_text) = cardinality(values_normalized))
);

-- Gold questions; the key is stable between loads (research R-11).
CREATE TABLE gold_question (
    key            text     PRIMARY KEY CHECK (key ~ '^Q-[0-9a-f]{10}$'),
    document_id    text     NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    text           text     NOT NULL CHECK (text <> ''),
    kind           text     NOT NULL DEFAULT 'text' CHECK (kind IN ('text', 'table', 'both')),
    has_answer     boolean  NOT NULL,
    false_premise  boolean  NOT NULL DEFAULT false,
    expected       text[]   NOT NULL DEFAULT '{}',
    clause_keys    text[]   NOT NULL DEFAULT '{}',
    origin         text     NOT NULL CHECK (origin IN ('own', 'set08', 'set09', 'generated')),
    source_file    text     NOT NULL CHECK (source_file <> ''),
    load_id        bigint   NOT NULL REFERENCES gold_load (id) ON DELETE RESTRICT,
    CHECK (has_answer OR cardinality(clause_keys) = 0)
);

-- A record of the results table and its cases.
CREATE TABLE eval_result (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at        timestamptz NOT NULL DEFAULT now(),
    label             text        NOT NULL DEFAULT '',
    stage             text        NOT NULL CHECK (stage IN (
                          'fields', 'rules', 'search_plain', 'search_rerank', 'gold_blind')),
    provenance        jsonb       NOT NULL,
    gold_sha256       char(64)    NULL CHECK (gold_sha256 ~ '^[0-9a-f]{64}$'),
    questions_sha256  char(64)    NULL CHECK (questions_sha256 ~ '^[0-9a-f]{64}$'),
    reviewed_share    numeric     NULL CHECK (reviewed_share BETWEEN 0 AND 1),
    blind_summary     jsonb       NULL,
    metrics           jsonb       NOT NULL,
    review_file       text        NULL,
    from_file         text        NULL
);

CREATE TABLE eval_case (
    result_id     bigint   NOT NULL REFERENCES eval_result (id) ON DELETE CASCADE,
    case_key      text     NOT NULL CHECK (case_key <> ''),
    document_id   text     NOT NULL,
    field         text     NULL,
    question_key  text     NULL,
    outcome       text     NULL CHECK (outcome IN (
                      'correct', 'wrong', 'missed', 'invented', 'unlabeled', 'no_result', 'manual',
                      'same', 'differs', 'blind_only', 'reviewed_only')),
    place         integer  NULL CHECK (place >= 1),
    flags         text[]   NOT NULL DEFAULT '{}',
    gold_sha      char(16) NOT NULL CHECK (gold_sha ~ '^[0-9a-f]{16}$'),
    PRIMARY KEY (result_id, case_key)
);
