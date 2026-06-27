#!/bin/bash
# setup_env.sh - Налаштування ізольованого Python-середовища з Metal-прискоренням для Apple Silicon
set -e

echo "=== Створення віртуального середовища Python ==="
python3 -m venv .venv

echo "=== Активація віртуального середовища ==="
source .venv/bin/activate

echo "=== Оновлення pip, setuptools та wheel ==="
pip install --upgrade pip setuptools wheel

echo "=== Налаштування компиляційних прапорців Metal для llama-cpp-python ==="
export CMAKE_ARGS="-DGGML_METAL=on -DGGML_METAL_NDEBUG=on -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64"
export FORCE_CMAKE=1

echo "=== Встановлення залежностей зrequirements.txt ==="
pip install -r requirements.txt

echo "=== Налаштування завершено успішно ==="
