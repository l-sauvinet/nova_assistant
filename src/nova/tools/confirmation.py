from typing import Protocol


class Confirmer(Protocol):
    """Asks the user to approve a destructive action, in the terminal or the desktop app's dialog.
    `warning` explains why the action may not come from the user (outside content read just before)."""

    def confirm(self, question: str, warning: str | None = None) -> bool: ...


class TerminalConfirmer:
    def confirm(self, question: str, warning: str | None = None) -> bool:
        if warning:
            print(f"\n{warning}")
        try:
            answer = input(f"\n⚠️  {question} [o/N] ").strip().lower()
        except EOFError:
            return False
        return answer in {"o", "oui", "y", "yes"}


class AlwaysDenyConfirmer:
    def confirm(self, question: str, warning: str | None = None) -> bool:
        return False
