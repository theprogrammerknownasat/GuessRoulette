import board
import digitalio
import time
import asyncio

class SevenSegmentDisplay:
    def __init__(self):
        # Initialize pins
        self.display = {
            "ser": digitalio.DigitalInOut(board.GP2),
            "rck": digitalio.DigitalInOut(board.GP4),
            "sck": digitalio.DigitalInOut(board.GP3),
            "oe1": digitalio.DigitalInOut(board.GP5),
            "oe2": digitalio.DigitalInOut(board.GP6),
        }

        # Configure pins as outputs
        for pin in self.display.values():
            pin.direction = digitalio.Direction.OUTPUT

        # Enable outputs (active low)
        self.display["oe1"].value = False
        self.display["oe2"].value = False

        # Initialize display buffer
        self.display_buffer = [0, 0, 0, 0]

    # Segment patterns for digits 0-9
    @staticmethod
    def get_segment_encoding(digit):
        patterns = [
            0b00111111,  # 0
            0b00000110,  # 1
            0b01011011,  # 2
            0b01001111,  # 3
            0b01100110,  # 4
            0b01101101,  # 5
            0b01111101,  # 6
            0b00000111,  # 7
            0b01111111,  # 8
            0b01101111   # 9
        ]
        return patterns[digit]

    def _shift_out(self, value):
        # Shift out 8 bits, MSB first
        for i in range(8):
            bit = (value >> (7 - i)) & 1
            self.display["ser"].value = bit
            self.display["sck"].value = False
            self.display["sck"].value = True

    def display_number(self, number):
        if not (0 <= number <= 9999):
            raise ValueError("Number must be between 0000 and 9999")
        
        # Convert number to digits and update buffer
        self.display_buffer = [
            (number // 1000) % 10,
            (number // 100) % 10,
            (number // 10) % 10,
            number % 10
        ]

    async def refresh_display(self):
        while True:
            # Display each digit
            for position, value in enumerate(self.display_buffer):
                # Shift cathode select (will cascade to second register)
                self._shift_out(1 << position)
                # Shift segment pattern
                self._shift_out(self.get_segment_encoding(value))
                # Latch data
                self.display["rck"].value = False
                self.display["rck"].value = True
                
                # Small delay between digits
                await asyncio.sleep(0.002)

    def display_off(self):
        self.display["oe1"].value = True
        self.display["oe2"].value = True

    def display_on(self):
        self.display["oe1"].value = False
        self.display["oe2"].value = False

    def clear(self):
        # Clear by shifting out zeros
        self._shift_out(0x00)
        self._shift_out(0x00)
        self.display["rck"].value = False
        self.display["rck"].value = True
        self.display_buffer = [0, 0, 0, 0]

if __name__ == "__main__":
    display = SevenSegmentDisplay()
    display.clear()
    display.display_on()
    display.display_number(0)

    async def increment_counter():
        counter = 0
        last_increment = time.monotonic()
        while True:
            now = time.monotonic()
            if now - last_increment >= 0.05:
                display.display_number(counter)
                counter = (counter + 1) % 10000
                last_increment = now
            await asyncio.sleep(0.001)

    loop = asyncio.get_event_loop()
    try:
        # Create and run both tasks
        refresh_task = loop.create_task(display.refresh_display())
        counter_task = loop.create_task(increment_counter())
        
        # Run both tasks concurrently
        loop.run_until_complete(asyncio.gather(refresh_task, counter_task))
    except KeyboardInterrupt:
        display.clear()
        display.display_off()
        loop.close()