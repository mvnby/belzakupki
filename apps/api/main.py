from fastapi import FastAPI

app = FastAPI(title="belzakupki")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
