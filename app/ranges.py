"""Parsing of the HTTP Range header (RFC 9110), single byte ranges only."""


class RangeNotSatisfiable(Exception):
    """The range is well-formed but lies outside the object."""


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """Return the inclusive (start, end) byte offsets that `header` asks for.

    Returns None for a header we don't understand (another unit, several
    ranges, bad syntax). The RFC says to ignore those and send the whole object.
    """
    unit, _, spec = header.partition("=")
    first, dash, last = spec.strip().partition("-")
    if unit.strip() != "bytes" or not dash or "," in spec:
        return None
    if not all(part == "" or part.isdecimal() for part in (first, last)):
        return None

    if first == "":
        if last == "":
            return None
        # Suffix range, "bytes=-N": the last N bytes.
        length = int(last)
        if length == 0:
            raise RangeNotSatisfiable(header)
        return max(size - length, 0), size - 1

    start = int(first)
    # Open-ended "bytes=N-" runs to the end; an end past the object is clamped.
    end = min(int(last), size - 1) if last else size - 1
    if start >= size:
        raise RangeNotSatisfiable(header)
    if start > end:
        return None
    return start, end
