import numpy as np
import pygame
import time
import threading
import math


class TrackPlayer(threading.Thread):
    def __init__(self, track, sample_rate=44100):
        """
        A thread to play a single track of frequencies.
        :param track: List of (frequency, start_time) tuples.
        :param sample_rate: Sample rate for generating sound.
        """
        super().__init__()
        self.track = track
        self.sample_rate = sample_rate
        self.running = True

    def run(self):
        pygame.mixer.init(frequency=self.sample_rate)
        start_time = time.time()

        for frequency, start_time_target in self.track:
            if not self.running:
                break

            # Wait for the correct time
            while time.time() - start_time < start_time_target:
                time.sleep(0.001)

            if frequency > 0:
                self.play_frequency(frequency, 0.1)  # Default duration of 0.1 seconds

        pygame.mixer.quit()

    def play_frequency(self, frequency, duration):
        """
        Generate and play a sine wave at the given frequency.
        :param frequency: Frequency of the sound.
        :param duration: Duration of the sound in seconds.
        """
        if frequency <= 0:
            return  # Silence for 0 Hz

        n_samples = int(self.sample_rate * duration)
        t = np.arange(n_samples)
        buffer = (32767 * 0.5 * np.sin(2.0 * np.pi * frequency * t / self.sample_rate)).astype(np.int16)
        buffer = np.column_stack((buffer, buffer))  # Make it 2-dimensional for stereo
        sound = pygame.sndarray.make_sound(buffer)
        sound.play(-1)
        time.sleep(duration)
        sound.stop()

    def stop(self):
        self.running = False


class MultiTrackPlayer:
    def __init__(self, tracks):
        """
        Initialize a multi-track player.
        :param tracks: List of tracks, each track is a list of (frequency, start_time).
        """
        self.tracks = tracks
        self.track_players = [TrackPlayer(track) for track in tracks]

    def play(self):
        """
        Start playing all tracks.
        """
        for player in self.track_players:
            player.start()

        # Wait for all threads to finish
        for player in self.track_players:
            player.join()

    def stop(self):
        """
        Stop playing all tracks.
        """
        for player in self.track_players:
            player.stop()


# Example usage
tracks = [
    [
        (0.00, 0.000000),
        (0.00, 0.000000),
        (0.00, 0.000000),
        (0.00, 0.000000),
        (0.00, 0.000000),
        (0.00, 0.000000),
        (0.00, 0.000000),
        (0.00, 0.000000),
        (440.00, 0.000000),
        (0.00, 0.187500),
        (493.88, 0.187500),
        (554.37, 0.375000),
        (0.00, 0.377604),
        (0.00, 0.593750),
        (440.00, 0.593750),
        (0.00, 0.781250),
        (440.00, 0.781250),
        (0.00, 0.968750),
        (493.88, 0.968750),
        (0.00, 1.187500),
        (554.37, 1.187500),
        (0.00, 1.406250),
        (440.00, 1.406250),
        (0.00, 1.593750),
        (440.00, 1.593750),
        (0.00, 1.781250),
        (415.30, 1.781250),
        (0.00, 1.968750),
        (369.99, 1.968750),
        (0.00, 2.187500),
        (415.30, 2.187500),
        (0.00, 2.375000),
        (440.00, 2.375000),
        (0.00, 2.531250),
        (493.88, 2.531250),
        (0.00, 2.750000),
        (415.30, 2.750000),
        (0.00, 2.937500),
        (329.63, 2.937500),
        (0.00, 3.125000),
        (440.00, 3.125000),
        (493.88, 3.312500),
        (0.00, 3.313802),
        (0.00, 3.500000),
        (554.37, 3.500000),
        (0.00, 3.656250),
        (440.00, 3.687500),
        (0.00, 3.872396),
        (440.00, 3.875000),
        (0.00, 4.062500),
        (493.88, 4.062500),
        (0.00, 4.250000),
        (554.37, 4.250000),
        (0.00, 4.468750),
        (440.00, 4.468750),
        (0.00, 4.656250),
        (440.00, 4.656250),
        (0.00, 4.843750),
        (415.30, 4.843750),
        (0.00, 5.062500),
        (369.99, 5.062500),
        (0.00, 5.218750),
        (493.88, 5.218750),
        (0.00, 5.468750),
        (415.30, 5.468750),
        (0.00, 5.625000),
        (329.63, 5.625000),
        (0.00, 5.812500),
        (440.00, 5.843750),
        (0.00, 6.250000),
        (880.00, 6.281250),
        (0.00, 6.468750),
        (987.77, 6.468750),
        (0.00, 6.687500),
        (1108.73, 6.687500),
        (0.00, 6.906250),
        (880.00, 6.906250),
        (0.00, 7.092448),
        (880.00, 7.093750),
        (0.00, 7.281250),
        (987.77, 7.281250),
        (0.00, 7.468750),
        (1108.73, 7.468750),
        (880.00, 7.687500),
        (0.00, 7.688802),
        (0.00, 7.875000),
        (880.00, 7.875000),
        (0.00, 8.059896),
        (830.61, 8.062500),
        (0.00, 8.250000),
        (739.99, 8.250000),
        (0.00, 8.468750),
        (830.61, 8.468750),
        (0.00, 8.656250),
        (880.00, 8.656250),
        (0.00, 8.843750),
        (987.77, 8.843750),
        (0.00, 9.031250),
        (830.61, 9.031250),
        (0.00, 9.250000),
        (659.26, 9.250000),
        (880.00, 9.437500),
        (0.00, 9.441406),
        (987.77, 9.593750),
        (0.00, 9.600260),
        (0.00, 9.812500),
        (1108.73, 9.812500),
        (0.00, 10.031250),
        (880.00, 10.031250),
        (0.00, 10.218750),
        (880.00, 10.218750),
        (0.00, 10.406250),
        (987.77, 10.406250),
        (0.00, 10.593750),
        (1108.73, 10.593750),
        (0.00, 10.750000),
        (987.77, 10.750000),
        (0.00, 10.937500),
        (880.00, 10.937500),
        (0.00, 11.125000),
        (830.61, 11.125000),
        (0.00, 11.312500),
        (739.99, 11.312500),
        (0.00, 11.500000),
        (987.77, 11.500000),
        (0.00, 11.687500),
        (830.61, 11.687500),
        (0.00, 11.875000),
        (659.26, 11.875000),
        (0.00, 12.093750),
        (880.00, 12.093750),
        (0.00, 12.907552),
        (0.00, 12.907552),
        (0.00, 12.907552),
        (0.00, 12.907552),
        (0.00, 12.907552),
        (0.00, 12.907552),
        (0.00, 12.907552),
        (0.00, 12.907552),
        (0.00, 12.907552),
        (0.00, 13.007552),
    ],
    [
        (220.00, 0.375000),
        (0.00, 0.968750),
        (220.00, 1.187500),
        (0.00, 1.781250),
        (146.83, 1.968750),
        (0.00, 2.375000),
        (164.81, 2.750000),
        (0.00, 3.312500),
        (220.00, 3.500000),
        (0.00, 4.093750),
        (220.00, 4.250000),
        (0.00, 4.843750),
        (146.83, 5.062500),
        (0.00, 5.468750),
        (164.81, 5.468750),
        (0.00, 5.625000),
        (220.00, 5.843750),
        (0.00, 6.250000),
        (440.00, 6.687500),
        (0.00, 7.312500),
        (440.00, 7.500000),
        (0.00, 8.062500),
        (293.66, 8.250000),
        (0.00, 8.875000),
        (329.63, 9.031250),
        (0.00, 9.670573),
        (440.00, 9.843750),
        (0.00, 10.406250),
        (440.00, 10.593750),
        (0.00, 11.125000),
        (293.66, 11.281250),
        (329.63, 11.656250),
        (0.00, 11.682292),
        (0.00, 11.875000),
        (440.00, 12.093750),
        (0.00, 12.906250),
        (0.00, 13.006250),
    ]
]

multi_player = MultiTrackPlayer(tracks)
multi_player.play()
