Feature: the notes page wears each note's state
  Scenario: a note reads draft until it is archived, and the page names the latest state
    Given a note is created
    Then the page lists it as not archived, and names its state as draft
    When it is archived
    Then the page lists it as archived, and names its state as archived
