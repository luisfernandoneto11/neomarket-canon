"""Run pytest and save output to file."""
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_b2c_product_card.py", "-v", "--tb=short"],
    capture_output=True,
    text=True,
)

with open("test_output_result.txt", "w", encoding="utf-8") as f:
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\n\nSTDERR:\n")
    f.write(result.stderr)
    f.write(f"\n\nReturn code: {result.returncode}\n")

print("Done. Check test_output_result.txt")