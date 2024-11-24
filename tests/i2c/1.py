# master.py
import machine
import time

# Define pins
LINE_DATA = machine.Pin(14, machine.Pin.IN, machine.Pin.PULL_UP)
LINE_CTRL = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)
START_PIN = machine.Pin(16, machine.Pin.IN, machine.Pin.PULL_UP)

# States
IDLE = 0
RECEIVING = 1
SENDING = 2

current_state = IDLE

def set_line_data(state):
    if state is None:
        LINE_DATA.init(machine.Pin.IN, machine.Pin.PULL_UP)
    else:
        LINE_DATA.init(machine.Pin.OUT)
        LINE_DATA.value(state)

def set_line_ctrl(state):
    if state is None:
        LINE_CTRL.init(machine.Pin.IN, machine.Pin.PULL_UP)
    else:
        LINE_CTRL.init(machine.Pin.OUT)
        LINE_CTRL.value(state)

def master_send(data_byte, slave_id):
    global current_state
    print(f"Master: Sending data to Slave {slave_id}: {data_byte}")
    
    current_state = SENDING
    # Signal start of transmission
    set_line_ctrl(0)
    time.sleep_ms(40)
    set_line_ctrl(None)
    
    # Send address and data
    send_byte(slave_id)
    send_byte(data_byte)
    
    print("Master: Data transmission complete")
    current_state = IDLE
    time.sleep_ms(100)  # Give slaves time to process

def send_byte(byte):
    for i in range(7, -1, -1):
        bit = (byte >> i) & 0x01
        set_line_data(bit)
        set_line_ctrl(0)
        time.sleep_ms(40)
        set_line_ctrl(None)
        # Wait for ack with timeout
        timeout = time.ticks_add(time.ticks_ms(), 1000)
        while LINE_CTRL.value() == 1:
            if time.ticks_diff(timeout, time.ticks_ms()) <= 0:
                print("Master: Timeout waiting for ack")
                return False
        set_line_data(None)
        while LINE_CTRL.value() == 0:
            if time.ticks_diff(timeout, time.ticks_ms()) <= 0:
                print("Master: Timeout waiting for line release")
                return False
    return True

def receive_byte():
    data_bits = []
    for _ in range(8):
        # Wait for bit with timeout
        timeout = time.ticks_add(time.ticks_ms(), 1000)
        while LINE_CTRL.value() == 1:
            if time.ticks_diff(timeout, time.ticks_ms()) <= 0:
                print("Master: Timeout waiting for bit")
                return None
        
        bit = LINE_DATA.value()
        data_bits.append(bit)
        set_line_ctrl(0)
        time.sleep_ms(40)
        set_line_ctrl(None)
        
        timeout = time.ticks_add(time.ticks_ms(), 1000)
        while LINE_CTRL.value() == 0:
            if time.ticks_diff(timeout, time.ticks_ms()) <= 0:
                print("Master: Timeout waiting for line release")
                return None
            
    data_byte = 0
    for bit in data_bits:
        data_byte = (data_byte << 1) | bit
    return data_byte

def master_receive():
    global current_state
    print("Master: Ready")
    
    last_send = time.ticks_ms()
    while True:
        if current_state == IDLE:
            # Check for slave requests
            if LINE_CTRL.value() == 0:
                current_state = RECEIVING
                print("Master: Device requesting to send data")
                set_line_ctrl(0)
                time.sleep_ms(40)
                set_line_ctrl(None)
                
                # Get sender ID and data
                sender_id = receive_byte()
                if sender_id is not None:
                    print(f"Master: Communication from Device {sender_id}")
                    data = receive_byte()
                    if data is not None:
                        print(f"Master: Received data: {data}")
                
                current_state = IDLE
                
            # Send data periodically
            elif time.ticks_diff(time.ticks_ms(), last_send) >= 2000:
                master_send(100, slave_id=1)
                last_send = time.ticks_ms()
                
        time.sleep_ms(1)

# Wait for start signal
while True:
    if START_PIN.value() == 1:
        master_receive()