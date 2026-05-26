import asyncio
import json
import httpx
import websockets

async def main():
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:9222/json")
        targets = resp.json()
    
    page_target = None
    for t in targets:
        if t["type"] == "page":
            page_target = t
            break
            
    if not page_target:
        print("No page target found")
        return
        
    ws_url = page_target["webSocketDebuggerUrl"]
    print(f"Connecting to websocket: {ws_url}")
    
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        await ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
        
        async def listen():
            try:
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    method = data.get("method")
                    if method == "Network.requestWillBeSent":
                        request = data["params"]["request"]
                        url = request["url"]
                        req_id = data["params"]["requestId"]
                        print(f"REQ: {request['method']} {url}")
                    elif method == "Network.responseReceived":
                        response = data["params"]["response"]
                        url = response["url"]
                        req_id = data["params"]["requestId"]
                        print(f"RES: {response['status']} {url}")
                        
                        if "api" in url:
                            # Ask for response body to inspect
                            await ws.send(json.dumps({
                                "id": 1000 + int(hash(req_id) % 10000),
                                "method": "Network.getResponseBody",
                                "params": {"requestId": req_id}
                            }))
                    elif "id" in data:
                        resp_id = data["id"]
                        if resp_id >= 1000:
                            body_info = data.get("result", {})
                            body = body_info.get("body", "")
                            print(f"BODY RESP for id={resp_id} (len={len(body)}): {body[:2000]}")
                            
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"Listener error: {e}")
                
        listener_task = asyncio.create_task(listen())
        
        url = "https://gias.by/gias/#/purchase/current/2e4a0d5d-fc23-47d8-a14b-90df0a677082"
        print(f"Navigating to detailed tender URL: {url}")
        await ws.send(json.dumps({
            "id": 3,
            "method": "Page.navigate",
            "params": {"url": url}
        }))
        
        await asyncio.sleep(8)
        listener_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
