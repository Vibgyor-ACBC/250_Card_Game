"""
250 Card Game — Interactive multi-round simulation

Each round is played automatically (bots pick the first legal card).
After every round the scoreboard is printed.

Commands (type at the "Press Enter" prompt):
  <Enter>    → play another round
  total      → show final scoreboard and declare winner, then exit
  quit / q   → exit immediately
"""
from engine import Game
from models import Card, GamePhase


# ── display helpers ─────────────────────────────────────────────────────────

SUIT_SYMBOLS = {"spades": "♠", "hearts": "♥", "diamonds": "♦", "clubs": "♣"}

def hand_str(player) -> str:
    return "  ".join(
        f"{c.rank}{SUIT_SYMBOLS[c.suit]}{'*' if c.point_value else ''}"
        for c in sorted(player.hand, key=lambda c: (c.suit, c.rank_index))
    )

def section(title: str) -> None:
    print(f"\n{'═'*62}")
    print(f"  {title}")
    print('═'*62)

def divider() -> None:
    print(f"  {'─'*56}")

def show_scoreboard(game: Game, names: list, pids: list) -> None:
    section("SCOREBOARD")
    name_map = {pid: name for pid, name in zip(pids, names)}
    sorted_players = sorted(
        [(game.scores.get(pid, 0), name_map[pid]) for pid in pids],
        reverse=True,
    )
    print(f"  {'Player':<12}  {'Score':>6}")
    divider()
    for score, name in sorted_players:
        bar = "█" * max(0, score) if score > 0 else ("▒" * abs(score) if score < 0 else "·")
        print(f"  {name:<12}  {score:>+6}  {bar}")
    print()

def declare_winner(game: Game, names: list, pids: list) -> None:
    section(f"FINAL RESULT  ({len(game.round_results)} rounds played)")
    name_map = {pid: name for pid, name in zip(pids, names)}
    sorted_players = sorted(
        [(game.scores.get(pid, 0), pid) for pid in pids],
        reverse=True,
    )
    print(f"  {'Rank':<6}  {'Player':<12}  {'Score':>6}")
    divider()
    for rank, (score, pid) in enumerate(sorted_players, 1):
        print(f"  {rank:<6}  {name_map[pid]:<12}  {score:>+6}")

    top_score = sorted_players[0][0]
    winners = [name_map[pid] for score, pid in sorted_players if score == top_score]
    print()
    if len(winners) == 1:
        print(f"  🏆  {winners[0]} wins the game!")
    else:
        print(f"  🏆  Tie between: {', '.join(winners)}!")
    print()


# ── bot helpers ─────────────────────────────────────────────────────────────

def get_two_askable(game: Game, bidder_id: str) -> list:
    bidder = game._get_player(bidder_id)
    forbidden = {Card("A", "spades")}
    candidates = [
        c for p in game.players if p.player_id != bidder_id
        for c in p.hand
        if c not in bidder.hand and c not in forbidden
    ]
    return [candidates[0].id, candidates[1].id]

def play_legal(game: Game):
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


# ── single round ─────────────────────────────────────────────────────────────

def play_round(game: Game, names: list, pids: list, round_num: int) -> None:
    name_map = {pid: name for pid, name in zip(pids, names)}

    section(f"ROUND {round_num}")
    print("  Initial hands (5 cards):\n")
    for p in game.players:
        print(f"  {p.name:10s}  [{hand_str(p)}]")

    # ── Bidding ──────────────────────────────────────────────────────────────
    section(f"ROUND {round_num} — BIDDING")

    lead_idx = (round_num - 1) % 6
    base_bid = 160 + (round_num % 3) * 10

    p0 = pids[lead_idx]
    p1 = pids[(lead_idx + 1) % 6]
    rest = [pids[(lead_idx + i) % 6] for i in range(2, 6)]

    bid_actions = [
        (p0, base_bid),
        (p1, base_bid + 15),
        (p0, base_bid + 25),
        (p1, base_bid + 40),
    ] + [(p, None) for p in rest] + [(p0, None)]

    for pid, amount in bid_actions:
        if game.phase != GamePhase.BIDDING:
            break
        r = game.place_bid(pid, amount)
        if not r.ok:
            continue
        label = f"{amount}" if amount else "pass"
        if r.data.get('highest_bidder_id'):
            leader = game._get_player(r.data['highest_bidder_id']).name
            status = f"  → highest {r.data['highest_bid']} ({leader})"
        else:
            status = ""
        active = len(r.data.get('active_bidders', []))
        active_str = f"  [{active} active]" if active > 1 else ""
        print(f"  {name_map[pid]:8s}  {label:>4s}{status}{active_str}")

    bidder = game._get_player(game.highest_bidder_id)
    print(f"\n  ★ {bidder.name} wins bid at {game.highest_bid}")

    # ── Trump & card ask ─────────────────────────────────────────────────────
    suits = ["spades", "hearts", "diamonds", "clubs"]
    trump = suits[round_num % 4]
    game.select_trump(game.highest_bidder_id, trump)
    print(f"  Trump: {trump.upper()}")

    card_ids = get_two_askable(game, game.highest_bidder_id)
    game.ask_for_cards(game.highest_bidder_id, card_ids)
    print(f"  {bidder.name} asks for: {card_ids[0]}  and  {card_ids[1]}")
    print(f"  (Teams revealed at end of round)\n")

    print("  Full hands (8 cards, * = point card):\n")
    for p in game.players:
        print(f"  {p.name:10s}  [{hand_str(p)}]")

    # ── Trick-taking ─────────────────────────────────────────────────────────
    section(f"ROUND {round_num} — TRICKS  (trump: {trump.upper()})")
    trick_num = 0
    while game.phase == GamePhase.PLAYING:
        trick_num += 1
        print(f"\n  — Trick {trick_num} —")
        for _ in range(6):
            if game.phase != GamePhase.PLAYING:
                break
            player, card, result = play_legal(game)
            sym = SUIT_SYMBOLS[card.suit]
            pts = f"  ({card.point_value} pts)" if card.point_value else ""
            print(f"    {player.name:8s}  {card.rank}{sym}{pts}")
            if result.event == "trick_won":
                winner_name = game._get_player(result.data['winner_id']).name
                print(f"    → {winner_name} wins trick  [{result.data['trick_points']} pts]")
            elif result.event == "round_ended":
                break

    # ── Round result ─────────────────────────────────────────────────────────
    section(f"ROUND {round_num} — RESULT")
    res = game.round_results[-1]
    print(f"  Bidder: {bidder.name}  (needed {res.bid})   Trump: {trump.upper()}\n")

    print(f"  {'Player':<10}  {'Role':<14}  {'Card pts':>8}")
    divider()
    for pid, team in res.team_revealed.items():
        p = game._get_player(pid)
        role = "★ Bidder" if pid == res.bidder_id else ("  Teammate" if team == "bidder_team" else "  Opponent")
        print(f"  {p.name:<10}  {role:<14}  {p.points_in_tricks:>8}")

    print(f"\n  Bidder team: {res.bidder_team_points} pts  (needed {res.bid})")
    print(f"  Opp team   : {res.opponent_team_points} pts")
    outcome = "✓  BIDDER TEAM WIN" if res.bidder_team_won else "✗  BIDDER TEAM FAIL"
    print(f"\n  {outcome}\n")

    print("  Score changes this round:")
    for p in game.players:
        team = res.team_revealed[p.player_id]
        is_bidder = p.player_id == res.bidder_id
        if res.bidder_team_won:
            delta = "+2" if is_bidder else ("+1" if team == "bidder_team" else " 0")
        else:
            delta = "-1" if is_bidder else (" 0" if team == "bidder_team" else "+1")
        print(f"    {p.name:8s}  {delta}  →  total {game.scores[p.player_id]:+d}")

    # Reset for next round
    game._start_round()


# ── entry point ──────────────────────────────────────────────────────────────

def run():
    game = Game()
    names = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank"]

    section("LOBBY — 250 Card Game")
    pids = []
    for name in names:
        r = game.add_player(name)
        pids.append(r.data["player_id"])
        print(f"  {name} joined  ({r.data['total_players']}/6)")

    print("\n  Commands after each round:")
    print("    <Enter>  → play another round")
    print("    total    → declare winner and exit")
    print("    quit     → exit immediately\n")

    round_num = 0
    while True:
        round_num += 1
        play_round(game, names, pids, round_num)
        show_scoreboard(game, names, pids)

        try:
            cmd = input("  → ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            cmd = "quit"

        if cmd in ("quit", "q"):
            print("\n  Game abandoned.\n")
            break
        elif cmd == "total":
            declare_winner(game, names, pids)
            break
        # <Enter> or anything else → next round


if __name__ == "__main__":
    run()
