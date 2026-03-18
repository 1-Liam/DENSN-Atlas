def validate_trace(events):
    """
    Buggy reference implementation: it tracks only that a round started and
    that BARRIER appeared once. It never models the latent majority-ready state
    induced by multiple votes.
    """
    saw_propose = False
    barrier_seen = False
    for event in events:
        if event == "PROPOSE":
            saw_propose = True
            barrier_seen = False
        elif event == "BARRIER":
            if not saw_propose:
                return False
            barrier_seen = True
        elif event.startswith("VOTE_"):
            if not saw_propose:
                return False
        elif event == "DECIDE":
            if not saw_propose or not barrier_seen:
                return False
        else:
            return False
    return True
