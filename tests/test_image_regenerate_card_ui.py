from pathlib import Path

from backend import image_regenerate_ui


ROOT = Path(__file__).resolve().parents[1]


def test_image_card_removes_fixed_three_variant_button():
    source = b"""        const fragment = document.createDocumentFragment();
        const regenerate = document.createElement('button');
        const variants = document.createElement('button');

        regenerate.type = 'button';
        regenerate.className = 'message-action-btn';
        regenerate.textContent = imageT(
            'ui.regenerate',
            'Regenerate'
        );
        regenerate.title = regenerate.textContent;

        variants.type = 'button';
        variants.className = 'message-action-btn';
        variants.textContent = '3\xc3\x97 ' + imageT(
            'ui.regenerate',
            'Regenerate'
        );
        variants.title = variants.textContent;

        regenerate.addEventListener('click', async () => {
            regenerate.disabled = true;
            variants.disabled = true;
            const originalLabel = regenerate.textContent;
            const started = await regenerateImageArtifact(source);

            if (!started && regenerate.isConnected) {
                regenerate.disabled = false;
                variants.disabled = false;
                regenerate.textContent = originalLabel;
            }
        });

        variants.addEventListener('click', async () => {
            regenerate.disabled = true;
            variants.disabled = true;
            const originalLabel = variants.textContent;
            variants.textContent = imageT(
                'common.loading',
                'Loading\xe2\x80\xa6'
            );

            const started = await generateImageVariants(source, 3);

            if (!started && variants.isConnected) {
                regenerate.disabled = false;
                variants.disabled = false;
                variants.textContent = originalLabel;
            }
        });

        fragment.append(regenerate, variants, enhanceMenu);
"""

    patched = image_regenerate_ui.patch_image_settings_source(source)

    assert b"const regenerate = document.createElement('button')" in patched
    assert b"const variants = document.createElement('button')" not in patched
    assert b"3\xc3\x97 " not in patched
    assert b"variants.addEventListener" not in patched
    assert b"variants.disabled" not in patched
    assert b"fragment.append(regenerate, enhanceMenu);" in patched


def test_variant_generation_runtime_is_not_removed():
    source = b"""    async function generateImageVariants(artifact, count = 3) {
        return true;
    }
"""

    assert image_regenerate_ui.patch_image_settings_source(source) == source


def test_production_backend_installs_image_regenerate_ui():
    source = (ROOT / "backend" / "entrypoint.py").read_text(encoding="utf-8")

    assert "from backend.image_regenerate_ui import ImageRegenerateUiMiddleware" in source
    assert "app.add_middleware(ImageRegenerateUiMiddleware)" in source
