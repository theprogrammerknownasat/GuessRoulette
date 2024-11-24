import time
from machine import Pin

# host

"""CLOCK_SPEED = 10  # 10hz

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
    """

from machine import Pin
import time

# Define FPGA connections
Q1 = [Pin(i, Pin.IN) for i in range(0, 8)]  # Q1[0]-Q1[7] are GPIO 0-7                      # GPIO 8
RCLK1 = Pin(9, Pin.OUT)  # GPIO 9
SRCLK1 = Pin(10, Pin.OUT)  # GPIO 10
SER1 = Pin(11, Pin.OUT)  # GPIO 11
QH1 = Pin(12, Pin.IN)  # GPIO 12


# Helper function to shift data into the shift register
def shift_data(serial_pin, clock_pin, data):
    print(data)
    for bit in data:
        print(bit)
        serial_pin.value(bit)  # Set the data bit
        SER1.high()  # Pulse the clock
        time.sleep(0.5)  # 10ms delay
        SER1.low()


# Helper function to latch data
def latch_data(latch_pin):
    latch_pin.high()  # Pulse the latch
    time.sleep(0.1)  # 10ms delay
    latch_pin.low()


# Helper function to read parallel outputs
def read_parallel_outputs(parallel_pins):
    return [pin.value() for pin in parallel_pins]


# Test sequence for multiple patterns
def test_shift_register(num_iterations):
    # Patterns to test
    test_patterns = [
        [0, 0, 0, 0, 0, 0, 0, 0],  # All 0s
        [1, 1, 1, 1, 1, 1, 1, 1],  # All 1s
        [0, 1, 0, 1, 0, 1, 0, 1],  # Alternating 01
        [1, 0, 1, 0, 1, 0, 1, 0],  # Alternating 10
        [1, 0, 0, 0, 0, 0, 0, 1],  # First and last bit high
    ]

    # Collect results
    results = []

    # Enable output

    for i in range(num_iterations):
        for pattern in test_patterns:
            shift_data(SER1, SRCLK1, pattern)  # Send the test pattern
            time.sleep(5)
            latch_data(RCLK1)  # Latch the data
            q1_outputs = read_parallel_outputs(Q1)  # Read parallel outputs
            qh1_output = QH1.value()  # Read serial output

            # Store the result
            results.append({
                "pattern": pattern,
                "q1_outputs": q1_outputs,
                "qh1_output": qh1_output,
            })

    # Disable output

    # Print results
    for idx, result in enumerate(results):
        print(f"Test {idx + 1}: Pattern Sent: {result['pattern']}")
        print(f"    Q1 Outputs: {result['q1_outputs']}")
        print(f"    QH Output: {result['qh1_output']}")

    RCLK1.low()
    SRCLK1.low()
    SER1.low()

    return results


# Run the test
test_results = test_shift_register(num_iterations=1)
