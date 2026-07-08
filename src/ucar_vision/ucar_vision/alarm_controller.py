#!/usr/bin/env python3
"""
报警控制器节点 — USB音频 + LED灯光 + 电机联动

硬件:
  - 讯飞 M260C USB麦克风阵列 (USB声卡, 播放WAV报警音)
  - GPIO LED 报警灯 (单颗红色LED, 串220Ω限流电阻)
  - JGB520 电机驱动

音频方案:
  - 使用 ALSA aplay 播放 WAV 文件 (Linux自带, 零Python依赖)
  - 报警音效自动生成 (Python内置wave模块, 无需外部音频文件)
  - 支持选择音频输出设备 (默认default, M260C可指定为 hw:1,0)

LED接线:
  GPIO_PIN → 220Ω电阻 → LED正极 → LED负极 → GND
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String, Int32
from geometry_msgs.msg import Twist
import time
import os
import sys
import struct
import math
import wave
import subprocess
import threading
import atexit


# ═══════════════════════════════════════════════════════
# 报警音效生成器 (纯Python, 无需外部依赖)
# ═══════════════════════════════════════════════════════

class AlarmSoundGenerator:
    """用Python内置wave模块生成报警WAV文件"""

    SAMPLE_RATE = 44100
    AMPLITUDE = 16000   # 16-bit signed, max 32767

    @classmethod
    def _make_wav(cls, filepath, samples, duration_sec):
        """写入单声道 16-bit PCM WAV"""
        n_frames = min(len(samples), int(cls.SAMPLE_RATE * duration_sec))
        with wave.open(filepath, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(cls.SAMPLE_RATE)
            raw = b''
            for i in range(n_frames):
                val = max(-32767, min(32767, int(samples[i] * cls.AMPLITUDE)))
                raw += struct.pack('<h', val)
            wf.writeframes(raw)
        return filepath

    @classmethod
    def generate_fall_alarm(cls, filepath, duration=3.0):
        """
        跌倒报警音: 低频急促警笛
        频率 400Hz→800Hz 往复扫描, 每次扫描0.15秒
        声音特征: 急促上升下降, 类似救护车警笛但频率更低
        """
        samples = []
        sweep_duration = 0.15  # 每次扫描时长
        n_sweeps = int(duration / sweep_duration)

        for sweep in range(n_sweeps):
            n = int(cls.SAMPLE_RATE * sweep_duration)
            for i in range(n):
                t = i / cls.SAMPLE_RATE
                # 400Hz → 800Hz 线性扫描
                freq = 400.0 + (800.0 - 400.0) * (t / sweep_duration)
                val = math.sin(2.0 * math.pi * freq * t)
                # 音量包络: 渐入渐出
                env = min(1.0, t / 0.02) * max(0.0, 1.0 - (t - sweep_duration + 0.02) / 0.02)
                samples.append(val * env)

        return cls._make_wav(filepath, samples, duration)

    @classmethod
    def generate_fire_alarm(cls, filepath, duration=3.0):
        """
        火焰报警音: 高频急促蜂鸣
        三短一长模式: beep-beep-beep-BEEEEP 循环
        """
        samples = []
        pattern = [0.08, 0.08, 0.08, 0.12, 0.08, 0.08, 0.08, 0.40]  # on/off交替
        freq_short = 1000.0   # 短鸣频率(尖锐)
        freq_long = 1500.0    # 长鸣频率(更尖锐)

        t = 0.0
        idx = 0
        frame = 0
        while t < duration:
            segment = pattern[idx % len(pattern)]
            n = int(cls.SAMPLE_RATE * segment)
            for i in range(n):
                t_current = i / cls.SAMPLE_RATE
                if idx % 2 == 0:  # 有声段
                    f = freq_long if segment > 0.3 else freq_short
                    val = math.sin(2.0 * math.pi * f * t_current)
                    # 方波调制让声音更刺耳
                    val = 1.0 if val > 0.1 else -1.0 if val < -0.1 else val
                    env = min(1.0, t_current / 0.005) * max(0.0, 1.0 - (t_current - segment + 0.005) / 0.005)
                    samples.append(val * env * 0.6)
                else:  # 静默段
                    samples.append(0.0)
            idx += 1
            t += segment

        return cls._make_wav(filepath, samples, duration)

    @classmethod
    def generate_ok_sound(cls, filepath, duration=0.5):
        """
        系统就绪音: 上升音阶 C-E-G 三和弦
        频率: 523Hz→659Hz→784Hz
        """
        samples = []
        note_duration = duration / 3.0
        freqs = [523.25, 659.25, 783.99]  # C5, E5, G5

        for note_idx, freq in enumerate(freqs):
            n = int(cls.SAMPLE_RATE * note_duration)
            for i in range(n):
                t = i / cls.SAMPLE_RATE
                val = math.sin(2.0 * math.pi * freq * t)
                # 钢琴式衰减包络
                env = math.exp(-t / (note_duration * 0.3))
                samples.append(val * env)

        return cls._make_wav(filepath, samples, duration)


# ═══════════════════════════════════════════════════════
# 报警控制器主节点
# ═══════════════════════════════════════════════════════

class AlarmController(Node):
    """报警融合: USB音频播报 + LED灯光 + 电机联动"""

    LEVEL_NONE = 0
    LEVEL_WARN = 1
    LEVEL_CRITICAL = 2

    def __init__(self):
        super().__init__('alarm_controller')

        # ═══════════════════════════════
        # 参数声明
        # ═══════════════════════════════

        # ── LED ──
        self.declare_parameter('led_gpio', 23)              # 报警LED的GPIO (BCM编号)
        self.declare_parameter('led_active_high', True)     # True=高电平点亮, False=低电平点亮

        # ── USB音频 ──
        self.declare_parameter('audio_enabled', True)        # 是否启用音频报警
        self.declare_parameter('audio_device', 'default')    # ALSA设备名
        # M260C USB声卡常见设备名: 'default', 'plughw:1,0', 'plughw:2,0'
        # 用 aplay -l 查看具体编号
        self.declare_parameter('audio_volume', 80)            # 音量 0-100 (aplay不支持调音量，仅记录)
        self.declare_parameter('sounds_dir', '/home/sunrise/ucar_01/sounds')

        # ── 报警行为 ──
        self.declare_parameter('auto_stop_on_alarm', True)       # 报警时停车
        self.declare_parameter('alarm_cooldown', 8.0)            # 冷却时间(秒)
        self.declare_parameter('led_blink_on_alarm', True)       # 报警时LED闪烁(否则常亮)
        self.declare_parameter('led_blink_interval', 0.3)        # 闪烁间隔(秒)

        # ── 模拟模式 ──
        self.declare_parameter('sim_mode', False)

        # ═══════════════════════════════
        # 读取参数
        # ═══════════════════════════════
        self.led_pin = self.get_parameter('led_gpio').value
        self.led_active_high = self.get_parameter('led_active_high').value
        self.audio_enabled = self.get_parameter('audio_enabled').value
        self.audio_device = self.get_parameter('audio_device').value
        self.sounds_dir = self.get_parameter('sounds_dir').value
        self.auto_stop = self.get_parameter('auto_stop_on_alarm').value
        self.alarm_cooldown = self.get_parameter('alarm_cooldown').value
        self.led_blink = self.get_parameter('led_blink_on_alarm').value
        self.led_blink_interval = self.get_parameter('led_blink_interval').value
        self.sim_mode = self.get_parameter('sim_mode').value

        # ═══════════════════════════════
        # 订阅
        # ═══════════════════════════════
        self.create_subscription(Bool, '/fall_alert', self.fall_callback, 10)
        self.create_subscription(Bool, '/fire_alert', self.fire_callback, 10)
        self.create_subscription(String, '/monitor_status', self.status_callback, 10)

        # ═══════════════════════════════
        # 发布
        # ═══════════════════════════════
        self.alarm_pub = self.create_publisher(String, '/alarm_status', 10)
        self.alarm_level_pub = self.create_publisher(Int32, '/alarm_level', 10)
        self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)

        # ═══════════════════════════════
        # LED GPIO 初始化
        # ═══════════════════════════════
        self.gpio = None
        self._init_gpio()

        # ═══════════════════════════════
        # 音频 初始化
        # ═══════════════════════════════
        self.audio_ok = False
        self.audio_player = None       # 当前播放的子进程
        self._init_audio()

        # ═══════════════════════════════
        # 状态
        # ═══════════════════════════════
        self.alarm_active = False
        self.alarm_type = None
        self.alarm_level = self.LEVEL_NONE
        self.last_alarm_time = 0.0
        self.status_msg = 'System OK'
        self.led_state = False          # LED当前状态
        self.led_blink_thread = None     # LED闪烁线程
        self.led_blink_running = False

        # LED 自检: 快闪3次表示系统就绪
        self._led_self_test()

        self.get_logger().info(
            f'╔══════════════════════════════════╗\n'
            f'║  Alarm Controller Ready         ║\n'
            f'║  LED:  GPIO{self.led_pin}                   ║\n'
            f'║  Audio: {"M260C USB" if self.audio_ok else "DISABLED":20s} ║\n'
            f'║  Device: {self.audio_device:22s} ║\n'
            f'║  SIM:   {"ON" if self.sim_mode else "OFF":22s} ║\n'
            f'╚══════════════════════════════════╝')

    # ═══════════════════════════════════
    # GPIO 初始化
    # ═══════════════════════════════════
    def _init_gpio(self):
        """初始化 LED GPIO"""
        if self.sim_mode:
            self.get_logger().info(f'[SIM] LED would use GPIO{self.led_pin}')
            return
        try:
            # RDK X5 支持两种 GPIO 库
            # 优先使用地平线 Hobot GPIO (如果可用)
            try:
                from hobot_gpio import GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.led_pin, GPIO.OUT)
                GPIO.output(self.led_pin, GPIO.LOW)
                self.gpio = GPIO
                self.get_logger().info(f'GPIO{self.led_pin} initialized (Hobot GPIO)')
                return
            except ImportError:
                pass

            # 后备: 标准 RPi.GPIO
            try:
                import RPi.GPIO as GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.led_pin, GPIO.OUT)
                GPIO.output(self.led_pin, GPIO.LOW)
                self.gpio = GPIO
                self.get_logger().info(f'GPIO{self.led_pin} initialized (RPi.GPIO)')
                return
            except ImportError:
                pass

            # 后备: 通过 sysfs 直接操作
            self.gpio = 'sysfs'
            self.get_logger().info(f'GPIO{self.led_pin} using sysfs fallback')
        except Exception as e:
            self.get_logger().warn(f'GPIO init failed: {e}, using sim')
            self.sim_mode = True

    def _led_write(self, on):
        """写 LED 电平"""
        if self.sim_mode:
            state = 'ON' if on else 'OFF'
            if self.led_state != on:
                self.get_logger().info(f'[SIM] LED → {state}')
            self.led_state = on
            return

        try:
            value = True if (on == self.led_active_high) else False
            if self.gpio == 'sysfs':
                self._sysfs_gpio_write(on)
            elif self.gpio is not None:
                self.gpio.output(self.led_pin,
                                 self.gpio.HIGH if value else self.gpio.LOW)
            self.led_state = on
        except Exception as e:
            self.get_logger().error(f'LED write error: {e}')

    def _sysfs_gpio_write(self, on):
        """通过 sysfs 控制 GPIO (万能后备方案)"""
        gpio_path = f'/sys/class/gpio/gpio{self.led_pin}'
        try:
            if not os.path.exists(gpio_path):
                with open('/sys/class/gpio/export', 'w') as f:
                    f.write(str(self.led_pin))
                time.sleep(0.1)
            with open(f'{gpio_path}/direction', 'w') as f:
                f.write('out')
            with open(f'{gpio_path}/value', 'w') as f:
                f.write('1' if on else '0')
        except Exception:
            pass  # sysfs 失败时静默

    def _led_self_test(self):
        """LED自检: 快闪3次"""
        for _ in range(3):
            self._led_write(True)
            time.sleep(0.1)
            self._led_write(False)
            time.sleep(0.1)
        self.get_logger().info('LED self-test: 3 blinks ✓')

    def _led_blink_thread_func(self, interval, duration):
        """LED 闪烁线程"""
        start = time.time()
        while self.led_blink_running and (time.time() - start < duration):
            self._led_write(True)
            time.sleep(interval)
            self._led_write(False)
            time.sleep(interval)
        # 闪烁结束后保持亮或灭
        if self.alarm_active:
            self._led_write(True)

    # ═══════════════════════════════════
    # USB 音频 初始化
    # ═══════════════════════════════════
    def _init_audio(self):
        """初始化音频: 检查设备 + 生成音效文件"""
        if not self.audio_enabled:
            self.get_logger().info('Audio disabled by config')
            return

        # 1. 检查 aplay 是否可用
        try:
            result = subprocess.run(['which', 'aplay'],
                                    capture_output=True, text=True, timeout=3)
            if result.returncode != 0:
                self.get_logger().warn('aplay not found, audio disabled')
                self.audio_enabled = False
                return
        except Exception:
            self.get_logger().warn('Cannot check aplay, audio disabled')
            self.audio_enabled = False
            return

        # 2. 列出音频设备
        try:
            result = subprocess.run(['aplay', '-l'], capture_output=True, text=True, timeout=3)
            self.get_logger().info(f'Audio devices:\n{result.stdout}')
        except Exception:
            pass

        # 3. 创建音效目录 + 生成WAV文件
        os.makedirs(self.sounds_dir, exist_ok=True)
        self._ensure_sound_files()

        # 4. 测试播放 (可选，异步)
        self.audio_ok = True
        self.get_logger().info(f'USB Audio ready, device={self.audio_device}')

    def _ensure_sound_files(self):
        """确保报警音效文件存在，不存在则自动生成"""
        sounds = {
            'fall_alarm.wav': ('跌倒报警(低音警笛)', AlarmSoundGenerator.generate_fall_alarm),
            'fire_alarm.wav': ('火焰报警(高频蜂鸣)', AlarmSoundGenerator.generate_fire_alarm),
            'system_ok.wav': ('系统就绪(上升和弦)', AlarmSoundGenerator.generate_ok_sound),
        }

        for filename, (desc, generator) in sounds.items():
            filepath = os.path.join(self.sounds_dir, filename)
            if not os.path.exists(filepath):
                try:
                    generator(filepath)
                    self.get_logger().info(f'Sound generated: {filename} ({desc})')
                except Exception as e:
                    self.get_logger().error(f'Failed to generate {filename}: {e}')

    # ═══════════════════════════════════
    # 音频播放
    # ═══════════════════════════════════
    def play_sound(self, sound_file, block=False):
        """
        播放WAV音效
        Args:
            sound_file: WAV文件名 (在 sounds_dir 下)
            block: True=阻塞播放, False=异步播放
        """
        if not self.audio_ok:
            return

        filepath = os.path.join(self.sounds_dir, sound_file)
        if not os.path.exists(filepath):
            self.get_logger().warn(f'Sound file not found: {filepath}')
            return

        # 终止上一个播放(避免重叠)
        self.stop_sound()

        cmd = ['aplay', '-D', self.audio_device, '-q', filepath]

        try:
            if block:
                subprocess.run(cmd, timeout=10)
            else:
                self.audio_player = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
                self.get_logger().info(f'Playing: {sound_file}')
        except Exception as e:
            self.get_logger().error(f'Audio play error: {e}')

    def stop_sound(self):
        """停止当前播放"""
        if self.audio_player is not None:
            try:
                self.audio_player.terminate()
                self.audio_player.wait(timeout=2)
            except Exception:
                try:
                    self.audio_player.kill()
                except Exception:
                    pass
            self.audio_player = None

    # ═══════════════════════════════════
    # 报警回调
    # ═══════════════════════════════════
    def fall_callback(self, msg):
        if msg.data:
            self.trigger_alarm('fall', self.LEVEL_CRITICAL)

    def fire_callback(self, msg):
        if msg.data:
            self.trigger_alarm('fire', self.LEVEL_CRITICAL)

    def status_callback(self, msg):
        self.status_msg = msg.data

    def trigger_alarm(self, alarm_type, level):
        """触发报警主流程"""
        now = self.get_clock().now().nanoseconds / 1e9

        # 冷却检查
        if now - self.last_alarm_time < self.alarm_cooldown:
            self.get_logger().info(
                f'Alarm cooldown ({self.alarm_cooldown - (now - self.last_alarm_time):.0f}s left)')
            return

        self.alarm_active = True
        self.alarm_type = alarm_type
        self.alarm_level = level
        self.last_alarm_time = now

        # ════ 步骤1: 发布报警状态 ════
        self.alarm_pub.publish(String(data=f'CRITICAL:{alarm_type}'))
        self.alarm_level_pub.publish(Int32(data=level))

        alarm_names = {'fall': '跌倒检测', 'fire': '火焰检测'}
        alarm_name = alarm_names.get(alarm_type, alarm_type)

        self.get_logger().error(
            f'\n'
            f'╔══════════════════════════════════════╗\n'
            f'║  🚨  {alarm_name} 报警触发！          ║\n'
            f'║  Type: {alarm_type:28s} ║\n'
            f'║  Time: {time.strftime("%H:%M:%S"):28s} ║\n'
            f'╚══════════════════════════════════════╝\n'
        )

        # ════ 步骤2: 自动停车 ════
        if self.auto_stop:
            self.stop_robot()

        # ════ 步骤3: LED 灯光报警 ════
        if self.led_blink:
            # 闪烁模式 (开新线程, 不阻塞主流程)
            self.led_blink_running = True
            duration = 10.0  # 闪烁持续10秒后自动关闭
            self.led_blink_thread = threading.Thread(
                target=self._led_blink_thread_func,
                args=(self.led_blink_interval, duration),
                daemon=True)
            self.led_blink_thread.start()
        else:
            # 常亮模式
            self._led_write(True)

        # ════ 步骤4: USB 音频报警 ════
        if alarm_type == 'fall':
            self.play_sound('fall_alarm.wav', block=False)
        elif alarm_type == 'fire':
            self.play_sound('fire_alarm.wav', block=False)

        # ════ 步骤5: 报警恢复定时器 (10秒后自动清除) ════
        self._alarm_clear_timer = self.create_timer(10.0, self._on_clear_timer)

    def _on_clear_timer(self):
        """定时器回调: 清除声光报警并自毁"""
        self._alarm_clear_timer.cancel()
        self._alarm_clear_timer = None
        self.clear_alarm()

    def clear_alarm(self):
        """清除声光报警 (也可外部调用)"""
        self.stop_sound()
        self._led_write(False)
        self.led_blink_running = False
        self.alarm_active = False
        self.alarm_level = self.LEVEL_NONE
        self.get_logger().info('Alarm cleared')

    # ═══════════════════════════════════
    # 机器人控制
    # ═══════════════════════════════════
    def stop_robot(self):
        """紧急停车"""
        stop = Twist()
        for _ in range(5):
            self.cmd_vel_pub.publish(stop)
            time.sleep(0.1)
        self.get_logger().warn('🛑 Robot STOPPED')

    # ═══════════════════════════════════
    # 手动控制 (可通过ROS2 service调用)
    # ═══════════════════════════════════
    def led_on(self):
        self._led_write(True)

    def led_off(self):
        self._led_write(False)

    def test_audio(self):
        """播放系统就绪音(用于测试音频设备)"""
        self.play_sound('system_ok.wav', block=True)
        self.get_logger().info('Audio test complete')

    # ═══════════════════════════════════
    # 清理
    # ═══════════════════════════════════
    def destroy_node(self):
        self.get_logger().info('Shutting down...')
        # 取消定时器
        if hasattr(self, '_alarm_clear_timer') and self._alarm_clear_timer is not None:
            self._alarm_clear_timer.cancel()
        self.stop_robot()
        self.stop_sound()
        self._led_write(False)
        self.led_blink_running = False
        try:
            if self.gpio is not None and self.gpio != 'sysfs':
                self.gpio.cleanup()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = AlarmController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
