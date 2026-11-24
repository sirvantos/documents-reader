-- Feature 07 (branch 006): passages, labels and indexes, minimal version
-- (specs/006-passages-and-indexes/data-model.md). The stage `indexing` exists since 0001.
-- Results reference document with ON DELETE CASCADE and run with ON DELETE RESTRICT.
CREATE EXTENSION IF NOT EXISTS vector;

-- One passage per parse record with own text (research R-3), and its word-index entry.
-- The text is not copied: it is document_text.text[start:end_]. No foreign key to
-- `clause`: `parse` rewrites a document's clauses with DELETE + INSERT, and readers check
-- source_text_sha256 and structure_run_id themselves (research R-7).
CREATE TABLE passage (
    document_id         text      NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    clause_key          text      NOT NULL CHECK (clause_key <> ''),
    ordinal             integer   NOT NULL CHECK (ordinal >= 0),
    part                text      NOT NULL CHECK (part IN ('preamble', 'main', 'tail')),
    start               integer   NOT NULL CHECK (start >= 0),
    end_                integer   NOT NULL,
    first_page          integer   NOT NULL,
    last_page           integer   NOT NULL,
    label               text      NOT NULL CHECK (label <> ''),
    lemmas              text      NOT NULL CHECK (lemmas <> ''),
    -- the word index (research R-5); ranking is chosen in feature 08
    tsv                 tsvector  GENERATED ALWAYS AS (to_tsvector('simple', lemmas)) STORED,
    source_text_sha256  char(64)  NOT NULL CHECK (source_text_sha256 ~ '^[0-9a-f]{64}$'),
    structure_run_id    bigint    NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    run_id              bigint    NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    PRIMARY KEY (document_id, clause_key),
    UNIQUE (document_id, ordinal),
    CHECK (end_ > start),
    CHECK (1 <= first_page AND first_page <= last_page)
);

CREATE INDEX passage_tsv_idx ON passage USING gin (tsv);

-- The meaning-index entry of a passage: one vector per model (research R-6). No ANN
-- index: a few thousand vectors are searched exactly (feature 08 decides by measurement).
CREATE TABLE passage_vector (
    document_id   text     NOT NULL,
    clause_key    text     NOT NULL,
    model         text     NOT NULL CHECK (model <> ''),
    embedding     vector   NOT NULL,
    dims          integer  NOT NULL CHECK (dims > 0 AND dims = vector_dims(embedding)),
    input_chars   integer  NOT NULL CHECK (input_chars > 0),
    truncated     boolean  NOT NULL,
    run_id        bigint   NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    PRIMARY KEY (document_id, clause_key, model),
    FOREIGN KEY (document_id, clause_key) REFERENCES passage (document_id, clause_key)
        ON DELETE CASCADE
);
