def validate_trace(events):
    """
    Buggy reference implementation: it remembers GRANT and BALANCE once seen.
    It does not model the hidden credit-live state correctly after REVOKE.
    """
    saw_grant = False
    saw_balance = False
    for event in events:
        if event == "GRANT":
            saw_grant = True
            saw_balance = False
        elif event == "BALANCE":
            if not saw_grant:
                return False
            saw_balance = True
        elif event == "REVOKE":
            if not saw_grant:
                return False
        elif event == "CHARGE" and not (saw_grant and saw_balance):
            return False
        else:
            return False
    return True
