"""Course-wide passage sampling for an empty-topic generation (T033).

When the user asks for a generation with no topic, retrieval.retrieve has
nothing to search for and returns no passages (an empty FTS match). This
module covers that case: given every source's passages in reading order
(one group per document or lecture), it samples across all of them so the
material spans the whole course instead of stopping at the first source.
Pure: no I/O, callers (sbobina.web.course_retrieval.sample_course) build the
groups from the index and the job store.
"""

from collections import deque
from collections.abc import Sequence

from sbobina.retrieval import RetrievedPassage


def _bisection_order(length: int) -> list[int]:
    """Indices 0..length-1 ordered so every prefix is spread across the span.

    Breadth-first midpoint bisection: the two endpoints come first, then the
    midpoint of the remaining span, then the midpoints of each half, and so
    on. A short prefix of this order already touches the start, the middle
    and the end instead of walking sequentially from the first item.
    """
    if length <= 0:
        return []
    order: list[int] = []
    seen: set[int] = set()
    for endpoint in (0, length - 1):
        if endpoint not in seen:
            order.append(endpoint)
            seen.add(endpoint)
    queue: deque[tuple[int, int]] = deque([(0, length - 1)])
    while queue:
        low, high = queue.popleft()
        if high - low <= 1:
            continue
        mid = (low + high) // 2
        if mid not in seen:
            order.append(mid)
            seen.add(mid)
        queue.append((low, mid))
        queue.append((mid, high))
    return order


def _fill_from_group(
    group: Sequence[RetrievedPassage],
    order: list[int],
    cursor: int,
    remaining_words: int,
) -> tuple[int, int] | None:
    """Next (position, cursor_after) from order[cursor:] that fits the budget.

    Passages that do not fit are skipped (not retried later): the caller
    moves on to the next source for this round, matching a round-robin, not
    a best-fit search.
    """
    while cursor < len(order):
        position = order[cursor]
        cursor += 1
        words = len(group[position].text.split())
        if words <= remaining_words:
            return position, cursor
    return None


def sample_across_sources(
    groups: Sequence[Sequence[RetrievedPassage]], budget_words: int
) -> list[RetrievedPassage]:
    """Round-robin sample across sources, each visited in a spread order.

    Every group is one source (a document or a lecture), its passages
    already in reading order. One round picks at most one passage per
    group: within a group, a passage that would overflow the budget is
    skipped in favour of the next one in that same round (unlike
    retrieval.cut_to_budget, which stops at the first overflow). The result
    stays ordered by (group, position in the source) so the prompt reads in
    the order the material was written.
    """
    orders = [_bisection_order(length=len(group)) for group in groups]
    cursors = [0] * len(groups)
    picked: list[tuple[int, int]] = []
    used_words = 0
    progressed = True
    while progressed:
        progressed = False
        for group_index, group in enumerate(groups):
            found = _fill_from_group(
                group=group,
                order=orders[group_index],
                cursor=cursors[group_index],
                remaining_words=budget_words - used_words,
            )
            if found is None:
                continue
            position, cursors[group_index] = found
            picked.append((group_index, position))
            used_words += len(group[position].text.split())
            progressed = True
    picked.sort()
    return [groups[group_index][position] for group_index, position in picked]
