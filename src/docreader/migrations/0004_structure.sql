-- Feature 04 (branch 004): structure parsing (specs/004-structure-parsing/data-model.md).
-- The stage `structure` exists since 0001. Results reference document with
-- ON DELETE CASCADE and run with ON DELETE RESTRICT.

-- One record of a parsed document: the preamble, a section, a clause or subclause of any
-- depth, or the tail; replaced as a whole when the document is parsed again (FR-011).
CREATE TABLE clause (
    document_id         text      NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    key                 text      NOT NULL CHECK (btrim(key) <> ''),
    ordinal             integer   NOT NULL CHECK (ordinal >= 0),
    kind                text      NOT NULL
                        CHECK (kind IN ('preamble', 'section', 'clause', 'tail')),
    number_printed      text      NULL,
    number              integer[] NULL,
    depth               smallint  NOT NULL,
    parent_key          text      NULL,
    title               text      NULL,
    section_number      integer   NULL,
    section_title       text      NULL,
    start               integer   NOT NULL CHECK (start >= 0),
    end_                integer   NOT NULL,
    first_page          integer   NOT NULL,
    last_page           integer   NOT NULL,
    source_text_sha256  char(64)  NOT NULL CHECK (source_text_sha256 ~ '^[0-9a-f]{64}$'),
    run_id              bigint    NOT NULL REFERENCES run (id) ON DELETE RESTRICT,
    PRIMARY KEY (document_id, key),
    UNIQUE (document_id, ordinal),
    FOREIGN KEY (document_id, parent_key) REFERENCES clause (document_id, key),
    CHECK ((kind IN ('section', 'clause')) = (number IS NOT NULL AND number_printed IS NOT NULL)),
    CHECK (depth = coalesce(array_length(number, 1), 0)),
    CHECK (end_ > start),
    CHECK (first_page <= last_page)
);

-- A record by text offset (features 05, 07).
CREATE INDEX clause_document_start_idx ON clause (document_id, start);
