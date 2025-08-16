"""Helpers for generating Label Studio configuration XML."""

from typing import Any, Iterable, Mapping


def build_ls_config(fields: Iterable[Mapping[str, Any]]) -> str:
    """Render a Label Studio project configuration from taxonomy fields."""
    lines: list[str] = ["<View>", '<Text name="text" value="$text"/>']
    for field in fields:
        helptext = str(field.get("helptext") or "")
        examples: Iterable[str] = field.get("examples") or []
        help_lines: list[str] = []
        if helptext:
            help_lines.append(f"<Help>{helptext}</Help>")
        for ex in examples:
            help_lines.append(f"<Example>{ex}</Example>")
        if field["type"] == "enum":
            lines.append(f'<Choices name="{field["name"]}" toName="text">')
            lines.extend(help_lines)
            options: Iterable[str] = field.get("options") or []
            for opt in options:
                lines.append(f'<Choice value="{opt}"/>')
            lines.append("</Choices>")
        else:
            lines.append(f'<TextArea name="{field["name"]}" toName="text">')
            lines.extend(help_lines)
            lines.append("</TextArea>")
    lines.append("</View>")
    return "\n".join(lines)


__all__ = ["build_ls_config"]
