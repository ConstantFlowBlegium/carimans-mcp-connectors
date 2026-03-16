import asyncio
from robaws_client import RobawsClient

async def test_api():
    client = RobawsClient()
    try:
        # Test work orders
        result = await client.get("work-orders", {"size": 1, "page": 0})
        print("✅ Work orders API connection successful!")
        
        # Test clients
        result = await client.get("clients", {"size": 1, "page": 0})
        print("✅ Clients API connection successful!")
        
        # Test suppliers
        result = await client.get("suppliers", {"size": 1, "page": 0})
        print("✅ Suppliers API connection successful!")
        
        # Test purchase orders
        result = await client.get("purchase-supply-orders", {"size": 1, "page": 0})
        print("✅ Purchase orders API connection successful!")
        
        print("🎉 All tested endpoints working!")
        
    except Exception as e:
        print(f"❌ API connection failed: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_api())