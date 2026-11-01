"""VAE diagnostic admission and failure cleanup without loading GPU libraries."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import managed_process
import runtime_coordinator

spec=importlib.util.spec_from_file_location('vae_probe',Path(__file__).resolve().parents[1]/'scripts/probe-ltx-vae-reconstruction.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


def test_pin_mismatch_fails_before_model_access(tmp_path):
    with mock.patch.object(probe.subprocess,'check_output',side_effect=['other\n','']):
        with pytest.raises(ValueError,match='unchanged pinned'):probe.validate(tmp_path,tmp_path,'half')


def test_resource_failure_terminates_owned_process_and_releases_lease(tmp_path):
    source=tmp_path/'source.png';source.write_bytes(b'test source')
    args=SimpleNamespace(runtime=tmp_path,model=tmp_path,stage='half',image=source,out=tmp_path/'output')
    admission={'memory_admission':{'swap_used_gb':0}}
    released=[]
    @contextlib.contextmanager
    def lease(*a,**kw):
        assert kw['exclusive_models']
        try:yield admission
        finally:released.append(True)
    process=mock.Mock();process.poll.return_value=None
    with mock.patch.object(probe,'validate',return_value={}), \
         mock.patch.object(probe.urllib.request,'urlopen',side_effect=[io.BytesIO(b'{"ok":true,"status":"ready"}'),io.BytesIO(b'{"active_count":0,"waiting_count":0}')]), \
         mock.patch('video_providers._prepare_first_frame',return_value={}), \
         mock.patch('ai_lifecycle_gate.check'), \
         mock.patch.object(runtime_coordinator,'video_runtime',side_effect=lease), \
         mock.patch.object(runtime_coordinator,'memory_budget_snapshot',return_value={'free_percent':1}), \
         mock.patch.object(managed_process,'spawn',return_value=process) as spawn, \
         mock.patch.object(managed_process,'terminate') as terminate:
        with pytest.raises(RuntimeError,match='RAM-Schutz'):probe.controller(args)
    terminate.assert_called_once_with(process)
    assert released==[True]
    assert spawn.call_args.kwargs['owner']=='video:vae-diagnostic'
    assert spawn.call_args.kwargs['env']['HF_HUB_OFFLINE']=='1'
    assert json.loads((args.out/'provenance.json').read_text())['admission']==admission
