def validate_trace(events):
    """
    Buggy reference implementation: it remembers only that ACQUIRE happened once.
    It does not model the hidden lease-live state correctly after RELEASE.
    """
    saw_acquire = False
    for event in events:
        if event == "ACQUIRE":
            saw_acquire = True
        elif event == "RELEASE":
            if not saw_acquire:
                return False
        elif event == "MUTATE" and not saw_acquire:
            return False
        else:
            return False
    return True
