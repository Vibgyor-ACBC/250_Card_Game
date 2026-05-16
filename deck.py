"""
250 Card Game — Deck
"""
from __future__ import annotations
import random
from models import Card, SUITS, RANKS, REMOVED_RANKS


def build_deck() -> list[Card]:
    """Return a shuffled 48-card deck (standard 52 minus the four 2s)."""
    deck = [
        Card(rank, suit)
        for suit in SUITS
        for rank in RANKS
        if rank not in REMOVED_RANKS
    ]
    assert len(deck) == 48, f"Expected 48 cards, got {len(deck)}"
    random.shuffle(deck)
    return deck


def deal_initial(deck: list[Card], num_players: int = 6) -> tuple[list[list[Card]], list[Card]]:
    """
    Deal 5 cards to each player.
    Returns (hands, remaining_deck).
    """
    hands: list[list[Card]] = [[] for _ in range(num_players)]
    for i in range(5 * num_players):
        hands[i % num_players].append(deck[i])
    remaining = deck[5 * num_players:]
    assert len(remaining) == 48 - 5 * num_players
    return hands, remaining


def deal_remaining(deck: list[Card], num_players: int = 6) -> list[list[Card]]:
    """
    Distribute the remaining 18 cards evenly (3 per player) so each
    player ends up with 8 cards total.
    """
    assert len(deck) == 18, f"Expected 18 remaining cards, got {len(deck)}"
    extras: list[list[Card]] = [[] for _ in range(num_players)]
    for i, card in enumerate(deck):
        extras[i % num_players].append(card)
    return extras
