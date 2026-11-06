"""AI research streaming: application row -> prompt -> SSE event generator.

Prompt construction and stream translation are domain logic, not request
handling, so per the four-layer rule in wiki/notes/dashboard-code-structure they
do not belong in a route body (where they used to live, all ~78 lines of it).
The route keeps only the API-key guard, the 404, and the Response wrapper.

Not a db_*.py module on purpose: nothing here touches jobs.db. The caller hands
in the application row it already loaded.
"""

from __future__ import annotations

import json

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4000

SYSTEM = (
    "You are a job application research assistant. Provide thorough, well-organized "
    "research that helps the applicant prepare. Use markdown headers and bullet points. "
    "Be specific and actionable. Cite sources where useful."
)


def build_question(app: dict, focus: str = "company", interviewer_name: str = "") -> str:
    """The user-turn prompt for one research focus.

    Falls through to the role prompt for an unknown focus, and for
    focus="interviewer" with no name — there is nothing to research without one.
    """
    if focus == "company":
        return (
            f"Research {app['company']} for a job application for the role of {app['role']}. "
            "Cover: company overview, products/services, culture & values, recent news, "
            "leadership, financials (if public), competitors, why someone would want to work there, "
            "and any red flags or risks. Format with clear sections."
        )
    if focus == "interviewer" and interviewer_name:
        return (
            f"Research {interviewer_name} at {app['company']} who will be interviewing "
            f"a candidate for the {app['role']} role. "
            "Find their background, career history, LinkedIn presence, any public writing or talks, "
            "and what topics they likely care about based on their role. "
            "Suggest conversation angles and questions to ask them."
        )
    return (
        f"Research the {app['role']} role at {app['company']}. "
        "Cover: what this role typically involves day-to-day, required skills, "
        "growth trajectory, how this role fits in the org, likely interview topics, "
        "and key things to demonstrate in interviews."
    )


def research_stream(app: dict, focus: str, interviewer_name: str, api_key: str):
    """Yield SSE `data:` frames for one research run.

    Errors are yielded as an `error` frame rather than raised: the response has
    already started streaming by then, so there is no status code left to set.
    """
    import anthropic as sdk

    client = sdk.Anthropic(api_key=api_key)
    question = build_question(app, focus, interviewer_name)

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
            messages=[{"role": "user", "content": question}],
        ) as stream:
            for event in stream:
                if not hasattr(event, "type"):
                    continue
                if event.type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block and getattr(block, "type", "") == "tool_use":
                        yield f"data: {json.dumps({'type': 'searching'})}\n\n"
                elif event.type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    text = getattr(delta, "text", None)
                    if text:
                        yield f"data: {json.dumps({'type': 'delta', 'text': text})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


if __name__ == "__main__":
    row = {"company": "Acme", "role": "Analyst"}
    assert "Research Acme for a job application" in build_question(row, "company")
    assert "Research Dana at Acme" in build_question(row, "interviewer", "Dana")
    # No name -> the interviewer prompt is unbuildable, so fall through to role.
    assert "Research the Analyst role" in build_question(row, "interviewer", "")
    assert "Research the Analyst role" in build_question(row, "nonsense")
    print("ok")
