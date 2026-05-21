import base64

encoded = "HM6Ly9sdWx1c3Ry+ZWFtLmNvbS9kL2+4zaTkzazBvazM4YQ=="

for skip in range(0, 5):
    try:
        trimmed = encoded[skip:].replace('+', '').replace(' ', '')
        padded = trimmed + "=" * (4 - len(trimmed) % 4)
        decoded = base64.b64decode(padded).decode("utf-8")
        print(f"skip={skip}: {decoded}")
    except Exception as e:
        print(f"skip={skip}: FAILED — {e}")
