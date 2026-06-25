"""Run cart tests and save output."""
import subprocess
import sys

PROJECT_DIR = r"c:\Users\Пользователь\Downloads\neomarket-canon-US-MOD-01\neomarket-canon-US-MOD-01"

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_b2c_cart.py", "-v", "--tb=short"],
    capture_output=True,
    text=True,
    cwd=PROJECT_DIR,
)

with open(PROJECT_DIR + "\\test_output_cart.txt", "w", encoding="utf-8") as f:
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\n\nSTDERR:\n")
    f.write(result.stderr)
    f.write(f"\n\nReturn code: {result.returncode}\n")

print(f"Return code: {result.returncode}")
print(f"STDOUT length: {len(result.stdout)}")
print(f"STDERR length: {len(result.stderr)}")
print("Output saved to test_output_cart.txt")