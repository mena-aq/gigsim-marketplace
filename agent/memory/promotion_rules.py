PROMOTION_THRESHOLD = 3
PROMOTION_RULE = (
    "An exact sentence you deleted is promoted to a style rule only after the same "
    f"deletion appears in {PROMOTION_THRESHOLD} distinct approved proposals."
)


def should_promote_style_edit(edit_count: int, consistent_pattern: bool) -> bool:
    """Require one exact deletion in at least three distinct approved threads."""
    return edit_count >= PROMOTION_THRESHOLD and consistent_pattern
