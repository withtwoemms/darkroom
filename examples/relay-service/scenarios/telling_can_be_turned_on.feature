Feature: the telling page can be turned on, read back, and turned off
  Scenario: a device agrees to be told, stays told across a reload, and stops
    Given the telling page says it has not asked yet
    When the device is asked and agrees
    Then the page shows the address it was given
    When the page is opened again
    Then it still shows the same address, without asking again
    When the telling is stopped
    Then the page says it is off and holds no address
