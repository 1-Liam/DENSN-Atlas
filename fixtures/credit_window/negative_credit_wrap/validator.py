def validate_trace(events):
    """
    Simplified validator for the negative-transfer family with no BALANCE token.
    """
    active = False
    for event in events:
        if event == "GRANT":
            if active:
                return False
            active = True
        elif event == "REVOKE":
            if not active:
                return False
            active = False
        elif event == "CHARGE" and not active:
            return False
        else:
            return False
    return not active
