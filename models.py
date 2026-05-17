"""
250 Card Game — Data models and constants
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import uuid


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUITS = ["spades", "hearts", "diamonds", "clubs"]
RANKS = ["3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

# Cards removed from standard 52-card deck (the 2s of each suit)
REMOVED_RANKS = {"2"}

POINT_VALUES: dict[str, int] = {
    "J": 5,
    "Q": 10,
    "K": 15,
    "A": 20,
}
QUEEN_OF_SPADES_BONUS = 50   # base Q=10 + 50 bonus = 60 total
TOTAL_POINTS = 250

# Rank ordering for trick resolution (low → high)
RANK_ORDER = ["3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class GamePhase(str, Enum):
    WAITING       = "waiting"        # lobby, waiting for 6 players
    DEALING       = "dealing"        # cards being dealt (initial 5)
    BIDDING       = "bidding"        # players submit bids
    TRUMP_SELECT  = "trump_select"   # highest bidder picks trump suit
    CARD_ASK      = "card_ask"       # highest bidder names 2 cards to find teammates
    REDEAL        = "redeal"         # remaining cards distributed (5 → 8 each)
    PLAYING       = "playing"        # trick-taking phase
    ROUND_END     = "round_end"      # scoring + reveal
    GAME_OVER     = "game_over"


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Card:
    rank: str   # "3".."A"
    suit: str   # "spades" | "hearts" | "diamonds" | "clubs"

    @property
    def id(self) -> str:
        return f"{self.rank}_{self.suit}"

    @property
    def point_value(self) -> int:
        base = POINT_VALUES.get(self.rank, 0)
        if self.rank == "Q" and self.suit == "spades":
            base += QUEEN_OF_SPADES_BONUS
        return base

    @property
    def rank_index(self) -> int:
        return RANK_ORDER.index(self.rank)

    def __repr__(self) -> str:
        return f"{self.rank}{'♠♥♦♣'[SUITS.index(self.suit)]}"


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

@dataclass
class Player:
    player_id: str
    name: str
    hand: list[Card] = field(default_factory=list)
    bid: Optional[int] = None          # None = passed / not yet bid
    tricks_won: list[list[Card]] = field(default_factory=list)

    @property
    def points_in_tricks(self) -> int:
        return sum(c.point_value for trick in self.tricks_won for c in trick)

    def remove_card(self, card: Card) -> None:
        self.hand.remove(card)

    def to_public_dict(self) -> dict:
        """Safe view: no hand contents exposed."""
        return {
            "player_id": self.player_id,
            "name": self.name,
            "hand_size": len(self.hand),
            "bid": self.bid,
            "points_won": self.points_in_tricks,
            "tricks_won": len(self.tricks_won),
        }

    def to_private_dict(self) -> dict:
        """Full view for the player themselves."""
        return {
            **self.to_public_dict(),
            "hand": [c.id for c in self.hand],
        }


# ---------------------------------------------------------------------------
# Trick
# ---------------------------------------------------------------------------

@dataclass
class Trick:
    leader_id: str
    plays: list[tuple[str, Card]] = field(default_factory=list)   # [(player_id, card)]

    @property
    def led_suit(self) -> Optional[str]:
        return self.plays[0][1].suit if self.plays else None

    @property
    def is_complete(self) -> bool:
        return len(self.plays) == 6

    def add_play(self, player_id: str, card: Card) -> None:
        self.plays.append((player_id, card))

    def winning_play(self, trump_suit: str) -> tuple[str, Card]:
        """
        Returns (player_id, winning_card).
        Trump beats led suit; within the same suit highest rank wins.
        """
        led = self.led_suit
        best_pid, best_card = self.plays[0]
        for pid, card in self.plays[1:]:
            best_pid, best_card = _compare(best_pid, best_card, pid, card, led, trump_suit)
        return best_pid, best_card


def _compare(
    pid_a: str, card_a: Card,
    pid_b: str, card_b: Card,
    led_suit: str,
    trump_suit: str,
) -> tuple[str, Card]:
    """Return the winning (pid, card) pair."""
    a_trump = card_a.suit == trump_suit
    b_trump = card_b.suit == trump_suit
    a_led   = card_a.suit == led_suit
    b_led   = card_b.suit == led_suit

    if a_trump and not b_trump:
        return pid_a, card_a
    if b_trump and not a_trump:
        return pid_b, card_b
    if a_trump and b_trump:
        winner = (pid_a, card_a) if card_a.rank_index > card_b.rank_index else (pid_b, card_b)
        return winner
    # neither is trump
    if a_led and not b_led:
        return pid_a, card_a
    if b_led and not a_led:
        return pid_b, card_b
    if a_led and b_led:
        winner = (pid_a, card_a) if card_a.rank_index > card_b.rank_index else (pid_b, card_b)
        return winner
    # neither led nor trump → first play holds
    return pid_a, card_a


# ---------------------------------------------------------------------------
# GameResult
# ---------------------------------------------------------------------------

@dataclass
class RoundResult:
    bidder_id: str
    bid: int
    bidder_team: list[str]       # player_ids
    opponent_team: list[str]    # player_ids
    bidder_team_points: int
    opponent_team_points: int
    bidder_team_won: bool
    team_revealed: dict          # {player_id: team_label}
    trick_log: list[dict]        # for replay / audit
