"""Markdown → Telegram HTML Converter.

Handles: headers, bold, italic, inline code, code blocks,
horizontal rules, LaTeX math expressions, and HTML entity escaping.
"""

import re


# Map of LaTeX commands to Unicode equivalents.
LATEX_SYMBOLS = {
    # Greek letters (lowercase)
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
    r"\theta": "θ", r"\vartheta": "ϑ", r"\iota": "ι", r"\kappa": "κ",
    r"\lambda": "λ", r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ",
    r"\pi": "π", r"\rho": "ρ", r"\sigma": "σ", r"\tau": "τ",
    r"\upsilon": "υ", r"\phi": "φ", r"\varphi": "φ", r"\chi": "χ",
    r"\psi": "ψ", r"\omega": "ω",
    # Greek letters (uppercase)
    r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ", r"\Lambda": "Λ",
    r"\Xi": "Ξ", r"\Pi": "Π", r"\Sigma": "Σ", r"\Phi": "Φ",
    r"\Psi": "Ψ", r"\Omega": "Ω",
    # Comparison / relational operators
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\sim": "∼",
    r"\equiv": "≡", r"\propto": "∝", r"\ll": "≪", r"\gg": "≫",
    # Arrows
    r"\rightarrow": "→", r"\to": "→", r"\leftarrow": "←",
    r"\leftrightarrow": "↔", r"\Rightarrow": "⇒", r"\Leftarrow": "⇐",
    r"\Leftrightarrow": "⇔", r"\uparrow": "↑", r"\downarrow": "↓",
    r"\mapsto": "↦",
    # Set / logic operators
    r"\in": "∈", r"\notin": "∉", r"\subset": "⊂", r"\supset": "⊃",
    r"\subseteq": "⊆", r"\supseteq": "⊇", r"\cup": "∪", r"\cap": "∩",
    r"\emptyset": "∅", r"\forall": "∀", r"\exists": "∃",
    r"\neg": "¬", r"\land": "∧", r"\lor": "∨",
    # Math operators
    r"\times": "×", r"\div": "÷", r"\cdot": "·", r"\pm": "±",
    r"\mp": "∓", r"\sqrt": "√", r"\infty": "∞", r"\partial": "∂",
    r"\nabla": "∇", r"\sum": "∑", r"\prod": "∏", r"\int": "∫",
    # Misc
    r"\degree": "°", r"\circ": "°", r"\star": "★", r"\bullet": "•",
    r"\ldots": "…", r"\cdots": "⋯", r"\dots": "…",
}


def markdown_to_telegram_html(text: str) -> str:
    """Convert standard Markdown to Telegram-compatible HTML.

    Handles: headers, bold, italic, inline code, code blocks,
    horizontal rules, LaTeX math expressions, and HTML entity escaping.
    """
    # Use §§ delimiters for placeholders — cannot collide with markdown syntax
    code_blocks = []

    def _save_code_block(m):
        idx = len(code_blocks)
        code = m.group(1)
        # Escape HTML inside code blocks
        code = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        code_blocks.append(f"<pre>{code}</pre>")
        return f"§§CB{idx}§§"

    text = re.sub(r"```(?:\w*)\n(.*?)```", _save_code_block, text, flags=re.DOTALL)

    # Protect inline code
    inline_codes = []

    def _save_inline_code(m):
        idx = len(inline_codes)
        code = m.group(1)
        code = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        inline_codes.append(f"<code>{code}</code>")
        return f"§§IC{idx}§§"

    text = re.sub(r"`([^`]+)`", _save_inline_code, text)

    # --- LaTeX math handling ---
    def _convert_latex(m):
        """Convert a LaTeX math expression to Unicode text."""
        content = m.group(1)
        # Replace LaTeX commands with Unicode (longest match first to avoid partial replacements)
        for latex_cmd, unicode_char in sorted(LATEX_SYMBOLS.items(), key=lambda x: -len(x[0])):
            content = content.replace(latex_cmd, unicode_char)
        # Clean up remaining LaTeX artifacts
        content = re.sub(r"\\(?:text|mathrm|mathbf|textbf)\{([^}]*)\}", r"\1", content)  # \text{...} → ...
        content = re.sub(r"[{}]", "", content)      # Remove stray braces
        content = content.replace("\\\\", "\n")       # Double backslash → newline
        content = content.replace("\\,", " ")         # Thin space
        content = content.replace("\\;", " ")         # Thick space
        content = content.replace("\\ ", " ")          # Explicit space
        content = re.sub(r"\\[a-zA-Z]+", "", content)  # Remove any remaining unknown \commands
        return content.strip()

    # Convert display math ($$...$$) first, then inline math ($...$)
    text = re.sub(r"\$\$(.+?)\$\$", _convert_latex, text, flags=re.DOTALL)
    text = re.sub(r"\$(.+?)\$", _convert_latex, text)

    # Also handle standalone LaTeX commands outside of $...$ (common in LLM output)
    for latex_cmd, unicode_char in sorted(LATEX_SYMBOLS.items(), key=lambda x: -len(x[0])):
        text = text.replace(latex_cmd, unicode_char)

    # Escape HTML entities in remaining text
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Headers → bold text
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Bold: **text**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Italic: *text* (not inside words)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)

    # Horizontal rules
    text = re.sub(r"^-{3,}$", "━━━━━━━━━━━━━━━━━━━", text, flags=re.MULTILINE)

    # Restore code blocks and inline code
    for idx, block in enumerate(code_blocks):
        text = text.replace(f"§§CB{idx}§§", block)
    for idx, code in enumerate(inline_codes):
        text = text.replace(f"§§IC{idx}§§", code)

    return text
