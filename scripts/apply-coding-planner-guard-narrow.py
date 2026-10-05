from pathlib import Path

runtime = Path("agent/runtime.py")
text = runtime.read_text(encoding="utf-8")
old = '                if mode == "coding":\n                    rejected_same_action = sum('
new = '                if mode == "coding" and action == "normal_chat":\n                    rejected_same_action = sum('
count = text.count(old)
if count != 1:
    raise SystemExit(f"runtime guard anchor count={count}")
runtime.write_text(text.replace(old, new, 1), encoding="utf-8")

Path(__file__).unlink()
print("Narrowed unsupported-action circuit breaker to normal_chat and removed one-shot helper.")
