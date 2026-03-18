def validate_trace(events):
    """
    Buggy reference implementation: it tracks only that ACQUIRE happened once.
    It never models the required lease epoch token before mutation.
    """
    saw_acquire = False
    epoch_seen = False
    for event in events:
        if event == "ACQUIRE":
            saw_acquire = True
            epoch_seen = False
        elif event == "EPOCH":
            if not saw_acquire:
                return False
            epoch_seen = True
        elif event == "RELEASE":
            if not saw_acquire:
                return False
        elif event == "MUTATE":
            if not saw_acquire or not epoch_seen:
                return False
        else:
            return False
    return True
