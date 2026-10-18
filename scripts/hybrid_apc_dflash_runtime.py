#!/usr/bin/env python3
"""Experimental in-process APC+ DFlash2 prefill adapter for mlx-vlm==0.6.17.

IMPORTANT: This is an *opt-in research prototype*. It does not edit the installed
mlx_vlm package on disk. It patches ResponseGenerator._run_speculative in
memory before starting the ordinary one-worker MLX-VLM server. It fails
closed on version/source mismatches, and only applies APC to single-request,
text-only, exact-cache, DFlash2 prefill. Batched/multimodal requests retain
the upstream speculative path.

The generated method preserves the upstream loop/decoder. Only the prefill
segment is augmented. Correctness, memory safety, and performance MUST be
verified on the target Apple-Silicon hardware before production use.
"""
from __future__ import annotations

import argparse
import importlib
from importlib.metadata import version
import inspect
import os
import sys
import textwrap


SUPPORTED_VERSION = "0.6.17"
FLAG = "NOBBY_EXPERIMENTAL_HYBRID"
MARKER = "# NOBBY_HYBRID_APC_DFLASH_017"

# The string anchors deliberately reference the v0.6.17 speculative path.
# If the installed version has changed structure, abort before server startup.
ANCHOR_BEFORE_PREFILL = """                prompt_started = time.perf_counter()
                out, input_mx = _run_chunked_speculative_prefill(
"""
ANCHOR_STATS = '''                    logger.info(
                        "Prefill completed: request=%s prompt_tokens=%d "
                        "cached_tokens=0 elapsed=%.3fs rate=%.1f tok/s",'''
ANCHOR_STATS_ARGS = '''                        prompt_tokens,
                        prompt_elapsed,
                        float(prompt_tps_map[uid] or 0.0),'''

PREFILL_ADAPTER = '''
                # NOBBY_HYBRID_APC_DFLASH_017: exact-prefix only.
                hybrid_apc_manager = None
                hybrid_matched_tokens = 0
                hybrid_full_ids = None
                hybrid_hash = 0
                hybrid_eligible = (
                    B == 1
                    and draft_kind == "dflash"
                    and self.apc_manager is not None
                    and self.apc_mode == "exact"
                    and prefill_step_size is not None
                    and pending[0].apc_semantic_hash is not None
                    and not pending[0].images
                    and not pending[0].audio
                    and not pending[0].videos
                    and all(
                        pending[0].raw_inputs.get(key) is None
                        for key in ("pixel_values", "input_features",
                                    "pixel_values_videos", "video_grid_thw",
                                    "image_grid_thw")
                    )
                )
                prompt_started = time.perf_counter()
                if hybrid_eligible:
                    hybrid_apc_manager = self.apc_manager
                    hybrid_full_ids = all_input_ids[0]
                    hybrid_hash = int(pending[0].apc_semantic_hash)
                    # Always keep a trailing text-only region uncached. A
                    # chat template may change its final assistant delimiter
                    # when the user sends a follow-up. We checkpoint *before*
                    # these trailing tokens, exactly as normal APC does.
                    hybrid_checkpoint = max(
                        0,
                        len(hybrid_full_ids)
                        - hybrid_apc_manager.exact_cache_guard_tokens,
                    )
                    if hybrid_checkpoint < hybrid_apc_manager.exact_cache_min_tokens:
                        hybrid_apc_manager = None
                    else:
                        try:
                            warm_cache, hybrid_matched_tokens = (
                                hybrid_apc_manager.lookup_exact_cache(
                                    hybrid_full_ids, extra_hash=hybrid_hash
                                )
                            )
                        except Exception:
                            logger.warning(
                                "Hybrid APC lookup failed; using cold DFlash2 prefill",
                                exc_info=True,
                            )
                            warm_cache = None
                            hybrid_matched_tokens = 0
                        if nobby_hybrid_diag is not None:
                            nobby_hybrid_diag.classify(
                                hybrid_full_ids, hybrid_hash,
                                matched_tokens=hybrid_matched_tokens,
                                minimum_tokens=hybrid_apc_manager.exact_cache_min_tokens,
                                guard_tokens=hybrid_apc_manager.exact_cache_guard_tokens,
                            )
                        if warm_cache is not None and 0 < hybrid_matched_tokens < len(hybrid_full_ids):
                            # Restore a deep-copied exact snapshot. Never
                            # reconstruct recurrent SSM state from KV blocks.
                            prompt_cache = warm_cache
                            hybrid_seq_keys = _sequence_aligned_prefill_keys(
                                prompt_kwargs, batch_size=1,
                                sequence_length=inputs_embeds_mx.shape[1],
                            )
                            prompt_kwargs = _drop_prefill_kwargs(
                                prompt_kwargs, hybrid_seq_keys, hybrid_matched_tokens
                            )
                            input_mx = input_mx[:, hybrid_matched_tokens:]
                            inputs_embeds_mx = inputs_embeds_mx[:, hybrid_matched_tokens:]
                        else:
                            hybrid_matched_tokens = 0

                    hybrid_early_boundary = nobby_checkpoint_policy.early_checkpoint(
                        hybrid_checkpoint, hybrid_matched_tokens,
                        hybrid_apc_manager.exact_cache_min_tokens,
                        prefill_step_size=prefill_step_size,
                    ) if hybrid_apc_manager is not None else None

                    # Commit a custom exact-cache checkpoint before the
                    # tail that changes between chat turns. This must happen
                    # BEFORE speculative final-token capture and decoding.
                    if hybrid_apc_manager is not None and hybrid_checkpoint > hybrid_matched_tokens:
                        remaining_to_checkpoint = hybrid_checkpoint - hybrid_matched_tokens
                        while remaining_to_checkpoint > 0:
                            step = min(
                                remaining_to_checkpoint,
                                max(1, int(prefill_step_size)),
                            )
                            hybrid_consumed = hybrid_checkpoint - remaining_to_checkpoint
                            if hybrid_early_boundary is not None and hybrid_consumed < hybrid_early_boundary:
                                step = min(step, hybrid_early_boundary - hybrid_consumed)
                            hybrid_seq_keys = _sequence_aligned_prefill_keys(
                                prompt_kwargs, batch_size=1,
                                sequence_length=inputs_embeds_mx.shape[1],
                            )
                            hybrid_step_kwargs = _slice_prefill_kwargs(
                                prompt_kwargs, hybrid_seq_keys, step
                            )
                            with mx.stream(generation_stream):
                                lm(
                                    input_mx[:, :step],
                                    cache=prompt_cache,
                                    inputs_embeds=inputs_embeds_mx[:, :step],
                                    n_to_process=step,
                                    **hybrid_step_kwargs,
                                )
                            mx.eval([c.state for c in prompt_cache])
                            input_mx = input_mx[:, step:]
                            inputs_embeds_mx = inputs_embeds_mx[:, step:]
                            prompt_kwargs = _drop_prefill_kwargs(
                                prompt_kwargs, hybrid_seq_keys, step
                            )
                            remaining_to_checkpoint -= step
                            hybrid_consumed += step
                            if hybrid_early_boundary is not None and hybrid_consumed == hybrid_early_boundary:
                                if not nobby_hybrid_early_store:
                                    # Causal control: keep the exact same prefill split,
                                    # but do NOT save a snapshot at this point.
                                    logger.info("Hybrid early checkpoint split-only: tokens=%d", hybrid_early_boundary)
                                else:
                                    try:
                                        hybrid_early_saved = hybrid_apc_manager.store_exact_cache(
                                            hybrid_full_ids[:hybrid_early_boundary],
                                            prompt_cache, extra_hash=hybrid_hash,
                                        )
                                        if hybrid_early_saved:
                                            logger.info("Hybrid early checkpoint stored: tokens=%d", hybrid_early_boundary)
                                        else:
                                            logger.warning("Hybrid early checkpoint was not stored: tokens=%d", hybrid_early_boundary)
                                        if nobby_hybrid_diag is not None:
                                            logger.info(
                                                "HYBRID_APC_LRU phase=early capacity=%s entries=%s",
                                                getattr(hybrid_apc_manager, "_exact_cache_max", None),
                                                len(getattr(hybrid_apc_manager, "_exact_cache", ())),
                                            )
                                    except Exception:
                                        logger.warning("Hybrid early checkpoint store failed", exc_info=True)
                                hybrid_early_boundary = None
                            mx.clear_cache()
                        try:
                            hybrid_final_saved = hybrid_apc_manager.store_exact_cache(
                                hybrid_full_ids[:hybrid_checkpoint],
                                prompt_cache, extra_hash=hybrid_hash,
                            )
                            if nobby_hybrid_diag is not None:
                                nobby_hybrid_diag.classify(
                                    hybrid_full_ids, hybrid_hash,
                                    matched_tokens=hybrid_matched_tokens,
                                    minimum_tokens=hybrid_apc_manager.exact_cache_min_tokens,
                                    guard_tokens=hybrid_apc_manager.exact_cache_guard_tokens,
                                    stored=hybrid_final_saved,
                                )
                                logger.info(
                                    "HYBRID_APC_LRU phase=final saved=%s capacity=%s entries=%s",
                                    hybrid_final_saved,
                                    getattr(hybrid_apc_manager, "_exact_cache_max", None),
                                    len(getattr(hybrid_apc_manager, "_exact_cache", ())),
                                )
                        except Exception:
                            logger.warning(
                                "Hybrid APC checkpoint unavailable",
                                exc_info=True,
                            )
                    logger.info(
                        "Hybrid APC/DFlash prefill: reused_tokens=%d, "
                        "full_prompt_tokens=%d",
                        hybrid_matched_tokens, len(hybrid_full_ids),
                    )
                out, input_mx = _run_chunked_speculative_prefill(
'''

def transform_speculative_method(source: str) -> str:
    """Return patched function source or reject any unexpected upstream drift."""
    # Match the original class-indented source first; dedent only for exec.
    code = source
    if MARKER in code:
        raise RuntimeError("Hybrid adapter already installed")
    required = {
        ANCHOR_BEFORE_PREFILL: 1,
        ANCHOR_STATS: 1,
        ANCHOR_STATS_ARGS: 1,
        "def _run_speculative(self):": 1,
        "run_speculative_server_rounds(": 1,
    }
    for anchor, expected in required.items():
        if code.count(anchor) != expected:
            raise RuntimeError(
                "MLX-VLM speculative code differs from verified 0.6.17 layout; "
                "hybrid adapter not installed"
            )
    # Keep performance metric numerators truthful for warm prefix reuse.
    code = code.replace(
        ANCHOR_BEFORE_PREFILL,
        PREFILL_ADAPTER[1:],  # strip leading newline
        1,
    )
    code = code.replace(
        '''                    prompt_tokens = prompt_tokens_map[uid]
                    prompt_tps_map[uid] = (
                        prompt_tokens / prompt_elapsed''',
        '''                    prompt_tokens = prompt_tokens_map[uid]
                    prompt_tps_map[uid] = (
                        max(0, prompt_tokens - hybrid_matched_tokens) / prompt_elapsed''',
        1,
    )
    code = code.replace(
        ANCHOR_STATS,
        '''                    logger.info(
                        "Prefill completed: request=%s prompt_tokens=%d "
                        "cached_tokens=%d elapsed=%.3fs rate=%.1f tok/s",''',
        1,
    )
    code = code.replace(
        ANCHOR_STATS_ARGS,
        '''                        prompt_tokens,
                        hybrid_matched_tokens,
                        prompt_elapsed,
                        float(prompt_tps_map[uid] or 0.0),''',
        1,
    )
    standalone = textwrap.dedent(code)
    compile(standalone, "<nobby-hybrid-apc-dflash>", "exec")
    return standalone


def install() -> None:
    if os.environ.get(FLAG) != "1":
        raise RuntimeError(f"{FLAG}=1 is required for experimental hybrid mode")
    if os.environ.get("APC_ENABLED", "").strip().lower() not in {"1", "true", "yes"}:
        raise RuntimeError("APC_ENABLED must be set for the hybrid adapter")
    installed = version("mlx-vlm")
    if installed != SUPPORTED_VERSION:
        raise RuntimeError(
            f"Hybrid requires mlx-vlm=={SUPPORTED_VERSION}, installed {installed}"
        )
    module = importlib.import_module("mlx_vlm.server.generation")
    original = module.ResponseGenerator._run_speculative
    replacement = transform_speculative_method(inspect.getsource(original))
    nobby_hybrid_diag = importlib.import_module("hybrid_cache_diagnostics") if os.getenv("NOBBY_HYBRID_CACHE_DIAG") == "1" else None
    vars(module)["nobby_hybrid_diag"] = nobby_hybrid_diag
    nobby_checkpoint_policy = importlib.import_module("hybrid_checkpoint_policy")
    vars(module)["nobby_checkpoint_policy"] = nobby_checkpoint_policy
    vars(module)["nobby_hybrid_early_store"] = os.getenv("NOBBY_HYBRID_EARLY_CHECKPOINT_STORE", "1") != "0"
    namespace: dict = {}
    exec(compile(replacement, "<nobby-hybrid-apc-dflash>", "exec"), vars(module), namespace)
    patched = namespace.get("_run_speculative")
    if not callable(patched):
        raise RuntimeError("Could not compile hybrid speculative method")
    module.ResponseGenerator._run_speculative = patched
    module.logger.warning(
        "EXPERIMENTAL Nobby hybrid APC+DFlash2 active (exact text-only single sequence). "
        "No installed MLX-VLM files were modified."
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--check-only", action="store_true")
    known, rest = parser.parse_known_args(argv)
    if known.check_only:
        installed = version("mlx-vlm")
        if installed != SUPPORTED_VERSION:
            raise RuntimeError(f"Requires mlx-vlm=={SUPPORTED_VERSION}, found {installed}")
        mod = importlib.import_module("mlx_vlm.server.generation")
        transform_speculative_method(inspect.getsource(mod.ResponseGenerator._run_speculative))
        print("Compatible MLX-VLM source layout; no patch applied")
        return 0

    # Prefix ensures ps-based Nobby service detection still sees "mlx_vlm server".
    if len(rest) < 2 or rest[:2] != ["mlx_vlm", "server"]:
        raise RuntimeError("Experimental runner requires 'mlx_vlm server' prefix")
    install()
    # Serve through the original upstream CLI. Uvicorn and the FastAPI routes
    # continue to reference the same ResponseGenerator class (patched in RAM).
    sys.argv = ["mlx_vlm.server"] + rest[2:]
    from mlx_vlm.server.cli import main as upstream_server_main
    upstream_server_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
