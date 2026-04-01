from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.card import router as card_router


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(card_router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok"}
