#!/usr/bin/env python3
"""
统一配置管理模块
=================
支持三级配置合并: dataclass 默认值 → YAML 文件 → 环境变量 → CLI 参数

使用:
    from core.config_manager import ConfigManager
    config = ConfigManager.resolve(yaml_path="config.yaml", cli_overrides={...})
"""

import logging
import os
import platform
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("config_manager")

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


# ============================================================================
# 配置数据类 (单一来源)
# ============================================================================
@dataclass
class Config:
    """语音助手完整配置"""

    # --- 串口 (M260C 唤醒引擎) ---
    serial_port: str = "COM11" if IS_WINDOWS else "/dev/ttyUSB0"
    serial_baudrate: int = 115200

    # --- ASR (语音识别) ---
    asr_backend: str = "iflytek"  # "whisper_api" | "iflytek"
    # whisper_api
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "sk-your-key-here")
    openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    whisper_model: str = "whisper-1"
    # iflytek
    iflytek_app_id: str = ""
    iflytek_api_key: str = ""
    iflytek_api_secret: str = ""

    # --- LLM (大模型对话) ---
    llm_backend: str = "ollama"  # "ollama" | "openai"
    # ollama
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2:latest"
    # openai
    llm_model: str = "gpt-4o-mini"
    system_prompt: str = (
        "你是一个智能语音助手，名叫小飞。"
        "请用简洁、自然的中文回答用户的问题。"
        "每次回答控制在2-3句话以内，适合语音播放。"
    )

    # --- TTS (语音合成) ---
    tts_backend: str = "edge"  # "edge" | "pyttsx3"
    # edge-tts
    edge_voice: str = "zh-CN-XiaoxiaoNeural"
    # pyttsx3
    pyttsx3_rate: int = 180

    # --- 音频 ---
    audio_input_device: Optional[int] = None  # None = 自动查找
    audio_output_device: Optional[int] = None
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    record_seconds_max: int = 8
    silence_threshold: float = 500.0
    silence_seconds: float = 1.5

    # --- 唤醒 ---
    wake_word: str = "小飞小飞"
    wake_score_threshold: int = 500
    wake_cooldown: float = 3.0
    wake_backend: str = "auto"  # "serial" | "audio" | "auto"

    # --- ROS ---
    ros_enabled: bool = False
    ros_master_uri: str = ""
    ros_angle_topic: str = "/angle"
    ros_question_topic: str = "/question"
    ros_answer_topic: str = "/answer"

    # --- 本地音频回退 ---
    local_audio_enabled: bool = True
    local_audio_dir: str = "audio_resources"
    wake_sound_file: str = ""

    # --- 其他 ---
    temp_dir: str = field(default_factory=tempfile.gettempdir)
    save_audio: bool = False
    debug: bool = False


# ============================================================================
# 配置管理器
# ============================================================================
class ConfigManager:
    """加载并合并多级配置"""

    @staticmethod
    def resolve(yaml_path: str = None, cli_overrides: dict = None) -> Config:
        """
        解析配置，优先级从低到高:
          1. Config() dataclass 默认值
          2. config.yaml 文件
          3. 环境变量
          4. CLI 参数 (cli_overrides dict)
        """
        config = Config()

        # 1. 加载 YAML (多路径搜索: 本地 > ROS2 install > ROS2 share > 源码)
        if yaml_path is None:
            search_paths = [
                Path(__file__).parent.parent / "config.yaml",           # 源码目录
                Path.cwd() / "config.yaml",                             # 运行目录
                Path("/home/sunrise/ucar_01/voice_assistant/config.yaml"),  # 硬编码 RDK 路径
                Path("/home/sunrise/ucar_01/install/voice_assistant/share/voice_assistant/config/config.yaml"),  # ROS2 install
            ]
            for p in search_paths:
                if p.exists():
                    yaml_path = str(p)
                    log.info(f"加载配置: {yaml_path}")
                    break
        if yaml_path:
            ConfigManager._apply_yaml(config, yaml_path)

        # 2. 环境变量覆盖
        ConfigManager._apply_env(config)

        # 3. CLI 参数覆盖 (最高优先级)
        if cli_overrides:
            ConfigManager._apply_cli(config, cli_overrides)

        # 4. 推导本地音频路径
        if config.local_audio_enabled and not config.wake_sound_file:
            resources = Path(__file__).parent.parent / config.local_audio_dir
            config.local_audio_dir = str(resources)
            config.wake_sound_file = str(resources / "wake_ding.wav")

        # 5. 调试模式下启用更详细的日志
        if config.debug:
            logging.getLogger().setLevel(logging.DEBUG)

        return config

    @staticmethod
    def _apply_yaml(config: Config, yaml_path: str):
        """从 YAML 文件读取配置并应用到 Config 对象"""
        try:
            import yaml
        except ImportError:
            log.warning("未安装 pyyaml，跳过 YAML 配置")
            return

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            log.debug(f"配置文件不存在: {yaml_path}")
            return
        except Exception as e:
            log.warning(f"读取配置文件失败: {e}")
            return

        if not data:
            return

        # 串口
        serial_cfg = data.get("serial", {})
        if isinstance(serial_cfg, dict):
            if "port" in serial_cfg:
                config.serial_port = serial_cfg["port"]
            if "baudrate" in serial_cfg:
                config.serial_baudrate = serial_cfg["baudrate"]

        # 唤醒
        wake_cfg = data.get("wake", {})
        if isinstance(wake_cfg, dict):
            if "word" in wake_cfg:
                config.wake_word = wake_cfg["word"]
            if "score_threshold" in wake_cfg:
                config.wake_score_threshold = wake_cfg["score_threshold"]
            if "cooldown" in wake_cfg:
                config.wake_cooldown = wake_cfg["cooldown"]

        # 唤醒后端
        wb_cfg = data.get("wake_backend", {})
        if isinstance(wb_cfg, dict):
            if "mode" in wb_cfg:
                config.wake_backend = wb_cfg["mode"]

        # ASR
        asr_cfg = data.get("asr", {})
        if isinstance(asr_cfg, dict):
            if "backend" in asr_cfg:
                config.asr_backend = asr_cfg["backend"]
            whisper_cfg = asr_cfg.get("whisper", {})
            if isinstance(whisper_cfg, dict):
                _apply_str(whisper_cfg, "api_key", config, "openai_api_key")
                _apply_str(whisper_cfg, "base_url", config, "openai_base_url")
                _apply_str(whisper_cfg, "model", config, "whisper_model")
            iflytek_cfg = asr_cfg.get("iflytek", {})
            if isinstance(iflytek_cfg, dict):
                _apply_str(iflytek_cfg, "app_id", config, "iflytek_app_id")
                _apply_str(iflytek_cfg, "api_key", config, "iflytek_api_key")
                _apply_str(iflytek_cfg, "api_secret", config, "iflytek_api_secret")

        # LLM
        llm_cfg = data.get("llm", {})
        if isinstance(llm_cfg, dict):
            if "backend" in llm_cfg:
                config.llm_backend = llm_cfg["backend"]
            if "system_prompt" in llm_cfg:
                config.system_prompt = llm_cfg["system_prompt"]
            ollama_cfg = llm_cfg.get("ollama", {})
            if isinstance(ollama_cfg, dict):
                _apply_str(ollama_cfg, "host", config, "ollama_host")
                _apply_str(ollama_cfg, "model", config, "ollama_model")
            openai_cfg = llm_cfg.get("openai", {})
            if isinstance(openai_cfg, dict):
                _apply_str(openai_cfg, "api_key", config, "openai_api_key")
                _apply_str(openai_cfg, "base_url", config, "openai_base_url")
                _apply_str(openai_cfg, "model", config, "llm_model")

        # TTS
        tts_cfg = data.get("tts", {})
        if isinstance(tts_cfg, dict):
            if "backend" in tts_cfg:
                config.tts_backend = tts_cfg["backend"]
            edge_cfg = tts_cfg.get("edge", {})
            if isinstance(edge_cfg, dict):
                _apply_str(edge_cfg, "voice", config, "edge_voice")
            pyttsx3_cfg = tts_cfg.get("pyttsx3", {})
            if isinstance(pyttsx3_cfg, dict):
                if "rate" in pyttsx3_cfg:
                    config.pyttsx3_rate = pyttsx3_cfg["rate"]

        # 音频
        audio_cfg = data.get("audio", {})
        if isinstance(audio_cfg, dict):
            for key in ["input_device", "output_device", "sample_rate", "channels",
                        "chunk_size", "record_seconds_max", "silence_threshold",
                        "silence_seconds"]:
                if key in audio_cfg and audio_cfg[key] is not None:
                    setattr(config, key, audio_cfg[key])

        # ROS
        ros_cfg = data.get("ros", {})
        if isinstance(ros_cfg, dict):
            if "enabled" in ros_cfg:
                config.ros_enabled = ros_cfg["enabled"]
            _apply_str(ros_cfg, "master_uri", config, "ros_master_uri")
            _apply_str(ros_cfg, "angle_topic", config, "ros_angle_topic")
            _apply_str(ros_cfg, "question_topic", config, "ros_question_topic")
            _apply_str(ros_cfg, "answer_topic", config, "ros_answer_topic")

        # 本地音频
        la_cfg = data.get("local_audio", {})
        if isinstance(la_cfg, dict):
            if "enabled" in la_cfg:
                config.local_audio_enabled = la_cfg["enabled"]
            _apply_str(la_cfg, "resources_dir", config, "local_audio_dir")
            _apply_str(la_cfg, "wake_sound", config, "wake_sound_file")

        # 其他
        misc_cfg = data.get("misc", {})
        if isinstance(misc_cfg, dict):
            if "save_audio" in misc_cfg:
                config.save_audio = misc_cfg["save_audio"]
            _apply_str(misc_cfg, "temp_dir", config, "temp_dir")
            if "debug" in misc_cfg:
                config.debug = misc_cfg["debug"]

    @staticmethod
    def _apply_env(config: Config):
        """应用环境变量覆盖"""
        import os
        for attr_name, env_var in _ENV_MAP.items():
            val = os.environ.get(env_var)
            if val:
                setattr(config, attr_name, val)

    @staticmethod
    def _apply_cli(config: Config, overrides: dict):
        """应用 CLI 参数覆盖"""
        for key, val in overrides.items():
            if val is not None and hasattr(config, key):
                setattr(config, key, val)


def _apply_str(src: dict, src_key: str, dest_obj: object, dest_attr: str):
    """安全地从 dict 读取字符串并设置属性，跳过 ${VAR} 占位符"""
    val = src.get(src_key)
    if val is not None and isinstance(val, str) and not val.startswith("${"):
        setattr(dest_obj, dest_attr, val)


# 环境变量映射
_ENV_MAP = {
    "openai_api_key": "OPENAI_API_KEY",
    "openai_base_url": "OPENAI_BASE_URL",
    "ollama_host": "OLLAMA_HOST",
    "iflytek_app_id": "IFLYTEK_APP_ID",
    "iflytek_api_key": "IFLYTEK_API_KEY",
    "iflytek_api_secret": "IFLYTEK_API_SECRET",
    "serial_port": "VOICE_SERIAL_PORT",
    "ros_master_uri": "ROS_MASTER_URI",
}
