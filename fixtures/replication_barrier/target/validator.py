def validate_trace(events):
    """
    Buggy reference implementation: it tracks only that a stage started and
    that BARRIER appeared once. It never models the latent barrier-ready state
    induced by enough replica confirmations.
    """
    saw_stage = False
    barrier_seen = False
    for event in events:
        if event == "STAGE":
            saw_stage = True
            barrier_seen = False
        elif event == "BARRIER":
            if not saw_stage:
                return False
            barrier_seen = True
        elif event.startswith("REPLICA_"):
            if not saw_stage:
                return False
        elif event == "PUBLISH":
            if not saw_stage or not barrier_seen:
                return False
        else:
            return False
    return True
