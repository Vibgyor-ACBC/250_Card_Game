"""
250 Card Game — Local simulation (no server needed)
Drives a full game directly through the engine so you can see every phase.

Run with:  python simulate.py
"""
from engine import Game
from models import Card, GamePhase, SUITS


# ── helpers ────────────────────────────────────────────────────────────────

def hand_str(player) -> str:
    return "  ".join(
        f"{c}{'*' if c.point_value else ''}"
        for c in sorted(player.hand, key=lambda c: (c.suit, c.rank_index))
    )
    # * marks point cards

def section(title: str) -> None:
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print('═'*60)

def show_hands(game: Game) -> None:
    for p in game.players:
        print(f"  {p.name:10s}  [{hand_str(p)}]")

def get_two_askable(game, bidder_id):
    """Return 2 card ids not in bidder's hand and not A_spades."""
    bidder = game._get_player(bidder_id)
    forbidden = {Card("A", "spades")}
    candidates = [
        c for p in game.players if p.player_id != bidder_id
        for c in p.hand
        if c not in bidder.hand and c not in forbidden
    ]
    return [candidates[0].id, candidates[1].id]

def play_legal(game):
    """Play the first legal card for the current player."""
    pid = game._current_player_id
    player = game._get_player(pid)
    led_suit = game.current_trick.led_suit if game.current_trick else None
    if led_suit:
        legal = [c for c in player.hand if c.suit == led_suit] or player.hand
    else:
        legal = player.hand
    card = legal[0]
    result = game.play_card(pid, card.id)
    return player, card, result


# ── main simulation ─────────────────────────────────────────────────────────

def run():
    game = Game()

    # ── 1. Add players ──────────────────────────────────────────────────────
    section("LOBBY — 6 players joining")
    names = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank"]
    pids = []
    for name in names:
        r = game.add_player(name)
        pids.append(r.data["player_id"])
        print(f"  {name} joined  (total: {r.data['total_players']}/6)")

    # ── 2. Show initial hands ────────────────────────────────────────────────
    section("INITIAL HANDS (5 cards each)")
    show_hands(game)

    # ── 3. Bidding ───────────────────────────────────────────────────────────
    section("BIDDING")
    bids = [160, None, 180, None, None, 170]   # Carol=180 wins
    for pid, amount, name in zip(pids, bids, names):
        r = game.place_bid(pid, amount)
        label = f"{amount}" if amount else "pass"
        status = f"  → highest now {r.data['highest_bid']} ({game._get_player(r.data['highest_bidder_id']).name})" \
                 if r.data.get('highest_bidder_id') else ""
        print(f"  {name:8s}  bids {label:>4s}{status}")

    bidder = game._get_player(game.highest_bidder_id)
    print(f"\n  Winner: {bidder.name} with bid {game.highest_bid}")

    # ── 4. Trump selection ───────────────────────────────────────────────────
    section("TRUMP SELECTION")
    trump = "hearts"
    game.select_trump(game.highest_bidder_id, trump)
    print(f"  {bidder.name} picks trump: {trump.upper()}")

    # ── 5. Card ask ──────────────────────────────────────────────────────────
    section("CARD ASK")
    card_ids = get_two_askable(game, game.highest_bidder_id)
    r = game.ask_for_cards(game.highest_bidder_id, card_ids)
    print(f"  {bidder.name} asks for: {card_ids[0]}  and  {card_ids[1]}")
    print(f"  (Teams are secret until the end)")

    # ── 6. Show full hands ───────────────────────────────────────────────────
    section("FULL HANDS (8 cards each)  [* = point card]")
    show_hands(game)

    # ── 7. Play all tricks ───────────────────────────────────────────────────
    section("TRICK-TAKING")
    trick_num = 0
    while game.phase == GamePhase.PLAYING:
        trick_num += 1
        print(f"\n  — Trick {trick_num} —")
        for _ in range(6):
            if game.phase != GamePhase.PLAYING:
                break
            player, card, result = play_legal(game)
            pts = f"  ({card.point_value} pts)" if card.point_value else ""
            print(f"    {player.name:8s} plays {card}{pts}")
            if result.event == "trick_won":
                winner_name = game._get_player(result.data['winner_id']).name
                print(f"    → {winner_name} wins trick  [{result.data['trick_points']} pts in trick]")
            elif result.event == "round_ended":
                break

    # ── 8. Round result ──────────────────────────────────────────────────────
    section("ROUND RESULT")
    res = game.round_results[-1]
    bidder_name = game._get_player(res.bidder_id).name

    print(f"  Bidder : {bidder_name}  (bid {res.bid})")
    print(f"  Trump  : {game.trump_suit.upper()}")
    print(f"  Asked  : {[c.id for c in game.asked_cards]}")

    print(f"\n  Card points collected:")
    for pid, team in res.team_revealed.items():
        p = game._get_player(pid)
        marker = "★ BIDDER" if pid == res.bidder_id else ("  team  " if team == "bidder_team" else "  opp   ")
        print(f"    {marker}  {p.name:8s}  {p.points_in_tricks:>3d} card pts")

    print(f"\n  Bidder team total : {res.bidder_team_points} / {res.bid} needed")
    print(f"  Opponent total    : {res.opponent_team_points}")
    outcome = "✓ BIDDER TEAM WINS" if res.bidder_team_won else "✗ BIDDER TEAM FAILS"
    print(f"\n  {outcome}")

    print(f"\n  Score changes this round:")
    for p in game.players:
        team = res.team_revealed[p.player_id]
        is_bidder = p.player_id == res.bidder_id
        if res.bidder_team_won:
            delta = "+2" if is_bidder else ("+1" if team == "bidder_team" else " 0")
        else:
            delta = "-1" if is_bidder else (" 0" if team == "bidder_team" else "+1")
        print(f"    {p.name:8s}  {delta}  → total {game.scores[p.player_id]}")

    print()


if __name__ == "__main__":
    run()
