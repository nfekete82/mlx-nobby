"""Offline, process-cached CLI contracts; probes never generate or fetch models."""
from functools import lru_cache
from pathlib import Path
import os
import re
import subprocess
import json
import struct


def _version(executable):
    # Read metadata belonging to this executable, rather than the web Python.
    root = Path(executable).resolve().parent.parent
    for metadata in root.glob('lib/python*/site-packages/mflux-*.dist-info/METADATA'):
        match = re.search(r'^Version: (.+)$', metadata.read_text(), re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


@lru_cache(maxsize=32)
def probe_mflux_cli(executable):
    executable = str(executable)
    result = {'available': False, 'supported_flags': frozenset(),
              'version': _version(executable), 'error': None}
    if not Path(executable).is_file() or not os.access(executable, os.X_OK):
        return result | {'error': 'MFLUX-CLI fehlt oder ist nicht ausführbar'}
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    try:
        process = subprocess.run([executable, '--help'], capture_output=True,
                                 text=True, timeout=30, env=environment, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        return result | {'error': 'MFLUX-CLI konnte nicht geprüft werden'}
    if process.returncode:
        return result | {'error': f'MFLUX-CLI-Prüfung fehlgeschlagen (Exit {process.returncode})'}
    flags = frozenset(re.findall(r'^\s+(--[a-z][a-z0-9-]*)(?=[\s,=]|$)', process.stdout, re.MULTILINE))
    if not flags:
        return result | {'error': 'MFLUX-CLI liefert keinen erkennbaren Argumentvertrag'}
    return result | {'available': True, 'supported_flags': flags}


def required_mflux_flags(model):
    flags = {'--model', '--prompt', '--width', '--height', '--steps', '--seed', '--output'}
    family = model['model_family']
    if family == 'qwen-image-edit':
        flags |= {'--image-paths', '--guidance'}
    else:
        flags |= {'--mlx-cache-limit-gb', '--low-ram'}
        if family not in {'qwen-image21', 'krea2', 'boogu'}:
            flags.add('--base-model')
        if family not in {'z-image-turbo', 'boogu'}:
            flags.add('--guidance')
    if model.get('quantization', 'none') != 'none' and (family != 'qwen-image-edit' or model.get('quantize_on_load')):
        flags.add('--quantize')
    if any(lora.get('enabled') for lora in model.get('loras', [])):
        flags |= {'--lora-paths', '--lora-scales'}
    return flags


def mflux_contract(model, executable):
    capabilities = probe_mflux_cli(str(executable))
    if not capabilities['available']:
        return False, capabilities['error']
    missing = required_mflux_flags(model) - capabilities['supported_flags']
    if missing:
        return False, 'MFLUX-CLI inkompatibel: notwendige Argumente fehlen: ' + ', '.join(sorted(missing))
    return True, 'Lokale Gewichte und kompatibler MFLUX-CLI-Vertrag vorhanden'


@lru_cache(maxsize=32)
def _quantized_text_encoder(signature):
    # Read headers only, never tensor data or model code. MFLUX Qwen's loader
    # skips quantization for this component in the supported 0.19.1 contract.
    for filename, _mtime, _size in signature:
        with open(filename, 'rb') as stream:
            prefix = stream.read(8)
            if len(prefix) != 8:
                raise ValueError('Ungültiger Qwen-Gewichtsheader')
            size = struct.unpack('<Q', prefix)[0]
            if size > 16 * 1024 * 1024:
                raise ValueError('Ungültiger Qwen-Gewichtsheader')
            raw_header = stream.read(size)
            if len(raw_header) != size:
                raise ValueError('Ungültiger Qwen-Gewichtsheader')
            header = json.loads(raw_header)
            if not isinstance(header, dict):
                raise ValueError('Ungültiger Qwen-Gewichtsheader')
        if any(name.endswith('.scales') for name in header):
            return True
        if any(name.endswith('.weight') and isinstance(tensor, dict) and tensor.get('dtype') == 'U32'
               for name, tensor in header.items()):
            return True
    return False


def mflux_weight_contract(model, root):
    if model['model_family'] not in {'qwen-image', 'qwen-image-edit', 'qwen-image21', 'krea2'}:
        return True, None
    component = Path(root) / 'text_encoder'
    files = sorted(component.glob('*.safetensors'))
    try:
        signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
        quantized = _quantized_text_encoder(signature)
    except (OSError, ValueError, struct.error):
        return False, 'Qwen-Cache enthält ungültige Text-Encoder-Gewichtsheader'
    if quantized:
        return False, 'Qwen-Cache inkompatibel: quantisierter Text-/Vision-Encoder; der unterstützte MFLUX-Qwen-Loader benötigt diesen Encoder unquantisiert. Keine automatischen Downloads.'
    return True, None
