Feature: a device that has refused the telling says so
  Scenario: the page names the refusal rather than failing silently
    Given the device has refused to be told
    Then the telling page says so on open, and offers no address
    When the control is pressed anyway
    Then the page still says the device refused, naming what the browser answered
