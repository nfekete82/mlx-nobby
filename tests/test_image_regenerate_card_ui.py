from pathlib import Path

from backend import image_regenerate_ui


ROOT = Path(__file__).resolve().parents[1]


def test_image_card_removes_fixed_three_variant_button():
    source = b"""    generation.createImageUpscaleMenu = source => {
        const fragment = document.createDocumentFragment();
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


def test_production_served_module_has_no_dangling_variant_references():
    import subprocess
    from fastapi.testclient import TestClient
    from backend.entrypoint import app

    source = (ROOT / "frontend/assets/chat/image-settings.js").read_bytes()
    patched = image_regenerate_ui.patch_image_settings_source(source)
    assert patched != source
    wrapper = patched.split(b"generation.createImageUpscaleMenu = source => {", 1)[1]
    wrapper = wrapper.split(b"return fragment;", 1)[0]
    assert b"variants" not in wrapper
    assert b"regenerate.addEventListener" in wrapper
    assert b"fragment.append(regenerate, enhanceMenu)" in wrapper
    assert b"async function generateImageVariants" in patched
    assert image_regenerate_ui.patch_image_settings_source(patched) == patched
    with TestClient(app, base_url="http://localhost") as client:
        served = client.get("/assets/chat/image-settings.js?v=regression")
    assert served.status_code == 200
    assert served.content == patched
    assert int(served.headers["content-length"]) == len(patched)
    subprocess.run(["node", "--input-type=commonjs", "-e", r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(0, 'utf8');
const start = source.indexOf('    generation.createImageUpscaleMenu = source => {');
const end = source.indexOf('        return fragment;', start) + '        return fragment;'.length;
class Element {
  constructor() { this.children = []; this.listeners = {}; this.isConnected = true; }
  append(...children) { this.children.push(...children); }
  addEventListener(name, listener) { this.listeners[name] = listener; }
}
const context = {generation: {}, document: {createElement: () => new Element(), createDocumentFragment: () => new Element()},
  originalCreateImageUpscaleMenu: () => new Element(), imageT: (_key, fallback) => fallback,
  regenerateImageArtifact: async () => false};
vm.runInNewContext(source.slice(start, end) + '\n    };', context);
const card = context.generation.createImageUpscaleMenu({prompt: 'create an image of a woman'});
if (card.children.length !== 2) throw new Error('Missing regeneration or enhancement control');
card.children[0].listeners.click().then(() => {
  if (card.children[0].disabled) throw new Error('Failed regeneration must remain retryable');
});
"""], input=served.content, check=True, capture_output=True)


def test_unknown_card_module_is_served_intact():
    source = (ROOT / "frontend/assets/chat/image-settings.js").read_bytes()
    changed = source.replace(b"variants.addEventListener('click'", b"variants.addEventListener('pointerup'")
    assert image_regenerate_ui.patch_image_settings_source(changed) == changed


def test_served_variant_runtime_executes_real_batches(tmp_path):
    import subprocess
    from email.utils import formatdate
    from fastapi.testclient import TestClient
    from backend.entrypoint import app

    source = ROOT / "frontend/assets/chat/image-settings.js"
    # Prior middleware responses retained this source timestamp, allowing a
    # browser to reuse broken transformed bytes after a middleware-only fix.
    validators = {"If-Modified-Since": formatdate(source.stat().st_mtime, usegmt=True),
                  "If-None-Match": '"old-transformed-script"', "Range": "bytes=0-10"}
    with TestClient(app, base_url="http://localhost") as client:
        served = client.get("/assets/chat/image-settings.js?v=20261002-gallery-final", headers=validators)
    assert served.status_code == 200
    assert served.headers["cache-control"] == "no-store"
    assert "last-modified" not in served.headers
    assert "etag" not in served.headers
    assert int(served.headers["content-length"]) == len(served.content)
    assert served.content == image_regenerate_ui.patch_image_settings_source(source.read_bytes())
    module = tmp_path / "served-image-settings.js"
    module.write_bytes(served.content)
    subprocess.run(["node", str(ROOT / "tests/test_image_variant_served.mjs"), str(module)],
                   cwd=ROOT, check=True, capture_output=True, text=True)
