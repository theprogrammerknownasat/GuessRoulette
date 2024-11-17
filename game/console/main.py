from enum import Enum

CLOCK_SPEED = 1  # 1hz


class PlayerState(Enum):
    DEFAULT = 0
    PICKER = 1
    GUESSER = 2
    BETTER = 3
    DEAD = 4
    DISCONNECTED = 5


class Player:
    def __init__(self, identifier: int):
        self.id = identifier
        self.state = PlayerState.DEFAULT
        self.score = 0
        self.bet = 0
        self.guess = 0
        self.health = 99





class Game:
    def __init__(self):
        self.players = []
        self.current_player = 0
        self.clock = 0

    def run(self):
        pass
