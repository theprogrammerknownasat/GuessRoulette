import time
from machine import Pin

# host

CLOCK_SPEED = 10  # 10hz

data_pins = [Pin(i, Pin.OUT) for i in range(2, 10)]
led = Pin(15, Pin.OUT)
stop_input = Pin(0, Pin.IN)
stop_output = Pin(1, Pin.OUT)


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
    binary_string = input("Enter a binary string (e.g., 00000010): ")

    # Convert string to a byte
    byte_value = int(binary_string, 2)
    send(byte_value)
    time.sleep(1)  # 1 second interval between sending bytes
    received_byte = recv()
    if received_byte == byte_value:
        led.value(1)  # Turn LED on if data is correct

    else:
        led.value(0)  # Turn LED off if data is incorrect
    time.sleep(3)  # Wait 3 seconds before next transmission