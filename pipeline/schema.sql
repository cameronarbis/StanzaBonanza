-- StanzaBonanza corpus schema. Ingestion owns DDL; the server only reads.
-- See docs/DESIGN.md section 4. (ASCII only here: this file is executed
-- verbatim and must survive any client_encoding.)

CREATE TABLE IF NOT EXISTS authors (
  id   SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS poems (
  id        SERIAL PRIMARY KEY,
  author_id INTEGER NOT NULL REFERENCES authors(id),
  title     TEXT NOT NULL,
  UNIQUE (author_id, title)
);

CREATE TABLE IF NOT EXISTS lines (
  id        SERIAL PRIMARY KEY,
  poem_id   INTEGER NOT NULL REFERENCES poems(id),
  text      TEXT NOT NULL,
  text_norm TEXT NOT NULL UNIQUE,
  valence   REAL NOT NULL CHECK (valence BETWEEN 0 AND 1),
  arousal   REAL NOT NULL CHECK (arousal BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS corpus_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
