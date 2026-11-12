"""Template variables (tinted-theming names plus roles) and the Mustache subset."""

import pytest

from mood_engine import template


def test_context_has_tinted_theming_variables(firebox):
    ctx = template.context(firebox)
    assert ctx["scheme-name"] == "FireBox" and ctx["scheme-slug"] == "firebox"
    assert ctx["scheme-system"] == "base24" and ctx["scheme-variant"] == "dark"
    assert ctx["scheme-is-dark-variant"] is True and ctx["scheme-is-light-variant"] is False
    assert ctx["base08-hex"] == "cc241d" and ctx["base08-hex-bgr"] == "1d24cc"
    assert (ctx["base08-hex-r"], ctx["base08-rgb-g"], ctx["base08-dec-b"]) == ("cc", "36", "0.11372549")
    assert ctx["base17-hex"] == "d3869b"


def test_context_has_roles_with_overrides(firebox):
    ctx = template.context(firebox)
    assert ctx["role-accent-hex"] == "fe8019"  # FireBox maps accent to base09
    assert ctx["role-error-hex"] == "ff8678"   # a literal override
    assert ctx["role-bg-rgb-r"] == "17"


def test_render_variables_sections_and_comments(firebox, solarized_light):
    src = ("{{! a comment }}bg=#{{base00-hex}} {{{scheme-name}}} {{& scheme-slug}}\n"
           "{{#scheme-is-dark-variant}}dark{{/scheme-is-dark-variant}}"
           "{{^scheme-is-dark-variant}}light{{/scheme-is-dark-variant}}\n")
    assert template.render(src, template.context(firebox)) == "bg=#111111 FireBox firebox\ndark\n"
    assert template.render(src, template.context(solarized_light)).endswith("light\n")


def test_standalone_tag_lines_disappear(firebox):
    src = "a\n  {{#scheme-is-light-variant}}\nlight only\n  {{/scheme-is-light-variant}}\nb\n"
    assert template.render(src, template.context(firebox)) == "a\nb\n"


def test_nested_sections(firebox):
    ctx = {**template.context(firebox), "flag": False}
    src = "{{#scheme-is-dark-variant}}x{{#flag}}y{{/flag}}{{^flag}}z{{/flag}}{{/scheme-is-dark-variant}}"
    assert template.render(src, ctx) == "xz"


def test_unknown_variables_and_bad_sections_are_errors(firebox):
    ctx = template.context(firebox)
    with pytest.raises(template.TemplateError, match="base0g-hex"):
        template.render("{{base0g-hex}}", ctx)
    with pytest.raises(template.TemplateError, match="unclosed"):
        template.render("{{#scheme-is-dark-variant}}", ctx)
    with pytest.raises(template.TemplateError, match="unexpected"):
        template.render("{{/scheme-is-dark-variant}}", ctx)


def test_a_tinted_theming_style_template(firebox):
    src = """\
# Scheme: {{scheme-name}}
palette = 0=#{{base00-hex}}
palette = 1=#{{base08-hex}}
background = {{base00-hex}}
foreground = {{base05-hex}}
"""
    out = template.render(src, template.context(firebox))
    assert "palette = 1=#cc241d" in out and "foreground = ebdbb2" in out
