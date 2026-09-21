Feature: note lifecycle
  Scenario: a note is created, retrievable, and archivable
    Creating a note returns its id; fetching shows the text without the
    secret token; archiving marks it archived, idempotently.
