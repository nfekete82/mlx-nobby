# Juggernaut XL Ragnarok: VAE quality diagnosis

Users reported that recent images look less realistic, particularly anatomy.
This diagnostic isolates the newly enabled **VAE tiling/slicing** from all
sampling and memory changes. It does **not** claim VAE is responsible.

After updating the branch, the normal production pipeline remains unchanged:
`sdxl_vae_mode` is omitted (identical to `optimized`). The optional
`disabled` value changes only the VAE tiling/slicing methods for that one
request; it never disables Diffusers/Accelerate model CPU offloading, the MPS
allocator high watermark (0.55 max), runtime memory lock, chat handoff or
active RAM/swap watchdog.

```bash
cd ~/mlx-web
git pull --ff-only origin fix/juggernaut-unified-memory-safety
./test-venv/bin/python -m pytest -q tests/test_sdxl_vae_diagnostic.py
# Only restart the service if it is idle:
curl -fsS http://127.0.0.1:8030/health
launchctl kickstart -k "gui/$(id -u)/de.nobby.mlx-images"
./image-venv/bin/python scripts/diagnose-juggernaut-vae.py
```

Optional same scene from a previously generated artifact:
`--prompt "..." --seed 42 --width 768 --height 1024 --steps 30 --cfg 5`.
Use `--dry-run` to display exact inputs without GPU.

Two **sequential** real images plus a contact sheet are saved to
`~/.config/mlx-web/benchmarks/juggernaut-vae/<timestamp>/` by default.
Both use the same Juggernaut checkpoint, scheduler, prompt, negative prompt,
seed, resolution, steps, and guidance. The pair differs only by VAE
tiling/slicing. The two runs may not be bit-identical due to MPS execution
nondeterminism even at identical settings.

If the disabled case hits the resource guard, the diagnostic stops safely;
this is expected rather than permission to relax the guard. Test only while
image service is idle. The script neither changes the registry nor deletes
user files. Ordinary requests keep VAE optimizations on.
