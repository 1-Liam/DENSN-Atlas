def validate_trace(events):
    """
    Buggy held-out variant: still missing a true guard-active state.
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
