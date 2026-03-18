def validate_trace(
    trace,
    module_count,
    start_token="OPEN_BATCH",
    update_token="STEP",
    finish_token="CLOSE_BATCH",
):
    expected = []
    for index in range(1, module_count + 1):
        expected.extend(
            [
                f"{start_token}_{index}",
                f"{update_token}_{index}",
                f"{finish_token}_{index}",
            ]
        )
    return trace == expected
