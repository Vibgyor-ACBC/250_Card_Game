# 250 Card Game — Backend

Python backend for the 6-player trick-taking card game "250".

## Setup

```bash
pip install -r requirements.txt
```

## Run the server

```bash
uvicorn server:app --reload --port 8000
```

## Run tests

```bash
python -m pytest tests.py -v
```

---

## Architecture

```
game250/
├── models.py      # Card, Player, Trick, RoundResult, GamePhase (data only)
├── deck.py        # Deck building and dealing helpers
├── engine.py      # Game state machine — all rules live here
├── server.py      # FastAPI + WebSocket server
└── tests.py       # Full test suite
```

## Game phases

```
WAITING → DEALING → BIDDING → TRUMP_SELECT → CARD_ASK → PLAYING → ROUND_END
                       ↑                                                ↓
                       └─────────────── (new round) ───────────────────┘
```

---

## WebSocket protocol

Connect to `ws://localhost:8000/ws/{game_id}`

All messages are JSON.

### Client → Server

| Action | Payload | When |
|---|---|---|
| `join_game` | `{ name }` | On connect |
| `place_bid` | `{ amount }` or `{}` to pass | BIDDING phase |
| `select_trump` | `{ suit }` | TRUMP_SELECT phase |
| `ask_for_cards` | `{ card_ids: ["rank_suit", "rank_suit"] }` | CARD_ASK phase |
| `play_card` | `{ card_id }` | PLAYING phase |
| `get_state` | _(none)_ | Any time |

### Server → Client events

| Event | Broadcast? | Notes |
|---|---|---|
| `joined` | Private | Confirms join; includes your `player_id` |
| `player_joined` | Room | New player announcement |
| `round_started` | All (personalised) | Each player gets their own hand |
| `bid_placed` | All | Current highest bid visible to all |
| `trump_selected` | All | Trump suit revealed |
| `cards_asked_game_starts` | Bidder gets full; others get sanitised | Card names hidden from non-bidder |
| `card_played` | All | Which card was played and by whom |
| `trick_won` | All | Winner, points in trick |
| `round_ended` | All | Full reveal: teams, scores, trick log |
| `state_update` | All (personalised) | Sent after major phase changes |
| `player_disconnected` | Room | Player name/id |

---

## Card ID format

Cards are identified by `{rank}_{suit}`, e.g.:
- `K_hearts` — King of Hearts  
- `Q_spades` — Queen of Spades (60 pts)  
- `10_diamonds` — Ten of Diamonds  
- `J_clubs` — Jack of Clubs

Valid ranks: `3 4 5 6 7 8 9 10 J Q K A`  
Valid suits: `spades hearts diamonds clubs`

---

## Scoring rules

- Face card point values: J=5, Q=10, K=15, A=20; Queen of Spades=60
- All number cards (3–10 excl. face) = 0 points
- Total points per round = 250
- **Bidder's team wins** if they collect ≥ their bid in points
- If they succeed → bidder team score += points collected
- If they fail → bidder team score -= bid amount; opponents += their points
- Teams are only revealed after all 8 tricks are played

## Bidding rules

- Any player may bid any positive integer ≤ 250, or pass
- Bidding is not mandatory
- **First-bid-wins** tiebreaker: if two players bid the same amount, the one who bid first is the winner
- If nobody bids, cards are re-dealt
