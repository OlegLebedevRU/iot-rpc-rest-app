import httpx
import asyncio
from core import settings


class WebhookConfig:
    def __init__(
        self,
        timeout: float = 5.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        """
        Конфигурация для вебхука: таймауты и повторные попытки.

        :param timeout: Таймаут HTTP-запроса в секундах.
        :param max_retries: Максимальное число попыток отправки при ошибке.
        :param backoff_factor: Коэффициент экспоненциальной задержки (wait = factor * 2^attempt).
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor


config = WebhookConfig(
    timeout=settings.webhook.timeout,
    max_retries=settings.webhook.max_retries,
    backoff_factor=settings.webhook.backoff_factor,
)

# webhook = Webhook(url="https://example.com/webhook", config=config)
# async with webhook:
#    response = await webhook.send({"event": "test"})


class Webhook:
    def __init__(self, url: str, config: WebhookConfig):
        """
        Асинхронный вебхук-клиент с поддержкой retry и таймаутов.

        :param url: URL вебхука.
        :param config: Экземпляр WebhookConfig с настройками таймаутов и повторов.
        """
        self.url = url
        self.config = config
        self.client = httpx.AsyncClient(timeout=config.timeout)

    async def send(self, payload: dict) -> httpx.Response:
        """
        Отправляет POST-запрос с retry-логикой и экспоненциальной задержкой.

        :param payload: Данные для отправки (будут сериализованы в JSON).
        :return: Ответ от сервера.
        :raises httpx.RequestError: Если все попытки неудачны.
        """
        last_exception = None

        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self.client.post(self.url, json=payload)
                response.raise_for_status()
                return response
            except httpx.RequestError as e:
                last_exception = e
                if attempt >= self.config.max_retries:
                    break
                # Экспоненциальная задержка
                wait = self.config.backoff_factor * (2**attempt)
                await asyncio.sleep(wait)

        raise last_exception

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
