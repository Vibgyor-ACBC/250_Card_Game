"""
250 Card Game — WebSocket server
Run with:  uvicorn server:app --reload --port 8000

Message protocol (JSON):
  Client → Server:  { "action": "<name>", ...payload }
  Server → Client:  { "event": "<name>", "data": {...} }
                or  { "error": "<message>" }

Actions:
  join_game        { name }
  place_bid        { amount }  — amount omitted or null = pass
  select_trump     { suit }
  ask_for_cards    { card_ids: ["rank_suit", "rank_suit"] }
  play_card        { card_id }
  get_state        (no payload — returns your personalised state)
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from engine import Game, ActionResult
from models import GamePhase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="250 Card Game")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Connection registry
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        # game_id → {player_id → WebSocket}
        self._rooms: dict[str, dict[str, WebSocket]] = {}
        # websocket → (game_id, player_id)
        self._ws_map: dict[WebSocket, tuple[str, str]] = {}

    def register(self, game_id: str, player_id: str, ws: WebSocket) -> None:
        self._rooms.setdefault(game_id, {})[player_id] = ws
        self._ws_map[ws] = (game_id, player_id)

    def unregister(self, ws: WebSocket) -> Optional[tuple[str, str]]:
        info = self._ws_map.pop(ws, None)
        if info:
            game_id, player_id = info
            self._rooms.get(game_id, {}).pop(player_id, None)
        return info

    def lookup(self, ws: WebSocket) -> Optional[tuple[str, str]]:
        return self._ws_map.get(ws)

    async def send(self, ws: WebSocket, payload: dict) -> None:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            pass

    async def broadcast(self, game_id: str, payload: dict,
                        exclude: Optional[str] = None) -> None:
        room = self._rooms.get(game_id, {})
        await asyncio.gather(*(
            self.send(ws, payload)
            for pid, ws in room.items()
            if pid != exclude
        ))

    async def broadcast_all(self, game_id: str, payload: dict) -> None:
        await self.broadcast(game_id, payload, exclude=None)


manager = ConnectionManager()

# ---------------------------------------------------------------------------
# Game registry (in-memory; one game per room for now)
# ---------------------------------------------------------------------------

games: dict[str, Game] = {}   # game_id → Game

def get_or_create_game(game_id: str) -> Game:
    if game_id not in games:
        games[game_id] = Game(game_id=game_id)
    return games[game_id]


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str):
    await websocket.accept()
    game = get_or_create_game(game_id)
    player_id: Optional[str] = None

    try:
        async for raw in websocket.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send(websocket, {"error": "Invalid JSON"})
                continue

            action = msg.get("action")
            if not action:
                await manager.send(websocket, {"error": "Missing 'action' field"})
                continue

            # ----------------------------------------------------------------
            # join_game — must be first action
            # ----------------------------------------------------------------
            if action == "join_game":
                if player_id is not None:
                    await manager.send(websocket, {"error": "Already joined"})
                    continue
                name = msg.get("name", "").strip()
                if not name:
                    await manager.send(websocket, {"error": "Name is required"})
                    continue
                result = game.add_player(name)
                if not result.ok:
                    await manager.send(websocket, {"error": result.error})
                    continue
                player_id = result.data["player_id"]
                manager.register(game_id, player_id, websocket)
                # Confirm to joining player
                await manager.send(websocket, {
                    "event": "joined",
                    "data": {"player_id": player_id, "name": name,
                             "game_id": game_id,
                             "total_players": result.data["total_players"]},
                })
                # Announce to room
                await manager.broadcast(game_id, {
                    "event": "player_joined",
                    "data": {"name": name, "total_players": result.data["total_players"]},
                }, exclude=player_id)
                # If round just started, broadcast state to all
                if result.event == "round_started":
                    for pid, ws in manager._rooms.get(game_id, {}).items():
                        p_state = game.state_for_player(pid)
                        await manager.send(ws, {"event": "round_started", "data": p_state})
                continue

            # All subsequent actions require an established player_id
            if player_id is None:
                await manager.send(websocket, {"error": "Join the game first"})
                continue

            # ----------------------------------------------------------------
            # get_state
            # ----------------------------------------------------------------
            if action == "get_state":
                await manager.send(websocket, {
                    "event": "state",
                    "data": game.state_for_player(player_id),
                })

            # ----------------------------------------------------------------
            # place_bid
            # ----------------------------------------------------------------
            elif action == "place_bid":
                amount = msg.get("amount")   # None = pass
                result = game.place_bid(player_id, amount)
                await _dispatch(websocket, player_id, game_id, game, result)

            # ----------------------------------------------------------------
            # select_trump
            # ----------------------------------------------------------------
            elif action == "select_trump":
                suit = msg.get("suit", "")
                result = game.select_trump(player_id, suit)
                await _dispatch(websocket, player_id, game_id, game, result)

            # ----------------------------------------------------------------
            # ask_for_cards
            # ----------------------------------------------------------------
            elif action == "ask_for_cards":
                card_ids = msg.get("card_ids", [])
                result = game.ask_for_cards(player_id, card_ids)
                await _dispatch(websocket, player_id, game_id, game, result,
                                 private_to_bidder=True)

            # ----------------------------------------------------------------
            # play_card
            # ----------------------------------------------------------------
            elif action == "play_card":
                card_id = msg.get("card_id", "")
                result = game.play_card(player_id, card_id)
                await _dispatch(websocket, player_id, game_id, game, result)

            else:
                await manager.send(websocket, {"error": f"Unknown action: {action}"})

    except WebSocketDisconnect:
        pass
    finally:
        info = manager.unregister(websocket)
        if info:
            g_id, p_id = info
            g = games.get(g_id)
            if g:
                p = g._get_player(p_id)
                name = p.name if p else p_id
                await manager.broadcast(g_id, {
                    "event": "player_disconnected",
                    "data": {"player_id": p_id, "name": name},
                })


# ---------------------------------------------------------------------------
# Helper: dispatch result to correct recipients
# ---------------------------------------------------------------------------

async def _dispatch(
    ws: WebSocket,
    player_id: str,
    game_id: str,
    game: Game,
    result: ActionResult,
    private_to_bidder: bool = False,
) -> None:
    if not result.ok:
        await manager.send(ws, {"error": result.error})
        return

    payload = {"event": result.event, "data": result.data}

    if private_to_bidder:
        # Only send card-ask details to the bidder; broadcast a sanitised version
        await manager.send(ws, payload)
        await manager.broadcast(game_id, {
            "event": result.event,
            "data": {k: v for k, v in result.data.items() if k != "asked_cards"},
        }, exclude=player_id)
    else:
        # Broadcast to all
        await manager.broadcast_all(game_id, payload)

    # After round ends, send each player their personalised updated state
    if result.event in ("round_ended", "round_started", "cards_asked_game_starts"):
        for pid, conn_ws in manager._rooms.get(game_id, {}).items():
            await manager.send(conn_ws, {
                "event": "state_update",
                "data": game.state_for_player(pid),
            })


# ---------------------------------------------------------------------------
# REST health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "active_games": len(games)}

@app.get("/games/{game_id}/state")
def game_state(game_id: str):
    """Debug endpoint — public state only."""
    g = games.get(game_id)
    if not g:
        return {"error": "Game not found"}
    return g._public_state()
