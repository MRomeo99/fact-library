"""FastAPI serving application."""

from fastapi import FastAPI

from serving.routers import crawl, facts, status

app = FastAPI(
    title="Client Fact Library",
    description="AI-agent-ready retrieval API for typed business facts.",
    version="0.1.0",
)

app.include_router(facts.router)
app.include_router(crawl.router)
app.include_router(status.router)


@app.get("/health")
def health():
    return {"status": "ok"}
