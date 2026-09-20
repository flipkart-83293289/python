from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import uvicorn

app = FastAPI(
    title="Device Security & Automation Controller",
    docs_url=None,  # Swagger Docs डिसेबल कर दिया है ताकि सुरक्षा बनी रहे
    redoc_url=None  # ReDoc UI डिसेबल
)

# आपका गुप्त ऑथेंटिकेशन टोकन
SECRET_API_KEY = "Dev69_SecureAuth_Token_987654321_X"

# API Key वेरिफिकेशन लॉजिक
def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != SECRET_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized Access - Invalid Secret Key")
    return x_api_key

# कमांड क्यू (Queue) और टेलीमेट्री डेटा स्टोरेज
pending_commands = []
latest_telemetry = {"status": "NO_DATA", "timestamp": 0}

# Pydantic डेटा मॉडल्स
class TelemetryPayload(BaseModel):
    deviceId: str
    timestamp: int
    batteryLevel: int
    status: str

class CommandResponse(BaseModel):
    command: Optional[str] = None
    payload: Optional[str] = None

class CommandIssue(BaseModel):
    command: str
    payload: Optional[str] = None


# 1. हेल्थ चेक एंडपॉइंट (सामान्य रिस्पॉन्स ताकि किसी को सर्वर का पता न चले)
@app.get("/")
def health_check():
    return {"status": "online", "message": "Server is active"}

# 2. टेलीमेट्री रिसीव करने का एंडपॉइंट (DeviceX से डेटा प्राप्त करना)
@app.post("/api/v1/telemetry", status_code=200)
async def receive_telemetry(data: TelemetryPayload, api_key: str = Depends(verify_api_key)):
    global latest_telemetry
    latest_telemetry = data.dict()
    return {"status": "success"}

# 3. पेंडिंग कमांड फेच करने का एंडपॉइंट (DeviceX हर 15 सेकंड में यहाँ से कमांड लेगा)
@app.get("/api/v1/command/fetch", response_model=CommandResponse)
async def fetch_pending_commands(api_key: str = Depends(verify_api_key)):
    if pending_commands:
        cmd = pending_commands.pop(0)
        return cmd
    return CommandResponse(command=None, payload=None)

# 4. कमांड इश्यू करने का एंडपॉइंट (यह केवल आपकी dashboard.html फाइल से ट्रिगर होगा)
@app.post("/api/v1/command/issue")
async def issue_command(cmd: CommandIssue, api_key: str = Depends(verify_api_key)):
    pending_commands.append({"command": cmd.command, "payload": cmd.payload})
    return {"status": "queued", "command": cmd.command}

if name == "main":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
