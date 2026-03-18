def validate_trace(events):
    """
    Buggy reference implementation: it remembers only that BEGIN happened once.
    It does not model the hidden guard-active state correctly after END.
    """
    saw_begin = False
    for event in events:
        if event == "BEGIN":
            saw_begin = True
        elif event == "END":
            if not saw_begin:
                return False
        elif event == "WRITE" and not saw_begin:
            return False
        else:
            return False
    return True
