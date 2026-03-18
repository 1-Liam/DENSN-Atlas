def validate_trace(trace, module_count, start_token="START", update_token="UPDATE", finish_token="FINISH"):
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
