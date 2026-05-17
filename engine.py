"""
250 Card Game — Game Engine (state machine)

One Game instance represents a single room / session.
All mutation goes through public methods; each method returns an
ActionResult so callers (websocket server, tests) can react.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Optional

from models import (
    Card, Player, Trick, RoundResult,
    GamePhase, SUITS, TOTAL_POINTS,
)
from deck import build_deck, deal_initial, deal_remaining


# ---------------------------------------------------------------------------
# ActionResult — uniform return type
# ---------------------------------------------------------------------------

@dataclass
class ActionResult:
    ok: bool
    error: Optional[str] = None
    event: Optional[str] = None   # event name to broadcast
    data: dict = field(default_factory=dict)

    @staticmethod
    def fail(msg: str) -> "ActionResult":
        return ActionResult(ok=False, error=msg)

    @staticmethod
    def success(event: str, **data) -> "ActionResult":
        return ActionResult(ok=True, event=event, data=data)


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------

class Game:
    MAX_PLAYERS = 6

    def __init__(self, game_id: Optional[str] = None):
        self.game_id: str = game_id or str(uuid.uuid4())
        self.players: list[Player] = []          # ordered seating
        self.phase: GamePhase = GamePhase.WAITING

        # Round state
        self._deck: list[Card] = []
        self._remaining_deck: list[Card] = []

        self.highest_bidder_id: Optional[str] = None
        self.highest_bid: int = 0
        self.trump_suit: Optional[str] = None
        self.asked_cards: list[Card] = []        # 2 cards bidder asks for

        # Team membership (revealed only at round end)
        self._bidder_team: list[str] = []        # player_ids incl. bidder
        self._opponent_team: list[str] = []

        # Playing state
        self.current_trick: Optional[Trick] = None
        self.trick_history: list[Trick] = []
        self.turn_order: list[str] = []          # player_ids in play order
        self.current_turn_index: int = 0

        # Bidding state
        self._active_bidders: list[str] = []     # players still eligible to bid (haven't passed)
        self._bids_received: set[str] = set()    # everyone who has acted at least once

        # Cumulative scores across rounds
        self.scores: dict[str, int] = {}         # player_id → total points

        # Round results log
        self.round_results: list[RoundResult] = []

    # -----------------------------------------------------------------------
    # Properties / helpers
    # -----------------------------------------------------------------------

    @property
    def player_ids(self) -> list[str]:
        return [p.player_id for p in self.players]

    def _get_player(self, player_id: str) -> Optional[Player]:
        return next((p for p in self.players if p.player_id == player_id), None)

    def _assert_phase(self, *phases: GamePhase) -> Optional[ActionResult]:
        if self.phase not in phases:
            return ActionResult.fail(f"Action not allowed in phase '{self.phase}'")
        return None

    @property
    def _current_player_id(self) -> Optional[str]:
        if not self.turn_order:
            return None
        return self.turn_order[self.current_turn_index % len(self.turn_order)]

    # -----------------------------------------------------------------------
    # Lobby
    # -----------------------------------------------------------------------

    def add_player(self, name: str) -> ActionResult:
        if err := self._assert_phase(GamePhase.WAITING):
            return err
        if len(self.players) >= self.MAX_PLAYERS:
            return ActionResult.fail("Game is full (6 players max)")
        pid = str(uuid.uuid4())
        player = Player(player_id=pid, name=name)
        self.players.append(player)
        self.scores[pid] = 0
        result = ActionResult.success("player_joined", player_id=pid, name=name,
                                      total_players=len(self.players))
        if len(self.players) == self.MAX_PLAYERS:
            self._start_round()
            result.event = "round_started"
            result.data.update(self._public_state())
        return result

    # -----------------------------------------------------------------------
    # Round lifecycle
    # -----------------------------------------------------------------------

    def _start_round(self) -> None:
        """Reset per-round state and deal initial 5 cards."""
        self.phase = GamePhase.DEALING
        self.highest_bidder_id = None
        self.highest_bid = 0
        self.trump_suit = None
        self.asked_cards = []
        self._bidder_team = []
        self._opponent_team = []
        self.current_trick = None
        self.trick_history = []
        self._bids_received = set()
        self._active_bidders = list(self.player_ids)  # all start as active

        for p in self.players:
            p.hand.clear()
            p.bid = None
            p.tricks_won.clear()

        self._deck = build_deck()
        hands, self._remaining_deck = deal_initial(self._deck)
        for player, hand in zip(self.players, hands):
            player.hand = hand

        # Turn order starts from seat 0 and rotates each round
        self.turn_order = list(self.player_ids)
        self.current_turn_index = 0

        self.phase = GamePhase.BIDDING

    # -----------------------------------------------------------------------
    # Bidding
    # -----------------------------------------------------------------------

    def place_bid(self, player_id: str, amount: Optional[int]) -> ActionResult:
        """
        amount=None  → player passes (permanently removed from bidding).
        amount=int   → must be strictly greater than the current highest bid.
        Bidding ends when only 1 active bidder remains (they win automatically)
        OR all remaining active bidders pass in succession leaving one winner.
        """
        if err := self._assert_phase(GamePhase.BIDDING):
            return err
        player = self._get_player(player_id)
        if not player:
            return ActionResult.fail("Unknown player")
        if player_id not in self._active_bidders:
            return ActionResult.fail("You have already passed and cannot bid again")

        if amount is None:
            # Player passes — remove them permanently
            self._active_bidders.remove(player_id)
            self._bids_received.add(player_id)
            player.bid = 0  # 0 = passed
        else:
            if not isinstance(amount, int) or amount <= 0:
                return ActionResult.fail("Bid must be a positive integer")
            if amount > TOTAL_POINTS:
                return ActionResult.fail(f"Bid cannot exceed {TOTAL_POINTS}")
            if amount <= self.highest_bid:
                return ActionResult.fail(
                    f"Bid must be strictly greater than current highest ({self.highest_bid})"
                )
            self.highest_bid = amount
            self.highest_bidder_id = player_id
            player.bid = amount
            self._bids_received.add(player_id)

        # Bidding closes when only one active bidder remains AND a bid exists.
        # If nobody has bid yet and one player remains, they must still act.
        if len(self._active_bidders) == 1 and self.highest_bidder_id is not None:
            self.phase = GamePhase.TRUMP_SELECT
        elif len(self._active_bidders) == 0:
            # Everyone passed without any bid → re-deal
            self._start_round()
            return ActionResult.success("no_bids_redeal")

        return ActionResult.success(
            "bid_placed",
            player_id=player_id,
            amount=amount,
            highest_bid=self.highest_bid,
            highest_bidder_id=self.highest_bidder_id,
            active_bidders=list(self._active_bidders),
        )

    # -----------------------------------------------------------------------
    # Trump selection
    # -----------------------------------------------------------------------

    def select_trump(self, player_id: str, suit: str) -> ActionResult:
        if err := self._assert_phase(GamePhase.TRUMP_SELECT):
            return err
        if player_id != self.highest_bidder_id:
            return ActionResult.fail("Only the highest bidder selects trump")
        suit = suit.lower()
        if suit not in SUITS:
            return ActionResult.fail(f"Invalid suit. Choose from: {', '.join(SUITS)}")
        self.trump_suit = suit
        self.phase = GamePhase.CARD_ASK
        return ActionResult.success("trump_selected", suit=suit)

    # -----------------------------------------------------------------------
    # Card ask (bidder names 2 cards to find teammates)
    # -----------------------------------------------------------------------

    def ask_for_cards(self, player_id: str, card_ids: list[str]) -> ActionResult:
        """
        Bidder names exactly 2 cards (by id e.g. 'K_hearts').
        Players holding those cards become the bidder's team — silently.
        """
        if err := self._assert_phase(GamePhase.CARD_ASK):
            return err
        if player_id != self.highest_bidder_id:
            return ActionResult.fail("Only the highest bidder asks for cards")
        if len(card_ids) != 2:
            return ActionResult.fail("You must ask for exactly 2 cards")

        # Parse card ids
        asked: list[Card] = []
        for cid in card_ids:
            parts = cid.split("_", 1)
            if len(parts) != 2 or parts[0] not in ["3","4","5","6","7","8","9","10","J","Q","K","A"] \
                    or parts[1] not in SUITS:
                return ActionResult.fail(f"Invalid card id: {cid}")
            card = Card(rank=parts[0], suit=parts[1])
            asked.append(card)

        if asked[0] == asked[1]:
            return ActionResult.fail("The two cards must be different")

        # Ace of Spades cannot be asked for
        ace_of_spades = Card(rank="A", suit="spades")
        for c in asked:
            if c == ace_of_spades:
                return ActionResult.fail("The Ace of Spades cannot be asked for")

        # The bidder cannot ask for cards in their own hand
        bidder = self._get_player(player_id)
        for c in asked:
            if c in bidder.hand:
                return ActionResult.fail(f"You already hold {c} — ask for cards you don't have")

        self.asked_cards = asked

        # Silently assign teams
        self._bidder_team = [player_id]
        for p in self.players:
            if p.player_id == player_id:
                continue
            for c in asked:
                if c in p.hand:
                    self._bidder_team.append(p.player_id)
                    break
        self._opponent_team = [p.player_id for p in self.players
                               if p.player_id not in self._bidder_team]

        # Distribute remaining cards
        extras = deal_remaining(self._remaining_deck)
        for player, extra in zip(self.players, extras):
            player.hand.extend(extra)

        self.phase = GamePhase.PLAYING
        # Highest bidder always leads the first trick
        bidder_index = self.turn_order.index(self.highest_bidder_id)
        self.current_turn_index = bidder_index
        self.current_trick = Trick(leader_id=self._current_player_id)

        return ActionResult.success(
            "cards_asked_game_starts",
            # Only tell bidder which cards were asked; don't reveal who holds them
            asked_cards=card_ids,
            first_turn=self._current_player_id,
        )

    # -----------------------------------------------------------------------
    # Playing tricks
    # -----------------------------------------------------------------------

    def play_card(self, player_id: str, card_id: str) -> ActionResult:
        if err := self._assert_phase(GamePhase.PLAYING):
            return err
        if player_id != self._current_player_id:
            return ActionResult.fail("It's not your turn")

        player = self._get_player(player_id)
        parts = card_id.split("_", 1)
        if len(parts) != 2:
            return ActionResult.fail("Invalid card id format (expected 'rank_suit')")
        card = Card(rank=parts[0], suit=parts[1])
        if card not in player.hand:
            return ActionResult.fail("You don't have that card")

        # Follow-suit enforcement: must follow led suit if possible.
        # Only if a player has no card of the led suit may they play any other suit,
        # including trump.
        led_suit = self.current_trick.led_suit
        if led_suit and card.suit != led_suit:
            has_led_suit = any(c.suit == led_suit for c in player.hand)
            if has_led_suit:
                return ActionResult.fail(f"You must follow suit ({led_suit})")

        player.remove_card(card)
        self.current_trick.add_play(player_id, card)
        self.current_turn_index += 1

        if self.current_trick.is_complete:
            return self._resolve_trick()

        return ActionResult.success(
            "card_played",
            player_id=player_id,
            card=card_id,
            next_turn=self._current_player_id,
            trick_plays=[(pid, c.id) for pid, c in self.current_trick.plays],
        )

    def _resolve_trick(self) -> ActionResult:
        trick = self.current_trick
        winner_id, winning_card = trick.winning_play(self.trump_suit)
        winner = self._get_player(winner_id)
        winner.tricks_won.append([c for _, c in trick.plays])
        self.trick_history.append(trick)

        # Next trick led by winner
        winner_index = self.turn_order.index(winner_id)
        self.current_turn_index = winner_index

        trick_points = sum(c.point_value for _, c in trick.plays)

        if self._all_cards_played():
            return self._end_round(last_trick_winner_id=winner_id,
                                   last_trick_points=trick_points)

        self.current_trick = Trick(leader_id=winner_id)
        return ActionResult.success(
            "trick_won",
            winner_id=winner_id,
            winning_card=winning_card.id,
            trick_points=trick_points,
            next_turn=winner_id,
            tricks_played=len(self.trick_history),
        )

    def _all_cards_played(self) -> bool:
        return all(len(p.hand) == 0 for p in self.players)

    # -----------------------------------------------------------------------
    # Round end & scoring
    # -----------------------------------------------------------------------

    def _end_round(self, last_trick_winner_id: str, last_trick_points: int) -> ActionResult:
        self.phase = GamePhase.ROUND_END

        bidder_pts = sum(
            self._get_player(pid).points_in_tricks
            for pid in self._bidder_team
        )
        opp_pts = TOTAL_POINTS - bidder_pts
        bidder_won = bidder_pts >= self.highest_bid

        # Update cumulative scores
        # Win:  bidder +2, bidder teammates +1 each, opponents +0
        # Loss: bidder -1, bidder teammates +0,      opponents +1 each
        if bidder_won:
            self.scores[self.highest_bidder_id] = self.scores.get(self.highest_bidder_id, 0) + 2
            for pid in self._bidder_team:
                if pid != self.highest_bidder_id:
                    self.scores[pid] = self.scores.get(pid, 0) + 1
        else:
            self.scores[self.highest_bidder_id] = self.scores.get(self.highest_bidder_id, 0) - 1
            for pid in self._opponent_team:
                self.scores[pid] = self.scores.get(pid, 0) + 1

        # Build reveal map
        team_revealed = {}
        for pid in self._bidder_team:
            team_revealed[pid] = "bidder_team"
        for pid in self._opponent_team:
            team_revealed[pid] = "opponent_team"

        result = RoundResult(
            bidder_id=self.highest_bidder_id,
            bid=self.highest_bid,
            bidder_team=list(self._bidder_team),
            opponent_team=list(self._opponent_team),
            bidder_team_points=bidder_pts,
            opponent_team_points=opp_pts,
            bidder_team_won=bidder_won,
            team_revealed=team_revealed,
            trick_log=[
                {
                    "trick_num": i + 1,
                    "plays": [(pid, c.id) for pid, c in t.plays],
                    "winner": t.winning_play(self.trump_suit)[0],
                }
                for i, t in enumerate(self.trick_history)
            ],
        )
        self.round_results.append(result)

        return ActionResult.success(
            "round_ended",
            bidder_id=self.highest_bidder_id,
            bid=self.highest_bid,
            trump_suit=self.trump_suit,
            asked_cards=[c.id for c in self.asked_cards],
            bidder_team=self._bidder_team,
            opponent_team=self._opponent_team,
            bidder_team_points=bidder_pts,
            opponent_team_points=opp_pts,
            bidder_team_won=bidder_won,
            team_revealed=team_revealed,
            cumulative_scores=dict(self.scores),
        )

    # -----------------------------------------------------------------------
    # State views
    # -----------------------------------------------------------------------

    def _public_state(self) -> dict:
        return {
            "game_id": self.game_id,
            "phase": self.phase,
            "players": [p.to_public_dict() for p in self.players],
            "highest_bid": self.highest_bid,
            "highest_bidder_id": self.highest_bidder_id,
            "trump_suit": self.trump_suit,
            "current_turn": self._current_player_id,
            "tricks_played": len(self.trick_history),
            "scores": self.scores,
        }

    def state_for_player(self, player_id: str) -> dict:
        """Personalised view: includes the requesting player's hand."""
        state = self._public_state()
        player = self._get_player(player_id)
        if player:
            state["your_hand"] = [c.id for c in player.hand]
            state["your_bid"] = player.bid
        return state
