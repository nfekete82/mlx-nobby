from backend.settings_ui_routes import SETTINGS_CSS, SETTINGS_SCRIPT, inject_settings_ui


def test_settings_ui_injection_adds_assets_once():
    source = b"<html><head><title>MLX</title></head><body><main>chat</main></body></html>"

    injected = inject_settings_ui(source)

    assert SETTINGS_CSS in injected
    assert SETTINGS_SCRIPT in injected
    assert injected.count(SETTINGS_CSS) == 1
    assert injected.count(SETTINGS_SCRIPT) == 1
    assert injected.index(SETTINGS_CSS) < injected.index(b"</head>")
    assert injected.index(SETTINGS_SCRIPT) < injected.index(b"</body>")

    reinjected = inject_settings_ui(injected)
    assert reinjected.count(SETTINGS_CSS) == 1
    assert reinjected.count(SETTINGS_SCRIPT) == 1
