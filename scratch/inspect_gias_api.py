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
        # Enable network
        await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        await ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
        
        target_request_id = None
        
        async def listen():
            nonlocal target_request_id
            try:
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    method = data.get("method")
                    if method == "Network.requestWillBeSent":
                        request = data["params"]["request"]
                        url = request["url"]
                        req_id = data["params"]["requestId"]
                        if "search/purchases" in url:
                            print(f"\n[REQUEST] id={req_id} method={request['method']} url={url}")
                            print("Headers:", json.dumps(request["headers"], indent=2))
                            target_request_id = req_id
                            # Try to get post data if POST
                            if request.get("hasPostData"):
                                # Request post data is sent in the event or we can request it
                                if "postData" in request:
                                    print("Post Data (direct):", request["postData"])
                                else:
                                    # Request post data via protocol
                                    await ws.send(json.dumps({
                                        "id": 100,
                                        "method": "Network.getRequestPostData",
                                        "params": {"requestId": req_id}
                                    }))
                    elif method == "Network.responseReceived":
                        response = data["params"]["response"]
                        url = response["url"]
                        req_id = data["params"]["requestId"]
                        if "search/purchases" in url:
                            print(f"\n[RESPONSE] id={req_id} status={response['status']} url={url}")
                            # Request response body
                            await ws.send(json.dumps({
                                "id": 200,
                                "method": "Network.getResponseBody",
                                "params": {"requestId": req_id}
                            }))
                    elif "id" in data:
                        # This is a response to our method calls
                        msg_id = data["id"]
                        if msg_id == 100:
                            print("Post Data (method):", data.get("result", {}).get("postData"))
                        elif msg_id == 200:
                            body_info = data.get("result", {})
                            body = body_info.get("body", "")
                            is_base64 = body_info.get("base64Encoded", False)
                            print(f"Response Body (base64={is_base64}):", body[:5000]) # Print first 5000 chars
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"Listener error: {e}")
                
        listener_task = asyncio.create_task(listen())
        
        print("Navigating to https://gias.by/gias/#/purchase/current...")
        await ws.send(json.dumps({
            "id": 3,
            "method": "Page.navigate",
            "params": {"url": "https://gias.by/gias/#/purchase/current"}
        }))
        
        await asyncio.sleep(10)
        listener_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
