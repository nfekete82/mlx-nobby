"""Phase-local LTX progress must not pretend to be overall render progress."""

import pytest

from ltx_progress import ProgressTail, parse_progress


def test_ancestral_denoising_is_only_phase_progress():
    result = parse_progress("Denoising (ancestral):  67%|██████▋   | 2/3 [03:12<01:36, 96.10s/it]")
    assert result["phase"] == "generating"
    assert result["current_step"] == 2
    assert result["total_steps"] == 3
    assert result["phase_progress"] == pytest.approx(2 / 3)
    assert result["progress"] is None
    assert result["progress_scope"] == "phase"


def test_vae_decode_resets_previous_sampler_percentage():
    for line in (
        "[vae-decode tiling] frames=40/8 px=768/64 est. 13.3 GB budget=24.0 GB",
        "[vae-decode tiling] peak Metal memory 17.53 GB",
    ):
        result = parse_progress(line)
        assert result["phase"] == "decoding"
        assert result["phase_progress"] is None
        assert result["current_step"] is None
        assert result["total_steps"] is None
        assert result["progress_message"] == "LTX dekodiert Videoframes"


def test_tail_switches_from_denoising_to_indeterminate_decode(tmp_path):
    path = tmp_path / "stage.partial.log"
    path.write_text(
        "Denoising (ancestral):  67%|██████▋   | 2/3 [03:12<01:36, 96.10s/it]\n",
        encoding="utf-8",
    )
    reader = ProgressTail(path)
    assert reader.read()["current_step"] == 2
    with path.open("a", encoding="utf-8") as stream:
        stream.write("[vae-decode tiling] frames=40/8 px=768/64 est. 13.3 GB budget=24.0 GB\n")
    decoded = reader.read()
    assert decoded["phase"] == "decoding"
    assert decoded["phase_progress"] is None
    assert decoded["current_step"] is None
    assert reader.read() == {}
