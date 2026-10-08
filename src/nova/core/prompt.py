def compose_system_prompt(base_prompt: str, context_sections: list[str]) -> str:
    """Appends runtime context (location, ...) provided by the user's device to the base prompt."""
    sections = [section for section in context_sections if section]
    if not sections:
        return base_prompt
    return base_prompt + "\n\n# Current context\n" + "\n".join(sections)
