import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from create_api_app import create_app
from core.models import Postamat, Device, DeviceOrgBind, Org

# from tests.utils import create_test_user, get_token_headers

app = create_app()


@pytest.fixture
async def setup_db(session: AsyncSession):
    # Создаём организацию
    org = Org(name="Test Org")
    session.add(org)
    await session.commit()

    # Создаём устройство и привязку
    device = Device(sn="SN_TEST_001", org_bind=[DeviceOrgBind(org_id=org.id)])
    session.add(device)
    await session.commit()

    # Создаём постамат
    postamat = Postamat(
        device_id=device.id,
        name="Test Postamat",
        address="Test Address",
        location={"lat": 1.0, "lng": 2.0},
    )
    session.add(postamat)
    await session.commit()

    return org, postamat


@pytest.mark.asyncio
async def test_get_all_postamats(session: AsyncSession, setup_db):
    org, postamat = setup_db
    # user = await create_test_user(session, org_id=org.id)
    # headers = await get_token_headers(user.email)

    async with AsyncClient(base_url="http://test") as ac:
        response = await ac.get(
            "/api/v1/postamats/",
            #    headers=headers,
            params={"org_id": org.id, "skip": 0, "limit": 10},
        )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    first = data[0]
    assert first["id"] == postamat.id
    # assert first["device_id"] == device.id
    assert first["name"] == "Test Postamat"
    assert first["address"] == "Test Address"
    assert first["location"] == {"lat": 1.0, "lng": 2.0}
    assert "device" in first
    assert first["device"]["sn"] == "SN_TEST_001"


@pytest.mark.asyncio
async def test_get_all_postamats_unauthorized():
    async with AsyncClient(base_url="http://test") as ac:
        response = await ac.get("/api/v1/postamats/")
    assert response.status_code == 401  # Unauthorized
