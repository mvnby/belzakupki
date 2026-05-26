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
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        
        # Let's wait a bit for any pending rendering to complete
        await asyncio.sleep(2)
        
        # Evaluate script to get link formats
        expr = """
        Array.from(document.querySelectorAll('a'))
          .map(a => ({href: a.href, text: a.innerText}))
          .filter(a => a.href.includes('purchase'))
          .slice(0, 10)
        """
        
        await ws.send(json.dumps({
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expr,
                "returnByValue": True
            }
        }))
        
        msg = await ws.recv()
        while True:
            data = json.loads(msg)
            if data.get("id") == 2:
                result = data.get("result", {}).get("result", {}).get("value")
                print("Links on page:", json.dumps(result, indent=2, ensure_ascii=False))
                break
            msg = await ws.recv()

if __name__ == "__main__":
    asyncio.run(main())
