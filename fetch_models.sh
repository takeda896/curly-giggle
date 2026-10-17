#!/usr/bin/env bash
# Kokoro TTS モデル(約350MB)を models/ にダウンロードする
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p models
base=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
[ -f models/kokoro-v1.0.onnx ] || curl -fL -o models/kokoro-v1.0.onnx "$base/kokoro-v1.0.onnx"
[ -f models/voices-v1.0.bin ] || curl -fL -o models/voices-v1.0.bin "$base/voices-v1.0.bin"
