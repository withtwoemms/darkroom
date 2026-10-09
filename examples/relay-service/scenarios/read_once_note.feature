Feature: a read-once note is gone after its first read
  Scenario: the first read is the only read
    Given a note created as read-once
    When it is fetched
    Then the text comes back
    When it is fetched again
    Then it is gone, and the answer says why
    When someone tries to archive it
    Then that is refused the same way
