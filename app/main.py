"""
Main FastAPI application with all routes.

Flow: Login → Persona Select → Scenario Select → Mission Select → Briefing → Chat → Context
"""
import json
import uuid
import markdown
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import PERSONA_META, BASE_DIR
from app.database import (
    init_db, validate_group_code, create_session, end_session,
    get_session, save_message, get_messages,
)
from app.prompt_assembler import (
    assemble_system_prompt, get_briefing, get_missions, get_scenario_list, parse_scenarios,
)
from app.claude_client import stream_response, strip_indre_tags
from app.auth import get_group_id, get_group_name


# --- Startup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Mount static files if dir exists
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def md_to_html(text: str) -> str:
    """Convert markdown text to HTML."""
    return markdown.markdown(text, extensions=["tables", "fenced_code"])


# --- Auth Routes ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Landing page / login."""
    group_id = get_group_id(request)
    if group_id:
        return RedirectResponse(url="/personas", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/auth/login")
async def login(request: Request, code: str = Form(...)):
    """Validate group code and set session cookie."""
    group = await validate_group_code(code.strip())
    if not group:
        return HTMLResponse(
            '<p class="text-red-500 text-sm">Ukendt holdkode. Prøv igen.</p>',
            status_code=200,
        )
    response = RedirectResponse(url="/personas", status_code=303)
    response.set_cookie("group_id", group["id"], max_age=86400 * 30)
    response.set_cookie("group_name", group["name"], max_age=86400 * 30)
    return response


@app.get("/auth/logout")
async def logout():
    """Clear session cookies."""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("group_id")
    response.delete_cookie("group_name")
    return response


# --- Persona Selection ---

@app.get("/personas", response_class=HTMLResponse)
async def persona_list(request: Request):
    """Show all available personas."""
    group_id = get_group_id(request)
    if not group_id:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse("persona_select.html", {
        "request": request,
        "personas": PERSONA_META,
        "group_name": get_group_name(request) or "",
    })


# --- Scenario Selection ---

@app.get("/personas/{persona_id}/scenarios", response_class=HTMLResponse)
async def scenario_list(request: Request, persona_id: str):
    """Show scenarios for a persona."""
    group_id = get_group_id(request)
    if not group_id:
        return RedirectResponse(url="/", status_code=303)

    if persona_id not in PERSONA_META:
        return RedirectResponse(url="/personas", status_code=303)

    scenarios = get_scenario_list(persona_id)
    return templates.TemplateResponse("scenario_select.html", {
        "request": request,
        "persona": PERSONA_META[persona_id],
        "persona_id": persona_id,
        "scenarios": scenarios,
    })


# --- Mission Selection ---

@app.get("/personas/{persona_id}/scenarios/{scenario_number}/mission", response_class=HTMLResponse)
async def mission_select(request: Request, persona_id: str, scenario_number: int):
    """Show missions for a scenario."""
    group_id = get_group_id(request)
    if not group_id:
        return RedirectResponse(url="/", status_code=303)

    if persona_id not in PERSONA_META:
        return RedirectResponse(url="/personas", status_code=303)

    scenarios = parse_scenarios(persona_id)
    if scenario_number not in scenarios:
        return RedirectResponse(url=f"/personas/{persona_id}/scenarios", status_code=303)

    missions = get_missions(persona_id, scenario_number)
    return templates.TemplateResponse("mission_select.html", {
        "request": request,
        "persona": PERSONA_META[persona_id],
        "persona_id": persona_id,
        "scenario": scenarios[scenario_number],
        "missions": missions,
    })


# --- Session Creation ---

@app.post("/sessions/new")
async def new_session(
    request: Request,
    persona_id: str = Form(...),
    scenario_number: int = Form(...),
    mission: str = Form(""),
):
    """Create a new conversation session and redirect to briefing."""
    group_id = get_group_id(request)
    if not group_id:
        return RedirectResponse(url="/", status_code=303)

    session_id = str(uuid.uuid4())[:8]
    mission_val = mission if mission else None

    await create_session(
        session_id=session_id,
        group_id=group_id,
        persona_id=persona_id,
        scenario_number=scenario_number,
        mission=mission_val,
    )

    return RedirectResponse(url=f"/sessions/{session_id}/briefing", status_code=303)


# --- Briefing ---

@app.get("/sessions/{session_id}/briefing", response_class=HTMLResponse)
async def briefing(request: Request, session_id: str):
    """Show briefing before conversation starts."""
    session = await get_session(session_id)
    if not session:
        return RedirectResponse(url="/personas", status_code=303)

    persona_id = session["persona_id"]
    scenario_number = session["scenario_number"]
    mission = session["mission"]

    briefing_data = get_briefing(persona_id, scenario_number)
    scenarios = parse_scenarios(persona_id)
    scenario = scenarios.get(scenario_number, {})

    # Get mission text if selected
    mission_text = ""
    if mission:
        missions = get_missions(persona_id, scenario_number)
        for m in missions:
            if m["id"] == mission:
                mission_text = m["text"]
                break

    return templates.TemplateResponse("briefing.html", {
        "request": request,
        "persona": PERSONA_META[persona_id],
        "persona_id": persona_id,
        "scenario": scenario,
        "session_id": session_id,
        "mission": mission,
        "mission_text": mission_text,
        "briefing_html": md_to_html(briefing_data["briefing"]),
    })


# --- Chat ---

@app.get("/sessions/{session_id}/chat", response_class=HTMLResponse)
async def chat_page(request: Request, session_id: str):
    """Show the chat interface."""
    session = await get_session(session_id)
    if not session:
        return RedirectResponse(url="/personas", status_code=303)

    persona_id = session["persona_id"]
    scenario_number = session["scenario_number"]

    # Get existing messages
    messages = await get_messages(session_id)
    scenarios = parse_scenarios(persona_id)
    scenario = scenarios.get(scenario_number, {})

    # Format messages for display (strip <indre> from visible)
    display_messages = []
    for msg in messages:
        display_messages.append({
            "role": msg["role"],
            "content": msg["content"] if msg["role"] == "user" else "",
            "visible_content": msg["visible_content"] or strip_indre_tags(msg["content"]) if msg["role"] == "assistant" else msg["content"],
        })

    return templates.TemplateResponse("chat.html", {
        "request": request,
        "persona": PERSONA_META[persona_id],
        "persona_id": persona_id,
        "session_id": session_id,
        "scenario_title": scenario.get("title", ""),
        "mission": session["mission"],
        "messages": display_messages,
    })


# --- Send Message + Stream Response ---

class MessageContent(BaseModel):
    content: str


@app.post("/sessions/{session_id}/send")
async def send_message(session_id: str, body: MessageContent):
    """
    Receive a student message and stream the persona's response via SSE.
    """
    session = await get_session(session_id)
    if not session:
        return StreamingResponse(
            iter(["data: {\"type\": \"error\", \"text\": \"Session ikke fundet\"}\n\n"]),
            media_type="text/event-stream",
        )

    persona_id = session["persona_id"]
    scenario_number = session["scenario_number"]

    # Save user message
    await save_message(session_id, "user", body.content)

    # Build conversation history (include full content with <indre> for context)
    db_messages = await get_messages(session_id)
    conversation_history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in db_messages
    ]

    # Assemble system prompt
    system_prompt = assemble_system_prompt(persona_id, scenario_number)

    # Stream response
    async def generate():
        full_content = ""
        visible_content = ""

        async for chunk in stream_response(system_prompt, conversation_history):
            if chunk["type"] == "visible":
                yield f"data: {json.dumps(chunk)}\n\n"
            elif chunk["type"] == "done":
                full_content = chunk["full_content"]
                visible_content = chunk["visible_content"]
                yield f"data: {json.dumps(chunk)}\n\n"

        # Save assistant message to database
        if full_content:
            await save_message(session_id, "assistant", full_content, visible_content)

        # Check if persona ended the conversation (look for exit signals)
        if any(signal in visible_content.lower() for signal in [
            "vi er færdige", "vi ses", "jeg går", "lukker vi den her",
            "det her giver ikke mening", "vi er done"
        ]):
            await end_session(session_id, ended_by="persona")
            yield f"data: {json.dumps({'type': 'end', 'ended_by': 'persona'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# --- End Session ---

@app.post("/sessions/{session_id}/end")
async def end_session_route(request: Request, session_id: str):
    """Student manually ends the conversation."""
    await end_session(session_id, ended_by="student")
    return RedirectResponse(url=f"/sessions/{session_id}/context", status_code=303)


# --- Context / Post-conversation ---

@app.get("/sessions/{session_id}/context", response_class=HTMLResponse)
async def context_page(request: Request, session_id: str):
    """Show context elements after conversation."""
    session = await get_session(session_id)
    if not session:
        return RedirectResponse(url="/personas", status_code=303)

    persona_id = session["persona_id"]
    scenario_number = session["scenario_number"]

    briefing_data = get_briefing(persona_id, scenario_number)
    scenarios = parse_scenarios(persona_id)
    scenario = scenarios.get(scenario_number, {})

    return templates.TemplateResponse("context.html", {
        "request": request,
        "persona": PERSONA_META[persona_id],
        "persona_id": persona_id,
        "session_id": session_id,
        "scenario_title": scenario.get("title", ""),
        "context_html": md_to_html(briefing_data["context"]),
    })


# --- Health check ---

@app.get("/health")
async def health():
    return {"status": "ok"}
