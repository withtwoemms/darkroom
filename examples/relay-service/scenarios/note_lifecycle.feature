Feature: note lifecycle
  Scenario: a note is created, retrievable, and archivable
    Given a note is created
    Then its id comes back and fetching it shows the text, never the token
    When it is archived, twice
    Then it reads archived both times
