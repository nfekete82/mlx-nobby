#!/usr/bin/env python3
"""Freeze TTS once, then render the same portrait/WAV with multiple seeds.

Runs the project's real renderer, including runtime coordination and padding.
All artifacts stay under --output; no Agent restart or settings changes needed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import talking_photo, talking_photo_ltx, talking_photo_quality
from agent.talking_photo_audio import validate_wav


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', required=True)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--audio', help='Existing audio; bypass TTS and freeze it once')
    source.add_argument('--text', help='Synthesize exactly once at native speed')
    p.add_argument('--voice')
    p.add_argument('--language', default='de')
    p.add_argument('--seeds', default='42,1234,1337,2026,858797624')
    p.add_argument('--repeat', type=int, default=1, help='Repeat each seed with identical audio')
    p.add_argument('--output', required=True, help='New directory for immutable test inputs/results')
    p.add_argument('--prepare-only', action='store_true', help='Freeze inputs without loading LTX')
    p.add_argument('--resume', action='store_true', help='Use the frozen inputs in an existing directory')
    return p


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    args = parser().parse_args()
    seeds = [int(s.strip()) for s in args.seeds.split(',')]
    if args.repeat < 1 or len(set(seeds)) != len(seeds) or any(s < 0 or s > 0x7fffffff for s in seeds):
        raise SystemExit('Seeds must be 0..2147483647 and repeat must be positive')
    root = Path(args.output).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=args.resume)
    manifest_path = root / 'inputs.json'
    if args.resume:
        manifest = json.loads(manifest_path.read_text())
        image_path = root / manifest['image_file']
        wav_path = root / 'frozen.wav'
        for path, key in [(image_path, 'image_sha256'), (wav_path, 'audio_sha256')]:
            if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[key]:
                raise SystemExit(f'Frozen input was changed: {path}')
    else:
        image_path = Path(args.image).expanduser().resolve()
        image = image_path.read_bytes()
        # Validate supported format with the existing image decoder.
        import base64
        mime = 'png' if image.startswith(b'\x89PNG') else 'jpeg'
        _, suffix = talking_photo.decode_image_data_url(
            f'data:image/{mime};base64,' + base64.b64encode(image).decode('ascii'))
        image_path = root / ('portrait' + suffix)
        image_path.write_bytes(image)
        payload = {'input': args.text, 'language': talking_photo_quality.tts_language(args.language)}
        if args.voice:
            payload['voice'] = args.voice
        audio = (Path(args.audio).expanduser().read_bytes() if args.audio
                 else talking_photo._request_tts(payload))
        (root / 'original-audio.bin').write_bytes(audio)
        wav = talking_photo._audio_to_wav(audio, root)
        wav_path = root / 'frozen.wav'
        wav_path.write_bytes(wav)
        manifest = {'tts_request': payload if args.text else None,
                    'voice': args.voice, 'language': args.language,
                    'audio_source': str(Path(args.audio).expanduser().resolve()) if args.audio else 'TTS once',
                    'image_file': image_path.name,
                    'image_sha256': hashlib.sha256(image).hexdigest(),
                    'audio_sha256': hashlib.sha256(wav).hexdigest(),
                    'audio_stats': validate_wav(wav)}
        write_json(manifest_path, manifest)
    image, wav = image_path.read_bytes(), wav_path.read_bytes()
    stats = validate_wav(wav)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    if args.prepare_only:
        return 0
    summary_path = root / 'comparison.json'
    results = json.loads(summary_path.read_text()) if args.resume and summary_path.exists() else []
    for seed in seeds:
        for repeat in range(1, args.repeat + 1):
            label = f'seed-{seed}-run-{repeat}'
            bundle = root / label
            if args.resume and (bundle / 'output.mp4').is_file():
                print(f'Skip completed {label}', flush=True)
                continue
            print(f'Rendering {label}', flush=True)
            os.environ['LTX_TALKING_PHOTO_SEED'] = str(seed)
            work = root / (label + '-work')
            try:
                video, details = talking_photo_ltx.generate(
                    label, image, image_path.suffix, wav, stats['frames'] / 16000,
                    work, cancelled=lambda: False, debug_dir=bundle)
                # Decode pixels for reproducibility: MP4 container hashes alone
                # can differ without any visible difference.
                md5 = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(bundle / 'output.mp4'),
                                      '-map', '0:v:0', '-f', 'framemd5', '-'],
                                     capture_output=True, text=True, check=True).stdout
                (bundle / 'frames.md5').write_text(md5)
                results.append({'run': label, 'seed': seed,
                                'conditioning_audio_sha256': details['conditioning_audio_sha256'],
                                'decoded_frames_sha256': hashlib.sha256(md5.encode()).hexdigest(),
                                'output_mp4_sha256': hashlib.sha256(video).hexdigest(),
                                'elapsed_seconds': details['elapsed_seconds']})
                write_json(summary_path, results)
                print(f'Completed {label}: {details["elapsed_seconds"]:.1f}s', flush=True)
            except Exception as exc:
                bundle.mkdir(parents=True, exist_ok=True)
                write_json(bundle / 'failure.json', {'run': label, 'seed': seed, 'error': str(exc)})
                raise
            finally:
                shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
