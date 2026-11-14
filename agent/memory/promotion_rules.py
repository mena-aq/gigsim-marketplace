def should_promote_style_edit(edit_count: int, consistent_pattern: bool) -> bool:
    """Require one exact deletion in at least three distinct approved threads."""
    return edit_count >= 3 and consistent_pattern
