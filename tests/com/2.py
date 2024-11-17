from machine import Pin
import time

# io

CLOCK_SPEED = 10  # 10hz

data_pins = [Pin(i, Pin.IN) for i in range(2, 10)]
led = Pin(15, Pin.OUT)
stop_input = Pin(0, Pin.IN)
stop_output = Pin(1, Pin.OUT)

received_byte = 0


def send(byte):
    for i in range(8):
        data_pins[i].value((byte >> i) & 1)
    time.sleep(1 / CLOCK_SPEED)


def recv():
    byte = 0
    for i in range(8):
        byte |= data_pins[i].value() << i
    time.sleep(1 / CLOCK_SPEED)
    return byte


while True:
    for pin in data_pins:
        if pin.value():
            received_byte = recv()
            time.sleep(3 / CLOCK_SPEED)  # Wait 3 clock cycles
            send(received_byte)
            print(received_byte)
            print("running")
            break