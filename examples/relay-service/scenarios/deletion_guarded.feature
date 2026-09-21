Feature: deletion is token-guarded
  Scenario: only the holder of the note's token may delete it
    Deleting with a wrong token is refused and the note survives;
    deleting with the right token succeeds and the note is gone.
