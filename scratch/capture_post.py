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
        # Enable network and page
        await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        await ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
        
        async def listen():
            try:
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    method = data.get("method")
                    if method == "Network.requestWillBeSent":
                        params = data.get("params", {})
                        request = params.get("request", {})
                        url = request.get("url", "")
                        req_id = params.get("requestId", "")
                        print(f"REQ: {req_id} | {request.get('method')} | {url}")
                        
                        if "search/purchases" in url:
                            print(f"--> Found search/purchases target!")
                            post_data = request.get("postData")
                            if post_data:
                                print(f"--> PostData in event: {post_data}")
                            else:
                                # Ask for it
                                await ws.send(json.dumps({
                                    "id": 100 + int(hash(req_id) % 1000),
                                    "method": "Network.getRequestPostData",
                                    "params": {"requestId": req_id}
                                }))
                                
                    elif method == "Network.responseReceived":
                        params = data.get("params", {})
                        response = params.get("response", {})
                        url = response.get("url", "")
                        req_id = params.get("requestId", "")
                        print(f"RES: {req_id} | {response.get('status')} | {url}")
                        
                        if "search/purchases" in url:
                            # Ask for response body
                            await ws.send(json.dumps({
                                "id": 2000 + int(hash(req_id) % 1000),
                                "method": "Network.getResponseBody",
                                "params": {"requestId": req_id}
                            }))
                            
                    elif "id" in data:
                        resp_id = data["id"]
                        if resp_id >= 100 and resp_id < 1000:
                            print(f"POST DATA RESP: {json.dumps(data.get('result', {}))}")
                        elif resp_id >= 2000:
                            body_info = data.get("result", {})
                            body = body_info.get("body", "")
                            print(f"BODY RESP (len={len(body)}): {body[:2000]}")
                            
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"Listener error: {e}")
                
        listener_task = asyncio.create_task(listen())
        
        # Navigate or Reload
        print("Reloading page...")
        await ws.send(json.dumps({
            "id": 3,
            "method": "Page.reload",
            "params": {"ignoreCache": True}
        }))
        
        await asyncio.sleep(12)
        listener_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
