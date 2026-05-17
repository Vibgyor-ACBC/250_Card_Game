"""
250 Card Game — Test suite
Run with:  python -m pytest tests.py -v
"""
import pytest
from models import Card, GamePhase, TOTAL_POINTS, SUITS
from engine import Game


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_full_game() -> tuple[Game, list[str]]:
    """Create a game with 6 players and return (game, player_ids)."""
    game = Game()
    player_ids = []
    for i in range(6):
        r = game.add_player(f"Player{i+1}")
        assert r.ok, r.error
        player_ids.append(r.data["player_id"])
    return game, player_ids


def bid_all_pass(game: Game, player_ids: list[str]) -> None:
    for pid in player_ids:
        game.place_bid(pid, None)


def complete_bidding(game: Game, player_ids: list[str], bidder_index: int, amount: int):
    """Bidder bids first, then all others pass — bidding closes when last active player passes."""
    # Bidder bids first so they hold the highest bid
    r = game.place_bid(player_ids[bidder_index], amount)
    assert r.ok, r.error
    # All others pass, one by one; the last pass closes bidding
    for i, pid in enumerate(player_ids):
        if i == bidder_index:
            continue
        r = game.place_bid(pid, None)
        assert r.ok, r.error


def find_card_not_in_hand(game: Game, player_id: str) -> Card:
    """Return a card that nobody in the game holds (for safe asking)."""
    all_held = {c for p in game.players for c in p.hand}
    from deck import build_deck
    for card in build_deck():
        if card not in all_held:
            return card
    raise RuntimeError("No card outside all hands — shouldn't happen")


def get_two_askable_cards(game: Game, bidder_id: str) -> list[str]:
    """Get 2 card ids that are NOT in the bidder's hand but ARE in someone else's."""
    bidder = game._get_player(bidder_id)
    candidates = []
    for p in game.players:
        if p.player_id == bidder_id:
            continue
        for c in p.hand:
            if c not in bidder.hand:
                candidates.append(c.id)
            if len(candidates) == 2:
                return candidates
    pytest.skip("Could not find 2 askable cards (degenerate deck)")


def advance_to_playing(game: Game, player_ids: list[str]) -> None:
    """Drive game from WAITING → PLAYING with player 0 as highest bidder."""
    complete_bidding(game, player_ids, bidder_index=0, amount=160)
    game.select_trump(player_ids[0], "spades")
    card_ids = get_two_askable_cards(game, player_ids[0])
    game.ask_for_cards(player_ids[0], card_ids)
    assert game.phase == GamePhase.PLAYING


# ---------------------------------------------------------------------------
# Deck tests
# ---------------------------------------------------------------------------

class TestDeck:
    def test_deck_has_48_cards(self):
        from deck import build_deck
        deck = build_deck()
        assert len(deck) == 48

    def test_no_twos(self):
        from deck import build_deck
        deck = build_deck()
        assert all(c.rank != "2" for c in deck)

    def test_total_points(self):
        from deck import build_deck
        total = sum(c.point_value for c in build_deck())
        assert total == TOTAL_POINTS

    def test_queen_of_spades_is_60(self):
        assert Card("Q", "spades").point_value == 60

    def test_deal_initial_gives_5_cards(self):
        from deck import build_deck, deal_initial
        deck = build_deck()
        hands, remaining = deal_initial(deck)
        assert all(len(h) == 5 for h in hands)
        assert len(remaining) == 18

    def test_deal_remaining_gives_3_extra(self):
        from deck import build_deck, deal_initial, deal_remaining
        deck = build_deck()
        _, remaining = deal_initial(deck)
        extras = deal_remaining(remaining)
        assert all(len(e) == 3 for e in extras)


# ---------------------------------------------------------------------------
# Lobby tests
# ---------------------------------------------------------------------------

class TestLobby:
    def test_add_6_players_starts_round(self):
        game = Game()
        for i in range(6):
            r = game.add_player(f"P{i}")
            assert r.ok
        assert game.phase == GamePhase.BIDDING

    def test_7th_player_rejected(self):
        game, _ = make_full_game()
        r = game.add_player("Extra")
        assert not r.ok

    def test_players_get_5_initial_cards(self):
        game, _ = make_full_game()
        assert all(len(p.hand) == 5 for p in game.players)


# ---------------------------------------------------------------------------
# Bidding tests
# ---------------------------------------------------------------------------

class TestBidding:
    def test_basic_bid(self):
        game, pids = make_full_game()
        r = game.place_bid(pids[0], 150)
        assert r.ok
        assert game.highest_bid == 150
        assert game.highest_bidder_id == pids[0]

    def test_higher_bid_wins(self):
        game, pids = make_full_game()
        game.place_bid(pids[0], 150)
        game.place_bid(pids[1], 200)
        assert game.highest_bidder_id == pids[1]

    def test_equal_bid_rejected(self):
        """A bid must strictly exceed the current highest — equal bids are rejected."""
        game, pids = make_full_game()
        game.place_bid(pids[0], 160)
        r = game.place_bid(pids[1], 160)
        assert not r.ok
        assert game.highest_bidder_id == pids[0]   # first bidder still leads

    def test_pass_is_valid(self):
        game, pids = make_full_game()
        r = game.place_bid(pids[0], None)
        assert r.ok
        assert game.highest_bidder_id is None

    def test_rebid_allowed_if_higher(self):
        """A player who has not passed can raise their own bid."""
        game, pids = make_full_game()
        game.place_bid(pids[0], 150)
        game.place_bid(pids[1], 160)
        r = game.place_bid(pids[0], 170)
        assert r.ok
        assert game.highest_bidder_id == pids[0]
        assert game.highest_bid == 170

    def test_passed_player_cannot_rebid(self):
        """Once a player passes they are locked out."""
        game, pids = make_full_game()
        game.place_bid(pids[0], 150)
        game.place_bid(pids[1], None)
        r = game.place_bid(pids[1], 160)
        assert not r.ok

    def test_all_pass_redeals(self):
        game, pids = make_full_game()
        bid_all_pass(game, pids)
        # After redeal game goes back to BIDDING with fresh hands
        assert game.phase == GamePhase.BIDDING
        assert all(len(p.hand) == 5 for p in game.players)

    def test_all_bids_trigger_trump_phase(self):
        game, pids = make_full_game()
        complete_bidding(game, pids, bidder_index=2, amount=170)
        assert game.phase == GamePhase.TRUMP_SELECT
        assert game.highest_bidder_id == pids[2]

    def test_back_and_forth_bidding(self):
        """Players can raise each other multiple times before anyone passes."""
        game, pids = make_full_game()
        game.place_bid(pids[0], 160)
        game.place_bid(pids[1], 175)
        r = game.place_bid(pids[0], 185)
        assert r.ok
        assert game.highest_bid == 185
        assert game.highest_bidder_id == pids[0]
        r = game.place_bid(pids[1], 200)
        assert r.ok
        assert game.highest_bidder_id == pids[1]
        # remaining players pass; pids[0] also passes -> pids[1] wins
        for pid in pids[2:]:
            game.place_bid(pid, None)
        game.place_bid(pids[0], None)
        assert game.phase == GamePhase.TRUMP_SELECT
        assert game.highest_bidder_id == pids[1]

    def test_bid_exceeding_250_rejected(self):
        game, pids = make_full_game()
        r = game.place_bid(pids[0], 300)
        assert not r.ok

    def test_negative_bid_rejected(self):
        game, pids = make_full_game()
        r = game.place_bid(pids[0], -10)
        assert not r.ok


# ---------------------------------------------------------------------------
# Trump selection tests
# ---------------------------------------------------------------------------

class TestTrumpSelection:
    def test_only_highest_bidder_can_select(self):
        game, pids = make_full_game()
        complete_bidding(game, pids, bidder_index=0, amount=160)
        r = game.select_trump(pids[1], "hearts")
        assert not r.ok

    def test_valid_suit_accepted(self):
        game, pids = make_full_game()
        complete_bidding(game, pids, bidder_index=0, amount=160)
        r = game.select_trump(pids[0], "hearts")
        assert r.ok
        assert game.trump_suit == "hearts"
        assert game.phase == GamePhase.CARD_ASK

    def test_invalid_suit_rejected(self):
        game, pids = make_full_game()
        complete_bidding(game, pids, bidder_index=0, amount=160)
        r = game.select_trump(pids[0], "joker")
        assert not r.ok


# ---------------------------------------------------------------------------
# Card ask tests
# ---------------------------------------------------------------------------

class TestCardAsk:
    def test_asking_cards_in_own_hand_rejected(self):
        game, pids = make_full_game()
        complete_bidding(game, pids, bidder_index=0, amount=160)
        game.select_trump(pids[0], "spades")
        bidder = game._get_player(pids[0])
        owned = [c.id for c in bidder.hand[:2]]
        r = game.ask_for_cards(pids[0], owned)
        assert not r.ok

    def test_asking_one_card_rejected(self):
        game, pids = make_full_game()
        complete_bidding(game, pids, bidder_index=0, amount=160)
        game.select_trump(pids[0], "spades")
        card_ids = get_two_askable_cards(game, pids[0])
        r = game.ask_for_cards(pids[0], card_ids[:1])
        assert not r.ok

    def test_valid_ask_starts_play(self):
        game, pids = make_full_game()
        complete_bidding(game, pids, bidder_index=0, amount=160)
        game.select_trump(pids[0], "spades")
        card_ids = get_two_askable_cards(game, pids[0])
        r = game.ask_for_cards(pids[0], card_ids)
        assert r.ok
        assert game.phase == GamePhase.PLAYING
        assert all(len(p.hand) == 8 for p in game.players)

    def test_teams_assigned(self):
        game, pids = make_full_game()
        complete_bidding(game, pids, bidder_index=0, amount=160)
        game.select_trump(pids[0], "spades")
        card_ids = get_two_askable_cards(game, pids[0])
        game.ask_for_cards(pids[0], card_ids)
        assert pids[0] in game._bidder_team
        assert len(game._bidder_team) + len(game._opponent_team) == 6

    def test_ace_of_spades_cannot_be_asked(self):
        """Bidder must never be allowed to ask for the Ace of Spades."""
        import random
        random.seed(42)
        # Keep re-dealing until A_spades is not in the bidder hand
        for _ in range(30):
            game, pids = make_full_game()
            complete_bidding(game, pids, bidder_index=0, amount=160)
            game.select_trump(pids[0], "hearts")
            bidder = game._get_player(pids[0])
            from models import Card
            ace_spades = Card("A", "spades")
            if ace_spades not in bidder.hand:
                # Get one other askable card to pair with A_spades
                other = next(
                    c.id for p in game.players if p.player_id != pids[0]
                    for c in p.hand if c != ace_spades
                )
                r = game.ask_for_cards(pids[0], ["A_spades", other])
                assert not r.ok, "Ace of Spades should be forbidden"
                assert "Ace of Spades" in r.error
                return
        pytest.skip("Ace of Spades always in bidder hand across 30 seeds")

    def test_ace_of_spades_as_second_card_rejected(self):
        """A_spades forbidden regardless of position in the request list."""
        import random
        random.seed(7)
        for _ in range(30):
            game, pids = make_full_game()
            complete_bidding(game, pids, bidder_index=0, amount=160)
            game.select_trump(pids[0], "clubs")
            bidder = game._get_player(pids[0])
            from models import Card
            ace_spades = Card("A", "spades")
            if ace_spades not in bidder.hand:
                other = next(
                    c.id for p in game.players if p.player_id != pids[0]
                    for c in p.hand if c != ace_spades
                )
                r = game.ask_for_cards(pids[0], [other, "A_spades"])
                assert not r.ok
                return
        pytest.skip("Ace of Spades always in bidder hand across 30 seeds")


# ---------------------------------------------------------------------------
# Trick-taking tests
# ---------------------------------------------------------------------------

class TestTrickTaking:
    def test_wrong_turn_rejected(self):
        game, pids = make_full_game()
        advance_to_playing(game, pids)
        # pids[1] tries to play out of turn
        p1 = game._get_player(pids[1])
        card_id = p1.hand[0].id
        r = game.play_card(pids[1], card_id)
        assert not r.ok

    def test_card_not_in_hand_rejected(self):
        game, pids = make_full_game()
        advance_to_playing(game, pids)
        current_pid = game._current_player_id
        r = game.play_card(current_pid, "2_spades")   # 2s are removed
        assert not r.ok

    def test_follow_suit_enforced(self):
        game, pids = make_full_game()
        advance_to_playing(game, pids)
        # Play first card (sets led suit)
        leader_id = game._current_player_id
        leader = game._get_player(leader_id)
        led_card = leader.hand[0]
        game.play_card(leader_id, led_card.id)

        led_suit = led_card.suit
        # Find next player who has the led suit AND another suit
        for _ in range(5):
            next_id = game._current_player_id
            next_player = game._get_player(next_id)
            has_led = [c for c in next_player.hand if c.suit == led_suit]
            has_other = [c for c in next_player.hand if c.suit != led_suit]
            if has_led and has_other:
                r = game.play_card(next_id, has_other[0].id)
                assert not r.ok, "Should have been forced to follow suit"
                return
            # If they can't follow (no led suit), play any card legally
            fallback = next_player.hand[0]
            game.play_card(next_id, fallback.id)

    def test_complete_trick_assigns_winner(self):
        game, pids = make_full_game()
        advance_to_playing(game, pids)
        # Play all 6 cards in a trick
        for _ in range(6):
            pid = game._current_player_id
            player = game._get_player(pid)
            # Play first legal card
            led_suit = game.current_trick.led_suit
            if led_suit:
                legal = [c for c in player.hand if c.suit == led_suit] or player.hand
            else:
                legal = player.hand
            game.play_card(pid, legal[0].id)
        # Trick should be resolved; a new trick or round_end
        assert game.phase in (GamePhase.PLAYING, GamePhase.ROUND_END)
        if game.phase == GamePhase.PLAYING:
            assert len(game.trick_history) == 1

    def test_bidder_leads_first_trick(self):
        """The highest bidder must be the first player to lead."""
        game, pids = make_full_game()
        advance_to_playing(game, pids)
        assert game._current_player_id == game.highest_bidder_id

    def test_trump_wins_when_no_led_suit(self):
        """A trump card beats all non-trump when the player cannot follow suit."""
        game, pids = make_full_game()
        advance_to_playing(game, pids)
        leader_id = game._current_player_id
        leader = game._get_player(leader_id)
        led_card = leader.hand[0]
        game.play_card(leader_id, led_card.id)
        led_suit = led_card.suit
        for _ in range(5):
            next_id = game._current_player_id
            next_p = game._get_player(next_id)
            has_led = [c for c in next_p.hand if c.suit == led_suit]
            trump_cards = [c for c in next_p.hand if c.suit == game.trump_suit]
            if not has_led and trump_cards:
                r = game.play_card(next_id, trump_cards[0].id)
                assert r.ok, f"Trump should be legal when player cannot follow suit: {r.error}"
                return
            legal = has_led or next_p.hand
            game.play_card(next_id, legal[0].id)
        import pytest; pytest.skip("No player found without led suit but with a trump card")

    def test_trump_blocked_when_player_has_led_suit(self):
        """If a player has the led suit, they must follow it — cannot play trump instead."""
        game, pids = make_full_game()
        advance_to_playing(game, pids)
        leader_id = game._current_player_id
        leader = game._get_player(leader_id)
        led_card = leader.hand[0]
        game.play_card(leader_id, led_card.id)
        led_suit = led_card.suit
        for _ in range(5):
            next_id = game._current_player_id
            next_p = game._get_player(next_id)
            has_led = [c for c in next_p.hand if c.suit == led_suit]
            trump_cards = [c for c in next_p.hand if c.suit == game.trump_suit]
            if has_led and trump_cards:
                r = game.play_card(next_id, trump_cards[0].id)
                assert not r.ok, "Should be forced to follow suit even if holding trump"
                return
            legal = has_led or next_p.hand
            game.play_card(next_id, legal[0].id)
        import pytest; pytest.skip("No player had both led suit and trump in hand")


# ---------------------------------------------------------------------------
# Scoring / round end tests
# ---------------------------------------------------------------------------

class TestScoring:
    def _play_full_game(self) -> Game:
        game, pids = make_full_game()
        advance_to_playing(game, pids)
        # Play all 8 tricks (8 cards each × 6 players = 48 plays)
        for _ in range(48):
            if game.phase != GamePhase.PLAYING:
                break
            pid = game._current_player_id
            player = game._get_player(pid)
            led_suit = game.current_trick.led_suit
            if led_suit:
                legal = [c for c in player.hand if c.suit == led_suit] or player.hand
            else:
                legal = player.hand
            game.play_card(pid, legal[0].id)
        return game

    def test_round_ends_after_all_tricks(self):
        game = self._play_full_game()
        assert game.phase == GamePhase.ROUND_END

    def test_total_points_equal_250(self):
        game = self._play_full_game()
        result = game.round_results[-1]
        assert result.bidder_team_points + result.opponent_team_points == TOTAL_POINTS

    def test_team_sizes_sum_to_6(self):
        game = self._play_full_game()
        result = game.round_results[-1]
        assert len(result.bidder_team) + len(result.opponent_team) == 6

    def test_bidder_team_won_logic(self):
        game = self._play_full_game()
        result = game.round_results[-1]
        if result.bidder_team_won:
            assert result.bidder_team_points >= result.bid
        else:
            assert result.bidder_team_points < result.bid

    def test_scores_on_bidder_win(self):
        """Bidder +2, teammates +1, opponents unchanged."""
        game, pids = make_full_game()
        advance_to_playing(game, pids)
        bidder_id = game.highest_bidder_id
        before = dict(game.scores)
        # Play all tricks
        for _ in range(48):
            if game.phase != GamePhase.PLAYING:
                break
            pid = game._current_player_id
            player = game._get_player(pid)
            led_suit = game.current_trick.led_suit
            legal = ([c for c in player.hand if c.suit == led_suit] or player.hand) if led_suit else player.hand
            game.play_card(pid, legal[0].id)
        result = game.round_results[-1]
        if result.bidder_team_won:
            assert game.scores[bidder_id] == before[bidder_id] + 2
            for pid in result.bidder_team:
                if pid != bidder_id:
                    assert game.scores[pid] == before[pid] + 1
            for pid in result.opponent_team:
                assert game.scores[pid] == before[pid]

    def test_scores_on_bidder_loss(self):
        """Bidder -1, teammates unchanged, opponents +1."""
        # Run many games until we see a loss (bid set high to make loss likely)
        import random
        random.seed(99)
        for _ in range(50):
            game, pids = make_full_game()
            # Force an impossibly high bid so bidder almost always loses
            complete_bidding(game, pids, bidder_index=0, amount=250)
            game.select_trump(pids[0], "spades")
            card_ids = get_two_askable_cards(game, pids[0])
            game.ask_for_cards(pids[0], card_ids)
            before = dict(game.scores)
            bidder_id = game.highest_bidder_id
            for _ in range(48):
                if game.phase != GamePhase.PLAYING:
                    break
                pid = game._current_player_id
                player = game._get_player(pid)
                led_suit = game.current_trick.led_suit
                legal = ([c for c in player.hand if c.suit == led_suit] or player.hand) if led_suit else player.hand
                game.play_card(pid, legal[0].id)
            result = game.round_results[-1]
            if not result.bidder_team_won:
                assert game.scores[bidder_id] == before[bidder_id] - 1
                for pid in result.bidder_team:
                    if pid != bidder_id:
                        assert game.scores[pid] == before[pid]
                for pid in result.opponent_team:
                    assert game.scores[pid] == before[pid] + 1
                return
        pytest.skip("Bidder always won across 50 random seeds with bid=250")


# ---------------------------------------------------------------------------
# Card model tests
# ---------------------------------------------------------------------------

class TestCardModel:
    def test_ace_value(self):  assert Card("A", "hearts").point_value == 20
    def test_king_value(self): assert Card("K", "clubs").point_value == 15
    def test_queen_value(self):assert Card("Q", "hearts").point_value == 10
    def test_jack_value(self): assert Card("J", "diamonds").point_value == 5
    def test_number_value(self):assert Card("7", "spades").point_value == 0
    def test_queen_spades(self):assert Card("Q", "spades").point_value == 60
    def test_card_id(self):     assert Card("K", "hearts").id == "K_hearts"
    def test_rank_ordering(self):
        assert Card("A", "hearts").rank_index > Card("K", "hearts").rank_index
        assert Card("3", "hearts").rank_index == 0


if __name__ == "__main__":
    import sys, pytest
    sys.exit(pytest.main([__file__, "-v"]))
