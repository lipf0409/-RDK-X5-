#!/usr/bin/env python3
"""JGB520 电机驱动 ROS2 节点 M1=左前 M2=左后 M3=右前 M4=右后"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from std_msgs.msg import Float32MultiArray
from tf2_ros import TransformBroadcaster
import serial
import time
import math

CALIB = [1.02, 1.04, 1.04, 1.03]  # M1左前 M2左后 M3右前 M4右后


class JGB520Driver(Node):
    def __init__(self):
        super().__init__('jgb520_driver')

        self.declare_parameter('serial_port', '/dev/ttyS1')
        self.declare_parameter('baudrate', 115200)
        self.declare_parameter('motor_type', 1)
        self.declare_parameter('wheel_diameter', 0.067)
        self.declare_parameter('wheel_base', 0.25)
        self.declare_parameter('encoder_resolution', 330)
        self.declare_parameter('max_speed', 0.5)
        self.declare_parameter('max_angular_speed', 1.0)
        self.declare_parameter('calib_m1', CALIB[0])
        self.declare_parameter('calib_m2', CALIB[1])
        self.declare_parameter('calib_m3', CALIB[2])
        self.declare_parameter('calib_m4', CALIB[3])

        self.serial_port = self.get_parameter('serial_port').value
        self.baudrate = self.get_parameter('baudrate').value
        self.motor_type = self.get_parameter('motor_type').value
        self.wheel_diameter = self.get_parameter('wheel_diameter').value
        self.wheel_base = self.get_parameter('wheel_base').value
        self.encoder_resolution = self.get_parameter('encoder_resolution').value
        self.max_speed = self.get_parameter('max_speed').value
        self.max_angular_speed = self.get_parameter('max_angular_speed').value
        self.calib = [
            self.get_parameter('calib_m1').value,
            self.get_parameter('calib_m2').value,
            self.get_parameter('calib_m3').value,
            self.get_parameter('calib_m4').value,
        ]

        self.cmd_sub = self.create_subscription(Twist, '/cmd_vel', self.cmd_vel_callback, 10)
        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self.encoder_pub = self.create_publisher(Float32MultiArray, '/encoder_raw', 10)

        # ★ TF 广播器 — slam_toolbox 必需
        self.tf_broadcaster = TransformBroadcaster(self)

        self.ser = None
        self.recv_buffer = ""
        self.speeds = [0.0, 0.0, 0.0, 0.0]  # M1-M4 当前速度 mm/s
        self.last_encoder_time = self.get_clock().now()
        self.serial_ok = False

        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0
        self.last_time = self.get_clock().now()

        self.try_connect_serial()

        self.odom_timer = self.create_timer(0.05, self.publish_odometry)
        self.read_timer = self.create_timer(0.02, self.read_encoder_data)
        self.reconnect_timer = self.create_timer(2.0, self.check_serial)

        self.get_logger().info('JGB520 Driver initialized')

    # ── 串口 ───────────────────────────────────────────

    def try_connect_serial(self):
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

        try:
            self.ser = serial.Serial(
                self.serial_port, self.baudrate,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout=0.05)
            time.sleep(0.15)

            # 配置驱动板参数
            self._send("$mtype:1#");       time.sleep(0.05)
            self._send("$mphase:30#");     time.sleep(0.05)
            self._send("$mline:11#");      time.sleep(0.05)
            self._send("$wdiameter:67#");  time.sleep(0.05)
            self._send("$MPID:1.5,0.12,0.5#");  time.sleep(0.05)
            self._send("$deadzone:800#");  time.sleep(0.05)

            # $MSPD 连续上报 (速度 mm/s)
            self._send("$upload:0,1,1#")

            self.serial_ok = True
            self.get_logger().info(
                f'Serial {self.serial_port} opened | '
                f'M1左前 M2左后 M3右前 M4右后 | '
                f'PID:1.5/0.12/0.5 dz:800'
            )
        except Exception as e:
            self.serial_ok = False
            self.get_logger().warn(f'Serial open failed: {e}, retrying...')

    def check_serial(self):
        if not self.serial_ok:
            self.try_connect_serial()

    def _send(self, data):
        if not self.serial_ok or not self.ser:
            return
        try:
            self.ser.write(data.encode())
            time.sleep(0.005)
        except Exception as e:
            self.get_logger().warn(f'Serial write error: {e}')
            self.serial_ok = False

    def _recv(self):
        if not self.serial_ok or not self.ser:
            return None
        try:
            if self.ser.in_waiting > 0:
                raw = self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')
                self.recv_buffer += raw
                msgs = self.recv_buffer.split('#')
                self.recv_buffer = msgs[-1]
                if len(msgs) > 1:
                    return msgs[0] + '#'
        except Exception as e:
            self.get_logger().warn(f'Serial read error: {e}')
            self.serial_ok = False
        return None

    # ── 编码器 ─────────────────────────────────────────

    def read_encoder_data(self):
        msg = self._recv()
        if not msg:
            return
        msg = msg.strip()
        # $MSPD:spd1,spd2,spd3,spd4#  速度 mm/s
        if msg.startswith("$MSPD:"):
            try:
                vals = [float(x) for x in msg[6:-1].split(',')]
                if len(vals) >= 4:
                    self.speeds = vals[:4]
                    self.last_encoder_time = self.get_clock().now()
                    enc_msg = Float32MultiArray()
                    enc_msg.data = vals[:4]
                    self.encoder_pub.publish(enc_msg)
            except Exception:
                pass

    # ── 速度控制 ───────────────────────────────────────

    def cmd_vel_callback(self, msg):
        try:
            linear = max(-self.max_speed, min(msg.linear.x, self.max_speed))
            angular = max(-self.max_angular_speed, min(msg.angular.z, self.max_angular_speed))

            # 差速运动学：左轮 = v - ω·d/2,  右轮 = v + ω·d/2
            left_target = (linear - angular * self.wheel_base / 2.0) * 1000.0
            right_target = (linear + angular * self.wheel_base / 2.0) * 1000.0

            # M1=左前 M2=左后 M3=右前 M4=右后 → [左, 左, 右, 右]
            raw = [left_target, left_target, right_target, right_target]

            # 加校准系数，限幅 ±500
            out = [int(max(-500, min(raw[i] * self.calib[i], 500))) for i in range(4)]
            self._send(f"$spd:{out[0]},{out[1]},{out[2]},{out[3]}#")

        except Exception as e:
            self.get_logger().warn(f'cmd_vel error: {e}')

    # ── 里程计 + TF ────────────────────────────────────

    def publish_odometry(self):
        now = self.get_clock().now()

        # ★ 先更新 dt（必须在所有 return 之前），防止 last_time 冻结导致 dt 爆炸
        dt = (now - self.last_time).nanoseconds / 1e9
        self.last_time = now

        # 编码器数据过期检查：超过 0.15 秒没收到新数据 → 视为停止
        encoder_age = (now - self.last_encoder_time).nanoseconds / 1e9
        if encoder_age > 0.15:
            self.speeds = [0.0, 0.0, 0.0, 0.0]

        # 过滤异常 dt
        if dt <= 0 or dt > 0.5:
            dt = 0.0

        # 用 $MSPD 速度积分（静止时 speed≈0，里程计不增长）
        if sum(abs(s) for s in self.speeds) >= 1.0:
            # M1左前 M2左后 / M3右前 M4右后 → 左右平均速度 (m/s)
            left_speed = (self.speeds[0] + self.speeds[1]) / 2.0 / 1000.0
            right_speed = (self.speeds[2] + self.speeds[3]) / 2.0 / 1000.0

            v = (left_speed + right_speed) / 2.0
            omega = (right_speed - left_speed) / self.wheel_base

            delta_x = v * math.cos(self.theta) * dt
            delta_y = v * math.sin(self.theta) * dt
            delta_theta = omega * dt

            self.x += delta_x
            self.y += delta_y
            self.theta += delta_theta
        else:
            v = 0.0
            omega = 0.0

        # ★★★ 关键修复：无条件发布 odom 话题（ROS1 base_driver 就是这样做的）
        # slam_toolbox 需要持续的 odom 消息来维持状态
        odom = Odometry()
        odom.header.stamp = now.to_msg()
        odom.header.frame_id = 'odom'
        odom.child_frame_id = 'base_link'
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.orientation.z = math.sin(self.theta / 2.0)
        odom.pose.pose.orientation.w = math.cos(self.theta / 2.0)
        odom.twist.twist.linear.x = v
        odom.twist.twist.angular.z = omega
        # 协方差：静止时宽松（给 scan matching 更大搜索空间），运动时紧凑
        if sum(abs(s) for s in self.speeds) < 1.0:
            odom.pose.covariance[0] = 0.05   # x
            odom.pose.covariance[7] = 0.05   # y
            odom.pose.covariance[35] = 0.05  # theta
            odom.twist.covariance[0] = 0.05
            odom.twist.covariance[35] = 0.05
        else:
            odom.pose.covariance[0] = 0.01   # x
            odom.pose.covariance[7] = 0.01   # y
            odom.pose.covariance[35] = 0.01  # theta
            odom.twist.covariance[0] = 0.01
            odom.twist.covariance[35] = 0.01
        self.odom_pub.publish(odom)

        # ★★★ 关键修复：无条件广播 TF: odom → base_link（ROS1 base_driver 也是这样做的）
        self._broadcast_tf(now)

    def _broadcast_tf(self, now=None):
        """广播 odom → base_link 的 TF 变换（slam_toolbox 必需）"""
        t = TransformStamped()
        t.header.stamp = (now or self.get_clock().now()).to_msg()
        t.header.frame_id = 'odom'
        t.child_frame_id = 'base_link'
        t.transform.translation.x = self.x
        t.transform.translation.y = self.y
        t.transform.translation.z = 0.0
        t.transform.rotation.z = math.sin(self.theta / 2.0)
        t.transform.rotation.w = math.cos(self.theta / 2.0)
        self.tf_broadcaster.sendTransform(t)

    # ── 清理 ───────────────────────────────────────────

    def stop_motors(self):
        try:
            self._send("$spd:0,0,0,0#")
        except Exception:
            pass

    def destroy_node(self):
        self.stop_motors()
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    driver = JGB520Driver()
    try:
        rclpy.spin(driver)
    except KeyboardInterrupt:
        pass
    finally:
        driver.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
