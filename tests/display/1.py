"""import digitalio
import board
import time

class SevenSegmentDisplay:
    def __init__(self):
        # a 4 digit 7 segment display with 4 digits, multiplexed through 1 74HC595 shift register
        self.display = {
            "ser": digitalio.DigitalInOut(board.GP2),
            "rck": digitalio.DigitalInOut(board.GP4),
            "sck": digitalio.DigitalInOut(board.GP3),
        }

        for pin in self.display.values():
            pin.direction = digitalio.Direction.OUTPUT

        self.cathodes = [
            digitalio.DigitalInOut(board.GP5),
            digitalio.DigitalInOut(board.GP6),
            digitalio.DigitalInOut(board.GP7),
            digitalio.DigitalInOut(board.GP8),
        ]

        for cathode in self.cathodes:
            cathode.direction = digitalio.Direction.OUTPUT

        self.display_buffer = [0, 0, 0, 0]
        self.previous_display_buffer = [None, None, None, None]

    def display_number(self, number):
        if not (0 <= number <= 9999):
            raise ValueError("Number must be between 0000 and 9999")

        # Convert number to a 4-digit string and update display buffer
        number_str = f"{number:04d}"
        self.display_buffer = [int(digit) for digit in number_str]

    def _shift_out(self, value, decimal=False):
        # Shifts out an 8-bit value through SER and SCK pins
        if decimal:
            value |= 0b10000000  # Set the MSB for the decimal point
        for i in range(8):
            bit = (value >> (7 - i)) & 1
            self.display["ser"].value = bit
            self.display["sck"].value = False  # Set SCK low
            self.display["sck"].value = True  # Set SCK high to shift the bit

    def refresh_display(self):
        # Refresh each digit one at a time
        for digit_index, digit_value in enumerate(self.display_buffer):
            # Shift register: segment control
            segments = self.get_segment_encoding(digit_value)
            self._shift_out(segments, decimal=False)  # Ensure decimal is off

            # Latch the outputs to update the display
            self.display["rck"].value = False
            self.display["rck"].value = True

            # Activate the current digit (cathode control)
            for i, cathode in enumerate(self.cathodes):
                cathode.value = (i == digit_index)

            # Small delay to reduce flicker
            time.sleep(0.005)

        # Ensure all cathodes are off after refreshing
        for cathode in self.cathodes:
            cathode.value = False

    @staticmethod
    def get_segment_encoding(digit):
        # Segment encodings for the 7-segment display (0-9)
        segment_encoding = [
            0b00111111,  # 0: A, B, C, D, E, F
            0b00000110,  # 1: B, C
            0b01011011,  # 2: A, B, G, E, D
            0b01001111,  # 3: A, B, G, C, D
            0b01100110,  # 4: F, G, B, C
            0b01101101,  # 5: A, F, G, C, D
            0b01111101,  # 6: A, F, G, E, D, C
            0b00000111,  # 7: A, B, C
            0b01111111,  # 8: A, B, C, D, E, F, G
            0b01101111,  # 9: A, B, C, D, F, G
        ]
        return segment_encoding[digit]

    def display_off(self):
        for cathode in self.cathodes:
            cathode.value = False

    def display_on(self):
        for cathode in self.cathodes:
            cathode.value = True

    def clear(self):
        self.display_buffer = [0, 0, 0, 0]
        self.previous_display_buffer = [None, None, None, None]

        self.display["rck"].value = False
        self.display["rck"].value = True


def main():
    display = SevenSegmentDisplay()
    number = 0
    last_update = time.monotonic()

    while True:
        current_time = time.monotonic()
        if current_time - last_update >= 1:
            display.display_number(number)
            number = (number + 1) % 10000  # Ensure the number stays within 0000-9999
            last_update = current_time

        display.refresh_display()

if __name__ == "__main__":
    main()

    """


class SevenSegmentDisplay:
    def __init__(self):
        # a 4 digit 7 segment display with 4 digits, multiplexed through 2 74HC595 shift registers
        self.display = {
            "ser": digitalio.DigitalInOut(board.GP2),
            "rck": digitalio.DigitalInOut(board.GP4),
            "sck": digitalio.DigitalInOut(board.GP3),
            "oe1": digitalio.DigitalInOut(board.GP6),
            "oe2": digitalio.DigitalInOut(board.GP5),
            "sclr1": digitalio.DigitalInOut(board.GP1),
            "sclr2": digitalio.DigitalInOut(board.GP0),
        }

        for pin in self.display.values():
            pin.direction = digitalio.Direction.OUTPUT

        self.display["oe1"].value = False
        self.display["oe2"].value = False

        self.display["sclr1"].value = True
        self.display["sclr2"].value = True
        time.sleep(0.001)
        self.display["sclr1"].value = False
        self.display["sclr2"].value = False

        self.display_buffer = [0, 0, 0, 0]
        self.previous_display_buffer = [None, None, None, None]

    def display_number(self, number):
        if not (0 <= number <= 9999):
            raise ValueError("Number must be between 0000 and 9999")

        # Convert number to a 4-digit string and update display buffer
        number_str = f"{number:04d}"
        self.display_buffer = [int(digit) for digit in number_str]

    def _shift_out(self, value):
        # Shifts out an 8-bit value through SER and SCK pins
        for i in range(8):
            bit = (value >> (7 - i)) & 1
            self.display["ser"].value = bit
            self.display["sck"].value = False  # Set SCK low
            self.display["sck"].value = True  # Set SCK high to shift the bit

    async def refresh_display(self):
        while True:
            # Refresh each digit one at a time
            for digit_index, digit_value in enumerate(self.display_buffer):
                # First shift register: segment control
                segments = self.get_segment_encoding(digit_value)
                self._shift_out(segments)

                # Second shift register: digit control (active-low)
                digit_control = ~(1 << digit_index) & 0x0F
                self._shift_out(digit_control)

                # Latch the outputs to update the display
                self.display["rck"].value = False
                self.display["rck"].value = True

                # Small delay to reduce flicker
                await asyncio.sleep(0.005)  # 0.002

            # Overall refresh delay to avoid flickering
            await asyncio.sleep(0.005)  # 0.001

    @staticmethod
    def get_segment_encoding(digit):
        # Segment encodings for the 7-segment display (0-9)
        segment_encoding = [
            0b00111111,  # 0
            0b00000110,  # 1
            0b01011011,  # 2
            0b01001111,  # 3
            0b01100110,  # 4
            0b01101101,  # 5
            0b01111101,  # 6
            0b00000111,  # 7
            0b01111111,  # 8
            0b01101111,  # 9
        ]
        return segment_encoding[digit]

    def display_off(self):
        self.display["oe1"].value = True
        self.display["oe2"].value = True

    def display_on(self):
        self.display["oe1"].value = False
        self.display["oe2"].value = False

    def clear(self):
        self.display_buffer = [0, 0, 0, 0]
        self.previous_display_buffer = [None, None, None, None]

        self.display["sclr1"].value = True
        self.display["sclr2"].value = True
        time.sleep(0.001)
        self.display["sclr1"].value = False
        self.display["sclr2"].value = False