"""Reversible hooks installed only in the isolated child process."""
from __future__ import annotations

import contextlib
import functools
import sys


class Instrumentation:
    def __init__(self, recorder):
        self.rec = recorder
        self.restore = contextlib.ExitStack()
        self.stage = 0
        self.loop_depth = 0
        self.last_step = None

    def patch(self, target, name, replacement):
        original = getattr(target, name)
        # Instance methods must be restored by deleting the local override.
        local = name in vars(target)
        setattr(target, name, replacement)
        self.restore.callback(setattr if local else delattr, target, name, *([original] if local else []))
        return original

    def aliases(self, original, replacement):
        for module_name, module in list(sys.modules.items()):
            if module_name.startswith(("ltx_core_mlx", "ltx_pipelines_mlx")) and module:
                for name, value in list(vars(module).items()):
                    if value is original:
                        self.patch(module, name, replacement)

    def wrap(self, target, name, phase, evaluate=True):
        original = getattr(target, name)
        @functools.wraps(original)
        def measured(*args, **kwargs):
            with self.rec.span(phase, callable=name):
                result = original(*args, **kwargs)
                if evaluate:
                    self.rec.materialize(result)
                return result
        self.patch(target, name, measured)

    def install(self, pipe):
        from ltx_pipelines_mlx.utils import blocks, samplers, _orchestration
        from ltx_core_mlx.model.video_vae import video_vae as vae
        # Pipe load covers DiT/VAE encoder/upsampler; block loaders separate nested loads.
        self.wrap(pipe, "load", "model_loading", evaluate=False)
        for name in ("_load_transformer_with_optional_streaming", "_load_dev_transformer",
                     "_load_upsampler", "_fuse_distilled_lora"):
            if hasattr(pipe, name):
                self.wrap(pipe, name, "model_loading", evaluate=False)
        self.wrap(pipe.image_conditioner, "load", "model_loading", evaluate=False)
        for cls in (blocks.PromptEncoder, blocks.VideoDecoder, blocks.AudioDecoder, blocks.AudioConditioner):
            self.wrap(cls, "load", "model_loading", evaluate=False)
        self.wrap(blocks.PromptEncoder, "encode", "text_encoding")
        self.wrap(blocks.AudioDecoder, "__call__", "audio_processing")
        if hasattr(pipe, "_upsample_latent"):
            self.wrap(pipe, "_upsample_latent", "latent_upsampling")
        self.wrap(vae.VideoEncoder, "encode", "image_encoding")
        # The WAV is deleted upstream after muxing; runner separately extracts output PCM.
        original_wave = _orchestration.save_waveform
        @functools.wraps(original_wave)
        def save_waveform(*args, **kwargs):
            with self.rec.span("audio_processing", callable="save_waveform"):
                return original_wave(*args, **kwargs)
        self.aliases(original_wave, save_waveform)

        original_step = samplers._step_timed
        @functools.wraps(original_step)
        def step(estimator, step_idx, video_x, audio_x):
            self.rec.materialize((video_x, audio_x))
            self.rec.mx.synchronize()
            self.rec.guard()
            now = self.rec.clock()
            self.rec.steps.append({"stage": self.stage, "step": step_idx + 1,
                                   "seconds": now - self.last_step,
                                   "completed_seconds": now - self.rec.zero,
                                   "metal": self.rec.metal()})
            original_step(estimator, step_idx, video_x, audio_x)
            self.last_step = self.rec.clock()
        self.patch(samplers, "_step_timed", step)

        def loop_wrapper(original):
            @functools.wraps(original)
            def loop(*args, **kwargs):
                if self.loop_depth:
                    return original(*args, **kwargs)
                self.stage += 1
                if self.stage > 2:
                    raise RuntimeError("Unexpected third denoise stage; instrumentation contract changed")
                with self.rec.span(f"denoising_stage_{self.stage}"):
                    self.last_step = self.rec.clock()
                    self.loop_depth += 1
                    try:
                        result = original(*args, **kwargs)
                        self.rec.materialize(result)
                        dit = pipe.dit
                        # StreamingLTXModel owns the underlying model as .inner.
                        inner = getattr(dit, "inner", dit)
                        dtype = getattr(inner, "compute_dtype", None)
                        self.rec.effective["dit_compute"].append({"stage": self.stage, "dtype": str(dtype)})
                        return result
                    finally:
                        self.loop_depth -= 1
            return loop
        for name in ("denoise_loop", "euler_ancestral_denoising_loop", "guided_denoise_loop"):
            original = getattr(samplers, name)
            self.aliases(original, loop_wrapper(original))
        if hasattr(pipe, "_stop_stage2_sparse_attention"):
            original_stop = pipe._stop_stage2_sparse_attention
            def stop_sparse(state):
                self.rec.effective["sparse_attention_calls"] += getattr(state, "calls", 0)
                return original_stop(state)
            self.patch(pipe, "_stop_stage2_sparse_attention", stop_sparse)

        # Generator construction does no decode work. Time every next() and evaluate its result.
        original_tiles = vae.VideoDecoder.tiled_decode
        @functools.wraps(original_tiles)
        def tiles(*args, **kwargs):
            iterator = iter(original_tiles(*args, **kwargs))
            try:
                while True:
                    with self.rec.span("vae_decoding", callable="tiled_decode.next"):
                        try:
                            chunk = next(iterator)
                        except StopIteration:
                            break
                        self.rec.materialize(chunk)
                    yield chunk
            finally:
                close = getattr(iterator, "close", None)
                if close:
                    close()
        self.patch(vae.VideoDecoder, "tiled_decode", tiles)
        self.wrap(blocks.VideoDecoder, "decode_and_stream", "decode_mux_stream", evaluate=False)

        original_sink = vae._ffmpeg_sink
        @contextlib.contextmanager
        def sink(cmd):
            # Inclusive lifetime overlaps all decode; self time is startup/final drain only.
            with self.rec.span("mux_session", argv=list(cmd)):
                with original_sink(cmd) as proc:
                    yield proc
        self.aliases(original_sink, sink)
        original_stream = vae.stream_chunks_to_ffmpeg
        @functools.wraps(original_stream)
        def stream(*args, **kwargs):
            with self.rec.span("frame_conversion_and_delivery"):
                return original_stream(*args, **kwargs)
        self.aliases(original_stream, stream)
        original_write = vae._OrderedFrameWriter.submit
        @functools.wraps(original_write)
        def write(*args, **kwargs):
            with self.rec.span("mux_pipe_backpressure"):
                return original_write(*args, **kwargs)
        self.patch(vae._OrderedFrameWriter, "submit", write)
        for name in ("finish", "shutdown"):
            self.wrap(vae._OrderedFrameWriter, name, "mux_pipe_backpressure", evaluate=False)
        # Instrument source-audio encode/resample for classic and distilled A2V.
        import ltx_pipelines_mlx.a2vid_two_stage as a2v
        original_audio = a2v.encode_source_audio
        @functools.wraps(original_audio)
        def source_audio(*args, **kwargs):
            with self.rec.span("audio_processing", callable="encode_source_audio"):
                result = original_audio(*args, **kwargs)
                self.rec.materialize(result)
                return result
        self.aliases(original_audio, source_audio)
        original_load_audio = a2v.load_audio
        @functools.wraps(original_load_audio)
        def load_audio(*args, **kwargs):
            with self.rec.span("audio_processing", callable="load_audio"):
                result = original_load_audio(*args, **kwargs)
                self.rec.materialize(result)
                return result
        self.aliases(original_load_audio, load_audio)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self.restore.__exit__(*exc)
