"""Built-in templates, presets, the example hooks.toml, `hooks --presets/--eject/--init`."""

import pytest

from mood_engine import cli, presets, sync, template

from .test_library import dirs, mac  # noqa: F401  (fixtures)


def write_hooks(dirs, body: str):
    (dirs / "config").mkdir(exist_ok=True)
    sync.hooks_path().write_text(body)


def test_every_preset_template_is_built_in_and_renders(firebox, solarized_light):
    for p in presets.PRESETS.values():
        path = presets.builtin_path(p.keys["template"])
        for t in (firebox, solarized_light):
            assert "{{" not in template.render(path.read_text(), template.context(t))
    assert presets.builtin_names() == ["colors.css", "ghostty", "theme.json", "zed.json"]
    with pytest.raises(KeyError):
        presets.builtin_path("builtin:nope")


def test_example_config_hooks_all_parse(tmp_path):
    """Uncommenting every example hook in hooks.example.toml gives a valid config."""
    lines, keep = [], False
    for line in presets.example_hooks().splitlines():
        if line == "# [[hook]]":
            keep = True
        elif keep and not (line.startswith("# ") and " = " in line):
            keep = False
        if keep:
            lines.append(line[2:])
    p = tmp_path / "hooks.toml"
    p.write_text("\n".join(lines) + "\n")
    hooks = {h.name: h for h in sync.load_hooks(p)}
    assert list(hooks) == ["Ghostty", "Zed", "CSS variables", "Theme JSON", "Alacritty", "my widget"]
    assert (hooks["Theme JSON"].notify, hooks["Theme JSON"].fade) == (presets.NOTIFY_NAME, 800)
    assert (hooks["Ghostty"].terminal, hooks["Ghostty"].fade, hooks["Ghostty"].run) == ("ghostty", 400, None)
    assert hooks["Zed"].fade == 1200 and hooks["Zed"].template == presets.builtin_path("zed.json")
    assert str(hooks["CSS variables"].output).endswith("somewhere/else/colors.css")
    assert hooks["Alacritty"].template == tmp_path / "templates" / "alacritty.toml"


def test_preset_fills_in_and_keys_override(dirs, mac):
    write_hooks(dirs, '[[hook]]\npreset = "zed"\nname = "Editor"\nfade = 300\n'
                      f'output = "{dirs / "zed.json"}"\n\n[[hook]]\npreset = "ghostty"\nenabled = false\n')
    zed, ghostty = sync.load_hooks()
    assert (zed.name, zed.fade, zed.output) == ("Editor", 300, dirs / "zed.json")
    assert zed.template == presets.builtin_path("zed.json") and zed.run is None
    assert ghostty.name == "Ghostty" and not ghostty.enabled
    sync.sync()                                   # the disabled Ghostty hook never runs
    assert '"name": "mood-engine"' in (dirs / "zed.json").read_text()


@pytest.mark.parametrize("body, msg", [
    ('preset = "kitty"', "unknown preset 'kitty'"),
    ("preset = 3", "unknown preset 3"),
    ('template = "builtin:kitty.conf"\noutput = "o"', "no built-in template 'kitty.conf'"),
    ('preset = "css"\nbogus = 1', "unknown key"),
])
def test_bad_presets_and_builtins(tmp_path, body, msg):
    p = tmp_path / "hooks.toml"
    p.write_text(f"[[hook]]\n{body}\n")
    with pytest.raises(sync.HookConfigError, match=msg):
        sync.load_hooks(p)


def test_builtin_fingerprint_names_the_template_not_the_install_path(dirs, mac):
    write_hooks(dirs, '[[hook]]\npreset = "css"\n')
    [h] = sync.load_hooks()
    content = h.template.read_bytes().hex()
    spec = {"name": "CSS variables", "run": None, "template": "builtin:colors.css",
            "output": h.output}
    assert sync.hook_fingerprint(h, "fp") == sync._sha("fp", spec, content)


def test_hooks_listing_presets_and_render(dirs, mac, capsys):
    write_hooks(dirs, '[[hook]]\npreset = "zed"\n')
    assert cli.main(["hooks"]) == 0
    assert "render builtin:zed.json → " in capsys.readouterr().out
    assert cli.main(["hooks", "--presets"]) == 0
    out = capsys.readouterr().out
    assert 'preset = "ghostty" stands for:' in out and "theme = mood-engine" in out
    assert 'terminal = "ghostty"' in out
    assert cli.main(["render", "builtin:nope"]) == 2


def test_eject_copies_once(dirs, mac, capsys):
    write_hooks(dirs, "")
    assert cli.main(["hooks", "--eject", "zed"]) == 0
    dest = dirs / "config" / "templates" / "zed.json"
    assert dest.read_text() == presets.builtin_path("zed.json").read_text()
    assert 'template = "templates/zed.json"' in capsys.readouterr().out
    dest.write_text("mine")
    assert cli.main(["hooks", "--eject", "builtin:zed.json"]) == 1 and dest.read_text() == "mine"
    assert cli.main(["hooks", "--eject", "builtin:ghostty"]) == 0
    assert (dirs / "config" / "templates" / "ghostty").exists()
    assert cli.main(["hooks", "--eject", "kitty"]) == 2


def test_init_writes_example_only_when_missing(dirs, mac, capsys):
    assert cli.main(["hooks", "--init"]) == 0
    assert sync.hooks_path().read_text() == presets.example_hooks()
    assert sync.load_hooks() == []                # everything in it is commented out
    sync.hooks_path().write_text("# mine\n")
    assert cli.main(["hooks", "--init"]) == 0
    assert sync.hooks_path().read_text() == "# mine\n"
    assert "--presets" in capsys.readouterr().out
