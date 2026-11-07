"""Deterministic dispatch before analytics. Classification never authorizes computation."""

import uuid

from pydantic import ValidationError

from . import briefing, engine, suggestions
from .db import get_db
from .router import Classification, classify
from .spec import InterpretationUnavailable


MESSAGES = {
    "opened": ("Here is your current briefing.", "Tässä on nykyinen aamubriefingisi."),
    "conversation": ("I can open your current briefing, help analyse governed business metrics, or explain a previous answer. What would you like to do?",
                     "Voin avata nykyisen aamubriefingisi, auttaa analysoimaan hallittuja liiketoiminnan mittareita tai selittää edellisen vastauksen. Mitä haluaisit tehdä?"),
    "previous": ("The latest recorded answer was:\n\n{answer}\n\n{evidence}\n\nI have not calculated new figures or inferred causes beyond this evidence.",
                 "Viimeisin tallennettu vastaus oli:\n\n{answer}\n\n{evidence}\n\nEn ole laskenut uusia lukuja tai päätellyt syitä tämän näytön ulkopuolelta."),
    "no_previous": ("There is no previous answer to explain in this conversation. Which result would you like to discuss?",
                    "Tässä keskustelussa ei vielä ole selitettävää aiempaa vastausta. Mistä tuloksesta haluaisit keskustella?"),
}


def message(key, language, **values):
    return MESSAGES[key][language == "fi"].format(**values)


def _auxiliary_turn(db, session_id, role, question, answer, routing_pending=None):
    # Deliberately never set/unset pending_request or analytics counters here.
    update = {"$push": {"turns": {"q": question, "answer": answer, "decision": "CHAT", "ts": engine.now()}},
              "$set": {"role": role, "updated_at": engine.now()}, "$setOnInsert": {"created_at": engine.now()}}
    if routing_pending is not None:
        update["$set"]["routing_pending"] = routing_pending
    db.conversations.update_one({"_id": session_id}, update, upsert=True)


def ask(question, role, session_id=None, language="en", abandon_pending=False):
    if abandon_pending:
        return engine.ask(question, role, session_id, language, True)
    db = get_db()
    session_id = session_id or uuid.uuid4().hex[:12]
    conversation = db.conversations.find_one({"_id": session_id}) or {}
    history = conversation.get("turns", [])
    pending = conversation.get("pending_request")
    unresolved = conversation.get("routing_pending")
    latest_questions = (pending or {}).get("latest_questions", [])
    if unresolved:
        latest_questions = [*latest_questions, {"text": unresolved["question"]}]
    values = suggestions.supported_values()
    original = ((pending or {}).get("original_request")
                or "\n\n".join((unresolved or {}).get("messages", [])) or question)
    # Everything above is read-only. Failures here must leave the conversation untouched.
    try:
        classified, elapsed = classify(question, history, pending, latest_questions, unresolved,
                                       values, language)
        classified = Classification.model_validate(classified)
        generated = (suggestions.validate(classified.clarification, [], original,
                                         (pending or {}).get("brief", {}), values)
                     if classified.needs_clarification else None)
        current = (suggestions.validate(unresolved["clarification"], [], original,
                                       (pending or {}).get("brief", {}), values)
                   if unresolved and unresolved.get("clarification") else None)
    except (ValidationError, TypeError, ValueError) as exc:
        raise InterpretationUnavailable("Invalid classification") from exc

    route = {"intent": classified.intent, "latency_ms": round(elapsed, 1)}
    base = {"question": question, "role": role, "language": language, "session_id": session_id,
            "decision": "CHAT", "routing": route,
            "intake": {"pending": bool(pending or unresolved)}}
    answered = None
    if current:
        chosen = next((s for s in current.suggestions if s.answer == question.strip()), None)
        if chosen and chosen.changes.model_dump(exclude_none=True):
            answered = (current.question, chosen)
            route["intent"] = "clarification_reply"
    if classified.needs_clarification and not answered:
        answer = generated.question.text
        messages = [*(unresolved or {}).get("messages", []), question]
        state = {"messages": messages, "question": answer, "clarification": generated.model_dump()}
        _auxiliary_turn(db, session_id, role, question, answer, state)
        return {**base, "answer": answer, "intake": {"pending": True,
            "questions": [generated.question.model_dump()]},
            "suggestions": [s.public() for s in generated.suggestions]}

    if classified.intent == "ui_action" and not answered:
        # Allowlist dispatch; never execute model-supplied URLs, code or role IDs.
        if classified.action != "open_briefing":
            raise InterpretationUnavailable("Unknown UI action")
        current = briefing.briefing(role, language)
        answer = message("opened", language)
        _auxiliary_turn(db, session_id, role, question, answer)
        return {**base, "answer": answer, "action": {"name": "open_briefing", "briefing": current}}

    if classified.intent in ("conversation", "explain_previous") and not answered:
        # Evidence-only responses: no additional model call, computation or fabricated causality.
        if classified.intent == "explain_previous":
            previous = next((turn for turn in reversed(history) if turn.get("answer")), None)
            answer = (message("previous", language, answer=previous["answer"],
                              evidence=previous.get("explanation", "")) if previous
                      else message("no_previous", language))
        else:
            answer = message("conversation", language)
            if pending and pending.get("latest_questions"):
                answer += "\n\n" + " ".join(q["text"] for q in pending["latest_questions"])
        _auxiliary_turn(db, session_id, role, question, answer)
        return {**base, "answer": answer}

    # Analytics/clarification still pass through the original deterministic gate.
    # Retain the complete unresolved message, including every metric/constraint.
    if answered:
        result = engine.ask(question, role, session_id, language, False, unresolved["messages"],
                            clarification_answer=answered)
    elif unresolved:
        result = engine.ask(question, role, session_id, language, False, unresolved["messages"])
    else:
        result = engine.ask(question, role, session_id, language)
    return {**result, "routing": route}
