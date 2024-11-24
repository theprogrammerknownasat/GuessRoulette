# slave.py
import machine
import time
import urandom

# Define pins
LINE_DATA = machine.Pin(14, machine.Pin.IN, machine.Pin.PULL_UP)
LINE_CTRL = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)
START_PIN = machine.Pin(16, machine.Pin.IN, machine.Pin.PULL_UP)

# Define slave ID
SLAVE_ID = 1

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

def slave_send(data_byte):
    global current_state
    print(f"Slave {SLAVE_ID}: Waiting for permission to send")
    
    # Wait for master to signal slave can send (LINE_CTRL high for >100ms)
    wait_start = time.ticks_ms()
    while True:
        if LINE_CTRL.value() == 1:
            if time.ticks_diff(time.ticks_ms(), wait_start) > 100:
                break
        else:
            wait_start = time.ticks_ms()
        time.sleep_ms(1)
    
    current_state = SENDING
    print(f"Slave {SLAVE_ID}: Sending data: {data_byte}")
    
    # Signal start of transmission
    set_line_ctrl(0)
    time.sleep_ms(40)
    set_line_ctrl(None)
    
    # Send address and data
    send_byte(SLAVE_ID)
    send_byte(data_byte)
    
    print("Slave: Data transmission complete")
    current_state = IDLE

def send_byte(byte):
    for i in range(7, -1, -1):
        bit = (byte >> i) & 0x01
        set_line_data(bit)
        set_line_ctrl(0)
        time.sleep_ms(40)
        set_line_ctrl(None)
        # Wait for ack
        while LINE_CTRL.value() == 1:
            pass
        set_line_data(None)
        while LINE_CTRL.value() == 0:
            pass

def slave_receive():
    global current_state
    print(f"Slave {SLAVE_ID}: Ready")
    
    has_data = False
    while True:
        print(current_state)
        if current_state == IDLE:
            if LINE_CTRL.value() == 0:
                current_state = RECEIVING
                set_line_ctrl(0)
                time.sleep_ms(40)
                set_line_ctrl(None)
                
                address = receive_byte()
                if address == SLAVE_ID:
                    print(f"Slave {SLAVE_ID}: Received msg for me")
                    set_line_ctrl(0)
                    time.sleep_ms(40) 
                    set_line_ctrl(None)
                    
                    data = receive_byte()
                    print(f"Slave {SLAVE_ID}: Got data: {data}")
                    
                current_state = IDLE
                
            elif has_data and LINE_CTRL.value() == 1:
                slave_send(42)
                has_data = False
                
        time.sleep_ms(1)
        
        # Toggle has_data every 2 seconds
        if time.ticks_ms() % 2000 == 0:
            has_data = True

def receive_byte():
    data_bits = []
    for _ in range(8):
        while LINE_CTRL.value() == 1:
            pass
        bit = LINE_DATA.value()
        data_bits.append(bit)
        set_line_ctrl(0)
        time.sleep_ms(40)
        set_line_ctrl(None)
        while LINE_CTRL.value() == 0:
            pass
            
    data_byte = 0
    for bit in data_bits:
        data_byte = (data_byte << 1) | bit
    return data_byte

# Wait for start signal then begin
while True:
    if START_PIN.value() == 1:
        slave_receive()