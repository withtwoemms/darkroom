Feature: note lifecycle
  Scenario: a note is created, retrievable, and archivable
    Given a note is created
    Then its id comes back and fetching it shows the text, never the token
    When it is archived, twice
    Then it reads archived both times
    And the surfaces hold:
      """surfaces
      POST /notes                  → 201 {id, token}
      GET /notes/{id}              → 200 {id, text, archived}; no token
      POST /notes/{id}/archive     → 200 {archived: true}, idempotent
      """
