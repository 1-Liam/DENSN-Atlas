def validate_trace(events):
    """
    Buggy reference implementation: it remembers only that START_SESSION happened once.
    It does not model the hidden epoch-live state correctly after FINISH_SESSION.
    """
    saw_start = False
    for event in events:
        if event == "START_SESSION":
            saw_start = True
        elif event == "FINISH_SESSION":
            if not saw_start:
                return False
        elif event == "UPDATE" and not saw_start:
            return False
        else:
            return False
    return True
