"""
Main FastAPI application with all routes.

Flow: Login → Persona Select → Scenario Select → Mission Select → Briefing → Chat → Context
"""
import json
import re
import uuid
import markdown
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import re
from app.config import PERSONA_META, BASE_DIR, ADMIN_PASSWORD
from app.database import (
    init_db, validate_group_code, create_session, end_session,
    get_session, save_message, get_messages, save_evaluation,
    get_all_groups, create_group, get_all_sessions, get_session_with_messages,
)
from app.prompt_assembler import (
    assemble_system_prompt, get_briefing, get_missions, get_scenario_list, parse_scenarios,
)
from app.claude_client import stream_response, strip_indre_tags, generate_evaluation
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
            if chunk["type"] == "error":
                yield f"data: {json.dumps(chunk)}\n\n"
                return
            elif chunk["type"] == "visible":
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

    # Check if evaluation already exists
    evaluation_html = ""
    if session.get("evaluation"):
        evaluation_html = md_to_html(session["evaluation"])

    # Build message list with parsed indre content for Samtale tab
    db_messages = await get_messages(session_id)
    display_messages = []
    for msg in db_messages:
        entry = {"role": msg["role"], "content": msg["content"]}
        if msg["role"] == "assistant":
            # Extract indre content
            indre_match = re.search(r"<indre>(.*?)</indre>", msg["content"], re.DOTALL)
            entry["indre_content"] = indre_match.group(1).strip() if indre_match else ""
            entry["visible_content"] = msg["visible_content"] or strip_indre_tags(msg["content"])
        display_messages.append(entry)

    return templates.TemplateResponse("context.html", {
        "request": request,
        "persona": PERSONA_META[persona_id],
        "persona_id": persona_id,
        "session_id": session_id,
        "scenario_title": scenario.get("title", ""),
        "context_html": md_to_html(briefing_data["context"]),
        "evaluation_html": evaluation_html,
        "messages": display_messages,
    })


# --- Admin ---

def check_admin(request: Request) -> bool:
    """Check if request has admin access via cookie or query param."""
    pwd = request.query_params.get("pwd", "")
    if pwd == ADMIN_PASSWORD:
        return True
    return request.cookies.get("is_admin") == "true"


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, group: str | None = None):
    """Admin dashboard with overview of all conversations."""
    if not check_admin(request):
        return HTMLResponse(
            """<div style="font-family:sans-serif;max-width:300px;margin:100px auto;text-align:center">
            <h2>Admin login</h2>
            <form method="GET" action="/admin">
                <input type="password" name="pwd" placeholder="Admin password"
                    style="padding:10px;width:100%;border:1px solid #ccc;border-radius:8px;margin:10px 0">
                <button type="submit"
                    style="padding:10px 20px;background:#1e293b;color:white;border:none;border-radius:8px;cursor:pointer;width:100%">
                    Log ind</button>
            </form></div>""",
            status_code=200,
        )

    groups = await get_all_groups()
    sessions = await get_all_sessions(group_id=group)

    # Count sessions per group
    all_sessions = await get_all_sessions()
    group_session_counts = {}
    total_messages = 0
    for s in all_sessions:
        gid = s.get("group_id", "")
        group_session_counts[gid] = group_session_counts.get(gid, 0) + 1
        total_messages += s.get("message_count", 0)

    response = templates.TemplateResponse("admin.html", {
        "request": request,
        "groups": groups,
        "sessions": sessions,
        "total_sessions": len(all_sessions),
        "total_messages": total_messages,
        "group_session_counts": group_session_counts,
        "persona_meta": PERSONA_META,
        "filter_group": group,
    })
    # Set admin cookie so they don't need password again
    response.set_cookie("is_admin", "true", max_age=86400)
    return response


@app.post("/admin/groups")
async def admin_create_group(request: Request, name: str = Form(...), code: str = Form(...)):
    """Create a new group code."""
    if not check_admin(request):
        return HTMLResponse('<p class="text-red-500">Ikke autoriseret</p>')

    group_id = str(uuid.uuid4())[:8]
    try:
        await create_group(group_id, name, code.strip())
        return HTMLResponse(f'<p class="text-green-600">Holdkode <strong>{code.upper()}</strong> oprettet!</p>')
    except Exception as e:
        return HTMLResponse(f'<p class="text-red-500">Fejl: koden findes allerede</p>')


@app.get("/admin/sessions/{session_id}", response_class=HTMLResponse)
async def admin_view_session(request: Request, session_id: str):
    """View a specific conversation with all messages."""
    if not check_admin(request):
        return RedirectResponse(url="/admin", status_code=303)

    session = await get_session(session_id)
    if not session:
        return RedirectResponse(url="/admin", status_code=303)

    messages = await get_messages(session_id)

    # Extract indre content for admin display
    display_messages = []
    for msg in messages:
        m = dict(msg)
        if msg["role"] == "assistant":
            # Extract indre monologue for display
            indre_match = re.search(r"<indre>(.*?)</indre>", msg["content"], re.DOTALL)
            m["indre_content"] = indre_match.group(1).strip() if indre_match else ""
            m["visible_content"] = msg["visible_content"] or strip_indre_tags(msg["content"])
        display_messages.append(m)

    persona_name = PERSONA_META.get(session["persona_id"], {}).get("name", session["persona_id"])

    response = templates.TemplateResponse("admin_session.html", {
        "request": request,
        "session": session,
        "messages": display_messages,
        "persona_meta": PERSONA_META,
        "persona_name": persona_name,
    })
    response.set_cookie("is_admin", "true", max_age=86400)
    return response


# --- Evaluation ---

@app.post("/sessions/{session_id}/evaluate", response_class=HTMLResponse)
async def evaluate_session(request: Request, session_id: str):
    """Generate evaluation for a session. Returns HTML fragment."""
    session = await get_session(session_id)
    if not session:
        return HTMLResponse('<p class="text-red-500">Session ikke fundet.</p>', status_code=404)

    # Return existing evaluation if already generated
    if session.get("evaluation"):
        return HTMLResponse(
            f'<div class="prose prose-sm prose-slate max-w-none">{md_to_html(session["evaluation"])}</div>'
        )

    persona_id = session["persona_id"]
    scenario_number = session["scenario_number"]
    mission = session["mission"]

    # Get persona name and scenario title
    persona_name = PERSONA_META.get(persona_id, {}).get("name", persona_id)
    scenarios = parse_scenarios(persona_id)
    scenario_name = scenarios.get(scenario_number, {}).get("title", f"Scenario {scenario_number}")

    # Get mission text
    mission_text = "Åben dialog"
    if mission:
        missions = get_missions(persona_id, scenario_number)
        for m in missions:
            if m["id"] == mission:
                mission_text = f"Opgave {m['id']}: {m['text']}"
                break

    # Get full conversation (including <indre> tags)
    messages = await get_messages(session_id)
    conversation = [{"role": msg["role"], "content": msg["content"]} for msg in messages]

    if not conversation:
        return HTMLResponse(
            '<p class="text-slate-500 italic">Ingen beskeder i samtalen at evaluere.</p>'
        )

    try:
        evaluation = await generate_evaluation(
            persona_name=persona_name,
            scenario_name=scenario_name,
            mission_text=mission_text,
            messages=conversation,
        )
        await save_evaluation(session_id, evaluation)
        return HTMLResponse(
            f'<div class="prose prose-sm prose-slate max-w-none">{md_to_html(evaluation)}</div>'
        )
    except Exception as e:
        return HTMLResponse(
            f'<p class="text-red-500">Kunne ikke generere feedback: {str(e)}</p>',
            status_code=500,
        )


# --- Health check ---

@app.get("/health")
async def health():
    return {"status": "ok"}
