"""Persistent image models, deliberately independent of LLM aliases."""
import copy
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict, model_validator

REGISTRY_FILE = Path(
    os.environ.get(
        "MLX_IMAGE_REGISTRY",
        str(Path.home() / ".config/mlx-web/image-models.json"),
    )
).expanduser()
MODEL_ROOTS = (Path.home() / "Models", Path.home() / ".cache/huggingface/hub")
LEGACY_ID = "FLUX.1-schnell"
LEGACY_REPO = "argmaxinc/mlx-FLUX.1-schnell-4bit-quantized"
QWEN_IMAGE_EDIT_ID = "mflux-qwen-image-edit-2511"
QWEN_IMAGE_EDIT_DEFAULT_STEPS = 8
MLXSERVE_QWEN_IMAGE21_ID = "mlxserve-qwen-image-2.1"
MLXSERVE_QWEN_IMAGE21_REPO = "ddalcu/Qwen-Image-2.1-MLX-Serve-4bit"
MLXSERVE_QWEN_IMAGE21_DEFAULT_STEPS = 20
JUGGERNAUT_XL_ID = "juggernaut-xl"
JUGGERNAUT_XL_DIRECTORY = Path.home() / "Models/JuggernautXL"
BUILTIN_DEFAULTS_REVISION = 3
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
REPO_PATTERN = re.compile(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\Z")
FAMILIES = {
    "flux1": (
        "mflux-generate",
        ("schnell", "dev"),
    ),
    "flux2-klein": (
        "mflux-generate-flux2",
        (
            "flux2-klein-4b",
            "flux2-klein-9b",
            "flux2-klein-base-4b",
            "flux2-klein-base-9b",
        ),
    ),
    "z-image": (
        "mflux-generate-z-image",
        ("z-image",),
    ),
    "z-image-turbo": (
        "mflux-generate-z-image-turbo",
        ("z-image-turbo",),
    ),
    "qwen-image": (
        "mflux-generate-qwen",
        ("qwen-image",),
    ),
    "qwen-image-edit": (
        "mflux-generate-qwen-edit",
        (
            "qwen-image-edit",
            "qwen-image-edit-2509",
            "qwen-image-edit-2511",
            "qwen-edit",
            "qwen-edit-2509",
            "qwen-edit-2511",
            "qwen-edit-plus",
        ),
    ),
}
_mutex = threading.RLock()


def validate_id(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value) or value == "auto":
        raise ValueError("Ungültige Image-Modell-ID")
    return value


def validate_path(value, *, file=False):
    source = Path(value).expanduser()

    if not source.is_absolute():
        raise ValueError("Ein absoluter lokaler Pfad ist erforderlich")

    if file and source.suffix != ".safetensors":
        raise ValueError("LoRA-Dateien müssen Safetensors sein")

    resolved = source.resolve()

    if not any(
        resolved.is_relative_to(root.resolve())
        for root in MODEL_ROOTS
    ):
        raise ValueError(
            "Modell-/LoRA-Pfade müssen unter ~/Models "
            "oder im Hugging-Face-Cache liegen"
        )

    # Keep the user-visible snapshot path instead of replacing a
    # Hugging Face symlink with its extensionless blob target.
    return str(source)


class LoRA(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    path: str | None = None
    repository: str | None = None
    scale: float = Field(default=1.0, ge=-2, le=2)
    enabled: bool = True
    trigger_word: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def check_source(self):
        if bool(self.path) == bool(self.repository):
            raise ValueError("LoRA benötigt genau einen Pfad oder ein Repository")
        if self.path:
            self.path = validate_path(self.path, file=True)
        if self.repository:
            repo, _, filename = self.repository.partition(":")
            if not REPO_PATTERN.fullmatch(repo) or (filename and not re.fullmatch(r"[A-Za-z0-9_.-]+\.safetensors", filename)):
                raise ValueError("Ungültiges LoRA-Repository (org/model[:datei.safetensors])")
        return self


class ImageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str
    name: str = Field(min_length=1, max_length=120)
    provider: Literal["diffusionkit", "mflux", "sdxl", "mlxserve"]
    repository: str | None = None
    local_path: str | None = None
    model_family: str
    base_model: str = "schnell"
    quantization: Literal["none", "q3", "q4", "q5", "q6", "q8"] = "q4"
    quantize_on_load: bool = False
    enabled: bool = True
    capabilities: list[str] = Field(default_factory=lambda: ["text_to_image", "variation"])
    default_steps: int = Field(default=4, ge=1, le=50)
    default_guidance: float = Field(default=0, ge=0, le=10)
    loras: list[LoRA] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def check_model(self):
        validate_id(self.id)
        if not self.repository and not self.local_path:
            raise ValueError("Repository oder lokaler Modellpfad fehlt")
        if self.repository and not REPO_PATTERN.fullmatch(self.repository):
            raise ValueError("Ungültiges Modell-Repository")
        if self.local_path:
            self.local_path = validate_path(self.local_path)
        if self.provider == "diffusionkit":
            if self.repository != LEGACY_REPO or self.local_path or self.model_family != "flux1" or self.base_model != "schnell" or self.quantization != "q4":
                raise ValueError("DiffusionKit unterstützt hier den bewährten FLUX.1-schnell-Q4-Pfad")
            if any(lora.enabled for lora in self.loras):
                raise ValueError("Der DiffusionKit-Fallback unterstützt keine LoRAs")
            if self.default_steps > 8:
                raise ValueError("DiffusionKit schnell: maximal 8 Steps")
        elif self.provider == "mlxserve":
            if (
                self.repository != MLXSERVE_QWEN_IMAGE21_REPO
                or self.local_path
                or self.model_family != "qwen-image21"
                or self.base_model != "qwen-image-2.1"
                or self.quantization != "q4"
                or self.quantize_on_load
                or any(lora.enabled for lora in self.loras)
            ):
                raise ValueError(
                    "Qwen Image 2.1/MLX-Serve benötigt den vorgesehenen "
                    "4-bit-Repository-Eintrag ohne LoRAs"
                )
            if self.default_guidance != 0:
                raise ValueError(
                    "Qwen Image 2.1/MLX-Serve verwendet standardmäßig Guidance 0"
                )
        elif self.provider == "sdxl":
            if (
                self.repository
                or not self.local_path
                or self.model_family != "sdxl"
                or self.base_model != "sdxl"
                or self.quantization != "none"
                or any(lora.enabled for lora in self.loras)
            ):
                raise ValueError("SDXL benötigt einen lokalen Checkpoint ohne LoRAs oder Quantisierung")
        elif self.model_family not in FAMILIES or self.base_model not in FAMILIES[self.model_family][1]:
            raise ValueError("Nicht unterstützte MFLUX-Modellfamilie/Basismodell-Kombination")
        if self.model_family == "flux2-klein" and "base" not in self.base_model and self.default_guidance != 1:
            raise ValueError("FLUX.2 Klein distilled benötigt Guidance 1")
        # Capabilities describe adapter support, never arbitrary HTTP claims.
        if self.provider == "mlxserve":
            self.capabilities = [
                "text_to_image",
            ]
        elif self.model_family == "qwen-image-edit":
            self.capabilities = [
                "image_edit",
                "multi_image_edit",
                "masked_edit",
                "reframe",
                "outpaint",
            ]

            if self.provider == "mflux":
                self.capabilities += [
                    "lora",
                    "multi_lora",
                ]
        elif self.provider == "sdxl":
            self.capabilities = [
                "text_to_image",
                "variation",
                "photorealistic",
                "people",
                "portrait",
                "fashion",
            ]
        else:
            self.capabilities = [
                "text_to_image",
                "variation",
            ]

            if self.provider == "mflux":
                self.capabilities += [
                    "lora",
                    "multi_lora",
                ]

        return self


def builtin_models():
    """Return safe, opt-in registry entries without downloading any weights.

    These entries describe the model families understood by the installed MFLUX
    runtime.  They deliberately start disabled; a user must have the matching
    local snapshot before activating one.  The DiffusionKit entry is kept as
    the always-on legacy fallback.
    """
    models = [ImageModel(
        id=LEGACY_ID,
        name="FLUX.1-schnell · bewährter Fallback",
        provider="diffusionkit",
        repository=LEGACY_REPO,
        model_family="flux1",
    ).model_dump()]
    for ident, name, repo, family, base, steps, guidance in (
        ("mflux-flux1-schnell", "FLUX.1-schnell · MFLUX", "black-forest-labs/FLUX.1-schnell", "flux1", "schnell", 4, 0),
        ("mflux-flux1-dev", "FLUX.1-dev · MFLUX", "black-forest-labs/FLUX.1-dev", "flux1", "dev", 28, 3.5),
        ("mflux-flux2-klein-4b", "FLUX.2 Klein 4B", "black-forest-labs/FLUX.2-klein-4B", "flux2-klein", "flux2-klein-4b", 4, 1),
        ("mflux-z-image", "Z-Image", "Tongyi-MAI/Z-Image", "z-image", "z-image", 30, 4),
        ("mflux-z-image-turbo", "Z-Image Turbo", "Tongyi-MAI/Z-Image-Turbo", "z-image-turbo", "z-image-turbo", 9, 0),
        ("mflux-qwen-image", "Qwen Image 2512", "Qwen/Qwen-Image-2512", "qwen-image", "qwen-image", 30, 3.5),
        (
            QWEN_IMAGE_EDIT_ID,
            "Qwen Image Edit 2511 · 4-bit",
            "AbstractFramework/qwen-image-edit-2511-4bit",
            "qwen-image-edit",
            "qwen-image-edit-2511",
            QWEN_IMAGE_EDIT_DEFAULT_STEPS,
            3.5,
        ),
        (
            "mflux-qwen-image-edit-2511-quality",
            "Qwen Image Edit 2511 · Quality · 8-bit",
            "Qwen/Qwen-Image-Edit-2511",
            "qwen-image-edit",
            "qwen-image-edit-2511",
            QWEN_IMAGE_EDIT_DEFAULT_STEPS,
            3.5,
        ),
    ):
        model_kwargs = dict(
            id=ident,
            name=name,
            provider="mflux",
            repository=repo,
            model_family=family,
            base_model=base,
            default_steps=steps,
            default_guidance=guidance,
            enabled=False,
        )

        if ident == "mflux-qwen-image-edit-2511-quality":
            model_kwargs["quantization"] = "q8"
            model_kwargs["quantize_on_load"] = True

        models.append(
            ImageModel(**model_kwargs).model_dump()
        )
    models.append(ImageModel(
        id=MLXSERVE_QWEN_IMAGE21_ID,
        name="Qwen Image 2.1 · MLX-Serve · 4-bit",
        provider="mlxserve",
        repository=MLXSERVE_QWEN_IMAGE21_REPO,
        model_family="qwen-image21",
        base_model="qwen-image-2.1",
        quantization="q4",
        enabled=False,
        default_steps=MLXSERVE_QWEN_IMAGE21_DEFAULT_STEPS,
        default_guidance=0.0,
    ).model_dump())

    models.append(ImageModel(
        id=JUGGERNAUT_XL_ID,
        name="Juggernaut XL",
        provider="sdxl",
        local_path=str(JUGGERNAUT_XL_DIRECTORY),
        model_family="sdxl",
        base_model="sdxl",
        quantization="none",
        enabled=False,
        default_steps=30,
        default_guidance=7.0,
    ).model_dump())
    return models


def initial_registry():
    return {
        "version": 1,
        "builtin_defaults_revision": BUILTIN_DEFAULTS_REVISION,
        "default_model": LEGACY_ID,
        "models": builtin_models(),
    }


def _save(data):
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".image-models-", dir=REGISTRY_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, REGISTRY_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_registry():
    with _mutex:
        if not REGISTRY_FILE.exists():
            _save(initial_registry())
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("Nicht unterstützte Image-Registry-Version")
        data["models"] = [ImageModel(**model).model_dump() for model in data["models"]]
        defaults_changed = (
            data.get("builtin_defaults_revision", 0)
            < BUILTIN_DEFAULTS_REVISION
        )
        if defaults_changed:
            for model in data["models"]:
                # Migrate only the previously shipped value. Explicitly
                # configured alternatives remain untouched.
                if (
                    model["id"] == QWEN_IMAGE_EDIT_ID
                    and model["default_steps"] == 30
                ):
                    model["default_steps"] = QWEN_IMAGE_EDIT_DEFAULT_STEPS
            data["builtin_defaults_revision"] = BUILTIN_DEFAULTS_REVISION
        # Add newly supported built-in families to an existing registry while
        # preserving all user edits (enabled flags, LoRAs and custom entries).
        known_ids = {model["id"] for model in data["models"]}
        added = [model for model in builtin_models() if model["id"] not in known_ids]
        if added:
            data["models"].extend(added)
        if added or defaults_changed:
            _save(data)
        ids = [model["id"] for model in data["models"]]
        if len(ids) != len(set(ids)) or data["default_model"] not in ids:
            raise ValueError("Ungültige Image-Registry: IDs/Standardmodell")
        return data


def get_model(model_id="auto", *, require_enabled=True):
    data = load_registry()
    model_id = data["default_model"] if model_id == "auto" else validate_id(model_id)
    model = next((item for item in data["models"] if item["id"] == model_id), None)
    if model is None:
        raise KeyError("Unbekanntes Image-Modell")
    if require_enabled and not model["enabled"]:
        raise ValueError("Dieses Image-Modell ist deaktiviert")
    return copy.deepcopy(model)


def update_model(model_id, patch):
    with _mutex:
        model = get_model(model_id, require_enabled=False)
        if "id" in patch and patch["id"] != model_id:
            raise ValueError("Modell-IDs können nicht geändert werden")
        model = ImageModel(**(model | patch)).model_dump()
        data = load_registry()
        if model_id == LEGACY_ID and model != get_model(LEGACY_ID, require_enabled=False):
            raise ValueError("Der bewährte Fallback-Eintrag bleibt unverändert; weitere Modelle separat registrieren")
        if data["default_model"] == model_id and not model["enabled"]:
            raise ValueError("Das Standardmodell kann nicht deaktiviert werden")
        data["models"] = [model if item["id"] == model_id else item for item in data["models"]]
        _save(data)
        return model


def add_model(payload):
    with _mutex:
        model = ImageModel(**payload).model_dump()
        data = load_registry()
        if any(item["id"] == model["id"] for item in data["models"]):
            raise ValueError("Modell-ID bereits registriert")
        data["models"].append(model)
        _save(data)
        return model


def set_default(model_id):
    with _mutex:
        model = get_model(model_id)
        data = load_registry()
        data["default_model"] = model["id"]
        _save(data)
        return model
