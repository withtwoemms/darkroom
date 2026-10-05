Feature: deletion is token-guarded
  Scenario: only the holder of the note's token may delete it
    Given a note created with its secret token
    When a wrong token tries to delete it
    Then the deletion is refused and the note survives
    When the right token deletes it
    Then the note is gone
