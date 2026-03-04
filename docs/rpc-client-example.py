import asyncio
import uuid
import json
import logging
from typing import Optional, Dict, Any

import ssl
import certifi
from gmqtt import Client as MQTTClient

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Константы
BROKER_HOST = "your-mqtt-broker.com"
BROKER_PORT = 8883
CLIENT_CERT_PATH = "path/to/client_cert.pem"
CLIENT_KEY_PATH = "path/to/client_key.pem"
CA_CERT_PATH = certifi.where()

# Серийный номер из CN сертификата (пример)
SN = "a3b1234567c10221d290825"

# Топики
TOPIC_REQ = f"dev/{SN}/req"
TOPIC_RES = f"dev/{SN}/res"
TOPIC_EVT = f"dev/{SN}/evt"
TOPIC_ACK = f"dev/{SN}/ack"

TOPIC_RSP = f"srv/{SN}/rsp"
TOPIC_TSK = f"srv/{SN}/tsk"
TOPIC_CMT = f"srv/{SN}/cmt"
TOPIC_EVA = f"srv/{SN}/eva"

# Таймеры (в секундах)
REQ_POLL_INTERVAL = 60  # Опрос на наличие задач
HEALTHCHECK_INTERVAL = 300  # Отправка keep-alive


class DeviceClient:
    def __init__(self):
        self.client_id = SN
        self.mqtt_client = MQTTClient(self.client_id)

        # Активные корреляции
        self.pending_requests: Dict[str, Dict[str, Any]] = {}

        self._setup_mqtt()

    def _setup_mqtt(self):
        # Подключение TLS
        self.mqtt_client.set_auth_credentials(
            None, None
        )  # Аутентификация через сертификат
        context = ssl.create_default_context(cafile=CA_CERT_PATH)
        context.load_cert_chain(CLIENT_CERT_PATH, CLIENT_KEY_PATH)
        self.mqtt_client.set_tls_config(context)

        # Обработчики событий
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.on_subscribe = self.on_subscribe

    async def start(self):
        logger.info(f"Connecting to broker {BROKER_HOST}:{BROKER_PORT}")
        await self.mqtt_client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)

        # Подписка на входящие топики
        self.mqtt_client.subscribe(TOPIC_RSP)
        self.mqtt_client.subscribe(TOPIC_TSK)
        self.mqtt_client.subscribe(TOPIC_CMT)

        # Запуск фоновых задач
        asyncio.create_task(self.polling_loop())
        asyncio.create_task(self.healthcheck_loop())

    def on_connect(self, client, flags, rc, properties):
        logger.info("Connected to MQTT broker with code %s", rc)

    def on_disconnect(self, client, packet, exc=None):
        logger.warning("Disconnected from MQTT broker")

    def on_subscribe(self, client, mid, qos, properties):
        logger.info("Subscribed with QoS %s", qos)

    async def on_message(self, client, topic, payload, qos, properties):
        try:
            correlation_data = properties.get("correlation_data", b"").decode()
            user_props = (
                dict(properties.get("user_property", []))
                if properties.get("user_property")
                else {}
            )

            logger.debug(
                "Received message: %s -> %s | Correlation: %s | Props: %s",
                topic,
                payload,
                correlation_data,
                user_props,
            )

            if topic == TOPIC_TSK:
                await self.handle_task_announcement(correlation_data, user_props)
            elif topic == TOPIC_RSP:
                await self.handle_task_response(correlation_data, payload, user_props)
            elif topic == TOPIC_CMT:
                await self.handle_commit(correlation_data, user_props)
            else:
                logger.warning("Unknown topic received: %s", topic)

        except Exception as e:
            logger.error("Error processing message: %s", e)

    async def handle_task_announcement(
        self, correlation_data: str, user_props: Dict[str, str]
    ):
        """Обработка анонса задачи от сервера"""
        method_code = user_props.get("method_code")
        logger.info(
            "Task announced: correlation=%s, method=%s", correlation_data, method_code
        )

        # Подтверждение получения (опционально)
        await self.send_ack(correlation_data)

        # Запрос параметров задачи
        await self.send_request(correlation_data)

    async def handle_task_response(
        self, correlation_data: str, payload: bytes, user_props: Dict[str, str]
    ):
        """Обработка параметров задачи"""
        method_code = user_props.get("method_code")
        request = self.pending_requests.pop(correlation_data, None)

        logger.info(
            "Task received: method=%s, correlation=%s", method_code, correlation_data
        )

        # Имитация выполнения задачи
        result = await self.execute_task(method_code, json.loads(payload))

        # Отправка результата
        await self.send_result(correlation_data, result, method_code)

    async def handle_commit(self, correlation_data: str, user_props: Dict[str, str]):
        """Подтверждение получения результата от сервера"""
        result_id = user_props.get("result_id")
        logger.info(
            "Commit received for result_id=%s, correlation=%s",
            result_id,
            correlation_data,
        )

    async def execute_task(self, method_code: str, params: dict) -> dict:
        """Выполнение задачи на устройстве"""
        logger.info("Executing task method_code=%s with params=%s", method_code, params)
        # Здесь ваша логика обработки команд
        await asyncio.sleep(1)  # имитация работы
        return {"status": "completed", "data": "success"}

    async def send_request(self, correlation_data: Optional[str] = None):
        """Отправка запроса на получение задачи"""
        if not correlation_data:
            correlation_data = (
                "00000000-0000-0000-0000-000000000000"  # Zero UUID для поллинга
            )

        properties = {"correlation_data": correlation_data.encode()}
        self.mqtt_client.publish(TOPIC_REQ, "", qos=1, properties=properties)
        logger.debug("Sent request with correlation: %s", correlation_data)

        # Сохраняем ожидание ответа
        self.pending_requests[correlation_data] = {
            "type": "request",
            "timestamp": asyncio.get_event_loop().time(),
        }

    async def send_ack(self, correlation_data: str):
        """Отправка подтверждения получения tsk (опционально)"""
        properties = {"correlation_data": correlation_data.encode()}
        self.mqtt_client.publish(TOPIC_ACK, "", qos=1, properties=properties)
        logger.debug("Sent ACK for correlation: %s", correlation_data)

    async def send_result(self, correlation_data: str, result: dict, method_code: str):
        """Отправка результата выполнения задачи"""
        properties = {
            "correlation_data": correlation_data.encode(),
            "user_property": [
                ("status_code", "200"),
                ("ext_id", "12345"),  # Пример внешнего ID
            ],
        }
        payload = json.dumps(result)
        self.mqtt_client.publish(TOPIC_RES, payload, qos=1, properties=properties)
        logger.info("Result sent for correlation: %s", correlation_data)

    async def send_event(self, event_type_code: int, event_data: dict):
        """Отправка асинхронного события"""
        correlation_id = str(uuid.uuid4())
        properties = {
            "correlation_data": correlation_id.encode(),
            "user_property": [
                ("event_type_code", str(event_type_code)),
                ("dev_event_id", "1001"),
                ("dev_timestamp", str(int(asyncio.get_event_loop().time()))),
            ],
        }
        payload = json.dumps(event_data)
        self.mqtt_client.publish(TOPIC_EVT, payload, qos=1, properties=properties)
        logger.info(
            "Event sent: type=%s, correlation=%s", event_type_code, correlation_id
        )

    async def polling_loop(self):
        """Цикл периодического опроса задач"""
        while True:
            try:
                await self.send_request()
            except Exception as e:
                logger.error("Error in polling loop: %s", e)
            await asyncio.sleep(REQ_POLL_INTERVAL)

    async def healthcheck_loop(self):
        """Цикл отправки keep-alive сообщений"""
        while True:
            try:
                await self.send_event(
                    event_type_code=44,
                    event_data={
                        "101": 1047,
                        "102": "2024-08-12T10:31:57Z",
                        "200": 44,
                        "300": [{"310": "1.04.025", "311": 13}],
                    },
                )
            except Exception as e:
                logger.error("Error in healthcheck loop: %s", e)
            await asyncio.sleep(HEALTHCHECK_INTERVAL)


# Точка входа
async def main():
    client = DeviceClient()
    await client.start()

    try:
        # Основной цикл
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await client.mqtt_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
