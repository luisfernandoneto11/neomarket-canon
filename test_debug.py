import asyncio
from unittest.mock import AsyncMock, patch
from services.product_card_service import ProductCardService

async def test():
    with patch('services.product_card_service.B2BClient') as MockClass:
        mock_instance = MockClass.return_value
        mock_instance.get_product_by_id = AsyncMock(return_value={
            'id': '123', 
            'status': 'MODERATED', 
            'deleted': False, 
            'is_hard_blocked': False, 
            'slug': 'test', 
            'title': 'Test Product', 
            'description': 'A test', 
            'images': [], 
            'characteristics': [], 
            'skus': [], 
            'category': None
        })
        service = ProductCardService()
        print('b2b_client type:', type(service.b2b_client))
        result = await service.get_product_card('123')
        print('Result:', result.title)

asyncio.run(test())