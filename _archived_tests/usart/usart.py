import serial
import time

UPLOAD_DATA = 2  # 接收实时的编码器 Receive real-time encoder

MOTOR_TYPE = 1   # 请根据实际情况修改 Modify according to your actual motor

# 串口初始化 Serial port initialization
ser = serial.Serial(
    port='/dev/ttyUSB0',  
    baudrate=115200,      
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    bytesize=serial.EIGHTBITS,
    timeout=1                     
)

recv_buffer = ""

def send_data(data):
    print("[TX] " + data)
    ser.write(data.encode())
    time.sleep(0.05)

def receive_data():
    global recv_buffer
    if ser.in_waiting > 0:
        raw_data = ser.read(ser.in_waiting).decode()
        print("[RX] " + raw_data.strip())
        recv_buffer += raw_data
        messages = recv_buffer.split("#")
        recv_buffer = messages[-1]
        if len(messages) > 1:
            return messages[0] + "#"
    return None

def set_motor_type(data):
    send_data("$mtype:{}#".format(data))

def set_motor_deadzone(data):
    send_data("$deadzone:{}#".format(data))

def set_pluse_line(data):
    send_data("$mline:{}#".format(data))

def set_pluse_phase(data):
    send_data("$mphase:{}#".format(data))

def set_wheel_dis(data):
    send_data("$wdiameter:{}#".format(data))

def control_speed(m1, m2, m3, m4):
    send_data("$spd:{},{},{},{}#".format(m1, m2, m3, m4))

def control_pwm(m1, m2, m3, m4):
    send_data("$pwm:{},{},{},{}#".format(m1, m2, m3, m4))

def parse_data(data):
    data = data.strip()
    if data.startswith("$MAll:"):
        values_str = data[6:-1]
        values = list(map(int, values_str.split(',')))
        parsed = ', '.join([f"M{i+1}:{value}" for i, value in enumerate(values)])
        return parsed
    elif data.startswith("$MTEP:"):
        values_str = data[6:-1]
        values = list(map(int, values_str.split(',')))
        parsed = ', '.join([f"M{i+1}:{value}" for i, value in enumerate(values)])
        return parsed
    elif data.startswith("$MSPD:"):
        values_str = data[6:-1]
        values = [float(value) if '.' in value else int(value) for value in values_str.split(',')]
        parsed = ', '.join([f"M{i+1}:{value}" for i, value in enumerate(values)])
        return parsed

def send_upload_command(mode):
    if mode == 0: send_data("$upload:0,0,0#")
    elif mode == 1: send_data("$upload:1,0,0#")
    elif mode == 2: send_data("$upload:0,1,0#")
    elif mode == 3: send_data("$upload:0,0,1#")

def set_motor_parameter():
    # 此处保留你原有的电机参数配置 Keep your original motor parameter configuration
    if MOTOR_TYPE == 1:
        set_motor_type(1); time.sleep(0.1)
        set_pluse_phase(30); time.sleep(0.1)
        set_pluse_line(11); time.sleep(0.1)
        set_wheel_dis(67.00); time.sleep(0.1)
        set_motor_deadzone(1600); time.sleep(0.1)
    # ... (其他电机类型省略，按原代码补充即可) ...

if __name__ == "__main__":
    try:
        print("Initializing motor parameters, please wait...")
        send_upload_command(UPLOAD_DATA)
        time.sleep(0.1)
        set_motor_parameter()

        # ===== 加减速参数配置 =====
        # Acceleration and Deceleration Parameters
        MAX_SPEED = 500       # 最大速度 mm/s (请根据你的小车实际情况调整) Maximum speed
        MIN_SPEED = 0         # 起始/停止速度 Starting/Stopping speed
        ACCEL_STEP = 10       # 每次循环增加的速度 Speed increment per loop
        DECEL_STEP = 10       # 每次循环减少的速度 Speed decrement per loop
        LOOP_DELAY = 0.05     # 每次循环的延时(秒)，值越小加减速越平滑 Loop delay in seconds

        current_speed = MIN_SPEED
        is_decelerating = False  # 标记是否在减速阶段 Flag for deceleration phase

        print("Starting Slow -> Fast -> Slow movement...")

        while True:
            # 1. 接收并解析编码器数据 Receive and parse encoder data
            received_message = receive_data()
            if received_message:
                parsed = parse_data(received_message)
                if parsed:
                    print(parsed)

            # 2. 速度控制逻辑 Speed control logic
            if not is_decelerating:
                # 加速阶段 Acceleration phase
                current_speed += ACCEL_STEP
                if current_speed >= MAX_SPEED:
                    current_speed = MAX_SPEED
                    is_decelerating = True  # 达到最大速度，切换到减速阶段 Switch to deceleration
            else:
                # 减速阶段 Deceleration phase
                current_speed -= DECEL_STEP
                if current_speed <= MIN_SPEED:
                    current_speed = MIN_SPEED
                    # 减速到0，停止电机并退出循环 Stop motor and exit loop
                    if MOTOR_TYPE == 4:
                        control_pwm(0, 0, 0, 0)
                    else:
                        control_speed(0, 0, 0, 0)
                    print("Movement completed. Motor stopped.")
                    break # 完成一次慢-快-慢，退出循环 Exit loop after one cycle

            # 3. 发送速度指令 Send speed command
            # 四个轮子同速(如果是差速转向小车，M1和M3可能需要取反，请根据实际接线调整)
            # Four wheels at the same speed (For differential drive, M1 and M3 might need to be negated depending on wiring)
            if MOTOR_TYPE == 4:
                control_pwm(current_speed*2, current_speed*2, current_speed*2, current_speed*2)
            else:
                control_speed(current_speed, current_speed, current_speed, current_speed)

            # 打印当前速度 Print current speed
            print(f"Current Speed: {current_speed} mm/s")

            time.sleep(LOOP_DELAY)

    except KeyboardInterrupt:
        print("\nProgram interrupted by user.")
    finally:
        # 确保程序退出时电机停止 Ensure motor stops when program exits
        if MOTOR_TYPE == 4:
            control_pwm(0, 0, 0, 0)
        else:
            control_speed(0, 0, 0, 0)
        print("Motors force stopped. Serial port closed.")
        ser.close()
