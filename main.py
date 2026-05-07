from fastapi import FastAPI

from agentic_bank.routes import router

app = FastAPI()
app.include_router(router)
