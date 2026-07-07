#!/bin/bash
# setup_env.sh — Налаштування ізольованого Python-середовища з автодетекцією GPU-бекенду
set -e

# ── Визначення GPU-бекенду ──────────────────────────────────────────
detect_gpu_backend() {
    OS="$(uname -s)"
    case "$OS" in
        Darwin)
            echo "metal"
            ;;
        Linux)
            if command -v nvidia-smi &>/dev/null; then
                echo "cuda"
            elif command -v rocm-smi &>/dev/null || [ -d /opt/rocm ]; then
                echo "rocm"
            else
                echo "cpu"
            fi
            ;;
        *)
            echo "cpu"
            ;;
    esac
}

GPU_BACKEND="$(detect_gpu_backend)"

case "$GPU_BACKEND" in
    metal)
        echo "🍎 Виявлено macOS — Metal GPU backend"
        export CMAKE_ARGS="-DGGML_METAL=on -DGGML_METAL_NDEBUG=on -DCMAKE_BUILD_TYPE=Release"
        ;;
    cuda)
        echo "🟢 Виявлено NVIDIA GPU — CUDA backend"
        export CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_BUILD_TYPE=Release"
        ;;
    rocm)
        echo "🔴 Виявлено AMD GPU — ROCm (HIP BLAS) backend"
        export CMAKE_ARGS="-DGGML_HIPBLAS=on -DCMAKE_BUILD_TYPE=Release"
        ;;
    *)
        echo "⚪ GPU не виявлено — CPU-only fallback"
        export CMAKE_ARGS="-DGGML_BLAS=OFF -DCMAKE_BUILD_TYPE=Release"
        ;;
esac
export FORCE_CMAKE=1

# ── Створення віртуального середовища ────────────────────────────────
echo "=== Створення віртуального середовища Python ==="
python3 -m venv .venv

echo "=== Активація віртуального середовища ==="
source .venv/bin/activate

echo "=== Оновлення pip, setuptools та wheel ==="
pip install --upgrade pip setuptools wheel

echo "=== Встановлення залежностей з requirements.txt ==="
pip install -r requirements.txt

echo "=== Налаштування завершено успішно ($GPU_BACKEND backend) ==="
