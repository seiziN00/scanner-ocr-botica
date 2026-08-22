from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI()


@app.get("/")
def leer_html():
    return FileResponse("qwen.html")
