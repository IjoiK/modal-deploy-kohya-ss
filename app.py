import modal
import subprocess
import toml
import logging
import os
from pathlib import Path


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PYTHON_VERSION = "3.10"
KOHYA_REPO_URL = "https://github.com/bmaltais/kohya_ss.git"

kohya_image = (
    modal.Image.from_registry(
        "nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04", add_python=PYTHON_VERSION
    )
    .env({
        "DEBIAN_FRONTEND": "noninteractive",
        "TZ": "Etc/UTC",
        "PYTORCH_CUDA_ALLOC_CONF": "max_split_size_mb:128" # Example, you can use: 64 or 32 also
    })
    .apt_install(
        "git",
        "wget",
        "libgl1-mesa-glx",
        "libglib2.0-0",
        "python3-tk",
        "libjpeg-dev",
        "libpng-dev",
        "google-perftools",
    )
    .env({"KOHYA_VERSION_DATE": "2025-05-25"})
    .env({"LD_PRELOAD": "/usr/lib/x86_64-linux-gnu/libtcmalloc.so.4"})
    .run_commands(
        "set -ex",
        "pip install --upgrade pip",
        f"git clone --recursive {KOHYA_REPO_URL} /kohya_ss",
        gpu="any",
    )
    .workdir("/kohya_ss")
    .run_commands(
        "set -ex",
        "ls -l",

        "sed -i -e '/torch/d' -e '/torchvision/d' -e '/torchaudio/d' -e '/xformers/d' -e '/bitsandbytes/d' requirements.txt",
        "echo '--- Содержимое requirements.txt ПОСЛЕ модификации: ---'",
        "cat requirements.txt",
        "echo '---------------------------------------------------'",

        "pip install --use-pep517 --upgrade -r requirements.txt",

        "echo 'Удаление предыдущих версий torch, torchvision, torchaudio, triton...'",
        "pip uninstall -y torch torchvision torchaudio triton",

        "echo 'Установка PyTorch 2.1.2+cu118...'",
        "pip install torch==2.1.2+cu118 torchvision==0.16.2+cu118 torchaudio==2.1.2+cu118 --extra-index-url https://download.pytorch.org/whl/cu118",

        "echo 'Установка xformers==0.0.23.post1+cu118...'",
        "pip install xformers==0.0.23.post1+cu118 --index-url https://download.pytorch.org/whl/cu118",

        "echo 'Установка bitsandbytes==0.41.1...'",
        "pip install bitsandbytes==0.41.1",

        "echo 'Установка diffusers...'",
        "pip install diffusers",

        "echo 'Установка accelerate...'",
        "pip install accelerate",

        "accelerate config default",
        "echo 'Установка основных зависимостей завершена.'",
        "rm -rf models dataset outputs configs",
        "ls -l",
        gpu="any",
    )
    .run_commands(
        "echo 'Установка Kohya_SS завершена.'",
    )
)

logger.info("Образ Kohya_SS определен.")

CONFIG_FILE = Path(__file__).parent / "config.toml"

try:
    config = toml.load(CONFIG_FILE)
    modal_settings = config.get('modal_settings', {})
    kohya_settings = config.get('kohya_settings', {})
    ALLOW_CONCURRENT_INPUTS = modal_settings.get('allow_concurrent_inputs', 10)
    CONTAINER_IDLE_TIMEOUT = modal_settings.get('container_idle_timeout', 600)
    TIMEOUT = modal_settings.get('timeout', 3600)
    GPU_CONFIG = modal_settings.get('gpu', "A10G")
    PORT = kohya_settings.get('port', 8000)
except Exception as e:
    ALLOW_CONCURRENT_INPUTS = 5
    CONTAINER_IDLE_TIMEOUT = 300
    TIMEOUT = 1800
    GPU_CONFIG = "A10G"
    PORT = 8000

app = modal.App(name="kohya-ss-gui", image=kohya_image)

class Paths:
    CACHE = "/cache"
    KOHYA_BASE = "/kohya_ss"
    MODELS = "/kohya_ss/models"
    DATASET = "/kohya_ss/dataset"
    OUTPUTS = "/kohya_ss/outputs"
    CONFIGS = "/kohya_ss/configs"

# Определение томов (остается как было)
cache_vol = modal.Volume.from_name("hf-cache", create_if_missing=True)
models_vol = modal.Volume.from_name("kohya-models", create_if_missing=True)
dataset_vol = modal.Volume.from_name("kohya-dataset", create_if_missing=True)
outputs_vol = modal.Volume.from_name("kohya-outputs", create_if_missing=True)
configs_vol = modal.Volume.from_name("kohya-configs", create_if_missing=True)

@app.function(
    gpu=GPU_CONFIG,
    timeout=TIMEOUT,
    scaledown_window=CONTAINER_IDLE_TIMEOUT,
    volumes={
        Paths.CACHE: cache_vol,
        Paths.MODELS: models_vol,
        Paths.DATASET: dataset_vol,
        Paths.OUTPUTS: outputs_vol,
        Paths.CONFIGS: configs_vol,
    },
    max_containers=1
)

@modal.concurrent(max_inputs=ALLOW_CONCURRENT_INPUTS)
@modal.web_server(PORT, startup_timeout=300)
def run_kohya_gui():
    import torch
    logger.info(f"PYTORCH VERSION: {torch.__version__}")
    kohya_script = "kohya_gui.py"

    start_command = (
        f"cd {Paths.KOHYA_BASE} && "
        f"accelerate launch --num_cpu_threads_per_process=4 {kohya_script} "
        f"--listen 0.0.0.0 --server_port {PORT} --headless"
        f" --noverify"
    )
    subprocess.Popen(start_command, shell=True)

@app.local_entrypoint()
def main():
    print("Используйте 'modal serve app.py' для запуска веб-сервера.")