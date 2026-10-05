Feature: notes page
  Scenario: a note saved through the page appears in the list
    Given the page titled "Relay Notes" renders its empty-state form
    When a note is typed and Save is clicked
    Then the note shows in the list, visibly
