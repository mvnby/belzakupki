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
        # Enable network and runtime
        await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        await ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
        
        urls = []
        async def listen():
            try:
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    method = data.get("method")
                    if method == "Network.requestWillBeSent":
                        request = data["params"]["request"]
                        url = request["url"]
                        print(f"Request: {request['method']} {url}")
                        urls.append(url)
                    elif method == "Network.responseReceived":
                        response = data["params"]["response"]
                        print(f"Response: {response['status']} {response['url']}")
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
        
        print("\nAll captured URLs:")
        for url in urls:
            print(url)

if __name__ == "__main__":
    asyncio.run(main())
