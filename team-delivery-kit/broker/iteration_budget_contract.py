"""Controller work cannot use a toolless summary as budget recovery."""


def bounded_failure(mode, fallback_eligible):
    return (mode in ('implementation','review','diagnostic')
            and fallback_eligible is True)
