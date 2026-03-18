def validate_trace(events):
    saw_prepare = False
    clear_seen = False
    for event in events:
        if event == "PREPARE":
            saw_prepare = True
            clear_seen = False
        elif event == "CLEAR":
            if not saw_prepare:
                return False
            clear_seen = True
        elif event.startswith("ACK_"):
            if not saw_prepare:
                return False
        elif event == "COMMIT":
            if not saw_prepare or not clear_seen:
                return False
        else:
            return False
    return True
