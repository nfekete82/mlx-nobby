# SDXL variant batches: bounded worker lifetime

On Apple unified memory, a reused PyTorch/MPS SDXL worker may retain per-image
allocations over a long batch. A user reported 6-image Juggernaut XL batch
where gallery images 2–5 completed and image 6 failed **during generation**
with the existing critical 20.0% free-system-memory guard. Another batch
completed six images; this is not conclusive evidence of a process memory leak.

## Change

SDXL multi-variant galleries retain **one exclusive runtime lease** for the
entire batch (so the chat/Memory/other media models do not restart between
images), but terminate the *owned* SDXL worker after each two newly completed
variants if more variants remain. The next image loads a fresh worker in the
same exclusive lease. Non-SDXL and single-variant routes are unchanged.
Completed image files/metadata are never deleted by the recycling path.

If a checkpoint fails to unload or a worker remains resident, the batch
stops and suppresses potentially unsafe chat restoration. The remaining
unprocessed variants are failed; previously completed images stay valid.
A failed individual variant also marks batch_failed for correct diagnostics.
This fix does not allow a render to proceed past the pre-existing 20% free-RAM,
0.5-GB per-job swap-growth, or 24-GB child RSS guards.

## Local acceptance before production

1. Verify the current private memory backup and unchanged production SHA.
2. Run Python test suites (synthetic, no GPU): tests/test_image_variants.py,
   tests/test_image_runtime.py, tests/test_sdxl_memory_safety.py and
   tests/test_exclusive_model_handoff.py.
3. Only after a safe integration deploy, run one sequential six-image
   Juggernaut XL gallery with no other heavy workloads. Collect the current
   model processes, initial/mid/final macOS free %, swap delta, finished
   artifacts, and restoration of the selected chat model. Expected SDXL
   worker recycles are after newly rendered variant 2 and 4 (which may
   correspond to gallery image 3 and 5 when the base is image 1).
4. If a guard trips, do not retry blindly or raise safety limits.
   Review the memory trend and preserve finished image artifacts.

The code change alone cannot prove macOS Metal reclaim behavior. Slow
reclaim or external memory pressure can still cause a safe abort.
